import unittest
from unittest.mock import MagicMock
from application.pipeline import LeadGenerationPipeline


class TestFullSystemIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_searcher = MagicMock()
        self.mock_browser = MagicMock()
        self.mock_db = MagicMock()
        self.mock_tracker = MagicMock()
        self.mock_config = MagicMock()
        self.mock_event_queue = MagicMock()

        # Fix: Configure the mock config object with required attributes
        self.mock_config.max_depth = 3
        self.mock_config.junk_domains = []
        self.mock_config.max_path_chars = 1000
        self.mock_config.max_observation_chars = 500
        self.mock_config.max_leafs = 3

    def test_end_to_end_hunt_flow(self):
        """
        Simulates:
        1. Search Query -> 2. URL Discovery -> 3. Scraping -> 4. LLM Conversion
        """
        # 1. Mock LLM Responses
        self.mock_llm.generate_search_queries.return_value = ["AI Startups"]
        self.mock_llm.investigate_page.return_value = {
            "decision": "CONVERT",
            "discovery_summary": "Good match",
            "lead_data": {"email": "boss@ai.com", "company": "AI Corp", "person": "Founder"}
        }

        # 2. Mock Search Results
        self.mock_searcher.search.return_value = ["https://ai.com"]

        # 3. Mock Browser
        self.mock_browser.extract_text.return_value = "We are an AI startup."

        # 4. Mock DB (Allow visit)
        self.mock_db.is_url_visited.return_value = False
        self.mock_db.is_email_contacted.return_value = False

        pipeline = LeadGenerationPipeline(
            llm=self.mock_llm,
            searcher=self.mock_searcher,
            browser=self.mock_browser,
            db=self.mock_db,
            tracker=self.mock_tracker,
            config=self.mock_config,
            event_queue=self.mock_event_queue
        )

        # Run the hunt
        pipeline.run_hunt("Find AI clients")

        # ASSERT: Check that the lead was found and queued
        self.mock_searcher.search.assert_called_with("AI Startups")
        self.mock_event_queue.put.assert_called()

        # Verify the lead put into the queue has the right email
        args, _ = self.mock_event_queue.put.call_args
        lead = args[0]
        self.assertEqual(lead.email, "boss@ai.com")