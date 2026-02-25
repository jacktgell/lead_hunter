import unittest
import queue
from unittest.mock import MagicMock
from application.work_email import BackgroundEmailWorker
from domain.models import Lead


class TestSystemInvariants(unittest.TestCase):
    """Testing the fundamental laws of the Lead Hunter ecosystem."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_email = MagicMock()
        self.event_queue = MagicMock()

        self.worker = BackgroundEmailWorker(
            db=self.mock_db, email_service=self.mock_email,
            telegram_svc=MagicMock(), interval_sec=0,
            template_str="Hello", event_queue=self.event_queue
        )

    def test_invariant_no_retry_after_hard_failure(self):
        """Rule: A lead marked as DEAD must never be re-queued."""
        lead = Lead(url="test.com", email="hard-bounce@test.com", retry_count=1)

        # Simulate a final failure
        self.mock_email.send_email.return_value = False

        # Fix: Prevent the worker from fetching a fallback lead to keep queue empty
        self.mock_db.get_random_uncontacted_lead.return_value = None

        self.worker._process_lead(lead)

        # Verify it was marked as failed
        self.mock_db.mark_failed.assert_called_with("hard-bounce@test.com")

        # Fix: Ensure put was not called (because no fallback was found)
        self.event_queue.put.assert_not_called()

    def test_invariant_jitter_calculation_bounds(self):
        """Rule: Sleep jitter must remain within 80% to 120% of base interval."""
        self.worker.base_interval_sec = 100
        for _ in range(100):
            jittered = self.worker._calculate_jittered_sleep()
            self.assertTrue(80 <= jittered <= 120)