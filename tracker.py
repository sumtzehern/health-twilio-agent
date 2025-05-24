# tracker.py, this file is used to track required fileld during the call

from typing import Dict, Set, List, Optional, Any

class PatientTracker:
    """
    Tracks patient information as it's collected during a conversation.
    
    Maintains the state of patient fields and provides methods to update,
    mark fields as declined, and check for completion status.
    """
    
    def __init__(self):
        self.fields = {
            "name": None,
            "dob": None,
            "insurance_provider": None,
            "insurance_id": None,
            "referral": None,
            "chief_complaint": None,
            "address": None,
            "phone": None,
            "email": None,
            "appointment": None
        }
        self.declined_fields: Set[str] = set() # Set of fields that the patient has explicitly declined to provide
    
    def update_field(self, key: str, value: str) -> None:
        """
        Update a patient field with a new value.
        
        Args:
            key: The field name to update
            value: The value to set for the field
        
        Raises:
            KeyError: If the field name doesn't exist
        """
        if key not in self.fields:
            raise KeyError(f"Unknown field: {key}")
        
        self.fields[key] = value
        
        # If a field is updated, it's no longer considered declined
        if key in self.declined_fields:
            self.declined_fields.remove(key)
    
    def mark_declined(self, key: str) -> None:
        """
        Mark a field as explicitly declined by the patient.
        
        Args:
            key: The field name to mark as declined
            
        Raises:
            KeyError: If the field name doesn't exist
        """
        if key not in self.fields:
            raise KeyError(f"Unknown field: {key}")
            
        self.declined_fields.add(key)
    
    def is_complete(self, required_fields: Set[str]) -> bool:
        """
        Check if all required fields are either filled or explicitly declined.
        
        Args:
            required_fields: Set of field names that must be completed
            
        Returns:
            bool: True if all required fields are completed or declined
        """
        for field in required_fields:
            if field not in self.fields:
                return False
                
            if self.fields[field] is None and field not in self.declined_fields:
                return False
                
        return True
    
    def get_missing_fields(self, required_fields: Set[str]) -> List[str]:
        """
        Get a list of required fields that are still missing.
        
        A field is considered missing if it's required but has no value
        and has not been explicitly declined.
        
        Args:
            required_fields: Set of field names that must be completed
            
        Returns:
            List[str]: List of field names that are still missing
        """
        missing = []
        
        for field in required_fields:
            if field in self.fields and self.fields[field] is None and field not in self.declined_fields:
                missing.append(field)
                
        return missing
    
    def reset(self) -> None:
        """
        Reset all fields and declined status.
        """
        for key in self.fields:
            self.fields[key] = None
        self.declined_fields.clear()

    def get_all_fields(self) -> Dict[str, Optional[str]]:
        """
        Get a copy of all fields and their current values.
        
        Returns:
            Dict[str, Optional[str]]: Dictionary of all fields with their values
        """
        return self.fields.copy()

# Example usage
if __name__ == "__main__":
    tracker = PatientTracker()
    tracker.update_field("name", "John Doe")
    tracker.mark_declined("email")
    print("Missing:", tracker.get_missing_fields(set(tracker.fields.keys())))
    print("Is Complete:", tracker.is_complete(set(tracker.fields.keys())))
