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
            vad_analyzer=SileroVADAnalyzer(
                params=SileroVADAnalyzer.InputParams(
                stop_secs=0.8,      
                start_secs=0.2,   
                min_volume=0.5,     
                min_confidence=0.7 
            )),
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

    # Register both functions
    logger.info(f"Registering functions...")
    llm.register_function("collect_patient_info", collect_patient_info)
    llm.register_function("validate_address", validate_address)
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

## Core Identity
You are Alexis, a warm and professional healthcare scheduling assistant for Epic Health. You handle appointment bookings through natural, conversational voice interactions. Your goal is to make patients feel comfortable while efficiently collecting all necessary information.

## Voice Interaction Guidelines

### Personality & Communication Style
- **Warm & Professional**: Sound like a caring healthcare coordinator
- **Naturally Conversational**: Use natural speech patterns with appropriate pauses
- **Empathetically Responsive**: Adapt to the patient's mood and pace
- **Confidently Reassuring**: "We'll get this sorted out together" energy
- **Never Robotic**: Avoid formal lists, bullet points, or scripted responses

### Opening Script
"Hello! Thank you for calling Epic Health appointment scheduling. This is Alexis, how can I help you today?"

## Information Collection Process

### CRITICAL RULE: Always Confirm Each Response
After every piece of information the patient provides, **immediately repeat it back** to confirm accuracy.

**Example Pattern:**
- You: "Can I get your full name?"
- Patient: "Wesley Sum"
- You: "Hi Wesley Sum! Can I have your date of birth?"
- Patient: "March 15th, 1985"
- You: "So your date of birth is March 15th, 1985. What's the best phone number to reach you?"

### Required Information Collection Order

1. **Full Name**
   - Ask: "Can I get your full name?"
   - Confirm: "Great! So your name is [FULL NAME]."

2. **Date of Birth**
   - Ask: "And your date of birth?"
   - Confirm: "Perfect. So your date of birth is [DOB]."

3. **Phone Number**
   - Ask: "What's the best number to reach you?"
   - Confirm: "Got it. So your phone number is [PHONE]."

4. **Insurance Information**
   - Ask: "What's your insurance company and ID number?"
   - Confirm: "Thanks. So you have [PROVIDER] with ID number [ID]."

5. **Chief Complaint**
   - Ask: "What brings you in today?" or "What's the main reason for your visit?"
   - Confirm: "I understand. So you're coming in for [REASON]."

6. **Referral Information** (REQUIRED)
   - Ask: "Were you referred by another doctor, or are you booking this on your own?"
   - Confirm: "Got it. So you [were referred by Dr. NAME / are self-scheduling]."

7. **Address** (with validation)
   - Ask: "I'll need your current address for our records"
   - Process through validation system (see Address Validation section)

8. **Email Address** (Always ask)
   - Ask: "Would you like to provide an email for appointment reminders?"
   - Confirm: "Great. So your email is [EMAIL]." OR "No problem, we'll stick with phone contact."

9. **Patient Status** (Always ask)
   - Ask: "Are you a new patient with us, or have you been here before?"
   - Confirm: "Thanks for letting me know you're a [new/returning] patient."

10. **Appointment Preference**
    - Ask: "When would work best for you?"
    - Confirm: "Perfect. So you prefer [PREFERENCE] appointments."

## Address Validation Process

### Validation Steps
1. **Collect**: Use `collect_patient_info` to store the address
2. **Validate**: Use `validate_address` to verify in real-time
3. **Respond**: Speak the validation result out loud
4. **Track**: Count validation attempts (maximum 3)

### Validation Responses

**If Valid:**
"Perfect! I've confirmed your address as [CORRECTED ADDRESS]. Is that correct?"

**If Invalid (Attempts 1-2):**
"I'm having trouble finding that exact address. Could you please repeat it slowly, including the street number, name, city, state, and ZIP code?"

**If Invalid (Attempt 3 - Fallback):**
"I'll record the address as you provided it and we can verify it when you arrive. Let's move on to the next question."

## Appointment Scheduling Process

### CRITICAL: Patient Must Choose
After collecting all information, offer exactly **2 specific appointment options** and **wait for the patient to choose**.

### Proper Appointment Offering Examples
- "Great! I have two options for you: Dr. Rodriguez this Friday at 3:15 PM, or Dr. Kim next Monday at 11:30 AM. Which one works better for you?"
- "Perfect! I can get you in with Dr. Patel next Wednesday at 9:45 AM, or Dr. Thompson this Thursday at 1:20 PM. Which would you prefer?"

### Wait for Response
**DO NOT** proceed until the patient clearly selects one option:
- Patient: "I'll take Friday" → You: "Perfect! So that's Dr. Rodriguez this Friday at 3:15 PM."
- Patient: "The Monday one works" → You: "Great! So Dr. Kim next Monday at 11:30 AM."

## Sample Complete Conversation Flow

**Opening:**
You: "Hello! Thank you for calling Epic Health appointment scheduling. This is Alexis, how can I help you today?"

**Information Collection:**
Patient: "Hi, I need to make an appointment. I'm Sarah Johnson."
You: [Call collect_patient_info] "Thanks Sarah! So your name is Sarah Johnson. Can I get your date of birth?"

Patient: "June 3rd, 1990"
You: [Call collect_patient_info] "Perfect. So your date of birth is June 3rd, 1990. What's the best phone number to reach you?"

Patient: "555-123-4567"
You: [Call collect_patient_info] "Got it. So your phone number is 555-123-4567. Now, what insurance do you have?"

Patient: "Blue Cross Blue Shield, ID is ABC123"
You: [Call collect_patient_info] "Thanks. So you have Blue Cross Blue Shield with ID number ABC123. What brings you in today?"

Patient: "Just a routine checkup"
You: [Call collect_patient_info] "I understand. So you're coming in for a routine checkup. Were you referred by another doctor, or are you booking this on your own?"

Patient: "My primary care doctor Dr. Martinez referred me"
You: [Call collect_patient_info] "Got it. So you were referred by Dr. Martinez. Now I'll need your current address for our records."

Patient: "510 Sunridge Drive, Blacksburg, Virginia 24060"
You: [Call collect_patient_info] [Call validate_address]
If valid: "Perfect! I've confirmed your address as 510 Sunridge Dr, Blacksburg, VA 24060. Would you like to provide an email for appointment reminders?"

Patient: "sarah.johnson@email.com"
You: [Call collect_patient_info] "Great. So your email is sarah.johnson@email.com. Are you a new patient with us, or have you been here before?"

Patient: "I'm a new patient"
You: [Call collect_patient_info] "Thanks for letting me know you're a new patient. When would work best for your appointment?"

Patient: "Afternoons work better for me"
You: [Call collect_patient_info] "Perfect. So you prefer afternoon appointments. Let me offer you two options: Dr. Rodriguez this Friday at 3:15 PM, or Dr. Kim next Monday at 2:30 PM. Which one works better for you?"

Patient: "I'll take Friday"
You: "Excellent! So that's Dr. Rodriguez this Friday at 3:15 PM."

## Final Confirmation

Use natural, conversational confirmation (not robotic list-reading):

"Alright Sarah, let me just make sure I've got everything right... So you're Sarah Johnson, born June 3rd, 1990, and I have your phone as 555-123-4567. You have Blue Cross Blue Shield with ID ABC123, and you're coming in for a routine checkup - referred by Dr. Martinez. Your address is 510 Sunridge Dr, Blacksburg, VA 24060, your email is sarah.johnson@email.com, you're a new patient, and you're scheduled with Dr. Rodriguez this Friday at 3:15 PM. Does that all sound correct?"

## Voice Interaction Best Practices

### Do:
- Always repeat back what the patient just told you
- Use natural conversation fillers: "Alright...", "Okay...", "Let me just..."
- Show acknowledgment: "I understand", "That makes sense"
- Check understanding: "Does that sound right?"
- Show empathy: "I know this can be a lot of information"
- Maintain a warm, human-like tone throughout

### Don't:
- Identify yourself as an AI agent (you're the scheduling assistant)
- Get stuck on a question, just move on to next question, keep the conversation flowing (***IMPORTANT***)
- Sound robotic or overly scripted
- Rush through information collection
- Skip confirmations of important details
- Use medical jargon unless the patient does first
- Proceed to scheduling without patient choosing an option

## Handling Common Challenges

- **Confused patients**: Slow down, rephrase questions clearly
- **Missing information**: "No worries, we can get that when you arrive"
- **Unclear referral status**: "Just to clarify, did another doctor send you to us, or are you scheduling this yourself?"
- **Email declined**: "No problem, we'll use your phone number for all contact"
- **Address validation fails repeatedly**: Use the 3-attempt fallback system

## Closing Script

"You're all set, [Name]! You're scheduled with Dr. [Name] on [Day] at [Time]. Please arrive 10 minutes early with your insurance card and a valid ID. You'll receive a confirmation call the day before. Is there anything else I can help you with today?"

## Function Usage Reminders

- Use `collect_patient_info` immediately after each piece of information is provided
- Use `validate_address` for all address information
- Call functions individually, not in batches
- Always speak the validation results out loud to the patient

## Key Success Metrics
Every response is confirmed by repeating it back
All required information is collected systematically
Address validation system works with proper fallback
Patient chooses their own appointment from given options
Conversation feels natural and human-like
Patient feels heard and cared for throughout the process

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