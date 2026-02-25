import unittest
import queue
import time
from unittest.mock import MagicMock
from application.work_email import BackgroundEmailWorker
from domain.models import Lead


class TestEmailWorkerThread(unittest.TestCase):
    def test_worker_processes_queue_and_handles_retry(self):
        """Tests that the worker correctly retries a failed email exactly once."""
        mock_db = MagicMock()
        mock_email = MagicMock()
        mock_tele = MagicMock()
        event_queue = queue.Queue()

        # Configure email to fail the first time, succeed the second
        mock_email.send_email.side_effect = [False, True]

        worker = BackgroundEmailWorker(
            db=mock_db,
            email_service=mock_email,
            telegram_svc=mock_tele,
            interval_sec=0,  # No sleep for tests
            template_str="Hi {founder_name}",
            event_queue=event_queue
        )

        test_lead = Lead(url="", email="fail@test.com", company_name="Test", founder_name="Jane")
        event_queue.put(test_lead)

        # Process first attempt (Failure)
        worker._process_lead(event_queue.get())
        self.assertEqual(test_lead.retry_count, 1)

        # Process second attempt (Success)
        worker._process_lead(event_queue.get())
        mock_db.mark_contacted.assert_called_with("fail@test.com")