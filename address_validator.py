import aiohttp
import asyncio
import os
import json
import re
from loguru import logger
from typing import Dict, Tuple, Optional
from dotenv import load_dotenv

load_dotenv(override=True)

class AddressValidator:
    """Address validation using SmartyStreets API only"""
    
    def __init__(self):
        self.smartystreets_auth_id = os.getenv("SMARTYSTREETS_AUTH_ID")
        self.smartystreets_auth_token = os.getenv("SMARTYSTREETS_AUTH_TOKEN")
        
        # Log configuration status
        if self.smartystreets_auth_id and self.smartystreets_auth_token:
            logger.info("✅ SmartyStreets API configured")
        else:
            logger.warning("❌ SmartyStreets API not configured - check .env file")
        
    async def validate_address_smartystreets(self, address: str) -> Dict:
        """Validate address using SmartyStreets API"""
        if not self.smartystreets_auth_id or not self.smartystreets_auth_token:
            logger.warning("SmartyStreets credentials not configured")
            return {"valid": False, "error": "SmartyStreets API not configured"}
            
        url = "https://us-street.api.smarty.com/street-address"
        
        # Try to parse address components for better accuracy
        components = self.parse_address_components(address)
        
        params = {
            "auth-id": self.smartystreets_auth_id,
            "auth-token": self.smartystreets_auth_token,
            "candidates": "1"
        }
        
        # Add parsed components if available, otherwise use full address as street
        if components["street"]:
            params["street"] = components["street"]
        else:
            params["street"] = address
            
        if components["city"]:
            params["city"] = components["city"]
        if components["state"]:
            params["state"] = components["state"]
        if components["zipcode"]:
            params["zipcode"] = components["zipcode"]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    logger.info(f"SmartyStreets API response status: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"SmartyStreets response: {json.dumps(data, indent=2)}")
                        
                        if data:
                            result = data[0]
                            formatted_address = f"{result['delivery_line_1']}, {result['last_line']}"
                            
                            return {
                                "valid": True,
                                "formatted_address": formatted_address,
                                "components": {
                                    "street": result.get('delivery_line_1', ''),
                                    "city": result.get('components', {}).get('city_name', ''),
                                    "state": result.get('components', {}).get('state_abbreviation', ''),
                                    "zip": result.get('components', {}).get('zipcode', '')
                                },
                                "confidence": "high",
                                "source": "SmartyStreets"
                            }
                        else:
                            return {"valid": False, "error": "Address not found in USPS database"}
                    elif response.status == 401:
                        return {"valid": False, "error": "Invalid SmartyStreets credentials"}
                    elif response.status == 402:
                        return {"valid": False, "error": "SmartyStreets subscription required"}
                    else:
                        error_text = await response.text()
                        return {"valid": False, "error": f"API error {response.status}: {error_text}"}
                        
        except asyncio.TimeoutError:
            logger.error("SmartyStreets API timeout")
            return {"valid": False, "error": "Address validation timeout"}
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Network connection error: {e}")
            return {"valid": False, "error": "Network connection failed"}
        except Exception as e:
            logger.error(f"SmartyStreets validation error: {e}")
            return {"valid": False, "error": f"Validation error: {str(e)}"}
    
    def parse_address_components(self, address: str) -> Dict[str, str]:
        """Basic address component parsing"""
        components = {
            "street": "",
            "city": "",
            "state": "",
            "zipcode": ""
        }
        
        if not address:
            return components
        
        # Try to extract ZIP code (5 digits at the end)
        zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', address)
        if zip_match:
            components["zipcode"] = zip_match.group(1)
            address = address.replace(zip_match.group(0), "").strip()
        
        # Split by commas
        parts = [part.strip() for part in address.split(',')]
        
        if len(parts) >= 3:
            # Format: street, city, state
            components["street"] = parts[0]
            components["city"] = parts[1]
            components["state"] = parts[2]
        elif len(parts) == 2:
            # Format: street, city state
            components["street"] = parts[0]
            city_state = parts[1].strip().split()
            if len(city_state) >= 2:
                components["state"] = city_state[-1]  # Last word is state
                components["city"] = " ".join(city_state[:-1])  # Everything else is city
            else:
                components["city"] = parts[1]
        else:
            # Single part - try to identify components
            words = address.split()
            if len(words) >= 3:
                # Assume last 1-2 words might be state
                if len(words[-1]) == 2 and words[-1].isalpha():
                    components["state"] = words[-1]
                    components["city"] = " ".join(words[-3:-1]) if len(words) > 3 else words[-2]
                    components["street"] = " ".join(words[:-3]) if len(words) > 3 else words[0]
        
        return components
    
    async def validate_address(self, address: str) -> Dict:
        """Main validation method - uses SmartyStreets only"""
        logger.info(f"🏠 Validating address: '{address}'")
        
        # Clean up the address input
        cleaned_address = self.clean_address_input(address)
        logger.info(f"🧹 Cleaned address: '{cleaned_address}'")
        
        # Validate with SmartyStreets
        result = await self.validate_address_smartystreets(cleaned_address)
        
        logger.info(f"📍 Address validation result: {result}")
        return result
    
    def clean_address_input(self, address: str) -> str:
        """Clean conversational address input"""
        if not address:
            return ""
            
        # Remove conversational prefixes
        prefixes_to_remove = [
            "i live at", "my address is", "i'm at", "the address is",
            "it's", "my home is at", "i reside at", "the address would be",
            "i'm located at", "you can find me at"
        ]
        
        cleaned = address.lower().strip()
        for prefix in prefixes_to_remove:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        
        # Convert spelled-out numbers
        number_replacements = {
            "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
            "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
            "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
            "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
            "eighteen": "18", "nineteen": "19", "twenty": "20"
        }
        
        # Handle spelled out numbers (including ZIP codes)
        words = cleaned.split()
        for i, word in enumerate(words):
            if word in number_replacements:
                words[i] = number_replacements[word]
        
        cleaned = " ".join(words)
        
        # Fix ZIP codes: join consecutive single digits separated by spaces
        # Match 4-5 consecutive single digits separated by spaces (for ZIP codes)
        cleaned = re.sub(r'\b(\d\s+){3,4}\d\b', lambda m: m.group().replace(' ', ''), cleaned)
        
        # Clean up extra spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Return with proper capitalization
        return cleaned.title()
    
    def is_address_complete(self, address: str) -> Tuple[bool, str]:
        """Check if address has minimum required components"""
        if not address or len(address.strip()) < 10:
            return False, "Address seems too short"
        
        # Check for basic components
        has_number = bool(re.search(r'\d', address))
        has_street_indicator = bool(re.search(r'\b(st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard|ct|court|pl|place|way|circle|cir)\b', address.lower()))
        has_city = len(address.split(',')) >= 2 or len(address.split()) >= 3
        
        if not has_number:
            return False, "Missing street number"
        if not has_street_indicator:
            return False, "Missing street type (St, Ave, Dr, etc.)"
        if not has_city:
            return False, "Missing city information"
        
        return True, "Address appears complete"

# Global validator instance
address_validator = AddressValidator()

async def validate_patient_address(address: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validate patient address and return result
    Returns: (is_valid, message, formatted_address)
    """
    # Basic completeness check
    is_complete, completeness_msg = address_validator.is_address_complete(address)
    if not is_complete:
        if "too short" in completeness_msg:
            return False, "That address seems a bit short. Could you give me the full address with street number, street name, city, state, and ZIP code?", None
        elif "street number" in completeness_msg:
            return False, "I don't see a street number there. Could you include the house or building number?", None
        elif "street type" in completeness_msg:
            return False, "Could you include the street type? Like Street, Avenue, Drive, etc.?", None
        elif "city" in completeness_msg:
            return False, "I'll need the city and state too. Could you give me the complete address?", None
    
    # Validate with API
    result = await address_validator.validate_address(address)
    
    if result["valid"]:
        formatted = result["formatted_address"]
        return True, f"Perfect! I've got your address as {formatted}. Does that look right?", formatted
    else:
        error = result.get("error", "unknown error")
        if "not found" in error.lower():
            return False, "I'm not finding that exact address in our system. Could you double-check the street name, number, or ZIP code for me?", None
        elif "credentials" in error.lower():
            logger.error("SmartyStreets API credentials issue")
            return False, "I'm having a small technical issue right now, but I'll record your address as you gave it to me.", address
        elif "timeout" in error.lower() or "network" in error.lower():
            return False, "My system's running a bit slow right now. Let me note down your address and we'll verify it later.", address
        elif "quota" in error.lower() or "subscription" in error.lower():
            logger.error("SmartyStreets API subscription/quota issue")
            return False, "I'm having a small technical issue right now, but I'll record your address as you gave it to me.", address
        else:
            return False, "Could you repeat that address for me? I want to make sure I get it exactly right.", None

# Test function for direct testing
async def test_address_validation():
    """Comprehensive test function for address validation"""
    print("🧪 Testing Address Validation System")
    print("=" * 60)
    
    test_addresses = [
        # Valid addresses
        "1600 Pennsylvania Avenue NW, Washington, DC 20500",
        "510 Sunridge Drive, Blacksburg, Virginia, 24060",
        "875 Powell Street, San Francisco, CA 94108",
        
        # Conversational input
        "I live at 510 Sunridge Drive in Blacksburg Virginia two four zero six zero",
        "My address is 123 Main Street, Anytown, VA 12345",
        "You can find me at 789 Oak Avenue, Richmond Virginia",
        
        # Edge cases
        "123 Fake Street, Nowhere, XX 99999",
        "incomplete address",
        "123 Main",
        "Main Street, Richmond, VA",
        
        # Spelled out numbers
        "One two three four Main Street, Richmond Virginia two three two three four"
    ]
    
    for i, address in enumerate(test_addresses, 1):
        print(f"\n{i}. Testing: '{address}'")
        print("-" * 50)
        
        is_valid, message, formatted = await validate_patient_address(address)
        
        if is_valid:
            print(f"✅ VALID")
            print(f"   Response: {message}")
            print(f"   Formatted: {formatted}")
        else:
            print(f"❌ INVALID")
            print(f"   Response: {message}")
            if formatted:
                print(f"   Recorded as: {formatted}")

async def quick_test():
    """Quick test with a single address"""
    address = "510 Sandwich Drive, Blacksburg, Virginia, 24060"
    print(f"Quick test: {address}")
    
    is_valid, message, formatted = await validate_patient_address(address)
    print(f"Valid: {is_valid}")
    print(f"Message: {message}")
    print(f"Formatted: {formatted}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        asyncio.run(quick_test())
    else:
        asyncio.run(test_address_validation())