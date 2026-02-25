import os
import time
import uuid
import threading
from typing import Callable, Dict
from core.interfaces import ITelegramService, ILeadRepository, IEmailService, IWebBrowser
from core.config import VisualizerConfig, TelegramConfig
from core.logger import get_logger

logger = get_logger(__name__)


class TelegramBotWorker(threading.Thread):
    MAIL_TESTER_DOMAIN = "mail-tester.com"
    MAIL_TESTER_BASE_URL = "https://www.mail-tester.com"

    def __init__(self, telegram_svc: ITelegramService, db: ILeadRepository,
                 vis_config: VisualizerConfig, bot_config: TelegramConfig,
                 email_service: IEmailService, template_str: str,
                 browser: IWebBrowser):
        super().__init__(daemon=True)
        self.telegram_svc = telegram_svc
        self.db = db
        self.vis_config = vis_config
        self.email_service = email_service
        self.template_str = template_str
        self.browser = browser

        self.graph_path = vis_config.output_file
        self.poll_timeout = bot_config.poll_timeout_sec
        self.poll_interval = bot_config.poll_interval_sec
        self._last_update_id = None

        self.command_router: Dict[str, Callable[[], None]] = {
            "1": self._cmd_send_graph,
            "2": self._cmd_send_stats,
            "3": self._cmd_send_menu,
            "4": self._cmd_run_mail_tester
        }

    def run(self):
        logger.info("Telegram Bot Worker started. Listening for commands...")
        self.telegram_svc.send_message("<b>Lead Hunter Daemon Online</b>\nSend '3' for menu.")

        while True:
            try:
                updates = self.telegram_svc.get_updates(offset=self._last_update_id, timeout=self.poll_timeout)

                for update in updates:
                    self._last_update_id = update["update_id"] + 1
                    message = update.get("message")

                    if not message or "text" not in message:
                        continue

                    if str(message["chat"]["id"]) != str(self.telegram_svc.chat_id):
                        logger.warning(f"Unauthorized access attempt from Chat ID: {message['chat']['id']}")
                        continue

                    user_text = str(message["text"]).strip()
                    logger.info(f"Received Telegram command: {user_text}")

                    handler = self.command_router.get(user_text, self._cmd_send_menu)
                    handler()

                time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Telegram Bot Worker encountered fatal error: {e}")
                time.sleep(10)

    def _cmd_send_graph(self):
        logger.info("Fulfilling request: Send Graph Image")

        if not os.path.exists(self.graph_path):
            self.telegram_svc.send_message("Graph file not found. It might not be generated yet.")
            return

        self.telegram_svc.send_message("Rendering live spider graph... Please wait a few seconds.")

        image_path = self.graph_path.replace(".html", ".png")
        success = self.browser.take_screenshot(self.graph_path, image_path)

        if success and os.path.exists(image_path):
            sent = self.telegram_svc.send_photo(
                file_path=image_path,
                caption="Current Lead Hunter Spider Graph"
            )
            if not sent:
                self.telegram_svc.send_message("Failed to upload the graph image to Telegram.")
        else:
            self.telegram_svc.send_message("Failed to render the graph into an image.")

    def _cmd_send_stats(self):
        logger.info("Fulfilling request: Send Stats")
        stats = self.db.get_stats()
        msg = (
            "<b>Hunt Statistics:</b>\n\n"
            f"URLs Visited: {stats['visited_urls']}\n"
            f"Total Secured Leads: {stats['total_leads']}\n"
            f"Queued for Email: {stats['uncontacted_leads']}\n"
        )
        self.telegram_svc.send_message(msg)

    def _cmd_run_mail_tester(self):
        logger.info("Fulfilling request: Run Deliverability Test")

        unique_id = uuid.uuid4().hex[:10]
        test_email_prefix = f"test-{unique_id}"
        target_email = f"{test_email_prefix}@{self.MAIL_TESTER_DOMAIN}"
        report_url = f"{self.MAIL_TESTER_BASE_URL}/{test_email_prefix}"

        self.telegram_svc.send_message(f"Dispatching test email to <b>{target_email}</b>...\nPlease wait.")

        try:
            subject = "Custom AI Engineering for Test Company"
            body = self.template_str.format(
                founder_name="Test Founder",
                company_name="Test Company"
            )

            success = self.email_service.send_email(
                to_address=target_email,
                subject=subject,
                body=body
            )

            if success:
                msg = (
                    "<b>Test Email Dispatched Successfully!</b>\n\n"
                    "Mail-Tester will now analyze your headers, IP reputation, and SPF/DKIM records.\n\n"
                    f"<b>Click here to view your live report:</b>\n{report_url}\n\n"
                    "<i>Note: It may take 10-20 seconds for the report to fully render on the website.</i>"
                )
                self.telegram_svc.send_message(msg)
            else:
                self.telegram_svc.send_message(
                    "<b>Error:</b> The email service failed to dispatch the test message. Check your SMTP configurations.")

        except Exception as e:
            logger.error(f"Failed to execute Mail-Tester command: {e}", exc_info=True)
            self.telegram_svc.send_message(f"<b>System Error:</b> Could not complete the test. Reason: {e}")

    def _cmd_send_menu(self):
        msg = (
            "<b>Lead Hunter Interactive Menu:</b>\n\n"
            "Please reply with a number:\n"
            "<b>1</b> - Request Live Spider Graph (PNG)\n"
            "<b>2</b> - Request DB Hunt Statistics\n"
            "<b>3</b> - Display this Menu\n"
            "<b>4</b> - Run Deliverability Test (Mail-Tester)"
        )
        self.telegram_svc.send_message(msg)