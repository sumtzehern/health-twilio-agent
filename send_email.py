import os
import resend

from dotenv import load_dotenv

load_dotenv(override=True)

api_key = os.environ.get("RESEND_API_KEY")
if not api_key:
    print("ERROR: RESEND_API_KEY not found in environment variables")

resend.api_key = api_key

def send_appointment_confirmation(patient_data, recipient_emails=None):
    """Send appointment confirmation email using Resend"""
    try:
        verified_email = "wesleysumswe@gmail.com"
        
        appointment = patient_data.get("appointment", {})
        
        params = {
            "from": "Epic Health <onboarding@resend.dev>",
            "to": [verified_email],  # Use the verified email for testing
            "subject": f"Appointment for {patient_data.get('name', 'New Patient')} (DEMO)",
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
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Epic Health</h1>
                    <p>Your Appointment is Confirmed</p>
                </div>
                
                <div class="content">
                    <p>Dear {patient_data.get('name', 'Patient')},</p>
                    
                    <p>Your appointment has been successfully scheduled with Epic Health. Please review the details below:</p>
                    
                    <div class="appointment-details">
                        <div class="appointment-item"><strong>Provider:</strong> Dr. {appointment.get('doctor_name', 'Not specified')}</div>
                        <div class="appointment-item"><strong>Date:</strong> {appointment.get('date', 'Not specified')}</div>
                        <div class="appointment-item"><strong>Time:</strong> {appointment.get('time', 'Not specified')}</div>
                        <div class="appointment-item"><strong>Reason:</strong> {patient_data.get('chief_complaint', 'Not specified')}</div>
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
                    <p>Phone: (555) 123-4567 | Email: info@epichealth.com</p>
                    <p>This email contains confidential information and is intended solely for the named recipient.</p>
                </div>
            </body>
            </html>
            """
        }
        
        # Send the email
        response = resend.Emails.send(params)
        print(f"Email sent: {response}")
        return True, "Email sent successfully"
        
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False, f"Failed to send email: {str(e)}"

# Test the function
if __name__ == "__main__":
    test_patient = {
        "name": "Test Patient",
        "appointment": {
            "doctor_name": "Smith",
            "date": "May 30, 2025",
            "time": "2:30 PM"
        }
    }
    
    success, message = send_appointment_confirmation(test_patient)
    print(f"Success: {success}")
    print(f"Message: {message}")