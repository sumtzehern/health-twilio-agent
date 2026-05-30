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

    def to_context_summary(self) -> str:
        """Compact state string to replace verbose conversation history mid-call.
        Keeps context under ~500 tokens regardless of call length."""
        collected = {k: v for k, v in self.patient_info.to_dict().items() if v}
        missing = list(self.get_missing_required_fields())
        return (
            f"[SESSION STATE]\n"
            f"Collected: {json.dumps(collected)}\n"
            f"Still needed: {missing}\n"
            f"Continue collecting missing fields conversationally."
        )
    
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
    global current_tracker, attempt_tracker
    current_tracker = PatientTracker()
    attempt_tracker = FieldAttemptTracker()
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
        "required": []
    }
}

validate_address_schema = {
    "name": "validate_address",
    "description": "Validate patient address in real-time during conversation. Call this when patient provides address information to ensure accuracy.",
    "parameters": {
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "The address string to validate (street, city, state, zip)"
            }
        },
        "required": ["address"]
    }
}

# Add field attempt tracking
class FieldAttemptTracker:
    def __init__(self):
        self.attempts = {}
        self.max_attempts = 3
    
    def increment_attempt(self, field: str) -> int:
        """Increment and return attempt count for a field"""
        self.attempts[field] = self.attempts.get(field, 0) + 1
        return self.attempts[field]
    
    def get_attempts(self, field: str) -> int:
        """Get current attempt count for a field"""
        return self.attempts.get(field, 0)
    
    def should_retry(self, field: str) -> bool:
        """Check if we should retry collecting this field"""
        return self.get_attempts(field) < self.max_attempts
    
    def mark_as_failed(self, field: str):
        """Mark field as failed after max attempts"""
        self.attempts[field] = self.max_attempts

# Global attempt tracker
attempt_tracker = FieldAttemptTracker()

async def collect_patient_info(function_call_params) -> str:
    """Enhanced function to collect and store patient information with robust missing field handling"""
    logger.info("🔥 collect_patient_info function called!")
    
    # Extract the arguments from FunctionCallParams object
    kwargs = function_call_params.arguments if hasattr(function_call_params, 'arguments') else {}
    logger.info(f"📥 Received arguments: {json.dumps(kwargs, indent=2)}")
    
    tracker = get_current_tracker()
    global attempt_tracker
    
    # Special handling for address validation with retry logic
    if 'address' in kwargs and kwargs['address']:
        address = kwargs['address']
        logger.info(f"🏠 Validating address: {address}")
        
        try:
            is_valid, message, formatted_address = await validate_patient_address(address)
            attempt_count = attempt_tracker.increment_attempt('address')
            
            if is_valid and formatted_address:
                # Use the validated/formatted address
                kwargs['address'] = formatted_address
                logger.info(f"✅ Address validated and formatted: {formatted_address}")
                # Reset attempts for successful validation
                attempt_tracker.attempts['address'] = 0
            else:
                # Address validation failed
                logger.warning(f"⚠️ Address validation failed (attempt {attempt_count}): {message}")
                
                if attempt_tracker.should_retry('address'):
                    # Store the original address but ask for retry
                    results = tracker.update_multiple_fields(kwargs)
                    return f"I'm having trouble finding that exact address. Could you please repeat it slowly, including the street number, name, city, state, and ZIP code? (Attempt {attempt_count} of {attempt_tracker.max_attempts})"
                else:
                    # Max attempts reached - accept the address and move on
                    attempt_tracker.mark_as_failed('address')
                    kwargs['address'] = address  # Use original address
                    logger.info(f"📝 Max address attempts reached, storing original: {address}")
                    results = tracker.update_multiple_fields(kwargs)
                    return "I'll record the address as you provided it and we can verify it when you arrive. Now, let's continue with the next question."
                
        except Exception as e:
            logger.error(f"❌ Address validation error: {e}")
            # Continue with original address if validation service fails
            pass
    
    # Enhanced phone validation with retry logic
    if 'phone' in kwargs and kwargs['phone']:
        phone = kwargs['phone']
        attempt_count = attempt_tracker.increment_attempt('phone')
        is_valid, formatted_or_error = validate_phone(phone)
        
        if is_valid:
            kwargs['phone'] = formatted_or_error  # Use formatted version
            logger.info(f"📞 Phone validated and formatted: {formatted_or_error}")
            attempt_tracker.attempts['phone'] = 0  # Reset on success
        else:
            logger.warning(f"📞 Phone validation failed (attempt {attempt_count}): {formatted_or_error}")
            
            if attempt_tracker.should_retry('phone'):
                return f"I need to double-check that phone number. {formatted_or_error}. Could you please repeat your phone number? (Attempt {attempt_count} of {attempt_tracker.max_attempts})"
            else:
                # Max attempts reached - store as-is and move on
                attempt_tracker.mark_as_failed('phone')
                kwargs['phone'] = phone  # Use original
                logger.info(f"📝 Max phone attempts reached, storing original: {phone}")
    
    # Enhanced email validation with retry logic
    if 'email' in kwargs and kwargs['email']:
        email = kwargs['email']
        attempt_count = attempt_tracker.increment_attempt('email')
        
        if validate_email(email):
            logger.info(f"📧 Email validated: {email}")
            attempt_tracker.attempts['email'] = 0  # Reset on success
        else:
            logger.warning(f"📧 Email validation failed (attempt {attempt_count}): {email}")
            
            if attempt_tracker.should_retry('email'):
                return f"That doesn't look like a valid email address. Could you please repeat your email? (Attempt {attempt_count} of {attempt_tracker.max_attempts})"
            else:
                # Max attempts reached - store as-is and move on
                attempt_tracker.mark_as_failed('email')
                logger.info(f"📝 Max email attempts reached, storing original: {email}")
    
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
    
    # CRITICAL: Always continue collecting missing information - NEVER end early
    if tracker.is_complete():
        # Create a natural confirmation summary
        info = tracker.patient_info
        response = f"Perfect! I have everything I need. Just to confirm - I have you down as {info.name}, born {info.dob}, with {info.insurance_provider} insurance. You're coming in for {info.chief_complaint}, and you prefer {info.appointment_preference} appointments. Does that all sound correct?"
        
    elif next_field:
        # ALWAYS ask for the next missing field - this prevents early call endings
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
                "address": "Thank you.",
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
        # Fallback - should rarely happen, but ensures conversation continues
        missing_list = list(missing)
        if missing_list:
            next_missing = missing_list[0]
            fallback_prompt = f"Can you tell me about your {next_missing.replace('_', ' ')}?"
            response = f"Let me get some more information from you. {natural_prompts.get(next_missing, fallback_prompt)}"
        else:
            response = "Thanks for that information. Is there anything else you'd like to add or update?"
    
    logger.info(f"📤 Function returning response: {response}")
    
    # Call callback if provided (Pipecat integration)
    if hasattr(function_call_params, 'result_callback'):
        await function_call_params.result_callback(response)
    
    return response

# Add this helper function to handle graceful field collection
def get_graceful_missing_field_response(missing_fields: list) -> str:
    """Generate a natural response for collecting missing fields"""
    if not missing_fields:
        return "Great! I think I have everything I need."
    
    # Priority order for collecting fields
    priority_order = [
        "name", "dob", "phone", "insurance_provider", "insurance_id", 
        "chief_complaint", "referral_info", "address", "email", 
        "patient_status", "appointment_preference"
    ]
    
    # Find the next field to collect based on priority
    for field in priority_order:
        if field in missing_fields:
            natural_prompts = {
                "name": "Let me start by getting your full name.",
                "dob": "And what's your date of birth?",
                "phone": "What's the best phone number to reach you at?",
                "insurance_provider": "What insurance company do you have?",
                "insurance_id": "And what's your member ID number?",
                "chief_complaint": "What brings you in today?",
                "address": "I'll need your current address for our records.",
                "appointment_preference": "When would work best for your appointment?",
                "email": "Would you like to provide an email for appointment reminders?",
                "referral_info": "Were you referred by another doctor, or are you scheduling this yourself?",
                "patient_status": "Are you a new patient with us, or have you been here before?"
            }
            return natural_prompts.get(field, f"Can you tell me about your {field.replace('_', ' ')}?")
    
    return "Let me gather a bit more information from you."

async def validate_address(function_call_params) -> str:
    """
    Validate patient address using SmartyStreets API during conversation
    """
    try:
        logger.info(f"🏠 Address validation function called with: {function_call_params}")
        
        # Extract address from function parameters
        if hasattr(function_call_params, 'arguments'):
            params = function_call_params.arguments if isinstance(function_call_params.arguments, dict) else json.loads(function_call_params.arguments)
        else:
            params = function_call_params
            
        address = params.get('address', '').strip()
        
        if not address:
            response = "I didn't catch your address clearly. Could you please repeat it slowly?"
            logger.info(f"📤 Validation response: {response}")
            return response
        
        # Validate the address
        is_valid, message, formatted_address = await validate_patient_address(address)
        
        # Get current tracker
        tracker = get_current_tracker()
        
        if is_valid:
            # Update the tracker with validated address
            tracker.update_field('address', formatted_address or address)
            logger.info(f"✅ Address validated and stored: {formatted_address}")
            
            # Return confirmation message that will be spoken
            response = f"Perfect! I've confirmed your address as {formatted_address}. Is that correct?"
            logger.info(f"📤 Validation response: {response}")
            return response
        else:
            # Don't store invalid address, ask for clarification with spoken message
            logger.warning(f"❌ Address validation failed: {message}")
            
            # Create a natural spoken response for the error
            if "not found" in message.lower():
                response = "I'm having trouble finding that exact address in our system. Could you please double-check the street name, number, or ZIP code and repeat it for me?"
            elif "timeout" in message.lower() or "network" in message.lower():
                response = "I'm experiencing a technical issue with address verification. Could you please repeat your address slowly so I can record it?"
            elif "short" in message.lower():
                response = "That address seems incomplete. Could you provide the full address including street number, street name, city, state, and ZIP code?"
            else:
                response = "Let me double-check that address with you. Could you please repeat it slowly, including the street number, street name, city, state, and ZIP code?"
            
            logger.info(f"📤 Validation error response: {response}")
            return response
            
    except Exception as e:
        logger.error(f"Address validation error: {e}")
        response = "I'm having some trouble with address validation right now. Could you please repeat your address slowly so I can make sure I have it recorded correctly?"
        logger.info(f"📤 Validation exception response: {response}")
    return response

# Validation functions
def validate_phone(phone: str) -> tuple[bool, str]:
    """Enhanced phone validation with detailed feedback"""
    import re
    
    if not phone:
        return False, "Phone number is required"
    
    # Remove all non-digits
    digits = re.sub(r'\D', '', phone)
    
    # Check length
    if len(digits) < 10:
        return False, f"Phone number too short - needs 10 digits, got {len(digits)}"
    elif len(digits) > 11:
        return False, f"Phone number too long - maximum 11 digits, got {len(digits)}"
    elif len(digits) == 11 and not digits.startswith('1'):
        return False, "11-digit number must start with 1 (country code)"
    
    # Format validation
    if len(digits) == 10:
        # US phone number format
        formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        return True, formatted
    elif len(digits) == 11 and digits.startswith('1'):
        # US phone with country code
        formatted = f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return True, formatted
    
    return False, "Invalid phone number format"

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
    except Exception as e:
        logger.error(f"Date of birth validation error: {e}")
        return False