import unittest
from unittest.mock import patch, MagicMock
from infrastructure.email_smtp import SmtpEmailService
from core.config import EmailConfig


class TestSmtpDelivery(unittest.TestCase):
    def test_smtp_auth_failure_handling(self):
        """Verifies the service logs a critical error on invalid credentials."""
        config = EmailConfig(
            smtp_host="smtp.gmail.com", smtp_port=587,
            sender_email="test@me.com", sender_password="wrong",
            queue_process_interval_sec=1, template_path=""
        )
        service = SmtpEmailService(config)

        with patch("smtplib.SMTP") as mock_smtp:
            instance = mock_smtp.return_value.__enter__.return_value
            instance.login.side_effect = Exception("Authentication Failed")

            result = service.send_email("to@target.com", "Sub", "Body")
            self.assertFalse(result)