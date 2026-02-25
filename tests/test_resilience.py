import unittest
from unittest.mock import MagicMock
from application.pipeline import LeadGenerationPipeline


class TestPipelineResilience(unittest.TestCase):
    def test_graceful_handling_of_browser_timeout(self):
        """Verifies the pipeline doesn't crash if the browser fails to render a page."""
        mock_browser = MagicMock()
        mock_browser.extract_text.side_effect = Exception("Browser Timeout")

        mock_config = MagicMock()
        # Fix: Ensure max_depth is an integer for comparison logic
        mock_config.max_depth = 5
        mock_config.junk_domains = []

        mock_db = MagicMock()
        mock_db.is_url_visited.return_value = False

        # Setup pipeline with mock browser
        pipeline = LeadGenerationPipeline(
            llm=MagicMock(), searcher=MagicMock(), browser=mock_browser,
            db=mock_db, tracker=MagicMock(), config=mock_config,
            event_queue=MagicMock()
        )

        # Should return empty list and log error, not raise exception
        leads = pipeline.investigate_url("https://broken.com", 0, [])
        self.assertEqual(leads, [])