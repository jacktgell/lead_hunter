import time
import warnings
import queue
import sys
from typing import Optional, Final

from core.config import load_settings, Settings
from core.logger import get_logger

# Domain & Application Logic
from domain.models import Lead
from application.tracker import GraphTracker
from application.work_email import BackgroundEmailWorker
from application.worker_telegram import TelegramBotWorker
from application.pipeline import LeadGenerationPipeline

# Infrastructure Adapters (Hexagonal Architecture)
from infrastructure.compute_gcp import GcpOllamaManager
from infrastructure.llm_dspy import DspyOllamaLLM
from infrastructure.browser_playwright import PlaywrightBrowser
from infrastructure.search_ddg import DuckDuckGoSearch
from infrastructure.database import LeadDatabase
from infrastructure.visualizer_pyvis import PyvisGraphVisualizer
from infrastructure.email_smtp import SmtpEmailService
from infrastructure.telegram_svc import TelegramService

# Suppress noisy resource warnings from low-level networking libs
warnings.filterwarnings("ignore", category=ResourceWarning)
logger = get_logger(__name__)


class DaemonConstants:
    """Explicit constants for the main application lifecycle."""
    CONFIG_PATH: Final[str] = "config.yaml"
    SHUTDOWN_MSG: Final[str] = "<b>Lead Hunter Daemon Shutting Down</b>"
    STARTUP_MSG: Final[str] = "<b>Lead Hunter Daemon Online</b>\nInitializing discovery..."


class LeadHunterDaemon:
    """
    Main orchestration engine that bootstraps infrastructure, 
    initializes services, and manages the autonomous hunt lifecycle.
    """

    def __init__(self, config_path: str = DaemonConstants.CONFIG_PATH):
        logger.info("Initializing Lead Hunter Daemon...")
        self.settings: Settings = load_settings(config_path)

        # Core infrastructure managers
        self.compute_manager = GcpOllamaManager(config=self.settings.gcp)
        self.browser: Optional[PlaywrightBrowser] = None
        self.telegram_service: Optional[TelegramService] = None

        # Shared thread-safe communication channel
        self.event_queue: queue.Queue[Lead] = queue.Queue()

        self._load_templates()

    def _load_templates(self) -> None:
        """Reads outreach templates from the configured workspace."""
        try:
            with open(self.settings.email.template_path, "r", encoding="utf-8") as f:
                self.email_template_str = f.read()
        except FileNotFoundError:
            logger.critical(f"Email template missing at {self.settings.email.template_path}")
            raise

    def bootstrap(self) -> LeadGenerationPipeline:
        """
        Wires together all infrastructure adapters and starts background workers.
        Returns a fully initialized LeadGenerationPipeline.
        """
        logger.info("Bootstrapping infrastructure... (GCP IAP Tunnel initialization)")

        # 1. Establish Secure Connection to Remote AI
        host_url = self.compute_manager.ensure_infrastructure_ready()

        # 2. Instantiate Adapters
        llm = DspyOllamaLLM(host_url=host_url, config=self.settings.llm)
        searcher = DuckDuckGoSearch(config=self.settings.search)
        db = LeadDatabase(db_path=self.settings.database.db_path)

        self.browser = PlaywrightBrowser(config=self.settings.browser)
        visualizer = PyvisGraphVisualizer(config=self.settings.visualizer)
        email_service = SmtpEmailService(config=self.settings.email)
        self.telegram_service = TelegramService(config=self.settings.telegram)

        # 3. Start Asynchronous Workers
        logger.info("Spawning background worker threads...")

        # Admin Interface Worker
        TelegramBotWorker(
            telegram_svc=self.telegram_service,
            db=db,
            vis_config=self.settings.visualizer,
            bot_config=self.settings.telegram,
            email_service=email_service,
            template_str=self.email_template_str,
            browser=self.browser
        ).start()

        # Automated Outreach Worker
        BackgroundEmailWorker(
            db=db,
            email_service=email_service,
            telegram_svc=self.telegram_service,
            interval_sec=self.settings.email.queue_process_interval_sec,
            template_str=self.email_template_str,
            event_queue=self.event_queue
        ).start()

        # 4. Initialize Tracker & Pipeline
        tracker = GraphTracker(visualizer=visualizer)

        return LeadGenerationPipeline(
            llm=llm,
            searcher=searcher,
            browser=self.browser,
            db=db,
            tracker=tracker,
            config=self.settings.pipeline,
            event_queue=self.event_queue
        )

    def run(self) -> None:
        """Main execution loop for the autonomous agent."""
        with self.compute_manager:
            pipeline = self.bootstrap()
            cycle_count = 1

            if self.telegram_service:
                self.telegram_service.send_message(DaemonConstants.STARTUP_MSG)

            while True:
                logger.info(f"--- STARTING HUNT CYCLE {cycle_count} ---")
                try:
                    leads = pipeline.run_hunt(self.settings.app.user_intent)

                    if leads:
                        logger.info(f"Cycle {cycle_count} complete. {len(leads)} leads secured.")
                    else:
                        logger.info(f"Cycle {cycle_count} complete. No new leads discovered.")

                    cycle_count += 1
                    logger.info(f"Cool-down: Sleeping for {self.settings.app.cycle_sleep_sec}s.")
                    time.sleep(self.settings.app.cycle_sleep_sec)

                except Exception as e:
                    logger.error(f"Cycle {cycle_count} Error: {str(e)}", exc_info=True)
                    time.sleep(self.settings.app.error_sleep_sec)
                    cycle_count += 1

    def shutdown(self) -> None:
        """Safely terminates all processes and cleans up cloud resources."""
        logger.info("System shutdown initiated...")

        if self.telegram_service:
            self.telegram_service.send_message(DaemonConstants.SHUTDOWN_MSG)

        if self.browser:
            try:
                self.browser.close()
                logger.info("Browser engine terminated.")
            except Exception as e:
                logger.error(f"Failed to close browser: {str(e)}")

        # GCP Shutdown is handled by the __exit__ of compute_manager
        logger.info("Final resource cleanup complete. Goodbye.")


if __name__ == "__main__":
    daemon = LeadHunterDaemon()
    try:
        daemon.run()
    except KeyboardInterrupt:
        logger.warning("User interrupted process.")
        daemon.shutdown()
    except Exception as fatal_e:
        logger.critical(f"FATAL SYSTEM FAILURE: {str(fatal_e)}", exc_info=True)
        daemon.shutdown()
        sys.exit(1)