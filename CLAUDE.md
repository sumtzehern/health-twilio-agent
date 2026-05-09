# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An AI-powered voice agent ("Alexis") for healthcare appointment scheduling over the phone. Patients call in via Twilio, the audio streams over WebSocket to a Pipecat pipeline (STT → LLM → TTS), and the agent collects structured patient info using Claude tool calling (Anthropic API). After the call ends, a confirmation email is sent via Resend.

## Running the Server

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in API keys

python main.py           # production mode
python main.py --test    # testing mode (disables continuous audio stream)
```

The server runs on port 8765. For Twilio to reach it, you need a public URL (e.g., via ngrok). Twilio must POST to `/` (returns TwiML that connects the call to the WebSocket), and the WebSocket endpoint is `/audio-stream`.

**Twilio setup**: configure your phone number's webhook to `POST https://<your-ngrok-url>/`. The `templates/streams.xml` file must have the correct WebSocket URL — update it to match your public host before use (the `.template` file shows the placeholder format).

## Running Tests

```bash
python test_patient_collection.py   # tests PatientTracker, field collection, validation
python test_llm.py                  # tests full Claude tool-calling conversation flow
python address_validator.py         # runs address validation integration tests
python address_validator.py quick   # tests a single address quickly
```

## Required Environment Variables

```
ANTHROPIC_API_KEY       # Claude (claude-sonnet-4-6) for LLM
DEEPGRAM_API_KEY        # STT (nova-3-medical model)
ELEVEN_API_KEY          # ElevenLabs TTS
RESEND_API_KEY          # Email confirmation delivery
SMARTYSTREETS_AUTH_ID   # Address validation
SMARTYSTREETS_AUTH_TOKEN
HOSPITAL_EMAILS         # Comma-separated list of email recipients for confirmations
```

## Architecture

### Pipeline (Pipecat)

`agent.py:run_agent()` assembles the real-time audio pipeline per call:

```
Twilio WebSocket → transport.input()
  → DeepgramSTT (nova-3-medical)
  → context_agg.user()
  → AnthropicLLMService (claude-sonnet-4-6, temp=0.1)
  → ElevenLabsTTS (voice_id hardcoded in agent.py)
  → transport.output()
  → AudioBufferProcessor (saves .wav recording)
  → context_agg.assistant()
```

`SileroVAD` handles voice activity detection. `TwilioFrameSerializer` handles Twilio's mulaw/8kHz audio format.

### Function Calling

Two tools are registered with the LLM via Pipecat's `ToolsSchema` / `FunctionSchema` (provider-agnostic — the `AnthropicLLMAdapter` converts them to Anthropic's `input_schema` format automatically):

- **`collect_patient_info`** — called after every patient utterance; stores fields into the global `PatientTracker`. Also handles phone/email/DOB validation with up to 3 retry attempts per field.
- **`validate_address`** — calls SmartyStreets API in real-time; returns spoken confirmation or error message.

Both functions accept a `FunctionCallParams` object (Pipecat convention) whose `.arguments` dict contains the actual parameters.

### State Management

`patient_tracker.py` holds two module-level globals reset per call via `set_new_tracker()`:
- `current_tracker: PatientTracker` — stores `PatientInfo` dataclass and tracks completion
- `attempt_tracker: FieldAttemptTracker` — limits retries to 3 per field (phone, email, address)

The `PatientTracker` knows the required fields (`name`, `dob`, `insurance_provider`, `insurance_id`, `chief_complaint`, `address`, `phone`, `appointment_preference`) vs optional ones (`email`, `referral_info`, `patient_status`).

### Post-Call Flow

After the pipeline finishes (`runner.run(task)` returns or raises), `agent.py` in the `finally` block:
1. Reads `PatientTracker` summary
2. Calls `send_appointment_confirmation()` from `send_email.py` if a phone number was collected
3. Logs completion percentage and missing fields

### Address Validation

`address_validator.py` → `AddressValidator` → SmartyStreets US Street Address API. Input is cleaned first (removes conversational prefixes like "my address is", converts spelled-out numbers, joins spaced-out ZIP digits). The module can be run standalone for testing.

### Email

`send_email.py:send_appointment_confirmation()` sends HTML email via Resend. The `from` address is hardcoded to `onboarding@resend.dev` (Resend's test domain). The `parse_appointment_preference()` function uses regex to extract doctor name, time, and relative day references from the LLM-generated appointment string.

## Key Design Notes

- **Global state is per-call**: `set_new_tracker()` is called at the top of `run_agent()`, resetting both trackers. This is not thread-safe for concurrent calls on the same process.
- **`runner.py`** is a Daily.co helper and appears to be unused — it's left over from a different Pipecat transport option.
- **ElevenLabs voice ID** is hardcoded in `agent.py:205`. Change it there to swap voices.
- **Hospital email recipients** fall back to a hardcoded list in `agent.py:521` if `HOSPITAL_EMAILS` env var is not set.
- The `collect_patient_info` function in `patient_tracker.py` handles the Pipecat `FunctionCallParams` protocol: it calls `function_call_params.result_callback(response)` at the end if available, which is how Pipecat routes the function result back into the pipeline.
