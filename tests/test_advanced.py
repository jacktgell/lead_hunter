import unittest
from unittest.mock import MagicMock
from application.pipeline import LeadGenerationPipeline
from domain.heuristics import UrlHeuristics


class TestAdvancedHuntLogic(unittest.TestCase):
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.max_depth = 2
        self.mock_config.junk_domains = []

        self.mock_db = MagicMock()
        self.mock_db.is_url_visited.return_value = False

        self.pipeline = LeadGenerationPipeline(
            llm=MagicMock(), searcher=MagicMock(), browser=MagicMock(),
            db=self.mock_db, tracker=MagicMock(), config=self.mock_config,
            event_queue=MagicMock()
        )

    def test_recursive_depth_limiter(self):
        """Ensures the crawler physically cannot exceed max_depth."""
        url = "https://example.com/deep/path"
        # Simulate being at depth 3 (which is > max_depth 2)
        leads = self.pipeline.investigate_url(url, depth=3, ledger=[])
        self.assertEqual(leads, [])
        self.mock_db.mark_url_visited.assert_not_called()

    def test_url_normalization_with_bad_input(self):
        """Tests that the normalization heuristic handles malformed relative paths."""
        base = "https://startup.com/about"
        target = "contact.html"
        result = UrlHeuristics.normalize(base, target)
        self.assertEqual(result, "https://startup.com/contact.html")

    def test_search_query_generation_fallback(self):
        """Ensures exceptions in query generation bubble up (or are handled)."""
        # Fix: Expect the exception to raise, as there is no try/except in run_hunt
        self.pipeline.llm.generate_search_queries.side_effect = Exception("LLM Down")

        with self.assertRaises(Exception) as cm:
            self.pipeline.run_hunt("intent")

        self.assertEqual(str(cm.exception), "LLM Down")