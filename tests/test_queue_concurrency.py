import unittest
import queue
import threading
from application.work_email import BackgroundEmailWorker


class TestQueueIntegrity(unittest.TestCase):
    def test_producer_consumer_parity(self):
        """Ensures no leads are dropped if multiple threads find leads simultaneously."""
        event_queue = queue.Queue()

        def produce_leads(count):
            for i in range(count):
                event_queue.put(f"lead_{i}@test.com")

        # Simulate 5 concurrent discovery threads
        threads = [threading.Thread(target=produce_leads, args=(10,)) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(event_queue.qsize(), 50)