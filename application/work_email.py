import time
import random
import threading
import queue
from typing import Final

from domain.models import Lead
from core.interfaces import ILeadRepository, IEmailService, ITelegramService
from core.logger import get_logger

logger = get_logger(__name__)


class EmailWorkerConstants:
    """Centralized configuration for outreach behavior."""
    DEFAULT_SUBJECT: Final[str] = "Custom AI Engineering"
    MAX_RETRIES: Final[int] = 1
    JITTER_MIN: Final[float] = 0.8
    JITTER_MAX: Final[float] = 1.2
    RETRY_DELAY_SECONDS: Final[int] = 60


class BackgroundEmailWorker(threading.Thread):
    """
    Asynchronous worker that consumes leads from a queue and executes
    outreach workflows with jittered timing to avoid anti-spam filters.
    """

    def __init__(
            self,
            db: ILeadRepository,
            email_service: IEmailService,
            telegram_svc: ITelegramService,
            interval_sec: int,
            template_str: str,
            event_queue: queue.Queue
    ):
        super().__init__(daemon=True)
        self.db = db
        self.email_service = email_service
        self.telegram_svc = telegram_svc
        self.base_interval_sec = interval_sec
        self.template_str = template_str
        self.event_queue = event_queue

    def _calculate_jittered_sleep(self) -> int:
        """Returns a randomized sleep duration to mimic human behavior."""
        min_sleep = int(self.base_interval_sec * EmailWorkerConstants.JITTER_MIN)
        max_sleep = int(self.base_interval_sec * EmailWorkerConstants.JITTER_MAX)
        return random.randint(min_sleep, max_sleep)

    def _notify_success(self, lead: Lead) -> None:
        """Dispatches a success notification to the configured Telegram channel."""
        tele_msg = (
            f"<b>Outreach Sent Successfully!</b>\n\n"
            f"<b>Contact:</b> {lead.email}\n"
            f"<b>Company:</b> {lead.company_name}\n"
            f"<b>Name:</b> {lead.founder_name}\n"
        )
        self.telegram_svc.send_message(tele_msg)

    def _handle_failure(self, lead: Lead) -> None:
        """Manages retry logic or permanent failure state for a lead."""
        if lead.retry_count < EmailWorkerConstants.MAX_RETRIES:
            lead.retry_count += 1
            logger.warning(
                f"Delivery to {lead.email} failed. Retry {lead.retry_count} scheduled "
                f"in {EmailWorkerConstants.RETRY_DELAY_SECONDS}s."
            )
            # Re-queue for later processing after a cool-down
            time.sleep(EmailWorkerConstants.RETRY_DELAY_SECONDS)
            self.event_queue.put(lead)
        else:
            logger.error(f"Lead {lead.email} exhausted all retries. Marking as DEAD.")
            self.db.mark_failed(lead.email)
            self._inject_fallback_lead()

    def _inject_fallback_lead(self) -> None:
        """Attempts to pull an uncontacted lead from DB to keep the worker active."""
        fallback = self.db.get_random_uncontacted_lead()
        if fallback:
            logger.info(f"Injecting fallback lead: {fallback.email}")
            domain_lead = Lead(
                url="",
                company_name=fallback.company_name,
                founder_name=fallback.founder_name,
                email=fallback.email
            )
            self.event_queue.put(domain_lead)

    def _process_lead(self, lead: Lead) -> None:
        """Orchestrates the email dispatch and database state update."""
        logger.info(f"Initiating outreach: {lead.email} (Attempt {lead.retry_count + 1})")

        body = self.template_str.format(
            founder_name=lead.founder_name,
            company_name=lead.company_name
        )

        success = self.email_service.send_email(
            to_address=lead.email,
            subject=EmailWorkerConstants.DEFAULT_SUBJECT,
            body=body
        )

        if success:
            self.db.mark_contacted(lead.email)
            self._notify_success(lead)

            sleep_time = self._calculate_jittered_sleep()
            logger.info(f"Outreach successful. Throttling for {sleep_time}s.")
            time.sleep(sleep_time)
        else:
            self._handle_failure(lead)

    def run(self) -> None:
        """Main worker execution loop."""
        logger.info("Background Email Worker active.")

        # Initialize by checking for backlog in persistence layer
        backlog_lead = self.db.get_uncontacted_lead()
        if backlog_lead:
            logger.info(f"Recovering backlog lead: {backlog_lead.email}")
            self.event_queue.put(Lead(
                url="",
                company_name=backlog_lead.company_name,
                founder_name=backlog_lead.founder_name,
                email=backlog_lead.email
            ))

        while True:
            try:
                # Blocking call waits for new leads from the LeadGenerationPipeline
                lead: Lead = self.event_queue.get(block=True)
                self._process_lead(lead)
                self.event_queue.task_done()
            except Exception as e:
                logger.error(f"Critical error in worker loop: {str(e)}", exc_info=True)
                time.sleep(EmailWorkerConstants.RETRY_DELAY_SECONDS)