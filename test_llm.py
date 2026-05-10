# test_llm.py
"""
Comprehensive test script to verify Claude function calling and patient data collection
without requiring phone calls
"""

import asyncio
import json
import os
from anthropic import AsyncAnthropic
from patient_tracker import (
    collect_patient_info_schema,
    collect_patient_info,
    set_new_tracker,
    get_current_tracker
)

class MockFunctionCallParams:
    """Mimics Pipecat's FunctionCallParams for testing."""
    def __init__(self, **kwargs):
        self.arguments = kwargs

# Anthropic tool schema (uses input_schema instead of parameters)
anthropic_collect_patient_info_schema = {
    "name": collect_patient_info_schema["name"],
    "description": collect_patient_info_schema["description"],
    "input_schema": collect_patient_info_schema["parameters"],
}

SYSTEM_PROMPT = """You are Alexis. A friendly, proactive, highly intelligent female with a warm, highly capable, and naturally empathetic healthcare scheduling assistant with a calm, professional voice and reassuring tone.

CRITICAL FUNCTION CALLING RULE:
BEFORE responding to ANY patient message, you MUST FIRST call the `collect_patient_info` function if they shared personal information. This is MANDATORY - no exceptions.

WORKFLOW FOR EVERY RESPONSE:
1. Did patient share info? → Call collect_patient_info() FIRST
2. Then provide your conversational response

CRITICAL INSTRUCTIONS:
1. ALWAYS call the `collect_patient_info` function whenever a patient shares ANY personal information
2. You must systematically collect all required information: name, date of birth, insurance provider, insurance ID, chief complaint, address, phone, and appointment preference
3. After each piece of information is shared, immediately call the function to store it
4. Keep track of what information you still need and guide the conversation to collect missing fields
5. Be natural and conversational while ensuring all data is captured

EXAMPLE INTERACTION:
Patient: "Hi, I need to schedule an appointment. My name is John Smith."
You: *FIRST call collect_patient_info(name="John Smith")*
THEN respond: "Thanks John! I've got your name. Now, can I get your date of birth?"

REMEMBER: Function call FIRST, then respond!"""


async def test_conversation_flow():
    """Test the complete conversation flow with function calling"""

    print("🧪 Testing Complete Conversation Flow")
    print("=" * 60)

    set_new_tracker()

    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=[anthropic_collect_patient_info_schema],
                temperature=0.1
            )

            # Find tool_use block if present
            tool_use_block = next(
                (block for block in response.content if block.type == "tool_use"),
                None
            )

            if tool_use_block:
                print("✅ Function was called!")
                print(f"   Function: {tool_use_block.name}")
                print(f"   Arguments: {json.dumps(tool_use_block.input)}")

                # Execute the function with direct kwargs (input is already a dict)
                result = await collect_patient_info(MockFunctionCallParams(**tool_use_block.input))

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

                # Get follow-up response
                follow_up = await client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=[anthropic_collect_patient_info_schema],
                    temperature=0.1
                )

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
