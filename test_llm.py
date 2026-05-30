# test_llm.py
"""
Comprehensive test script to verify Claude function calling and patient data collection
without requiring phone calls
"""

import asyncio
import json
import os
import time
from anthropic import AsyncAnthropic
from patient_tracker import (
    collect_patient_info_schema,
    collect_patient_info,
    set_new_tracker,
    get_current_tracker
)
from test_helpers import MockFunctionCallParams
from prompts import SYSTEM_PROMPT

# Anthropic tool schema (uses input_schema instead of parameters)
anthropic_collect_patient_info_schema = {
    "name": collect_patient_info_schema["name"],
    "description": collect_patient_info_schema["description"],
    "input_schema": collect_patient_info_schema["parameters"],
}


async def test_conversation_flow():
    """Test the complete conversation flow with function calling"""

    print("🧪 Testing Complete Conversation Flow")
    print("=" * 60)

    set_new_tracker()

    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Latency + cost accumulators
    turn_metrics = []

    # Cached system prompt — cache_control keeps it warm across turns
    cached_system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    # Model routing: Haiku for simple single-field turns, Sonnet for complex extraction
    SIMPLE_FIELDS = {"name", "dob", "phone", "email", "patient_status", "appointment_preference"}

    def pick_model() -> str:
        nf = get_current_tracker().get_next_required_field()
        return "claude-haiku-4-5-20251001" if nf in SIMPLE_FIELDS else "claude-sonnet-4-6"

    # Per-model cost rates ($/M tokens): (input, cache_read, cache_write, output)
    MODEL_RATES = {
        "claude-sonnet-4-6":           (3.00, 0.30, 3.75, 15.00),
        "claude-haiku-4-5-20251001":   (0.80, 0.08, 1.00,  4.00),
    }

    test_scenarios = [
        {
            "user_input": "Hi, I need to schedule an appointment. My name is Sarah Johnson.",
            "expected_function_call": True,
            "expected_data": {"name": "Sarah Johnson"}
        },
        {
            "user_input": "My date of birth is March 15th, 1990.",
            "expected_function_call": True,
            "expected_data": {"dob": "03/15/1990"}
        },
        {
            "user_input": "I have Blue Cross Blue Shield insurance, ID number ABC123456.",
            "expected_function_call": True,
            "expected_data": {"insurance_provider": "Blue Cross Blue Shield", "insurance_id": "ABC123456"}
        },
        {
            "user_input": "I'm coming in for a routine checkup.",
            "expected_function_call": True,
            "expected_data": {"chief_complaint": "routine checkup"}
        },
        {
            "user_input": "My address is 123 Main Street, Springfield, IL 62701.",
            "expected_function_call": True,
            "expected_data": {"address": "123 Main Street, Springfield, IL 62701"}
        },
        {
            "user_input": "My phone number is 555-123-4567.",
            "expected_function_call": True,
            "expected_data": {"phone": "555-123-4567"}
        },
        {
            "user_input": "I prefer morning appointments, maybe around 10 AM.",
            "expected_function_call": True,
            "expected_data": {"appointment_preference": "morning appointments, around 10 AM"}
        }
    ]

    # Conversation history (without system message — passed separately in Anthropic API)
    messages = [
        {"role": "assistant", "content": "Hello! Thank you for calling Epic Health. This is Alexis, how can I help you today?"}
    ]

    print("🤖 Assistant: Hello! Thank you for calling Epic Health. This is Alexis, how can I help you today?")
    print()

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"📝 Test {i}: {scenario['user_input']}")

        messages.append({"role": "user", "content": scenario["user_input"]})

        try:
            turn_start = time.perf_counter()
            model = pick_model()

            t0 = time.perf_counter()
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                system=cached_system,
                messages=messages,
                tools=[anthropic_collect_patient_info_schema],
                temperature=0.1
            )
            claude_first_ms = (time.perf_counter() - t0) * 1000

            # Find tool_use block if present
            tool_use_block = next(
                (block for block in response.content if block.type == "tool_use"),
                None
            )

            tool_exec_ms = 0
            claude_followup_ms = 0
            followup_usage = None

            if tool_use_block:
                print("✅ Function was called!")
                print(f"   Function: {tool_use_block.name}")
                print(f"   Arguments: {json.dumps(tool_use_block.input)}")

                t1 = time.perf_counter()
                result = await collect_patient_info(MockFunctionCallParams(**tool_use_block.input))
                tool_exec_ms = (time.perf_counter() - t1) * 1000

                # Add assistant turn (tool use) and tool result to history
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_use_block.id,
                        "content": result
                    }]
                })

                t2 = time.perf_counter()
                follow_up = await client.messages.create(
                    model=model,  # same model for both calls within a turn
                    max_tokens=1024,
                    system=cached_system,
                    messages=messages,
                    tools=[anthropic_collect_patient_info_schema],
                    temperature=0.1
                )
                claude_followup_ms = (time.perf_counter() - t2) * 1000
                followup_usage = follow_up.usage

                assistant_text = next(
                    (block.text for block in follow_up.content if hasattr(block, "text")),
                    ""
                )
                messages.append({"role": "assistant", "content": assistant_text})
                print(f"🤖 Assistant: {assistant_text}")

            else:
                print("❌ Function was NOT called")
                text = next(
                    (block.text for block in response.content if hasattr(block, "text")),
                    ""
                )
                if text:
                    print(f"🤖 Assistant: {text}")
                    messages.append({"role": "assistant", "content": text})

            turn_ms = (time.perf_counter() - turn_start) * 1000

            # input_tokens already excludes cache tokens — they're reported separately
            def calc_cost(usage, mdl):
                if usage is None:
                    return 0, 0, 0, 0, 0
                ri, rr, rw, ro = MODEL_RATES.get(mdl, MODEL_RATES["claude-sonnet-4-6"])
                read  = getattr(usage, "cache_read_input_tokens", 0) or 0
                write = getattr(usage, "cache_creation_input_tokens", 0) or 0
                regular_in = usage.input_tokens
                out = usage.output_tokens
                cost = (regular_in * ri + read * rr + write * rw + out * ro) / 1_000_000
                return regular_in, read, write, out, cost

            r1_in, r1_read, r1_write, r1_out, c1 = calc_cost(response.usage, model)
            r2_in, r2_read, r2_write, r2_out, c2 = calc_cost(followup_usage, model)

            turn_cost = c1 + c2
            cache_read  = r1_read + r2_read
            cache_write = r1_write + r2_write

            model_tag = "haiku" if "haiku" in model else "sonnet"
            metrics = {
                "turn": i,
                "model": model_tag,
                "claude_first_ms": round(claude_first_ms),
                "tool_exec_ms": round(tool_exec_ms),
                "claude_followup_ms": round(claude_followup_ms),
                "total_turn_ms": round(turn_ms),
                "input_tokens": r1_in + r2_in,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "output_tokens": r1_out + r2_out,
                "cost_usd": round(turn_cost, 5),
            }
            turn_metrics.append(metrics)
            cache_tag = f"  cache=+{cache_write}w/{cache_read}r" if (cache_read or cache_write) else ""
            print(f"   [{model_tag}] first={claude_first_ms:.0f}ms  tool={tool_exec_ms:.0f}ms  followup={claude_followup_ms:.0f}ms  total={turn_ms:.0f}ms  cost=${turn_cost:.4f}{cache_tag}")

            # Context compression: replace history with compact state after every 4 turns.
            # (Production threshold: 8-10 turns. Set to 4 here so it fires in this 7-turn test.)
            COMPRESS_EVERY = 4
            if i % COMPRESS_EVERY == 0:
                state_summary = get_current_tracker().to_context_summary()
                tokens_before = sum(len(str(m)) for m in messages)
                messages = [
                    {"role": "user",      "content": state_summary},
                    {"role": "assistant", "content": "Understood, I have the session state. Continuing."},
                    *messages[-2:]  # keep last 2 turns for conversational continuity
                ]
                tokens_after = sum(len(str(m)) for m in messages)
                print(f"   [compress] history trimmed: ~{tokens_before} → ~{tokens_after} chars  ({len(messages)} messages kept)")

        except Exception as e:
            print(f"❌ Error: {e}")

        print("-" * 40)

    print("\n📊 FINAL STATUS:")
    tracker = get_current_tracker()
    summary = tracker.get_summary()

    print(f"Completion: {summary['completion_percentage']:.1f}%")
    print(f"Collected Data: {json.dumps(summary['patient_info'], indent=2)}")
    print(f"Missing Fields: {summary['missing_required']}")
    print(f"Is Complete: {summary['is_complete']}")

    if turn_metrics:
        print("\n⏱  LATENCY + COST REPORT")
        print("=" * 60)
        first_calls  = [m["claude_first_ms"] for m in turn_metrics]
        followups    = [m["claude_followup_ms"] for m in turn_metrics if m["claude_followup_ms"]]
        totals       = [m["total_turn_ms"] for m in turn_metrics]
        total_cost   = sum(m["cost_usd"] for m in turn_metrics)
        total_in     = sum(m["input_tokens"] for m in turn_metrics)
        total_out    = sum(m["output_tokens"] for m in turn_metrics)

        print(f"Claude first-response  avg={sum(first_calls)/len(first_calls):.0f}ms  "
              f"min={min(first_calls):.0f}ms  max={max(first_calls):.0f}ms")
        if followups:
            print(f"Claude follow-up       avg={sum(followups)/len(followups):.0f}ms  "
                  f"min={min(followups):.0f}ms  max={max(followups):.0f}ms")
        print(f"Full turn (both calls) avg={sum(totals)/len(totals):.0f}ms  "
              f"min={min(totals):.0f}ms  max={max(totals):.0f}ms")
        total_cache_read  = sum(m.get("cache_read_tokens", 0) for m in turn_metrics)
        total_cache_write = sum(m.get("cache_write_tokens", 0) for m in turn_metrics)
        print(f"Tokens  in={total_in}  out={total_out}  cache_read={total_cache_read}  cache_write={total_cache_write}")
        print(f"Cost this run: ${total_cost:.4f}")
        print(f"Estimated cost per 40-turn call: ${total_cost/len(turn_metrics)*40:.3f}")
        print(f"\n  Estimated end-to-end turn (with STT+TTS):")
        avg_claude = sum(totals)/len(totals)
        print(f"    Claude (measured):   {avg_claude:.0f}ms")
        print(f"    Deepgram Nova-3:     ~275ms  (documented p50)")
        print(f"    ElevenLabs TTS:      ~400ms  (first audio chunk)")
        print(f"    Twilio network:      ~100ms  (round-trip)")
        print(f"    --------------------------------")
        print(f"    Total estimate:      ~{avg_claude+275+400+100:.0f}ms")


async def test_individual_function_calls():
    """Test individual function calls with specific data"""

    print("\n🔧 Testing Individual Function Calls")
    print("=" * 60)

    set_new_tracker()

    test_data = [
        {"name": "John Doe"},
        {"dob": "01/15/1985"},
        {"insurance_provider": "Aetna", "insurance_id": "XYZ789"},
        {"chief_complaint": "annual physical"},
        {"address": "456 Oak Ave, Chicago, IL 60601"},
        {"phone": "312-555-0123"},
        {"appointment_preference": "Tuesday afternoons"}
    ]

    for i, data in enumerate(test_data, 1):
        print(f"Test {i}: {data}")
        try:
            result = await collect_patient_info(MockFunctionCallParams(**data))
            print(f"✅ Result: {result}")
        except Exception as e:
            print(f"❌ Error: {e}")
        print("-" * 30)

    tracker = get_current_tracker()
    summary = tracker.get_summary()
    print(f"\n📊 Final completion: {summary['completion_percentage']:.1f}%")


async def test_api_keys():
    """Test if all API keys are working"""

    print("\n🔑 Testing API Keys")
    print("=" * 60)

    try:
        client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hello"}]
        )
        print("✅ Anthropic API: Working")
    except Exception as e:
        print(f"❌ Anthropic API: {e}")

    print("✅ Deepgram API: Skipped (requires audio)")
    print("✅ ElevenLabs API: Skipped (requires TTS)")


async def main():
    """Run all tests"""
    print("🚀 Starting Comprehensive Function Calling Tests")
    print("=" * 80)

    await test_api_keys()
    await test_individual_function_calls()
    await test_conversation_flow()

    print("\n🎉 All tests completed!")

if __name__ == "__main__":
    asyncio.run(main())
