import os
import sys
import threading
import traceback
from typing import Dict, Any, Optional, Final

from dotenv import load_dotenv
from google.cloud import logging as gcp_logging
from colorama import Fore, Style, init

# Initialize colorama for cross-platform console color support
init(autoreset=True)
load_dotenv()


class LoggerConfigurationError(Exception):
    """Raised when critical logging configuration is missing from the environment."""
    pass


class LogConstants:
    """Centralized constants for log configuration and styling."""
    DEFAULT_ENV: Final[str] = "develop"
    DEFAULT_LEVEL: Final[str] = "INFO"
    DEFAULT_CUSTOMER: Final[str] = "system"

    LEVEL_MAP: Final[Dict[str, int]] = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50
    }

    THEME: Final[Dict[str, str]] = {
        "DEBUG": Fore.GREEN,
        "INFO": Fore.BLUE,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.RED + Style.BRIGHT
    }


class GcpClientProvider:
    """Thread-safe, lazy-initialized provider for the GCP Logging Client."""
    _client: Optional[gcp_logging.Client] = None
    _lock = threading.Lock()

    @classmethod
    def get_client(cls, project_id: str) -> gcp_logging.Client:
        if cls._client is None:
            with cls._lock:
                if cls._client is None:
                    try:
                        cls._client = gcp_logging.Client(project=project_id)
                    except Exception as e:
                        raise LoggerConfigurationError(f"Failed to initialize GCP Logging Client: {str(e)}")
        return cls._client


class GcpLogger:
    """
    Standardized logger for writing structured logs to GCP and local console.
    Handles level filtering, formatting, and graceful degradation on network failure.
    """

    def __init__(self, process: str, env: str, project_id: str, log_level_str: str):
        self.process = process
        self.environment = env
        self.project_id = project_id

        # O(1) level comparison
        self.min_level = LogConstants.LEVEL_MAP.get(log_level_str.upper(), 20)
        self._gcp_logger: Optional[Any] = None
        self._lock = threading.Lock()

    def _get_gcp_logger(self) -> Any:
        """Lazily fetches the specific GCP logger instance for this process."""
        if self._gcp_logger is None:
            with self._lock:
                if self._gcp_logger is None:
                    client = GcpClientProvider.get_client(self.project_id)
                    self._gcp_logger = client.logger(self.process)
        return self._gcp_logger

    def _should_log(self, severity: str) -> bool:
        """Determines if a log should be processed based on the configured LOG_LEVEL."""
        return LogConstants.LEVEL_MAP.get(severity, 20) >= self.min_level

    def _print_to_console(self, severity: str, message: str) -> None:
        """Outputs color-coded logs to the standard output."""
        color = LogConstants.THEME.get(severity, Fore.RESET)
        sys.stdout.write(f"{color}{severity}: [{self.process}] {message}{Style.RESET_ALL}\n")
        sys.stdout.flush()

    def debug(self, message: str, customer_id: str = LogConstants.DEFAULT_CUSTOMER, **kwargs: Any) -> None:
        self.write_log_entry("DEBUG", message, customer_id, **kwargs)

    def info(self, message: str, customer_id: str = LogConstants.DEFAULT_CUSTOMER, **kwargs: Any) -> None:
        self.write_log_entry("INFO", message, customer_id, **kwargs)

    def warning(self, message: str, customer_id: str = LogConstants.DEFAULT_CUSTOMER, **kwargs: Any) -> None:
        self.write_log_entry("WARNING", message, customer_id, **kwargs)

    def error(self, message: str, customer_id: str = LogConstants.DEFAULT_CUSTOMER, **kwargs: Any) -> None:
        self.write_log_entry("ERROR", message, customer_id, **kwargs)

    def critical(self, message: str, customer_id: str = LogConstants.DEFAULT_CUSTOMER, **kwargs: Any) -> None:
        self.write_log_entry("CRITICAL", message, customer_id, **kwargs)

    def exception(self, message: str, customer_id: str = LogConstants.DEFAULT_CUSTOMER, **kwargs: Any) -> None:
        """Logs an ERROR level message and automatically appends the current exception traceback."""
        kwargs['exc_info'] = True
        self.write_log_entry("ERROR", message, customer_id, **kwargs)

    def write_log_entry(self, severity: str, message: str, customer_id: str, **kwargs: Any) -> None:
        """Core logging logic. Handles struct packaging, GCP dispatch, and fallback."""
        if not self._should_log(severity):
            return

        if kwargs.get('exc_info'):
            message += f"\n{traceback.format_exc()}"
            kwargs.pop('exc_info', None)

        log_entry = {
            "process": self.process,
            "message": message,
            "environment": self.environment,
            "customer": customer_id,
            "extra": kwargs
        }

        # Attempt GCP Delivery
        try:
            gcp_logger = self._get_gcp_logger()
            gcp_logger.log_struct(log_entry, severity=severity)
        except Exception as e:
            # Fallback constraint: Never silently fail, never crash the main thread
            sys.stderr.write(f"[GCP_LOG_FAILURE] Could not deliver {severity} log to GCP: {str(e)}\n")
            sys.stderr.write(f"[GCP_LOG_FALLBACK] {log_entry}\n")
            sys.stderr.flush()

        # Local Console Mirroring
        if self.environment.lower() != 'production':
            self._print_to_console(severity, message)


def get_logger(name: str) -> GcpLogger:
    """
    Factory function to instantiate a configured logger for a specific module.
    Reads environment variables strictly at instantiation time.
    """
    inf_env = os.getenv("INF_ENV", LogConstants.DEFAULT_ENV)
    project_id = os.getenv("PROJECT_ID")
    log_level = os.getenv("LOG_LEVEL", LogConstants.DEFAULT_LEVEL)

    if not project_id:
        # We do not raise an exception here to avoid breaking imports in environments
        # where GCP is not active (like local testing). We supply a dummy/local-only ID.
        sys.stderr.write(f"WARNING: PROJECT_ID not found in environment. GCP Logging will likely fail for '{name}'.\n")
        project_id = "LOCAL_MOCK_PROJECT"

    return GcpLogger(
        process=name,
        env=inf_env,
        project_id=project_id,
        log_level_str=log_level
    )