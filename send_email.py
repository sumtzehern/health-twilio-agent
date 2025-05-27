import os
import resend
import re
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv(override=True)

api_key = os.environ.get("RESEND_API_KEY")
if not api_key:
    print("ERROR: RESEND_API_KEY not found in environment variables")

resend.api_key = api_key

def parse_appointment_preference(appointment_preference):
    """Parse appointment preference string into structured data"""
    if not appointment_preference:
        return {"doctor_name": "Not specified", "date": "Not specified", "time": "Not specified"}
    
    # Extract doctor name - pattern: "Dr. [Name]"
    doctor_match = re.search(r'Dr\.\s+([A-Za-z]+)', appointment_preference)
    doctor_name = doctor_match.group(1) if doctor_match else "Not specified"
    
    # Extract day/date info
    date_info = "Not specified"
    time_info = "Not specified"
    
    # Look for time patterns like "10:15 AM", "2:30 PM"
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))', appointment_preference)
    if time_match:
        time_info = time_match.group(1)
    
    # Look for day references
    day_patterns = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, 
        "friday": 4, "saturday": 5, "sunday": 6
    }

    for day_name, day_num in day_patterns.items():
        if f"next {day_name}" in appointment_preference.lower():
            # Calculate next occurrence of this day
            today = datetime.now()
            days_ahead = (day_num - today.weekday()) % 7
            if days_ahead == 0:  # Today is that day, so get next week
                days_ahead = 7
            target_date = today + timedelta(days=days_ahead)
            date_info = target_date.strftime("%A, %B %d, %Y")
            break
        elif f"this {day_name}" in appointment_preference.lower():
            # Calculate this week's occurrence (or next week if already passed)
            today = datetime.now()
            days_ahead = (day_num - today.weekday()) % 7
            if days_ahead == 0:  # Today is that day
                days_ahead = 7  # Get next week's occurrence
            target_date = today + timedelta(days=days_ahead)
            date_info = target_date.strftime("%A, %B %d, %Y")
            break
        elif day_name in appointment_preference.lower() and ("next" not in appointment_preference.lower() and "this" not in appointment_preference.lower()):
            # Just the day name mentioned (assume next occurrence)
            today = datetime.now()
            days_ahead = (day_num - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = today + timedelta(days=days_ahead)
            date_info = target_date.strftime("%A, %B %d, %Y")
            break

    # Also handle specific date patterns like "May 30th", "June 3rd", etc.
    date_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?', appointment_preference.lower())
    if date_match and date_info == "Not specified":
        month_name = date_match.group(1)
        day = int(date_match.group(2))
        try:
            current_year = datetime.now().year
            month_num = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4,
                'may': 5, 'june': 6, 'july': 7, 'august': 8,
                'september': 9, 'october': 10, 'november': 11, 'december': 12
            }[month_name]
            target_date = datetime(current_year, month_num, day)
            # If the date has passed this year, assume next year
            if target_date < datetime.now():
                target_date = datetime(current_year + 1, month_num, day)
            date_info = target_date.strftime("%A, %B %d, %Y")
        except (ValueError, KeyError):
            pass  # Keep "Not specified" if parsing fails
    
    return {
        "doctor_name": doctor_name,
        "date": date_info,
        "time": time_info
    }

def send_appointment_confirmation(patient_data, recipient_emails=None):
    """Send appointment confirmation email using Resend"""
    try:
        verified_email = "wesleysumswe@gmail.com"
        
        # Parse the appointment preference string
        appointment_pref = patient_data.get("appointment_preference", "")
        parsed_appointment = parse_appointment_preference(appointment_pref)
        
        # Handle missing information gracefully
        name = patient_data.get('name', 'New Patient')
        phone = patient_data.get('phone', 'Not provided')
        chief_complaint = patient_data.get('chief_complaint', 'Not specified')
        insurance_provider = patient_data.get('insurance_provider', 'Not specified')
        insurance_id = patient_data.get('insurance_id', 'Not specified')
        referral_info = patient_data.get('referral_info', 'Self-scheduled') or 'Self-scheduled'
        
        # Add note about incomplete information if present
        incomplete_note = ""
        if '_incomplete_note' in patient_data:
            incomplete_note = f"""
            <div style="background-color: #fff3cd; color: #856404; padding: 10px; margin: 10px 0; border: 1px solid #ffeeba; border-radius: 4px;">
                <strong>Note:</strong> {patient_data['_incomplete_note']}
            </div>
            """
        
        params = {
            "from": "Epic Health <onboarding@resend.dev>",
            "to": [verified_email],
            "subject": f"Appointment Confirmation for {name}",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        line-height: 1.6;
                        color: #333333;
                        max-width: 600px;
                        margin: 0 auto;
                    }}
                    .header {{
                        background-color: #0066cc;
                        color: white;
                        padding: 20px;
                        text-align: center;
                    }}
                    .content {{
                        padding: 20px;
                    }}
                    .appointment-details {{
                        background-color: #f2f2f2;
                        border-left: 4px solid #0066cc;
                        padding: 15px;
                        margin: 20px 0;
                    }}
                    .appointment-item {{
                        margin-bottom: 10px;
                    }}
                    .footer {{
                        background-color: #f9f9f9;
                        padding: 15px;
                        font-size: 12px;
                        text-align: center;
                        border-top: 1px solid #dddddd;
                    }}
                    .button {{
                        background-color: #0066cc;
                        color: white;
                        padding: 10px 20px;
                        text-decoration: none;
                        border-radius: 4px;
                        display: inline-block;
                        margin-top: 15px;
                    }}
                    .highlight {{
                        font-weight: bold;
                        color: #0066cc;
                    }}
                    .missing-info {{
                        color: #856404;
                        font-style: italic;
                    }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Epic Health</h1>
                    <p>Your Appointment is Confirmed</p>
                </div>
                
                <div class="content">
                    {incomplete_note}
                    
                    <p>Dear {name},</p>
                    
                    <p>Your appointment has been successfully scheduled with Epic Health. Please review the details below:</p>
                    
                    <div class="appointment-details">
                        <div class="appointment-item"><strong>Provider:</strong> Dr. {parsed_appointment['doctor_name']}</div>
                        <div class="appointment-item"><strong>Date:</strong> {parsed_appointment['date']}</div>
                        <div class="appointment-item"><strong>Time:</strong> {parsed_appointment['time']}</div>
                        <div class="appointment-item"><strong>Reason:</strong> {chief_complaint}</div>
                        <div class="appointment-item"><strong>Phone:</strong> {phone}</div>
                        <div class="appointment-item"><strong>Insurance:</strong> {insurance_provider} (ID: {insurance_id})</div>
                        <div class="appointment-item"><strong>Referral:</strong> {referral_info}</div>
                        <div class="appointment-item"><strong>Location:</strong> Epic Health Medical Center<br>875 Powell Street<br>Suite 203<br>San Francisco, CA 94108</div>
                    </div>
                    
                    <h3>Preparation Instructions</h3>
                    <ul>
                        <li>Please arrive <span class="highlight">15 minutes early</span> to complete any necessary paperwork</li>
                        <li>Bring your insurance card and photo ID</li>
                        <li>Bring a list of current medications</li>
                        <li>If this is your first visit, please complete the new patient forms on our website</li>
                    </ul>
                    
                    <p><a href="https://epichealth.com/patient-portal" class="button">Access Patient Portal</a></p>
                    
                    <p>If you need to reschedule or have any questions, please contact our office at (555) 123-4567.</p>
                    
                    <p>Thank you for choosing Epic Health for your healthcare needs.</p>
                    
                    <p>Best regards,<br>The Epic Health Team</p>
                </div>
                
                <div class="footer">
                    <p>Epic Health Medical Center | 875 Powell Street, San Francisco, CA 94108</p>
                </div>
            </body>
            </html>
            """
        }
        
        # Send the email
        response = resend.Emails.send(params)
        return True, "Email sent successfully"
        
    except Exception as e:
        logger.error(f"Error sending appointment confirmation: {e}")
        return False, str(e)

# Test the function
if __name__ == "__main__":
    test_patient = {
        "name": "Test Patient",
        "appointment_preference": "Dr. Chen, next Tuesday at 10:15 AM"
    }
    
    success, message = send_appointment_confirmation(test_patient)
    print(f"Success: {success}")
    print(f"Message: {message}")