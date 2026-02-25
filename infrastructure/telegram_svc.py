import requests
from typing import List, Dict, Any, Optional, Final, Tuple

from core.interfaces import ITelegramService
from core.config import TelegramConfig
from core.logger import get_logger

logger = get_logger(__name__)


class TelegramConstants:
    """Namespace for fixed Telegram API endpoints and parameters."""
    API_BASE: Final[str] = "https://api.telegram.org/bot"
    PARSE_MODE_HTML: Final[str] = "HTML"
    DEFAULT_NETWORK_TIMEOUT: Final[int] = 10
    FILE_UPLOAD_TIMEOUT: Final[int] = 30


class TelegramService(ITelegramService):
    """
    Concrete adapter for the Telegram Bot API.
    Provides methods for real-time alerting, document/photo transmission,
    and long-polling for administrative commands.
    """

    def __init__(self, config: TelegramConfig):
        self.bot_token = config.bot_token
        self.chat_id = config.chat_id
        self._base_url = f"{TelegramConstants.API_BASE}{self.bot_token}"

    def __repr__(self) -> str:
        """Prevents the bot token from being exposed in logs or debuggers."""
        return f"<TelegramService(chat_id={self.chat_id}, token=REDACTED)>"

    def send_message(self, text: str) -> bool:
        """Dispatches an HTML-formatted text message to the admin chat."""
        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": TelegramConstants.PARSE_MODE_HTML
        }
        return self._dispatch_request(
            "POST",
            url,
            json=payload,
            timeout=TelegramConstants.DEFAULT_NETWORK_TIMEOUT
        )

    def send_document(self, file_path: str, caption: str = "") -> bool:
        """Uploads and dispatches a file attachment."""
        url = f"{self._base_url}/sendDocument"
        return self._upload_file(url, "document", file_path, caption)

    def send_photo(self, file_path: str, caption: str = "") -> bool:
        """Uploads and renders an image directly in the chat window."""
        url = f"{self._base_url}/sendPhoto"
        return self._upload_file(url, "photo", file_path, caption)

    def get_updates(self, offset: Optional[int], timeout: int) -> List[Dict[str, Any]]:
        """Long-polls the API for new user messages/commands."""
        url = f"{self._base_url}/getUpdates"
        params = {
            "timeout": timeout,
            "allowed_updates": ["message"]
        }
        if offset is not None:
            params["offset"] = offset

        try:
            # We add a buffer to the local timeout to allow the API to return first
            response = requests.get(url, params=params, timeout=timeout + 5)
            response.raise_for_status()

            data = response.json()
            if data.get("ok"):
                return data.get("result", [])

            logger.warning(f"Telegram API response not OK: {data}")
            return []

        except requests.exceptions.Timeout:
            # Expected behavior during long polling
            return []
        except Exception as e:
            logger.error(f"Telegram command polling failed: {str(e)}", exc_info=True)
            return []

    def _upload_file(self, url: str, field_name: str, file_path: str, caption: str) -> bool:
        """Internal helper to manage multipart/form-data file uploads."""
        payload = {"chat_id": self.chat_id, "caption": caption}

        try:
            with open(file_path, "rb") as f:
                files = {field_name: f}
                response = requests.post(
                    url,
                    data=payload,
                    files=files,
                    timeout=TelegramConstants.FILE_UPLOAD_TIMEOUT
                )
                response.raise_for_status()
                return True
        except FileNotFoundError:
            logger.error(f"Upload failed. File not found at: {file_path}")
            return False
        except Exception as e:
            logger.error(f"Telegram file upload failed [{field_name}]: {str(e)}", exc_info=True)
            return False

    def _dispatch_request(self, method: str, url: str, **kwargs) -> bool:
        """Standardized request wrapper for status-aware execution."""
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram request failed ({method} {url}): {str(e)}", exc_info=True)
            return False