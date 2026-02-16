"""
Email Utilities
Helper functions for sending emails
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailUtils:
    """Utilities for sending emails"""

    def __init__(self, smtp_server: str, smtp_port: int, sender_email: str, sender_password: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password

    def send_email(self, 
                   recipient_emails: List[str], 
                   subject: str, 
                   body: str,
                   attachments: Optional[List[str]] = None,
                   html: bool = False) -> bool:
        """Send an email"""
        try:
            # Create message
            message = MIMEMultipart()
            message['From'] = self.sender_email
            message['To'] = ', '.join(recipient_emails)
            message['Subject'] = subject

            # Add body
            mime_type = 'html' if html else 'plain'
            message.attach(MIMEText(body, mime_type))

            # Add attachments
            if attachments:
                for file_path in attachments:
                    self._attach_file(message, file_path)

            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(message)

            logger.info(f"Email sent successfully to: {', '.join(recipient_emails)}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def _attach_file(self, message: MIMEMultipart, file_path: str) -> None:
        """Attach a file to the email"""
        try:
            with open(file_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())

            encoders.encode_base64(part)
            filename = Path(file_path).name
            part.add_header('Content-Disposition', f'attachment; filename= {filename}')
            message.attach(part)

            logger.info(f"Attached file: {filename}")

        except Exception as e:
            logger.error(f"Failed to attach file {file_path}: {e}")
            raise

    def send_test_report(self, 
                        recipient_emails: List[str], 
                        report_path: str,
                        test_summary: str) -> bool:
        """Send test report email"""
        subject = f"Test Execution Report - {Path(report_path).stem}"
        
        body = f"""
        <html>
        <body>
            <h2>Test Execution Completed</h2>
            <p>{test_summary}</p>
            <p>Please find the detailed report attached.</p>
        </body>
        </html>
        """

        return self.send_email(
            recipient_emails=recipient_emails,
            subject=subject,
            body=body,
            attachments=[report_path],
            html=True
        )
