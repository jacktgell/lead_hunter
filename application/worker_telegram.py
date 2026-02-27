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
                    if "@" in user_text:
                        self._cmd_send_custom_test(user_text)
                    else:
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
        """Instructs the user how to run a deliverability test with the new workflow."""
        msg = (
            "<b>Deliverability Test Instructions:</b>\n\n"
            "1. Open <a href='https://www.mail-tester.com'>mail-tester.com</a> in your browser.\n"
            "2. Copy the exact random email address displayed on their screen.\n"
            "3. <b>Paste that email address directly into this chat.</b>\n\n"
            "The daemon will instantly fire a test template to that inbox so you can check your spam score."
        )
        self.telegram_svc.send_message(msg)

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


    def _cmd_send_custom_test(self, target_email: str):
        """Fires a test email to any address pasted into the chat."""
        self.telegram_svc.send_message(f"Dispatching test outreach to <b>{target_email}</b>...")

        try:
            subject = "Custom AI Engineering / Python Architecture"
            body = self.template_str.format(
                founder_name="Hiring Manager",
                company_name="Tech Corp"
            )

            success = self.email_service.send_email(
                to_address=target_email,
                subject=subject,
                body=body
            )

            if success:
                self.telegram_svc.send_message(
                    "<b>Test Email Dispatched Successfully!</b>\nCheck the inbox to verify formatting and deliverability.")
            else:
                self.telegram_svc.send_message("<b>Error:</b> SMTP dispatch failed. Check logs.")

        except Exception as e:
            logger.error(f"Failed to execute custom test: {e}", exc_info=True)
            self.telegram_svc.send_message(f"<b>System Error:</b> {e}")