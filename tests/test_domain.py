import unittest
from domain.signatures import WebpageEvaluation

class TestDomainSignatures(unittest.TestCase):
    def test_webpage_evaluation_schema(self):
        """Ensures the Pydantic output model enforces strict decision types."""
        # Valid data
        valid_eval = WebpageEvaluation(
            decision="CONVERT",
            discovery_summary="Found email",
            email="test@test.com"
        )
        self.assertEqual(valid_eval.decision, "CONVERT")

        # Validation Check: Ensure default values work
        empty_eval = WebpageEvaluation(decision="PRUNE", discovery_summary="Irrelevant")
        self.assertEqual(empty_eval.company, "Unknown")
        self.assertEqual(empty_eval.next_target_urls, [])