# patient_tracker.py

import json
import logging
from datetime import datetime
from typing import Dict, Set, Optional, Any, List
from dataclasses import dataclass, asdict
from enum import Enum
from address_validator import validate_patient_address

logger = logging.getLogger(__name__)

class FieldStatus(Enum):
    MISSING = "missing"
    PARTIAL = "partial"
    COMPLETE = "complete"
    VALIDATED = "validated"

@dataclass
class PatientInfo:
    """Structured patient information with validation"""
    name: Optional[str] = None
    dob: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_id: Optional[str] = None
    chief_complaint: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    appointment_preference: Optional[str] = None
    referral_info: Optional[str] = None
    patient_status: Optional[str] = None  # new/returning
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def get_completed_fields(self) -> Set[str]:
        """Return set of fields that have values"""
        return {k for k, v in asdict(self).items() if v is not None and v.strip()}

class PatientTracker:
    """patient tracker with field validation and completion tracking"""
    
    def __init__(self):
        self.patient_info = PatientInfo()
        self.required_fields = {
            "name", "dob", "insurance_provider", "insurance_id", 
            "chief_complaint", "address", "phone", "appointment_preference"
        }
        self.optional_fields = {"email", "referral_info", "patient_status"}
        self.field_prompts = {
            "name": "Can I get your full name, please?",
            "dob": "And your date of birth?",
            "insurance_provider": "What's the name of your insurance provider?",
            "insurance_id": "What's your insurance ID number?",
            "chief_complaint": "What's the main reason for your visit today?",
            "address": "Can I grab your current address for our records?",
            "phone": "What's your best phone number?",
            "email": "Would you like to provide an email for appointment reminders?",
            "appointment_preference": "What days and times work best for you?",
            "referral_info": "Were you referred by another doctor?",
            "patient_status": "Are you a new patient or returning patient?"
        }
        self.validation_attempts = {}
    
    def update_field(self, field_name: str, value: Any) -> bool:
        """Update a specific field with validation"""
        if hasattr(self.patient_info, field_name):
            # Basic validation
            if value and str(value).strip():
                setattr(self.patient_info, field_name, str(value).strip())
                logger.info(f"Updated {field_name}: {value}")
                return True
            else:
                logger.warning(f"Invalid value for {field_name}: {value}")
                return False
        return False
    
    def update_multiple_fields(self, data: Dict[str, Any]) -> Dict[str, bool]:
        """Update multiple fields at once"""
        results = {}
        for field, value in data.items():
            results[field] = self.update_field(field, value)
        return results
    
    def get_missing_required_fields(self) -> Set[str]:
        """Get list of missing required fields"""
        completed = self.patient_info.get_completed_fields()
        return self.required_fields - completed
    
    def get_completion_percentage(self) -> float:
        """Get completion percentage of required fields"""
        completed = len(self.patient_info.get_completed_fields() & self.required_fields)
        return (completed / len(self.required_fields)) * 100
    
    def is_complete(self) -> bool:
        """Check if all required fields are completed"""
        return len(self.get_missing_required_fields()) == 0
    
    def get_next_required_field(self) -> Optional[str]:
        """Get the next missing required field to collect"""
        missing = self.get_missing_required_fields()
        if not missing:
            return None
        
        # Return fields in logical order
        field_order = ["name", "dob", "phone", "insurance_provider", "insurance_id", 
                      "chief_complaint", "address", "appointment_preference"]
        
        for field in field_order:
            if field in missing:
                return field
        
        # Return any remaining missing field
        return next(iter(missing))
    
    def get_field_prompt(self, field_name: str) -> str:
        """Get the prompt for a specific field"""
        return self.field_prompts.get(field_name, f"Please provide your {field_name}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of current patient information"""
        return {
            "patient_info": self.patient_info.to_dict(),
            "completion_percentage": self.get_completion_percentage(),
            "missing_required": list(self.get_missing_required_fields()),
            "is_complete": self.is_complete(),
            "next_field_needed": self.get_next_required_field()
        }
    
    def reset(self):
        """Reset patient information for new call"""
        self.patient_info = PatientInfo()
        self.validation_attempts = {}
        logger.info("Patient tracker reset for new call")

# Global tracker instance
current_tracker = None

def get_current_tracker() -> PatientTracker:
    """Get the current patient tracker instance"""
    global current_tracker
    if current_tracker is None:
        current_tracker = PatientTracker()
    return current_tracker

def set_new_tracker():
    """Create a new tracker instance"""
    global current_tracker
    current_tracker = PatientTracker()
    return current_tracker

# Function schemas for OpenAI function calling
collect_patient_info_schema = {
    "name": "collect_patient_info",
    "description": "Extract and store patient information from conversation. Call this whenever the patient provides any personal information.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Patient's full name"
            },
            "dob": {
                "type": "string", 
                "description": "Date of birth in MM/DD/YYYY format"
            },
            "insurance_provider": {
                "type": "string",
                "description": "Insurance company name (e.g., Blue Cross, Aetna, Medicare)"
            },
            "insurance_id": {
                "type": "string",
                "description": "Insurance ID/member number"
            },
            "chief_complaint": {
                "type": "string",
                "description": "Main reason for visit or health concern"
            },
            "address": {
                "type": "string",
                "description": "Full address including street, city, state, zip"
            },
            "phone": {
                "type": "string",
                "description": "Phone number"
            },
            "email": {
                "type": "string",
                "description": "Email address"
            },
            "appointment_preference": {
                "type": "string",
                "description": "Preferred appointment time/day"
            },
            "referral_info": {
                "type": "string",
                "description": "Referring doctor or self-referral information"
            },
            "patient_status": {
                "type": "string",
                "description": "Whether patient is new or returning"
            }
        },
        "required": []  # No required params - extract what's available
    }
}

async def collect_patient_info(function_call_params) -> str:
    """Function to collect and store patient information - handles Pipecat's FunctionCallParams"""
    logger.info("🔥 collect_patient_info function called!")
    
    # Extract the arguments from FunctionCallParams object
    kwargs = function_call_params.arguments if hasattr(function_call_params, 'arguments') else {}
    logger.info(f"📥 Received arguments: {json.dumps(kwargs, indent=2)}")
    
    tracker = get_current_tracker()
    
    # Special handling for address validation
    if 'address' in kwargs and kwargs['address']:
        address = kwargs['address']
        logger.info(f"🏠 Validating address: {address}")
        
        try:
            is_valid, message, formatted_address = await validate_patient_address(address)
            
            if is_valid and formatted_address:
                # Use the validated/formatted address
                kwargs['address'] = formatted_address
                logger.info(f"✅ Address validated and formatted: {formatted_address}")
            else:
                # Address validation failed - still store what they provided but ask for clarification
                logger.warning(f"⚠️ Address validation failed: {message}")
                
                # Store the original address
                results = tracker.update_multiple_fields(kwargs)
                
                # Return the validation message
                if hasattr(function_call_params, 'result_callback'):
                    await function_call_params.result_callback(message)
                return message
                
        except Exception as e:
            logger.error(f"❌ Address validation error: {e}")
            # Continue with original address if validation service fails
            pass
    
    # Update fields that were provided
    results = tracker.update_multiple_fields(kwargs)
    updated_fields = [k for k, v in results.items() if v]
    
    if updated_fields:
        logger.info(f"✅ Updated patient fields: {updated_fields}")
    else:
        logger.warning("⚠️ No fields were updated - check data format")
    
    # Get current status
    summary = tracker.get_summary()
    completion = summary["completion_percentage"]
    missing = summary["missing_required"]
    next_field = summary["next_field_needed"]
    
    logger.info(f"📊 Current completion: {completion:.1f}%")
    logger.info(f"📋 Missing fields: {missing}")
    logger.info(f"➡️ Next field needed: {next_field}")
    
    # Generate natural, conversational responses
    if tracker.is_complete():
        # Create a natural confirmation summary
        info = tracker.patient_info
        response = f"Perfect! I have everything I need. Just to confirm - I have you down as {info.name}, born {info.dob}, with {info.insurance_provider} insurance. You're coming in for {info.chief_complaint}, and you prefer {info.appointment_preference} appointments. Does that all sound correct?"
        
    elif next_field:
        # Natural prompts for next field
        natural_prompts = {
            "name": "Can I get your full name, please?",
            "dob": "And what's your date of birth?",
            "phone": "What's the best phone number to reach you at?",
            "insurance_provider": "What insurance company do you have?",
            "insurance_id": "And what's your member ID number?",
            "chief_complaint": "What brings you in today? Is this for a routine check-up or something specific?",
            "address": "Can I get your current address for our records?",
            "appointment_preference": "What days and times work best for your schedule?",
            "email": "Would you like to give me an email address for appointment reminders?",
            "referral_info": "Were you referred by another doctor, or are you scheduling this yourself?",
            "patient_status": "Are you a new patient with us, or have you been here before?"
        }
        
        prompt = natural_prompts.get(next_field, f"Can you tell me about your {next_field.replace('_', ' ')}?")
        
        # Add acknowledgment of what was just provided
        if updated_fields:
            last_field = updated_fields[-1]
            acknowledgments = {
                "name": "Got it, thanks!",
                "dob": "Perfect.",
                "phone": "Great, I've got that number.",
                "insurance_provider": "Okay, noted.",
                "insurance_id": "Thanks for that.",
                "chief_complaint": "Understood.",
                "address": "Thank you.", # This will be overridden by validation message if address was provided
                "appointment_preference": "Sounds good.",
                "email": "Perfect.",
                "referral_info": "Got it.",
                "patient_status": "Thanks for letting me know."
            }
            
            # Special case for validated address
            if last_field == "address" and 'address' in kwargs:
                ack = "Perfect! I've confirmed that address."
            else:
                ack = acknowledgments.get(last_field, "Thanks.")
                
            response = f"{ack} {prompt}"
        else:
            response = prompt
            
    else:
        response = "Thanks for that information. Is there anything else you'd like to add or update?"
    
    logger.info(f"📤 Function returning response: {response}")
    
    # Call the result callback as required by Pipecat
    if hasattr(function_call_params, 'result_callback'):
        await function_call_params.result_callback(response)
    
    return response

# Validation functions
def validate_phone(phone: str) -> bool:
    """Basic phone validation"""
    import re
    # Remove all non-digits
    digits = re.sub(r'\D', '', phone)
    return len(digits) >= 10

def validate_email(email: str) -> bool:
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_dob(dob: str) -> bool:
    """Basic date of birth validation"""
    try:
        # Try to parse various date formats
        for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%m/%d/%y']:
            try:
                datetime.strptime(dob, fmt)
                return True
            except ValueError:
                continue
        return False
    except:
        return False