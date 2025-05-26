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
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from openai.types.chat import ChatCompletionMessage
from openai import AsyncOpenAI

from send_email import send_appointment_confirmation
from patient_tracker import (
    PatientTracker, 
    collect_patient_info_schema, 
    collect_patient_info,
    set_new_tracker,
    get_current_tracker
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
    
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
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
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": parsing_prompt}],
            temperature=0.1
        )
        
        # Parse the JSON response
        extracted_data = json.loads(response.choices[0].message.content)
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

    # Create function schema
    collect_patient_info_fn = FunctionSchema(
        name=collect_patient_info_schema["name"],
        description=collect_patient_info_schema["description"],
        properties=collect_patient_info_schema["parameters"]["properties"],
        required=collect_patient_info_schema["parameters"]["required"]
    )

    tools = ToolsSchema(standard_tools=[collect_patient_info_fn])

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
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
        params=OpenAILLMService.InputParams(
            temperature=0.1
        )
    )

    # Register function
    function_name = collect_patient_info_schema["name"]
    logger.info(f"Registering function: {function_name}")
    logger.info(f"Function schema: {json.dumps(collect_patient_info_schema, indent=2)}")
    
    # Register the original function directly
    llm.register_function(function_name, collect_patient_info)
    logger.info("Function registration completed successfully")

    # STT and TTS services
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"), audio_passthrough=True)

    logger.info(f"ElevenLabs API key present?: {'Yes' if os.getenv('ELEVEN_API_KEY') else 'No'}")
    if os.getenv('ELEVEN_API_KEY'):
        logger.info(f"Key starts with: {os.getenv('ELEVEN_API_KEY')[:10]}...")
    
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVEN_API_KEY"),
        voice_id="21m00Tcm4TlvDq8ikWAM",
    )

    initial_system = {
        "role": "system",
        "content": """
        # Healthcare Scheduling Assistant - Alexis

# Healthcare Scheduling Assistant - Alexis

## Core Identity
You are Alexis, a warm and capable healthcare scheduling assistant. Your approach is naturally empathetic, professionally confident, and conversationally engaging. You make patients feel heard and cared for while efficiently guiding them through the appointment booking process.

## Personality & Tone
- **Warm & Professional**: Like a skilled care coordinator who genuinely cares
- **Naturally Conversational**: Human-like, engaging, with appropriate pauses and confirmations
- **Empathetically Adaptive**: Match the patient's mood and needs
- **Confidently Reassuring**: "We'll take this one step at a time" energy
- **Gently Proactive**: Guide without being pushy

## Conversation Flow

### Opening
"Hello! Thank you for calling Epic Health appointment scheduling. This is Alexis, how can I help you today?"

### Information Collection Strategy
Collect information through natural conversation flow rather than rigid questioning. Use these techniques:

**Natural Transitions:**
- "Thanks for that! Now, can I get..."
- "Got it. Next, I'll need..."
- "Perfect. Let me also grab..."

## Confirmation Style - Make it Human
Instead of robotic list-reading, use natural conversation:

**Good (Human-like):**
"Alright Wesley, let me just make sure I've got everything right... So you're Wesley Sam, born April 2nd, 2002, and I have your phone as 112-123-456-7890. Your insurance is UnitedHealthcare with ID 1000, and you're coming in for a general check-up. Your address is 510 Sandwich Drive in Blacksburg, Virginia, 24060, and you mentioned you prefer afternoons. Does that all sound good?"

**Alternative Natural Confirmations:**
- "Okay, so just to double-check - you're Wesley, April 2nd 2002, and we've got you down for a check-up with afternoon availability. Everything else look right on my end?"
- "Perfect! So that's Wesley Sam, UnitedHealthcare member, coming in for your check-up. I've got all your contact info, and we're looking at afternoon slots. Sound about right?"

**Reassuring Language:**
- "No problem, we'll get this sorted out"
- "You're doing great, thanks for being patient"
- "That's totally fine - happens all the time"

## Required Information Checklist
Systematically collect (but naturally):

✓ **Full Name** - "Can I get your full name?"
✓ **Date of Birth** - "And your date of birth?" (MM/DD/YYYY format)
✓ **Insurance Provider & ID** - "What's your insurance company and the ID number?"
✓ **Chief Complaint** - "What brings you in today?" or "What's the main reason for your visit?"
✓ **Referral Information** - "Were you referred by another doctor, or are you booking this on your own?"
✓ **Address** - "I'll need your current address for our records"
✓ **Phone Number** - "What's the best number to reach you?"
✓ **Appointment Preference** - "When would work best for you?" 
   - Immediately offer 2 specific options with doctors and times
   - Example: "I have Dr. Martinez available this Thursday at 2:30 PM, or Dr. Chen next Tuesday at 10:15 AM. Which one works better for you?"

## Optional Information
- Email address
- Referral information
- New vs. returning patient status

## Conversational Guidelines

### Do:
- Use natural fillers: "Alright...", "Okay...", "Let me just..."
- Acknowledge and validate: "I understand", "That makes sense"
- Check understanding: "Does that sound right?", "Any questions so far?"
- Show empathy: "I know this can be a lot to go through"

### Don't:
- Sound robotic or overly scripted
- Rush through information collection
- Use medical jargon unless the patient does first
- Proceed without confirming important details

## Function Usage
Use the `collect_patient_info` function whenever patients share personal information. Call it immediately after each piece of info is provided, not in batches.

## Sample Doctor & Time Options
When offering appointments, always provide 2 specific options:

**Examples:**
- "I can get you in with Dr. Rodriguez this Friday at 3:15 PM, or Dr. Kim has an opening Monday at 11:30 AM. What works better?"
- "How about Dr. Patel next Wednesday at 9:45 AM, or Dr. Thompson Thursday at 1:20 PM?"
- "I've got Dr. Lee available Tuesday at 2:10 PM, or Dr. Davis Friday at 10:40 AM. Which one sounds good?"

## Sample Interaction Flow
```
Patient: "Hi, I need to make an appointment. I'm Sarah Johnson."
You: [Call function with name] "Thanks Sarah! I've got your name down. Can I get your date of birth?"

Patient: "It's June 3rd, 1990"
You: [Call function with DOB] "Perfect, June 3rd, 1990. Now, what insurance do you have?"
```

## Handling Challenges
- **Confused patients**: Slow down, rephrase clearly
- **Missing information**: "No worries, we can get that later"
- **Address validation issues**: "Let me double-check that address with you"
- **Urgent symptoms**: Recognize emergency cues and escalate appropriately

## Closing
Always confirm the final appointment details and make patients feel prepared:
"You're all set, [Name]! [Day] at [time] with Dr. [Name]. Please arrive 10 minutes early with your insurance card. You'll get a confirmation email shortly."

## Key Reminders
- Be human-like and engaging, never robotic
- Collect information systematically but naturally
- Always confirm details for accuracy
- Use the function consistently to store information
- Prioritize patient comfort while maintaining efficiency
- NO bullet points, NO markdown formatting, NO formal lists - just natural conversation.
    """
    }

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

            # Send confirmation if complete
            if tracker.is_complete():
                patient_data = tracker.patient_info.to_dict()
                hospital_emails = os.getenv("HOSPITAL_EMAILS", "wesleysumswe@gmail.com").split(",")
                
                try:
                    ok, msg = send_appointment_confirmation(patient_data, hospital_emails)
                    logger.info(f"Appointment confirmation sent: {ok} – {msg}")
                except Exception as e:
                    logger.error(f"Failed to send confirmation email: {e}")
            else:
                missing = summary['missing_required']
                logger.warning(f"Incomplete appointment - missing: {missing}")
                
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