
Eval:
- Latency, how did we trade off test it, how can we swap out differnt component and measure those 
- accuracy, accuracy update
- Context

using LLM to decide when to call tool, for context engineering, we use tool call first, then resopnse. this would instead of using regex we use promtp to judge

Limitation, this is not thread-safe

The key decision: 
  The architecture makes the right bet: let the model handle the conversational complexity, let the code handle the structured data

---

## Measured Performance + Optimization Results

### Before (baseline, measured from test_llm.py 2026-05-25)

Real numbers from instrumented run — 7-turn scripted conversation, claude-sonnet-4-6, temp=0.1:

| Metric | Value |
|--------|-------|
| Claude first-response latency | avg 2707ms, min 1321ms, max 9042ms |
| Claude follow-up latency (after tool) | avg 1874ms, min 1351ms, max 2289ms |
| Full turn (both Claude calls combined) | avg 3510ms, min 1845ms, max 9043ms |
| Tool execution time (pure Python) | <5ms |
| Input tokens (7 turns) | 43,010 |
| Output tokens (7 turns) | 486 |
| Cost for this run | $0.1363 |
| Estimated cost per 40-turn call | $0.779 |

Estimated full end-to-end turn as patient hears it:
- Claude (measured): ~3510ms
- Deepgram Nova-3 (documented p50): ~275ms
- ElevenLabs first audio chunk: ~400ms
- Twilio network: ~100ms
- **Total estimate: ~4285ms**

4 seconds is the honest number. Users start feeling a response is slow around 2 seconds.

### What changes and why

**Change 1 — Eliminate second Claude call per turn**
The tool `collect_patient_info` already returns the spoken response (e.g. "Got it, thanks! And what's your date of birth?"). Claude then makes a second API call to paraphrase it. That second call is ~1.8s of pure waste. Fix: prompt Claude to output nothing after calling a tool — the tool result goes directly to TTS via Pipecat's result_callback.

**Change 2 — Prompt caching on the system prompt**
The system prompt (~3,800 tokens) is re-sent on every API call. Caching it with `cache_control: {"type": "ephemeral"}` means turns 2–40 skip reprocessing it. Cache hits are billed at $0.30/M instead of $3/M input — 90% cost reduction on the system prompt portion.

**Change 3 — Context window compression after turn 8**
43K input tokens for 7 turns means by turn 30 you're at ~180K tokens and cost explodes. Fix: after collecting structured data, replace verbose conversation history with a compact summary dict and keep only the last 2 turns in the message array.

**Change 4 — Model routing: Haiku for simple fields, Sonnet for complex**
Name, DOB, phone, appointment preference are simple extraction. Haiku handles these in ~300ms vs Sonnet's ~1400ms. Only insurance IDs, addresses, and chief complaint go to Sonnet. Roughly half the turns in a real call are simple fields.

### After (projected)

| Metric | Before | After |
|--------|--------|-------|
| Claude latency per turn | ~3510ms (2 calls) | ~800ms avg (1 call, Haiku/Sonnet mix) |
| Full turn with STT+TTS | ~4285ms | ~1975ms |
| Context tokens at turn 30 | ~180K | <10K |
| Cost per 40-turn call | $0.779 | ~$0.12 |

The patient-perceived improvement: 4s → 2s. That's the line between "feels broken" and "feels natural" for voice AI.