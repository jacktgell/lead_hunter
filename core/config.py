import os
import yaml
from typing import List, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv

from core.logger import get_logger

logger = get_logger(__name__)


class ConfigurationError(Exception):
    """Raised when application configuration is missing, malformed, or lacks required secrets."""
    pass


class EnvKeys:
    """Explicit constants for environment variable mappings."""
    PROJECT_ID = "PROJECT_ID"
    GCP_ZONE = "GCP_ZONE"
    GCP_INSTANCE_NAME = "GCP_INSTANCE_NAME"
    SMTP_EMAIL = "SMTP_EMAIL"
    SMTP_PASSWORD = "SMTP_PASSWORD"
    TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
    TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"
    EMAIL_VERIFICATION_API_KEY = "EMAIL_VERIFICATION_API_KEY"


class ConfigConstants:
    """Explicit constants for default configuration values."""
    DEFAULT_WORKSPACE = "workspaces/default"
    DEFAULT_CONFIG_PATH = "config.yaml"


# --- Pydantic Data Models ---

class AppConfig(BaseModel):
    active_workspace: str
    user_intent: str
    cycle_sleep_sec: int
    error_sleep_sec: int


class PipelineConfig(BaseModel):
    max_depth: int
    max_leafs: int
    max_path_chars: int
    max_observation_chars: int
    junk_domains: List[str]


class DatabaseConfig(BaseModel):
    db_path: str


class GcpConfig(BaseModel):
    project_id: str
    zone: str
    instance_name: str
    default_port: int
    boot_settle_time_sec: int
    tunnel_warmup_sec: int
    api_max_retries: int
    api_poll_delay_sec: int


class LlmConfig(BaseModel):
    model_name: str
    prompts_path: str
    temperature: float = 0.1
    top_p: float = 0.5
    num_ctx: int = 16384
    repeat_penalty: float = 1.1
    seed: int = 42


class BrowserConfig(BaseModel):
    headless: bool
    timeout_ms: int


class SearchConfig(BaseModel):
    blocked_tlds: List[str]
    request_delay_sec: int


class VisualizerConfig(BaseModel):
    output_file: str


class EmailConfig(BaseModel):
    smtp_host: str
    smtp_port: int
    sender_email: str
    sender_password: str
    queue_process_interval_sec: int
    template_path: str
    verification_api_key: str


class TelegramConfig(BaseModel):
    bot_token: str
    chat_id: str
    poll_interval_sec: int
    poll_timeout_sec: int


class Settings(BaseModel):
    app: AppConfig
    pipeline: PipelineConfig
    database: DatabaseConfig
    gcp: GcpConfig
    llm: LlmConfig
    browser: BrowserConfig
    search: SearchConfig
    visualizer: VisualizerConfig
    email: EmailConfig
    telegram: TelegramConfig


# --- Configuration Bootstrapping Logic ---


def _read_yaml(config_path: str) -> Dict[str, Any]:
    """Reads and parses the base YAML configuration file."""
    if not os.path.exists(config_path):
        raise ConfigurationError(f"Configuration file {config_path} not found.")

    with open(config_path, "r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Failed to parse YAML file at {config_path}: {e}")


def _resolve_workspace_paths(yaml_data: Dict[str, Any]) -> Dict[str, Any]:
    """Resolves relative file paths to absolute paths based on the active workspace."""
    app_data = yaml_data.get('app', {})
    workspace_dir = app_data.get('active_workspace', ConfigConstants.DEFAULT_WORKSPACE)

    os.makedirs(workspace_dir, exist_ok=True)
    logger.debug(f"Resolved active workspace to: {workspace_dir}")

    try:
        db_data = yaml_data.setdefault('database', {})
        llm_data = yaml_data.setdefault('llm', {})
        vis_data = yaml_data.setdefault('visualizer', {})
        email_data = yaml_data.setdefault('email', {})

        db_data['db_path'] = os.path.join(workspace_dir, db_data.get('db_path', ''))
        llm_data['prompts_path'] = os.path.join(workspace_dir, llm_data.get('prompts_path', ''))
        vis_data['output_file'] = os.path.join(workspace_dir, vis_data.get('output_file', ''))
        email_data['template_path'] = os.path.join(workspace_dir, email_data.get('template_path', ''))
    except AttributeError as e:
        raise ConfigurationError(f"Malformed configuration structure preventing path resolution: {e}")

    return yaml_data


def _inject_user_intent(yaml_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts the user intent from the workspace prompts file and injects it into app config."""
    prompts_full_path = yaml_data.get('llm', {}).get('prompts_path', '')

    if not os.path.exists(prompts_full_path):
        raise ConfigurationError(f"Critical workspace prompts file missing: {prompts_full_path}")

    with open(prompts_full_path, "r", encoding="utf-8") as pf:
        try:
            prompts_data = yaml.safe_load(pf) or {}
            locations_list = prompts_data.get('config', {}).get('target_locations', [])
            locations_str = ", ".join(locations_list) if locations_list else "Global / Remote"

            raw_intent = prompts_data['config']['target_intent'].strip()
            target_intent = raw_intent.format(locations=locations_str)

            app_data = yaml_data.setdefault('app', {})
            app_data['user_intent'] = target_intent
            logger.debug(f"Successfully injected locations ({locations_str}) into user_intent.")

        except KeyError as e:
            raise ConfigurationError(f"Workspace prompts file ({prompts_full_path}) is missing required key: {e}")
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Failed to parse prompts YAML file: {e}")

    return yaml_data


def _inject_environment_secrets(yaml_data: Dict[str, Any]) -> Dict[str, Any]:
    """Overrides configuration properties with secure environment variables."""
    # GCP Injection
    gcp_data = yaml_data.setdefault('gcp', {})
    gcp_data['project_id'] = os.getenv(EnvKeys.PROJECT_ID, "")
    gcp_data['zone'] = os.getenv(EnvKeys.GCP_ZONE, "")
    gcp_data['instance_name'] = os.getenv(EnvKeys.GCP_INSTANCE_NAME, "")

    # Email Service Injection
    email_data = yaml_data.setdefault('email', {})
    email_data['sender_email'] = os.getenv(EnvKeys.SMTP_EMAIL, "")
    email_data['sender_password'] = os.getenv(EnvKeys.SMTP_PASSWORD, "")
    email_data['verification_api_key'] = os.getenv(EnvKeys.EMAIL_VERIFICATION_API_KEY, "")

    if not email_data['sender_email'] or not email_data['sender_password']:
        raise ConfigurationError(f"Missing required SMTP credentials in environment variables.")

    # Telegram Injection
    telegram_data = yaml_data.setdefault('telegram', {})
    telegram_data['bot_token'] = os.getenv(EnvKeys.TELEGRAM_BOT_TOKEN, "")
    telegram_data['chat_id'] = os.getenv(EnvKeys.TELEGRAM_CHAT_ID, "")

    # Preserve YAML defaults if environment overrides are not specified
    telegram_data['poll_interval_sec'] = telegram_data.get('poll_interval_sec', 2)
    telegram_data['poll_timeout_sec'] = telegram_data.get('poll_timeout_sec', 30)

    logger.debug("Successfully injected environment secrets into configuration payload.")
    return yaml_data


def load_settings(config_path: str = ConfigConstants.DEFAULT_CONFIG_PATH) -> Settings:
    """
    Main entrypoint for configuration loading.
    Executes a pipeline of data extraction, path resolution, and secret injection.
    """
    load_dotenv()
    logger.info(f"Initializing configuration pipeline from {config_path}...")

    try:
        raw_config = _read_yaml(config_path)
        config_with_paths = _resolve_workspace_paths(raw_config)
        config_with_intent = _inject_user_intent(config_with_paths)
        final_config_dict = _inject_environment_secrets(config_with_intent)

        # Pydantic validates the final dictionary against our type definitions
        settings = Settings(**final_config_dict)
        logger.info("Configuration loaded and validated successfully.")
        return settings

    except Exception as e:
        logger.error(f"Failed to load application settings: {str(e)}", exc_info=True)
        raise