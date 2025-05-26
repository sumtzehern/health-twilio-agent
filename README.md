# Epic Health AI Voice Agent 🏥🤖

A sophisticated AI-powered voice agent for healthcare appointment scheduling that handles phone calls through Twilio, collects patient information, validates addresses in real-time, and sends confirmation emails.

## 🎯 What Does This Do?

This system creates an intelligent voice assistant named "Alexis" that can:

- **Answer phone calls** for healthcare appointment scheduling
- **Collect patient information** through natural conversation (name, DOB, insurance, address, etc.)
- **Validate addresses** in real-time using SmartyStreets API
- **Book appointments** by offering specific doctor/time options
- **Send confirmation emails** automatically when appointments are complete
- **Handle complex conversations** with function calling and context management

## 🛠️ Tech Stack

### Core Framework
- **[Pipecat AI](https://docs.pipecat.ai/)** - Real-time voice AI pipeline framework
- **FastAPI** - Web server and WebSocket handling
- **Python 3.8+** - Backend language

### AI & Voice Services
- **OpenAI GPT-4o** - Large Language Model for conversation
- **ElevenLabs** - Text-to-Speech (TTS) synthesis
- **Deepgram** - Speech-to-Text (STT) transcription
- **Silero VAD** - Voice Activity Detection

### Communication & Validation
- **Twilio** - Phone system integration
- **SmartyStreets API** - Real-time address validation
- **SMTP Email** - Appointment confirmations
- **ngrok** - Secure tunneling for development

### Additional Tools
- **loguru** - Advanced logging
- **python-dotenv** - Environment management
- **aiohttp** - Async HTTP client

## 🏗️ System Architecture
Phone Call (Twilio) → ngrok → FastAPI Server → Pipecat Pipeline
↓
[STT] → [LLM + Functions] → [TTS] → WebSocket → Twilio → Caller
↓
[Patient Tracker] → [Address Validator] → [Email Sender]

## 📋 Use Cases

### Primary Use Case: Healthcare Appointment Scheduling
- **Target Users**: Healthcare clinics, medical practices, telehealth providers
- **Scenario**: Patients call to schedule appointments, agent collects all necessary information
- **Outcome**: Complete patient intake with verified information and confirmed appointment

### Key Features:
1. **Natural Conversation Flow**: Feels like talking to a human receptionist
2. **Data Validation**: Real-time address verification and data quality checks
3. **Function Calling**: Structured data collection with OpenAI function calling
4. **Error Handling**: Graceful fallbacks when validation fails
5. **Multi-Channel Output**: Voice response + email confirmation + logged data

## 🔧 Configuration

### Conversation Flow
The agent follows this structured approach:
1. Name collection and confirmation
2. Date of birth
3. Phone number
4. Insurance information
5. Chief complaint (reason for visit)
6. Referral information
7. Address (with real-time validation)
8. Email address
9. Patient status (new/returning)
10. Appointment preference and scheduling

### Function Calling
The system uses OpenAI function calling for:
- `collect_patient_info`: Stores patient data
- `validate_address`: Real-time address verification

### Address Validation
- Uses SmartyStreets API for USPS validation
- Attempts validation up to 3 times
- Falls back gracefully if validation fails
- Provides natural language feedback

## 📊 Monitoring & Logging

The system provides comprehensive logging:
- **Conversation flow** - Each step of patient interaction
- **Function calls** - Data collection and validation
- **Address validation** - Success/failure with details
- **Email sending** - Confirmation delivery status
- **Audio processing** - STT/TTS performance