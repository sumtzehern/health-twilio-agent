import json
import logging
import re
from datetime import datetime
from typing import Dict, Set, Optional, Any, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class PatientInfo:
    """Structured patient information"""
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
    patient_status: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def get_completed_fields(self) -> Set[str]:
        return {k for k, v in asdict(self).items() if v is not None and str(v).strip()}

class RobustPatientTracker:
    """Patient tracker with automatic information extraction"""
    
    def __init__(self):
        self.patient_info = PatientInfo()
        self.required_fields = {
            "name", "dob", "insurance_provider", "insurance_id", 
            "chief_complaint", "address", "phone", "appointment_preference"
        }
        self.conversation_history = []
        
        # Patterns for automatic extraction
        self.extraction_patterns = {
            "phone": [
                r'\b(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b',
                r'\b(\(\d{3}\)\s?\d{3}[-.\s]?\d{4})\b'
            ],
            "email": [
                r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b'
            ],
            "dob": [
                r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})\b',
                r'\b(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})\b',
                r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}\b'
            ],
            "insurance_id": [
                r'\b([A-Z]{2,3}\d{6,9})\b',
                r'\bmember\s+(?:id|number)[\s:]+([A-Z0-9]+)\b',
                r'\binsurance\s+(?:id|number)[\s:]+([A-Z0-9]+)\b'
            ]
        }
    
    def extract_from_text(self, text: str) -> Dict[str, Any]:
        """Extract patient information from text using patterns"""
        extracted = {}
        text_lower = text.lower()
        
        # Extract using patterns
        for field, patterns in self.extraction_patterns.items():
            if not getattr(self.patient_info, field):  # Only if field is empty
                for pattern in patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    if matches:
                        extracted[field] = matches[0]
                        break
        
        # Extract name (look for "my name is" or "I'm")
        if not self.patient_info.name:
            name_patterns = [
                r'my name is ([a-zA-Z\s]+?)(?:\.|,|$)',
                r'i\'m ([a-zA-Z\s]+?)(?:\.|,|$)',
                r'this is ([a-zA-Z\s]+?)(?:\.|,|$)',
                r'name[\s:]+([a-zA-Z\s]+?)(?:\.|,|$)'
            ]
            for pattern in name_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    name = match.group(1).strip().title()
                    if len(name.split()) >= 2:  # At least first and last name
                        extracted['name'] = name
                        break
        
        # Extract insurance provider
        if not self.patient_info.insurance_provider:
            insurance_keywords = [
                'blue cross', 'aetna', 'cigna', 'humana', 'anthem', 'kaiser', 
                'medicare', 'medicaid', 'united healthcare', 'bcbs'
            ]
            for keyword in insurance_keywords:
                if keyword in text_lower:
                    extracted['insurance_provider'] = keyword.title()
                    break
        
        # Extract chief complaint (look for health-related keywords)
        if not self.patient_info.chief_complaint:
            complaint_patterns = [
                r'(?:i have|i\'m having|suffering from|experiencing) ([^.]+)',
                r'(?:pain in|hurt|ache|sick|fever|cough|headache)',
                r'(?:checkup|physical|appointment for) ([^.]+)',
                r'(?:follow up|follow-up) (?:for|on) ([^.]+)'
            ]
            for pattern in complaint_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    if len(match.groups()) > 0:
                        extracted['chief_complaint'] = match.group(1).strip()
                    else:
                        extracted['chief_complaint'] = match.group(0).strip()
                    break
        
        return extracted
    
    def process_conversation_turn(self, user_message: str) -> Dict[str, Any]:
        """Process a conversation turn and extract information"""
        # Store conversation
        self.conversation_history.append({
            'timestamp': datetime.now().isoformat(),
            'user_message': user_message,
            'extracted_info': {}
        })
        
        # Extract information
        extracted = self.extract_from_text(user_message)
        
        # Update patient info
        updated_fields = []
        for field, value in extracted.items():
            if hasattr(self.patient_info, field) and value:
                setattr(self.patient_info, field, value)
                updated_fields.append(field)
                logger.info(f"Auto-extracted {field}: {value}")
        
        # Store what was extracted in this turn
        if self.conversation_history:
            self.conversation_history[-1]['extracted_info'] = extracted
        
        return {
            'extracted_fields': updated_fields,
            'extracted_data': extracted,
            'completion_percentage': self.get_completion_percentage(),
            'missing_required': list(self.get_missing_required_fields()),
            'next_field_needed': self.get_next_required_field()
        }
    
    def update_field(self, field_name: str, value: Any) -> bool:
        """Manually update a field"""
        if hasattr(self.patient_info, field_name) and value and str(value).strip():
            setattr(self.patient_info, field_name, str(value).strip())
            logger.info(f"Manually updated {field_name}: {value}")
            return True
        return False
    
    def get_missing_required_fields(self) -> Set[str]:
        completed = self.patient_info.get_completed_fields()
        return self.required_fields - completed
    
    def get_completion_percentage(self) -> float:
        completed = len(self.patient_info.get_completed_fields() & self.required_fields)
        return (completed / len(self.required_fields)) * 100
    
    def is_complete(self) -> bool:
        return len(self.get_missing_required_fields()) == 0
    
    def get_next_required_field(self) -> Optional[str]:
        missing = self.get_missing_required_fields()
        if not missing:
            return None
        
        field_order = ["name", "dob", "phone", "insurance_provider", "insurance_id", 
                      "chief_complaint", "address", "appointment_preference"]
        
        for field in field_order:
            if field in missing:
                return field
        return next(iter(missing))
    
    def get_field_prompt(self, field_name: str) -> str:
        prompts = {
            "name": "Can I get your full name, please?",
            "dob": "What's your date of birth?",
            "phone": "What's your phone number?",
            "insurance_provider": "What insurance company do you have?",
            "insurance_id": "What's your insurance member ID number?",
            "chief_complaint": "What's the main reason for your visit today?",
            "address": "Can I get your current address?",
            "appointment_preference": "What days and times work best for you?",
            "email": "Would you like to provide an email for reminders?",
            "referral_info": "Were you referred by another doctor?",
            "patient_status": "Are you a new patient or have you been here before?"
        }
        return prompts.get(field_name, f"Please provide your {field_name}")
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            "patient_info": self.patient_info.to_dict(),
            "completion_percentage": self.get_completion_percentage(),
            "missing_required": list(self.get_missing_required_fields()),
            "is_complete": self.is_complete(),
            "next_field_needed": self.get_next_required_field(),
            "conversation_turns": len(self.conversation_history)
        }
    
    def reset(self):
        self.patient_info = PatientInfo()
        self.conversation_history = []
        logger.info("Patient tracker reset")

# Global tracker
current_tracker = None

def get_current_tracker() -> RobustPatientTracker:
    global current_tracker
    if current_tracker is None:
        current_tracker = RobustPatientTracker()
    return current_tracker

def set_new_tracker() -> RobustPatientTracker:
    global current_tracker
    current_tracker = RobustPatientTracker()
    return current_tracker

# Enhanced function schema that's more likely to be called
collect_patient_info_schema = {
    "name": "collect_patient_info",
    "description": "REQUIRED: Extract and store patient information from their message. Call this function for EVERY user message to capture any personal details they share.",
    "parameters": {
        "type": "object",
        "properties": {
            "user_message": {
                "type": "string",
                "description": "The complete user message to analyze for patient information"
            },
            "extracted_info": {
                "type": "object",
                "description": "Any patient information found in the message",
                "properties": {
                    "name": {"type": "string", "description": "Patient's full name"},
                    "dob": {"type": "string", "description": "Date of birth"},
                    "insurance_provider": {"type": "string", "description": "Insurance company"},
                    "insurance_id": {"type": "string", "description": "Insurance ID number"},
                    "chief_complaint": {"type": "string", "description": "Reason for visit"},
                    "address": {"type": "string", "description": "Full address"},
                    "phone": {"type": "string", "description": "Phone number"},
                    "email": {"type": "string", "description": "Email address"},
                    "appointment_preference": {"type": "string", "description": "Preferred appointment time"},
                    "referral_info": {"type": "string", "description": "Referral information"},
                    "patient_status": {"type": "string", "description": "New or returning patient"}
                }
            }
        },
        "required": ["user_message"]
    }
}

async def collect_patient_info(user_message: str, extracted_info: Dict[str, Any] = None) -> str:
    """Enhanced function that processes every user message"""
    tracker = get_current_tracker()
    logger.info(f"collect_patient_info called with: {args}")
    
    # Process the message for automatic extraction
    auto_extracted = tracker.process_conversation_turn(user_message)
    
    # Also process any manually provided extracted_info
    if extracted_info:
        for field, value in extracted_info.items():
            if value:
                tracker.update_field(field, value)
    
    # Get current status
    summary = tracker.get_summary()
    completion = summary["completion_percentage"]
    missing = summary["missing_required"]
    next_field = summary["next_field_needed"]
    
    # Create response based on what was found and what's still needed
    response_parts = []
    
    # Acknowledge what was extracted
    if auto_extracted['extracted_fields']:
        response_parts.append(f"Got it, I've recorded your {', '.join(auto_extracted['extracted_fields'])}.")
    
    # Guide to next field if incomplete
    if not tracker.is_complete() and next_field:
        prompt = tracker.get_field_prompt(next_field)
        response_parts.append(prompt)
    elif tracker.is_complete():
        response_parts.append("Perfect! I have all your information. Let me confirm your appointment details.")
    
    # Default response if nothing specific to say
    if not response_parts:
        if missing:
            next_field = list(missing)[0]
            prompt = tracker.get_field_prompt(next_field)
            response_parts.append(prompt)
        else:
            response_parts.append("Thanks for that information.")
    
    response = " ".join(response_parts)
    
    # Log for debugging
    logger.info(f"Function called - Completion: {completion:.0f}%, Extracted: {auto_extracted['extracted_fields']}")
    
    return response