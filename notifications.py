import smtplib, os, json
from email.message import EmailMessage
try:
    from twilio.rest import Client
except Exception:
    Client = None

def send_email(smtp_host, smtp_port, smtp_user, smtp_password, sender, recipients, subject, body):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients if isinstance(recipients, list) else [recipients])
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True, "Email sent"
    except Exception as e:
        return False, str(e)

def send_sms(twilio_sid, twilio_token, from_number, to_numbers, body):
    if Client is None:
        return False, "Twilio client not installed"
    try:
        client = Client(twilio_sid, twilio_token)
        results = []
        for to in to_numbers:
            msg = client.messages.create(body=body, from_=from_number, to=to)
            results.append(msg.sid)
        return True, results
    except Exception as e:
        return False, str(e)