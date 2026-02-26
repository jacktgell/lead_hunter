import unittest
from unittest.mock import MagicMock
from application.pipeline import LeadGenerationPipeline

import unittest
from unittest.mock import MagicMock
from application.pipeline import LeadGenerationPipeline


class TestLeadValidation(unittest.TestCase):
    def test_flag_leads_missing_critical_fields_for_enrichment(self):
        """Tests that the pipeline flags leads without emails for later enrichment instead of deleting them."""
        # Mock dependencies
        pipeline = LeadGenerationPipeline(
            llm=MagicMock(), searcher=MagicMock(), browser=MagicMock(),
            db=MagicMock(), tracker=MagicMock(), config=MagicMock(),
            event_queue=MagicMock()
        )

        # Scenarios of malformed LLM outputs
        scenarios = [
            {"email": None, "company": "NoEmailCorp"},
            {"email": "invalid-at-sign", "company": "BadEmail"},
            {"email": "", "company": "EmptyCorp"}
        ]

        for data in scenarios:
            result = pipeline._handle_convert("url", data, "Summary")

            # The pipeline should no longer discard the lead (length should be 1)
            self.assertEqual(len(result), 1, f"Pipeline incorrectly discarded lead: {data}")

            # Verify the email was successfully flagged for enrichment
            saved_lead = result[0]
            self.assertTrue("NEEDS_ENRICHMENT" in saved_lead.email, f"Email not flagged correctly: {saved_lead.email}")