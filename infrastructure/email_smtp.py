import smtplib
from email.mime.text import MIMEText
from typing import Final

from core.interfaces import IEmailService
from core.config import EmailConfig
from core.logger import get_logger

logger = get_logger(__name__)


class EmailConstants:
    """Centralized constants to eliminate magic strings in MIME construction."""
    HEADER_SUBJECT: Final[str] = "Subject"
    HEADER_FROM: Final[str] = "From"
    HEADER_TO: Final[str] = "To"
    DEFAULT_TIMEOUT_SEC: Final[int] = 30


class SmtpDeliveryError(Exception):
    """Domain-specific exception indicating a failure in the SMTP protocol or authentication."""
    pass

class SmtpHardBounceError(Exception):
    """Raised when the SMTP server explicitly rejects the recipient (e.g., 550 error)."""
    pass

class SmtpEmailService(IEmailService):
    """
    Concrete implementation of the email dispatch service via standard SMTP.
    Provides secure STARTTLS transmission and explicit timeout handling.
    """

    def __init__(self, config: EmailConfig) -> None:
        """Injects configuration dependencies."""
        self.config = config

    def send_email(self, to_address: str, subject: str, body: str) -> bool:
        """
        Constructs and dispatches a MIME text email.

        Args:
            to_address: The target recipient's email address.
            subject: The subject line of the email.
            body: The raw text payload of the email.

        Returns:
            bool: True if the email was successfully handed off to the SMTP server, False otherwise.
        """
        logger.info(f"Preparing dispatch to {to_address} via {self.config.smtp_host}:{self.config.smtp_port}")

        msg = MIMEText(body)
        msg[EmailConstants.HEADER_SUBJECT] = subject
        msg[EmailConstants.HEADER_FROM] = self.config.sender_email
        msg[EmailConstants.HEADER_TO] = to_address

        try:
            # Explicit timeout prevents zombie threads if the network partitions
            with smtplib.SMTP(
                    host=self.config.smtp_host,
                    port=self.config.smtp_port,
                    timeout=EmailConstants.DEFAULT_TIMEOUT_SEC
            ) as server:

                # Upgrade connection to secure TLS encrypted channel
                server.starttls()
                server.login(self.config.sender_email, self.config.sender_password)
                server.send_message(msg)

            logger.info(f"Successfully delivered email payload to {to_address}")
            return True

        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"HARD BOUNCE for {to_address}: {str(e)}")
            raise SmtpHardBounceError(f"Recipient refused: {to_address}")

        except smtplib.SMTPException as e:
            wrapped_error = SmtpDeliveryError(f"Protocol rejection or auth failure: {str(e)}")
            logger.error(f"SMTP delivery failed for {to_address}: {str(wrapped_error)}", exc_info=True)
            return False

        except TimeoutError as e:
            logger.error(f"SMTP connection timed out for {to_address} after {EmailConstants.DEFAULT_TIMEOUT_SEC}s.",
                         exc_info=True)
            return False

        except Exception as e:
            logger.critical(f"Unexpected execution failure during email dispatch to {to_address}: {str(e)}",
                            exc_info=True)
            return False