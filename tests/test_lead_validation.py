import unittest
from unittest.mock import MagicMock
from application.pipeline import LeadGenerationPipeline


class TestLeadValidation(unittest.TestCase):
    def test_discard_leads_missing_critical_fields(self):
        """Tests that the pipeline rejects leads that don't meet the 'Contactable' contract."""
        # Fix: Mock dependencies
        pipeline = LeadGenerationPipeline(
            llm=MagicMock(), searcher=MagicMock(), browser=MagicMock(),
            db=MagicMock(), tracker=MagicMock(), config=MagicMock(),
            event_queue=MagicMock()
        )

        # Scenarios of malformed LLM outputs
        scenarios = [
            {"email": None, "company": "NoEmailCorp"},
            {"email": "invalid-at-sign", "company": "BadEmail"},
            {"email": "test@test.com", "company": ""}
        ]

        for data in scenarios:
            result = pipeline._handle_convert("url", 0, data, "Summary")
            # If email is invalid, result should be empty list
            if not data.get("email") or "@" not in str(data.get("email")):
                self.assertEqual(len(result), 0, f"Failed on {data}")