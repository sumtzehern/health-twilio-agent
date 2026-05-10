# test_patient_collection.py
"""
Simple test script to verify patient information collection
"""

import asyncio
import json
from patient_tracker import (
    PatientTracker,
    collect_patient_info,
    set_new_tracker,
    get_current_tracker
)
from test_helpers import MockFunctionCallParams

async def test_data_collection():
    """Test the patient data collection system"""
    
    print("Testing Patient Information Collection System")
    print("=" * 50)
    
    # Initialize tracker
    tracker = set_new_tracker()
    
    # Test scenarios
    test_scenarios = [
        {
            "description": "Collect basic name",
            "data": {"name": "John Smith"}
        },
        {
            "description": "Add date of birth",
            "data": {"dob": "03/15/1985"}
        },
        {
            "description": "Add insurance info",
            "data": {"insurance_provider": "Blue Cross Blue Shield", "insurance_id": "ABC123456"}
        },
        {
            "description": "Add contact info",
            "data": {"phone": "555-123-4567", "email": "john.smith@email.com"}
        },
        {
            "description": "Add visit reason",
            "data": {"chief_complaint": "Annual physical exam"}
        },
        {
            "description": "Add address",
            "data": {"address": "123 Main St, Boston, MA 02101"}
        },
        {
            "description": "Add appointment preference",
            "data": {"appointment_preference": "Wednesday afternoon or Friday morning"}
        }
    ]
    
    # Run test scenarios
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n{i}. {scenario['description']}")
        print(f"   Input: {scenario['data']}")
        
        # Call the collection function
        response = await collect_patient_info(MockFunctionCallParams(**scenario['data']))
        print(f"   Response: {response[:100]}...")
        
        # Show current status
        current_tracker = get_current_tracker()
        summary = current_tracker.get_summary()
        print(f"   Completion: {summary['completion_percentage']:.1f}%")
        print(f"   Missing: {summary['missing_required']}")
    
    # Final summary
    print("\n" + "=" * 50)
    print("FINAL PATIENT INFORMATION")
    print("=" * 50)
    
    final_tracker = get_current_tracker()
    final_summary = final_tracker.get_summary()
    
    print(f"Completion Status: {final_summary['completion_percentage']:.1f}%")
    print(f"Is Complete: {final_summary['is_complete']}")
    print(f"Missing Fields: {final_summary['missing_required']}")
    
    print("\n📋 Collected Information:")
    print(json.dumps(final_summary['patient_info'], indent=2))
    
    return final_summary

async def test_incomplete_scenario():
    """Test handling of incomplete information"""
    
    print("\n🔍 Testing Incomplete Information Handling")
    print("=" * 50)
    
    # Reset tracker
    tracker = set_new_tracker()
    
    # Collect only partial information
    partial_data = {
        "name": "Jane Doe",
        "phone": "555-987-6543",
        "chief_complaint": "Follow-up appointment"
    }
    
    response = await collect_patient_info(MockFunctionCallParams(**partial_data))
    print(f"Response: {response}")
    
    summary = get_current_tracker().get_summary()
    print(f"\nCompletion: {summary['completion_percentage']:.1f}%")
    print(f"Next field needed: {summary['next_field_needed']}")
    print(f"Missing required: {summary['missing_required']}")

async def test_validation():
    """Test data validation"""
    
    print("\n🔍 Testing Data Validation")
    print("=" * 50)
    
    from patient_tracker import validate_phone, validate_email, validate_dob
    
    test_cases = [
        ("Phone", validate_phone, ["555-123-4567", "5551234567", "555.123.4567", "invalid"]),
        ("Email", validate_email, ["test@example.com", "user.name@domain.org", "invalid-email", "test@"]),
        ("Date", validate_dob, ["03/15/1985", "1985-03-15", "03-15-1985", "invalid-date"])
    ]
    
    for field_type, validator, test_values in test_cases:
        print(f"\n{field_type} Validation:")
        for value in test_values:
            result = validator(value)
            status = "Valid" if result else "Invalid"
            print(f"  {value:20} -> {status}")

async def main():
    """Run all tests"""
    print("Starting Patient Collection System Tests\n")
    
    # Test 1: Complete data collection
    await test_data_collection()
    
    # Test 2: Incomplete data handling
    await test_incomplete_scenario()
    
    # Test 3: Data validation
    await test_validation()
    
    print("\n✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(main())