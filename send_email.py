# send_email.py

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv(override=True)

def send_appointment_confirmation(patient_data, recipient_emails):
    """
    Send an appointment confirmation email with all collected patient information.
    
    Args:
        patient_data: Dictionary containing all patient information
        recipient_emails: List of email addresses or single email address
    """
    # Email server configuration
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    
    # Handle single email or list of emails
    if isinstance(recipient_emails, str):
        recipient_emails = [recipient_emails]
    
    # Create message
    message = MIMEMultipart("alternative")
    message["Subject"] = "Your Appointment Confirmation with Epic Health(DEMO)"
    message["From"] = sender_email
    message["To"] = ", ".join(recipient_emails)  # Join multiple recipients
    
    # HTML message body
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ width: 80%; margin: 0 auto; padding: 20px; }}
            h1 {{ color: #0066cc; }}
            .appointment-details {{ background-color: #f5f5f5; padding: 15px; border-radius: 5px; }}
            .footer {{ margin-top: 30px; font-size: 12px; color: #999; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Your Appointment is Confirmed!</h1>
            <p>Hello {patient_data.get('name', 'Valued Patient')},</p>
            <p>Thank you for scheduling your appointment with Epic Health. Here's a summary of your appointment details:</p>
            
            <div class="appointment-details">
                <h2>Appointment Information</h2>
                <p><strong>Doctor:</strong> Dr. {patient_data.get('appointment', {}).get('doctor_name', '')}</p>
                <p><strong>Date:</strong> {patient_data.get('appointment', {}).get('date', '')}</p>
                <p><strong>Time:</strong> {patient_data.get('appointment', {}).get('time', '')}</p>
                <p><strong>Reason for Visit:</strong> {patient_data.get('chief_complaint', '')}</p>
                
                <h2>Your Information</h2>
                <p><strong>Name:</strong> {patient_data.get('name', '')}</p>
                <p><strong>Date of Birth:</strong> {patient_data.get('dob', '')}</p>
                <p><strong>Phone:</strong> {patient_data.get('phone', '')}</p>
                <p><strong>Address:</strong> {patient_data.get('address', '')}</p>
                <p><strong>Insurance Provider:</strong> {patient_data.get('insurance_provider', '')}</p>
                <p><strong>Insurance ID:</strong> {patient_data.get('insurance_id', '')}</p>
            </div>
            
            <h2>Preparing for Your Visit</h2>
            <ul>
                <li>Please arrive 10 minutes before your scheduled appointment time</li>
                <li>Bring your insurance card and a valid photo ID</li>
                <li>If this is your first visit, please complete the new patient forms available on our website</li>
                <li>If you need to reschedule or cancel, please call us at least 24 hours in advance</li>
            </ul>
            
            <p>If you have any questions before your appointment, please don't hesitate to contact us at (555) 123-4567.</p>
            
            <p>We look forward to seeing you!</p>
            
            <p>Warm regards,<br>The Epic Health Team</p>
            
            <div class="footer">
                <p>This is an automated confirmation email. Please do not reply to this message.</p>
                <p>© 2025 Epic Health. All rights reserved.</p>
                <p><em>Demo Version - For testing purposes only</em></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Attach HTML part
    part = MIMEText(html, "html")
    message.attach(part)
    
    # Send email
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_emails, message.as_string())
        return True, "Email sent successfully"
    except Exception as e:
        return False, f"Failed to send email: {str(e)}"