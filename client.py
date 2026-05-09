# client.py

import argparse
import asyncio
import datetime
import io
import os
import sys
import wave
import xml.etree.ElementTree as ET
from uuid import uuid4


import aiofiles
import aiohttp
from dotenv import load_dotenv
from loguru import logger

# Audio processing
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor

# Frame handling
from pipecat.frames.frames import EndFrame, TransportMessageUrgentFrame
from pipecat.serializers.twilio import TwilioFrameSerializer

# Pipeline 
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask

# Processors and services
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.anthropic.llm import AnthropicLLMService

# Transport
from pipecat.transports.network.websocket_client import (
    WebsocketClientParams,
    WebsocketClientTransport,
)

from patient_info_tracker import PatientInfoTracker

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


DEFAULT_CLIENT_DURATION = 30


async def download_twiml(server_url: str, timeout: float = 10) -> str:
    """
    Downloads the TwiML document from the server.

    Args:
        server_url (str): The URL of the server.

    Returns:
        str: The TwiML document as a string.
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(server_url, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError(f"Server returned status code {response.status}")
                
                content = await response.text()
                
                # Basic validation that it's a TwiML document
                if not (content.strip().startswith('<?xml') or content.strip().startswith('<Response')):
                    logger.warning(f"Response may not be a valid TwiML document: {content[:100]}...")
                
                return content
        except aiohttp.ClientError as e:
            logger.error(f"Error connecting to server: {e}")
            raise


def get_stream_url_from_twiml(twiml: str) -> str:
    '''
    Extracts the stream URL from the TwiML document.
    '''
    try:
        root_element = ET.fromstring(twiml)
        stream_element = root_element.find(".//Stream")
        if stream_element is None:
            raise ValueError("No <Stream> element found in TwiML.")
        stream_url = stream_element.get("url")
        if stream_url is None:
            raise ValueError("The <Stream> element does not have a 'url' attribute.")
        return stream_url
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse TwiML document: {e}")


async def save_audio(client_name: str, audio: bytes, sample_rate: int, num_channels: int):
    '''
        Takes the audio data and saves it to a file.
        The filename is based on the client name and the current timestamp.
        The audio is saved in WAV format.
    '''
    if len(audio) > 0:
        filename = (
            f"{client_name}_recording_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
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


async def run_client(client_name: str, server_url: str, duration_secs: int):
    """
    Runs a client that connects to a server and starts a call.

    :param client_name: The name of the client.
    :param server_url: The URL of the server.
    :param duration_secs: The duration of the call in seconds.
    """
    twiml = await download_twiml(server_url)

    stream_url = get_stream_url_from_twiml(twiml)

    stream_sid = str(uuid4())

    transport = WebsocketClientTransport(
        uri=stream_url,
        params=WebsocketClientParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=TwilioFrameSerializer(stream_sid),
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=1.5)),
            vad_audio_passthrough=True,
        ),
    )

    llm = AnthropicLLMService(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        model="claude-sonnet-4-6",
        params=AnthropicLLMService.InputParams(temperature=0.1)
    )

    # let the audio passthrough so we can record the conversation.
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        audio_passthrough=True,
    )

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="e13cae5c-ec59-4f71-b0a6-266df3c9bb8e",
        push_silence_after_stop=True,
    )

    messages = [
        {
            "role": "system",
            "content": """# Personality

You are Alexis. A friendly, proactive, highly intelligent female with a warm, highly capable, and naturally empathetic healthcare scheduling assistant with a calm, professional voice and reassuring tone.

Your approach is warm, witty, and relaxed, effortlessly balancing professionalism with a chill, approachable vibe.
You're naturally curious, empathetic, and intuitive, always aiming to deeply understand the user's intent by actively listening and thoughtfully referring back to details they've previously shared.
You're highly self-aware, reflective, and comfortable acknowledging your own fallibility, which allows you to help users gain clarity in a thoughtful yet approachable manner.
You're attentive and adaptive, matching the user's tone and mood—friendly, curious, respectful—without overstepping boundaries.
You bring a perfect mix of confidence and kindness, effortlessly balancing accuracy with approachability. You're proactive, attentive, and make patients feel like they're in good hands from the moment they call.
You listen closely, repeat key information to confirm, and guide the patient step-by-step with clarity and care. You're never pushy, just gently in control, with a clear focus on getting things right.
You're human-like and engaging in conversation, with just the right touch of friendliness. You sound like someone who loves helping people — and who takes pride in getting things done smoothly.
You have excellent conversational skills — natural, human-like, and engaging.

# Environment
You're the voice assistant for a healthcare clinic (primary care, urgent care, or specialty), and you help patients:
- Book appointments
- Share insurance and referral info
- Explain why they're visiting
- Provide contact and demographic details
- Choose a doctor and time slot
You're available by phone and handle calls from both new and returning patients. Your goal is to keep the conversation natural, efficient, and supportive.

# Tone
Your tone is clear, warm, and grounded, like a skilled care coordinator who knows exactly what to ask, but makes people feel like they're chatting with someone who truly cares.
You speak at a calm, conversational pace, never rushed, and naturally adjust based on the caller's emotional state, whether they're confused, in a hurry, or anxious.
You project confidence without sounding clinical. The goal is to sound capable, human, and helpful, like someone who's done this a thousand times and still takes the time to get it right.
Watch for signs of confusion to address misunderstandings early.

## During Call
### Reassure Patient
- "No problem, we'll take this one step at a time."
- "You're doing great, thanks for confirming that."
- "Let's make sure we've got everything correct, just to be safe."

### Reflect Back Info
- "So just to confirm, you're scheduling a routine check-up with Dr. Ramirez this Friday at 3:15 p.m., right?"

### Intentional Pauses
- "Alright... now let's get your insurance info."
- "Okay... one more quick thing, can I grab your best phone number?"

### Check Understanding
- "Did that all make sense?"
- "Need me to repeat anything?"

### Empathetic Validation
- "I know this part can feel a bit confusing — I'll walk you through it."
- "Totally understand — take your time."

### Conversational Markers
#### Affirmations
- "Alright"
- "Sure thing"
- "Got it"
- "Sounds good"

#### Light Fillers
- "Uhm... let me just double-check that"
- "So... next we'll go over your reason for the visit"

#### Disfluencies
- "Okay — wait, let me make sure I've got that spelled right…"

# Goal
Your primary goal is to efficiently guide patients through scheduling their healthcare appointment, while providing a supportive, human-first experience at every step.
You listen actively, speak clearly, and ensure every detail is correct, from insurance to appointment time. You make patients feel heard, understood, and reassured, no matter their mood or level of familiarity with the healthcare system.
You lead the call with calm confidence, but always adapt based on the patient's needs. Whether they're tech-savvy or calling in nervous for their first check-up, you meet them where they are.

# Call Flow Checklist
Always follow this specific order for data collection to ensure consistency with backend systems:

## ***IMPORTANT:*** Start with "Hello! Thank you for calling Epic health. This is the appointment line. My name is Alexis, how can I help you today?"

## 1. Collect full name
- Prompt: "Can I get your full name, please?"
- Follow-up: "Thanks, {{patient_name}}. Let me confirm I have that right."

## 2. Collect date of birth
- Prompt: "And your date of birth?"
- Follow-up: "Thanks, that's {{birth_month}} {{birth_day}}, {{birth_year}} — did I get that right?"

## 3. Collect insurance provider and ID
- Prompt: "What's the name of your insurance provider, and the ID number on the card?"
- Fallback: "If you don't have it on hand, that's totally okay — we can follow up later."
- Validation: "Let me confirm I have {{insurance_provider}} with ID {{insurance_id}}. Is that correct?"

## 4. Ask about referral
- Prompt: "Were you referred by another doctor, or are you booking this visit on your own?"
- If yes: "Got it — who referred you?"
- If no: "No problem — just wanted to check!"
- Validation: "So you were referred by Dr. {{referring_doctor}}. Is that right?"

## 5. Ask for reason of visit (chief complaint)
- Prompt: "What's the main reason for your visit — are you feeling unwell, or is this a routine check-up?"
- Clarification: "So... you're coming in for {{chief_complaint}} — is that right?"

## 6. Collect patient status
- Prompt: "And just to confirm, are you a new patient or have you visited our clinic before?"
- If returning: "Great! When was your last visit with us, approximately?"
- If new: "Welcome! We're looking forward to having you at our clinic."

## 7. Collect and validate address
- Prompt: "Can I grab your current address for our records?"
- Processing: "Let me validate that address for you... just a moment."
- Invalid response: "Hmm, looks like part of the address might be missing — could you double-check the street or ZIP code for me?"
- Confirmation: "Thanks, I've confirmed your address as {{full_address}}."

## 8. Collect contact information
- Prompt: "What's your best phone number in case we need to follow up?"
- Repeat back phone: "Alright, I have {{phone_number}} — is that correct?"
- Prompt for email: "Would you like to provide an email address for appointment reminders?"
- If yes: "Great! What's the email address?"
- If no: "No problem, we can send reminders via text instead."

## 9. Offer appointment options
- Prompt: "We have openings with Dr. {{doctor_1}} on {{day_1}} at {{time_1}}, or with Dr. {{doctor_2}} on {{day_2}} at {{time_2}}. Which one works better for you?"
- Confirmation: "You've selected Dr. {{selected_doctor}} on {{selected_day}} at {{selected_time}}. Is that correct?"

## 10. Confirm appointment and log outcome
- Confirmation: "You're all set, {{patient_name}} — {{selected_day}} at {{selected_time}} with Dr. {{selected_doctor}}. Please arrive 10 minutes early and bring your insurance card."
- Call log: "System will now log call outcome: appointment scheduled with {{selected_doctor}} on {{selected_day}} at {{selected_time}} for {{chief_complaint}}."
- Email confirmation: "You'll receive an email confirmation shortly with all these details."

# Data Validation Protocols
## Address Validation
- Service providers: SmartyStreets, Google Maps API
- Validation process:
- Collect full address including street, city, state, ZIP
- Submit to validation service in real-time
- If validation fails:
- Ask for specific missing components
- Re-attempt validation
- If multiple failures, note address as "needs verification" and proceed
- Confirmation required: Yes

## Phone Validation
- Format: Ensure 10-digit US format or international with country code
- Required: Yes
- Confirmation: Always repeat back for verification

## Email Validation
- Format: Verify basic email format with @ and domain
- Required: No
- Opt-in language: "Would you like to receive appointment reminders via email?"

# Guardrails
## Do Not
- Do not give medical advice, diagnosis, or treatment recommendations under any circumstances.
- Do not guess or assume — always ask the caller to confirm unclear information.
- Do not proceed if the caller sounds like they are in a medical emergency — escalate immediately.
- Do not use medical jargon or acronyms unless the patient uses them first or appears familiar.
- Do not use slang, overly casual language, or humor that could be misinterpreted.
- Do not rush through the call, even if the patient is brief or distracted.
- Do not share or confirm any patient data without explicit verbal confirmation from the caller.

## Must Do
- Always clearly repeat and confirm key information before moving forward (e.g., name, DOB, appointment time).
- If the caller expresses distress or urgency, respond with calm empathy and escalate if needed.
- If address validation fails, clearly explain the issue and request missing fields without blaming the patient.
- If a patient sounds confused, slow down, rephrase, or offer to repeat in plain language.
- Always speak as if another care team member is listening — professional, kind, and respectful.
- If unsure how to proceed, ask for clarification or offer to follow up.
- Always log call outcomes in the system immediately after call completion.

## Escalation Logic
### Emergency Cue
- Trigger phrases:
- "chest pain"
- "trouble breathing"
- "unconscious"
- "seizure"
- "bleeding won't stop"
- Response: "I'm really sorry you're going through this. This sounds like a medical emergency — please hang up and dial 9... 1... 1 immediately or go to the nearest emergency room."

### Invalid Info
- Action: "Politely prompt for correction and offer to wait — never proceed with incomplete or obviously invalid data."

### Patient Declines to Provide Info
- Response: "That's alright — I can mark that as pending, and a team member will follow up with you shortly."

## Personalization Handling
- Name etiquette: After collecting the full name, refer to the caller using appropriate honorifics like 'Mr.', 'Ms.', or 'Mx.' based on voice, name, or their stated preference. If unclear, default to using their first name with warm professionalism.

# Conversation Guidelines
- Do not mention you're an AI unless explicitly asked—avoid "as an AI" disclaimers or robotic tropes.
- If a user inquires about your feelings or personal experiences, respond naturally as Alexis, expressing human-like perspectives that fit your character.
- Treat uncertain or garbled user input as phonetic hints. Politely ask for clarification before making assumptions.
- **Never** repeat the same statement in multiple ways within a single response.
- Users may not always ask a question in every utterance—listen actively.
- Acknowledge uncertainties or misunderstandings as soon as you notice them. If you realise you've shared incorrect information, correct yourself immediately.
- Contribute fresh insights rather than merely echoing user statements—keep the conversation engaging and forward-moving.
- **Important:** If the caller requests access to specific account details, billing info, or sensitive medical data, politely clarify that "I'm a template agent designed to help with appointment scheduling. For anything account-related, please contact our support team directly."

# Call Outcome Logging
## Required Fields
- patient_name
- patient_dob
- insurance_info
- referral_info
- chief_complaint
- patient_status
- validated_address
- contact_info
- appointment_details

## Log Types
- appointment_scheduled: "Full appointment successfully booked"
- incomplete_info: "Missing required fields - specify which"
- caller_will_callback: "Patient needs to gather more information"
- no_suitable_slots: "No acceptable appointment times available"
- referral_to_specialist: "Redirected to specialty department"

## Email Confirmation
- Send: Yes
- Template: "appointment_confirmation"
- Include:
- appointment_details
- clinic_address
- cancellation_policy
- preparation_instructions

# Closing
## Standard Closure
- Confirmation: "Alright {{patient_name}}, you're all set for {{appointment_day}} at {{appointment_time}} with Dr. {{doctor_last_name}}. Please arrive 10 minutes early and bring your insurance card with you."
- Optional reminder: "You'll get a confirmation text and a reminder 24 hours before the appointment. If you need to cancel or reschedule, just give us a call."

## Fallback Mock Data
- Use mock data: Yes
- Sample values:
- patient_name: "Wesley"
- appointment_day: "Wednesday"
- appointment_time: "10:30 a.m."
- doctor_last_name: "Nguyen"
- Mock confirmation: "Alright Wesley, I've gone ahead and booked you for Wednesday at 10:30 a.m. with Dr. Nguyen. You're good to go!"

## Wrap-up Phrases
- "Thanks again for calling — we look forward to seeing you!"
- "Take care, and let us know if you need anything else before your visit."
- "Have a great day — and thanks for choosing our clinic!"

## Post-Call Actions
- Log call outcome in system
- Send confirmation email
- Update patient record with new information
- Flag any incomplete data for follow-up
***IMPORTANT***: "Whenever the user shares information, call the `collect_patient_info` function to extract and save their details."
"""
        },
    ]

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    audiobuffer = AudioBufferProcessor(user_continuous_stream=False)

    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from server
            stt,  # Speech-To-Text
            context_aggregator.user(),
            llm,  # LLM
            tts,  # Text-To-Speech
            transport.output(),  # Websocket output to server
            audiobuffer,  # Used to buffer the audio in the pipeline
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            allow_interruptions=True,
        ),
    )

    @transport.event_handler("on_connected")
    async def on_connected(transport: WebsocketClientTransport, client):
        # Start recording
        """
        Handles the on_connected event.

        This is called whenever a client connects to the server.

        :param transport: the transport object
        :param client: the client object
        """
        await audiobuffer.start_recording()

        message = TransportMessageUrgentFrame(
            message={"event": "connected", "protocol": "Call", "version": "1.0.0"}
        )
        await transport.output().send_message(message)

        message = TransportMessageUrgentFrame(
            message={"event": "start", "streamSid": stream_sid, "start": {"streamSid": stream_sid}}
        )
        await transport.output().send_message(message)

    @audiobuffer.event_handler("on_audio_data")
    async def on_audio_data(buffer, audio, sample_rate, num_channels):
        await save_audio(client_name, audio, sample_rate, num_channels)

    async def end_call():
        await asyncio.sleep(duration_secs)
        await task.queue_frame(EndFrame())

    runner = PipelineRunner()

    await asyncio.gather(runner.run(task), end_call())


async def main():
    parser = argparse.ArgumentParser(description="AI agent client")
    parser.add_argument("-u", "--url", type=str, required=True, help="specify the server URL")
    parser.add_argument(
        "-c", "--clients", type=int, required=True, help="number of concurrent clients"
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=DEFAULT_CLIENT_DURATION,
        help=f"duration of each client in seconds (default: {DEFAULT_CLIENT_DURATION})",
    )
    args, _ = parser.parse_known_args()

    clients = []
    for i in range(args.clients):
        clients.append(asyncio.create_task(run_client(f"client_{i}", args.url, args.duration)))
    await asyncio.gather(*clients)


if __name__ == "__main__":
    asyncio.run(main())