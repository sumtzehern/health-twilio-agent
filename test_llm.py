# test_llm.py
"""
Comprehensive test script to verify OpenAI function calling and patient data collection
without requiring phone calls
"""

import asyncio
import json
import os
from openai import AsyncOpenAI
from patient_tracker import (
    collect_patient_info_schema, 
    collect_patient_info, 
    set_new_tracker,
    get_current_tracker
)

async def test_conversation_flow():
    """Test the complete conversation flow with function calling"""
    
    print("🧪 Testing Complete Conversation Flow")
    print("=" * 60)
    
    # Initialize tracker
    set_new_tracker()
    
    # Initialize OpenAI client
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Enhanced system prompt (same as your agent)
    system_prompt = """You are Alexis. A friendly, proactive, highly intelligent female with a warm, highly capable, and naturally empathetic healthcare scheduling assistant with a calm, professional voice and reassuring tone.

🚨 CRITICAL FUNCTION CALLING RULE 🚨
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

🚨 REMEMBER: Function call FIRST, then respond! 🚨"""
    
    # Test conversation scenarios
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
    
    # Initialize conversation
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": "Hello! Thank you for calling Epic Health. This is Alexis, how can I help you today?"}
    ]
    
    print("🤖 Assistant: Hello! Thank you for calling Epic Health. This is Alexis, how can I help you today?")
    print()
    
    # Run through test scenarios
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"📝 Test {i}: {scenario['user_input']}")
        
        # Add user message
        messages.append({"role": "user", "content": scenario["user_input"]})
        
        try:
            # Make API call
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                functions=[collect_patient_info_schema],
                function_call="auto",
                temperature=0.1
            )
            
            message = response.choices[0].message
            
            # Check if function was called
            if hasattr(message, 'function_call') and message.function_call:
                print("✅ Function was called!")
                print(f"   Function: {message.function_call.name}")
                print(f"   Arguments: {message.function_call.arguments}")
                
                # Execute the function
                args = json.loads(message.function_call.arguments)
                result = await collect_patient_info(**args)
                
                # Add function result to conversation
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "function_call": {
                        "name": message.function_call.name,
                        "arguments": message.function_call.arguments
                    }
                })
                messages.append({
                    "role": "function",
                    "name": message.function_call.name,
                    "content": result
                })
                
                # Get follow-up response
                follow_up = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    functions=[collect_patient_info_schema],
                    function_call="auto",
                    temperature=0.1
                )
                
                assistant_response = follow_up.choices[0].message.content
                messages.append({"role": "assistant", "content": assistant_response})
                
                print(f"🤖 Assistant: {assistant_response}")
                
            else:
                print("❌ Function was NOT called")
                if message.content:
                    print(f"🤖 Assistant: {message.content}")
                    messages.append({"role": "assistant", "content": message.content})
            
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print("-" * 40)
    
    # Final status check
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
    
    # Reset tracker
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
            result = await collect_patient_info(**data)
            print(f"✅ Result: {result}")
        except Exception as e:
            print(f"❌ Error: {e}")
        print("-" * 30)
    
    # Final status
    tracker = get_current_tracker()
    summary = tracker.get_summary()
    print(f"\n📊 Final completion: {summary['completion_percentage']:.1f}%")

async def test_api_keys():
    """Test if all API keys are working"""
    
    print("\n🔑 Testing API Keys")
    print("=" * 60)
    
    # Test OpenAI
    try:
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=10
        )
        print("✅ OpenAI API: Working")
    except Exception as e:
        print(f"❌ OpenAI API: {e}")
    
    # Test other APIs (you can add Deepgram and ElevenLabs tests here)
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
