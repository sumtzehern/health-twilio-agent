# Alexis — AI Voice Agent for Healthcare Appointment Scheduling

An AI-powered phone agent that handles patient intake end-to-end: answers calls via Twilio, runs a real-time Pipecat audio pipeline (STT → Claude → TTS), collects structured patient data through function calling, validates addresses against USPS, and sends confirmation emails post-call.

---

## The Design Problem

Phone-based patient intake is a solved problem for humans — a receptionist asks questions, listens, corrects errors, and types into a form. The engineering challenge is replicating that loop under voice latency constraints where each pipeline stage must complete in under 300ms or the conversation feels broken.

The naive approach (transcribe → send full context to LLM → speak response) introduces 3–5 seconds of silence per turn. That's a dead phone call. Every architectural decision in this system exists to eliminate or hide that latency.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          INBOUND CALL FLOW                              │
└─────────────────────────────────────────────────────────────────────────┘
git
  Patient Phone
       │
       │  PSTN (mulaw 8kHz)
       ▼
┌─────────────┐    TwiML webhook     ┌──────────────────┐
│   Twilio    │ ──────────────────▶  │  FastAPI /        │
│  (PSTN GW)  │                      │  POST → TwiML     │
│             │ ◀────────────────── │  GET /audio-stream│
└─────────────┘  WebSocket (mulaw)   └────────┬─────────┘
                                              │
                                              ▼
                          ┌───────────────────────────────────┐
                          │       Pipecat Pipeline (async)     │
                          │                                    │
                          │  ┌──────────────────────────────┐ │
                          │  │  FastAPIWebsocketTransport   │ │
                          │  │  + TwilioFrameSerializer     │ │
                          │  └────────────┬─────────────────┘ │
                          │               │ raw audio frames   │
                          │               ▼                    │
                          │  ┌──────────────────────────────┐ │
                          │  │    SileroVAD (local CPU)     │ │
                          │  │  end-of-speech detection     │ │
                          │  └────────────┬─────────────────┘ │
                          │               │ speech segments    │
                          │               ▼                    │
                          │  ┌──────────────────────────────┐ │
                          │  │   Deepgram STT               │ │
                          │  │   model: nova-3-medical      │ │
                          │  └────────────┬─────────────────┘ │
                          │               │ transcript text    │
                          │               ▼                    │
                          │  ┌──────────────────────────────┐ │
                          │  │  LLMContext aggregator │ │
                          │  │  (message history + tools)   │ │
                          │  └────────────┬─────────────────┘ │
                          │               │ messages[]         │
                          │               ▼                    │
                          │  ┌──────────────────────────────┐ │
                          │  │  AnthropicLLMService         │ │
                          │  │  claude-sonnet-4-6, temp=0.1 │ │
                          │  │                              │ │
                          │  │  registered tools:           │ │
                          │  │  • collect_patient_info      │ │
                          │  │  • validate_address          │ │
                          │  └──────┬───────────────────────┘ │
                          │         │                          │
                          │    ┌────┴─────────────────────┐   │
                          │    │   function call dispatch  │   │
                          │    └────┬──────────┬──────────┘   │
                          │         │          │               │
                          │         ▼          ▼               │
                          │  ┌──────────┐ ┌───────────────┐  │
                          │  │PatientTr-│ │AddressValidator│  │
                          │  │acker +   │ │SmartyStreets   │  │
                          │  │Attempt   │ │US Street API   │  │
                          │  │Tracker   │ └───────┬───────┘  │
                          │  └────┬─────┘         │           │
                          │       └───────┬────────┘           │
                          │               │ tool result string  │
                          │               ▼                    │
                          │  ┌──────────────────────────────┐ │
                          │  │     ElevenLabs TTS           │ │
                          │  │     (streaming synthesis)    │ │
                          │  └────────────┬─────────────────┘ │
                          │               │ audio frames       │
                          │               ▼                    │
                          │  ┌──────────────────────────────┐ │
                          │  │  FastAPIWebsocket output     │ │
                          │  │  + AudioBufferProcessor      │ │
                          │  │    (saves .wav recording)    │ │
                          │  └──────────────────────────────┘ │
                          └───────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                         POST-CALL FLOW                                  │
└─────────────────────────────────────────────────────────────────────────┘

  call ends
     │
     ▼
  agent.py finally block
     │
     ├── PatientTracker.get_summary()
     │         (completion %, missing fields)
     │
     └── send_appointment_confirmation()
               │
               └── Resend API → HTML email → hospital_emails[]


┌─────────────────────────────────────────────────────────────────────────┐
│                     STATE PER CALL                                      │
└─────────────────────────────────────────────────────────────────────────┘

  set_new_tracker() called at top of run_agent()
        │
        ├── PatientTracker  (PatientInfo dataclass + required/optional sets)
        └── FieldAttemptTracker  (per-field retry counter, max=3)
```

---

## Why These Decisions

### Pipecat over a custom pipeline

Pipecat solves the hardest part of real-time voice AI: composing async streaming stages that each have different I/O contracts (raw bytes vs. frames vs. text vs. API responses) without introducing head-of-line blocking. Building that from scratch means reimplementing backpressure, cancellation, and frame routing — all before writing a line of product logic. Pipecat's `Pipeline` / `PipelineTask` model gives us all of that and lets us swap transport (Twilio today, Daily.co tomorrow) or TTS provider without touching the core conversation logic.

The `AnthropicLLMAdapter` inside Pipecat is also load-bearing: it translates Pipecat's provider-agnostic `FunctionSchema` / `ToolsSchema` into Anthropic's `input_schema` format automatically. That means the tool definitions in `patient_tracker.py` are portable — they don't encode any Anthropic-specific wire format.

### Deepgram Nova-3 Medical over a general STT model

Medical intake conversations are a worst-case input for general STT models. Patients say things like "I have Humana, my member ID is HMK dash 4 4 7 7 2 1" or "I was referred by Dr. Ciminelli." General models degrade significantly on insurance company names, drug names, and doctor surnames — exactly the fields this agent collects.

Nova-3 Medical is trained on clinical audio and handles these terms with meaningfully higher accuracy. A transcription error on an insurance ID propagates as bad data into the confirmation email and downstream systems — there's no human in the loop to catch it. The model choice is a data-quality decision, not a cost decision.

### Silero VAD running locally

VAD (voice activity detection) decides when a patient has finished speaking and the LLM turn should begin. If VAD is remote (an API call), you add a round-trip to the hottest part of the latency path — every single turn. Silero runs on CPU inside the same process as the pipeline, adding ~5ms instead of ~150ms. The tradeoff is a slightly higher memory footprint, which is acceptable for a single-call server process.

VAD also gates the entire pipeline: without it, the STT service streams continuously and the LLM would receive a fragmented, incomplete turn on every pause. Silero's end-of-speech detection ensures Claude sees complete patient utterances.

### Claude with function calling for structured extraction

The core problem in intake is bridging natural language to a structured record. A patient doesn't say "my chief_complaint is lower back pain" — they say "my back's been killing me for two weeks, probably from sitting at my desk." The agent needs to decide what to write into each field.

Claude's function calling is the right primitive here for two reasons:

1. **Reliability at low temperature.** The LLM runs at `temperature=0.1`. Function calls are the primary output mechanism, not prose. This produces deterministic field extraction with very low hallucination rate on factual fields like names, DOBs, and insurance IDs.

2. **Tool result routing.** When `collect_patient_info` or `validate_address` return a string, Pipecat routes that string back into the LLM context as the tool result, which Claude then speaks. The conversation control logic (what to ask next, how to handle a failed validation) lives in the tool return value and the system prompt — not in application code. The LLM is the state machine.

### 3-attempt fallback per field

Infinite retries on a failed field will cause call abandonment. One attempt is not enough for voice input, where the first transcription might be noisy or incomplete. Three is a standard in IVR design: it's enough for the patient to correct a genuine error without feeling interrogated.

The `FieldAttemptTracker` enforces this at the tool layer, not in the system prompt. System-prompt instructions ("try 3 times") can be ignored by the model mid-conversation; code cannot. When `attempt_tracker.should_retry(field)` returns `False`, the tool unconditionally moves on. The LLM never has the option to retry further.

### Post-call transcript parsing as a safety net

During a live call, function calls can be missed — the patient answers two questions at once, or interrupts before the tool fires. The `parse_transcript_for_patient_info()` function is a second Claude pass over the full conversation transcript after the call ends. It catches fields that the real-time path dropped.

This is defense-in-depth: the primary collection mechanism is real-time function calling; the secondary is post-call NLP. The confirmation email is assembled from the merged result of both. The cost of the second API call (~$0.003 for a typical call length) is trivially justified against the cost of an incomplete patient record.

### Global module-level state reset per call

`PatientTracker` and `FieldAttemptTracker` are module-level globals reset by `set_new_tracker()` at the top of each `run_agent()` invocation. This is a deliberate simplicity tradeoff for a single-call-per-process deployment model. Thread safety would require passing tracker instances through the entire Pipecat pipeline call chain — a significant complexity cost for a scenario (concurrent calls on one process) that isn't the target deployment. The design is honest about its constraints: CLAUDE.md calls this out explicitly.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in API keys

python main.py         # production
python main.py --test  # disables continuous audio stream
```

Twilio webhook: configure your number to `POST https://<ngrok-url>/`. Update `templates/streams.xml` with your public WebSocket URL.

### Required environment variables

```
ANTHROPIC_API_KEY         # claude-sonnet-4-6
DEEPGRAM_API_KEY          # nova-3-medical STT
ELEVEN_API_KEY            # ElevenLabs TTS
RESEND_API_KEY            # post-call email
SMARTYSTREETS_AUTH_ID     # USPS address validation
SMARTYSTREETS_AUTH_TOKEN
HOSPITAL_EMAILS           # comma-separated recipient list
```

### Tests

```bash
python test_patient_collection.py   # PatientTracker, field validation, retry logic
python test_llm.py                  # full Claude tool-calling conversation flow
python address_validator.py         # SmartyStreets integration
python address_validator.py quick   # single address smoke test
```

---

## What the Email Confirmation Looks Like

<img width="604" alt="Confirmation email" src="https://github.com/user-attachments/assets/91fa337a-bcc5-4de5-b7c9-08fcb2a3e872" />
<img width="605" alt="Confirmation email detail" src="https://github.com/user-attachments/assets/65f4260e-6030-4abf-952d-606816cec14a" />

---

## Known Constraints

- **Single-call-per-process only.** Global state is not thread-safe. Run one server instance per concurrent call (or add proper session isolation).
- **ElevenLabs voice ID is hardcoded** in `agent.py:204`. Change it there to swap voices.
- **`runner.py`** is a Daily.co transport leftover. Unused.
- **`from` address** in `send_email.py` uses Resend's `onboarding@resend.dev` test domain. Configure a real domain for production.
- **`parse_appointment_preference()`** in `send_email.py` uses regex to extract doctor name, time, and day from the LLM-generated appointment string. It's brittle to novel phrasings — a structured tool call would be more reliable.
