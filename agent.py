# agent.py

import datetime
import io
import os
import sys
import wave
import json

import aiofiles
from dotenv import load_dotenv
from fastapi import WebSocket
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from anthropic import AsyncAnthropic

from prompts import SYSTEM_PROMPT
from send_email import send_appointment_confirmation
from patient_tracker import (
    PatientTracker, 
    collect_patient_info_schema, 
    collect_patient_info,
    set_new_tracker,
    get_current_tracker,
    validate_address_schema,
    validate_address
)

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


# save audio
async def save_audio(server_name: str, audio: bytes, sample_rate: int, num_channels: int):
    if len(audio) > 0:
        filename = (
            f"{server_name}_recording_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        )
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wf:
                wf.setsampwidth(2)
                wf.setnchannels(num_channels)
                wf.setframerate(sample_rate)
                wf.writeframes(audio)
            async with aiofiles.open(filename, "wb") as file:
                await file.write(buffer.getvalue())
        logger.info(f"Merged audio saved to {filename}")
    else:
        logger.info("No audio data to save")


async def parse_transcript_for_patient_info(transcript: str) -> dict:
    """Parse the entire conversation transcript to extract patient information"""
    
    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    parsing_prompt = f"""
You are a data extraction specialist. Extract patient information from this healthcare conversation transcript.

TRANSCRIPT:
{transcript}

Extract the following information if mentioned:
- name: Patient's full name
- dob: Date of birth (format as MM/DD/YYYY)
- insurance_provider: Insurance company name
- insurance_id: Insurance ID/member number
- chief_complaint: Reason for visit
- address: Full address
- phone: Phone number
- email: Email address
- appointment_preference: Preferred appointment time/day
- referral_info: Referring doctor information
- patient_status: New or returning patient

Return ONLY a JSON object with the extracted data. Use null for missing information.
Example: {{"name": "John Smith", "dob": "03/15/1985", "phone": "555-123-4567", "insurance_provider": null}}
"""

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": parsing_prompt}],
            temperature=0.1
        )

        # Parse the JSON response
        extracted_data = json.loads(response.content[0].text)
        logger.info(f"Extracted data from transcript: {extracted_data}")
        return extracted_data
        
    except Exception as e:
        logger.error(f"Error parsing transcript: {e}")
        return {}


async def enhanced_collect_patient_info(function_call_params):
    """Enhanced wrapper for collect_patient_info with error handling and logging"""
    try:
        # Handle FunctionCallParams object from Pipecat
        if hasattr(function_call_params, 'arguments'):
            args = function_call_params.arguments
            logger.info(f"🔧 Function called with FunctionCallParams, args: {args}")
        else:
            args = function_call_params
            logger.info(f"🔧 Function called with direct args: {args}")
        
        # Check if original function expects FunctionCallParams or kwargs
        import inspect
        original_sig = inspect.signature(collect_patient_info)
        
        if len(original_sig.parameters) == 1:
            # Original function expects FunctionCallParams object
            result = await collect_patient_info(function_call_params)
        else:
            # Original function expects keyword arguments
            result = await collect_patient_info(**args)
            
        logger.info(f"Function completed successfully: {result}")
        return result
    except Exception as e:
        logger.error(f"Error in collect_patient_info: {str(e)}")
        return {"status": "error", "message": f"Failed to collect patient info: {str(e)}"}


async def run_agent(websocket_client: WebSocket, stream_sid: str, testing: bool):
    set_new_tracker()

    # Create function schemas
    collect_patient_info_fn = FunctionSchema(
        name=collect_patient_info_schema["name"],
        description=collect_patient_info_schema["description"],
        properties=collect_patient_info_schema["parameters"]["properties"],
        required=collect_patient_info_schema["parameters"]["required"]
    )
    
    # Add address validation function schema
    validate_address_fn = FunctionSchema(
        name=validate_address_schema["name"],
        description=validate_address_schema["description"],
        properties=validate_address_schema["parameters"]["properties"],
        required=validate_address_schema["parameters"]["required"]
    )

    # Include both functions in tools
    tools = ToolsSchema(standard_tools=[collect_patient_info_fn, validate_address_fn])

    # Transport setup
    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
            serializer=TwilioFrameSerializer(stream_sid),
        ),
    )

    # LLM service with function calling
    llm = AnthropicLLMService(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        model="claude-sonnet-4-6",
        params=AnthropicLLMService.InputParams(
            temperature=0.1
        )
    )

    # Register both functions
    logger.info(f"Registering functions...")
    llm.register_function("collect_patient_info", collect_patient_info)
    llm.register_function("validate_address", validate_address)
    logger.info("Function registration completed successfully")

    # STT and TTS services
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"), model="nova-3-medical", audio_passthrough=True)

    logger.info(f"ElevenLabs API key present?: {'Yes' if os.getenv('ELEVEN_API_KEY') else 'No'}")
    if os.getenv('ELEVEN_API_KEY'):
        logger.info(f"Key starts with: {os.getenv('ELEVEN_API_KEY')[:10]}...")
    
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVEN_API_KEY"),
        voice_id="21m00Tcm4TlvDq8ikWAM",
    )

    initial_system = {"role": "system", "content": SYSTEM_PROMPT}

    # Context and pipeline setup
    context = OpenAILLMContext(messages=[initial_system], tools=tools)
    context_agg = llm.create_context_aggregator(context)
    audiobuffer = AudioBufferProcessor(user_continuous_stream=not testing)

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_agg.user(),
        llm,
        tts,
        transport.output(),
        audiobuffer,
        context_agg.assistant()
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            allow_interruptions=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        await audiobuffer.start_recording()
        await task.queue_frames([context_agg.user().get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.cancel()

    @audiobuffer.event_handler("on_audio_data")
    async def on_audio_data(buffer, audio, sample_rate, num_channels):
        server_name = f"server_{websocket_client.client.port}"
        await save_audio(server_name, audio, sample_rate, num_channels)

    # Run the pipeline
    runner = PipelineRunner(handle_sigint=False, force_gc=True)
    
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
    finally:
        logger.info("Call ended, performing post-call actions...")

        # Get final patient information
        try:
            tracker = get_current_tracker()
            summary = tracker.get_summary()
            
            logger.info(f"Call completion: {summary['completion_percentage']:.1f}%")
            logger.info(f"Patient info collected: {json.dumps(summary['patient_info'], indent=2)}")

            patient_data = tracker.patient_info.to_dict()
            
            # Check if we have at least a phone number
            if patient_data.get('phone'):
                # Add a note about missing information if any
                missing = summary['missing_required']
                if missing:
                    patient_data['_incomplete_note'] = f"INCOMPLETE - Missing: {', '.join(missing)}"
                
            hospital_emails = os.getenv("HOSPITAL_EMAILS", "wesleysumswe@gmail.com,jeff@assorthealth.com, connor@assorthealth.com, cole@assorthealth.com, jciminelli@assorthealth.com").split(",")
                
            try:
                ok, msg = send_appointment_confirmation(patient_data, hospital_emails)
                logger.info(f"Appointment confirmation sent: {ok} – {msg}")
            except Exception as e:
                logger.error(f"Failed to send confirmation email: {e}")
            else:
                logger.error("Call ended without collecting phone number - no confirmation sent")
                
        except Exception as e:
            logger.error(f"Error in post-call processing: {e}")


# Enhanced utility class with better error handling
class PatientDataManager:
    """Utility class for managing patient data across calls"""
    
    @staticmethod
    def export_patient_data(tracker: PatientTracker, format: str = "json") -> str:
        """Export patient data in various formats"""
        try:
            data = tracker.get_summary()
            
            if format == "json":
                return json.dumps(data, indent=2)
            elif format == "csv":
                import csv
                import io
                output = io.StringIO()
                if data['patient_info']:
                    writer = csv.DictWriter(output, fieldnames=data['patient_info'].keys())
                    writer.writeheader()
                    writer.writerow(data['patient_info'])
                return output.getvalue()
            else:
                return str(data)
        except Exception as e:
            logger.error(f"Error exporting patient data: {e}")
            return f"Export error: {str(e)}"
    
    @staticmethod
    def validate_required_fields(tracker: PatientTracker) -> tuple[bool, list]:
        """Validate all required fields are present and valid"""
        try:
            missing = tracker.get_missing_required_fields()
            validation_errors = []
            
            patient_info = tracker.patient_info
            
            # Validate phone if present
            if patient_info.phone:
                try:
                    from patient_tracker import validate_phone
                    if not validate_phone(patient_info.phone):
                        validation_errors.append("Invalid phone number format")
                except ImportError:
                    logger.warning("Phone validation function not available")
            
            # Validate email if present
            if patient_info.email:
                try:
                    from patient_tracker import validate_email
                    if not validate_email(patient_info.email):
                        validation_errors.append("Invalid email format")
                except ImportError:
                    logger.warning("Email validation function not available")
            
            # Validate date of birth if present
            if patient_info.dob:
                try:
                    from patient_tracker import validate_dob
                    if not validate_dob(patient_info.dob):
                        validation_errors.append("Invalid date of birth format")
                except ImportError:
                    logger.warning("DOB validation function not available")
            
            is_valid = len(missing) == 0 and len(validation_errors) == 0
            return is_valid, list(missing) + validation_errors
            
        except Exception as e:
            logger.error(f"Error validating fields: {e}")
            return False, [f"Validation error: {str(e)}"]