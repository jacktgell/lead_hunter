import unittest
from domain.heuristics import UrlHeuristics


class TestUrlIntelligence(unittest.TestCase):
    def test_url_ranking_priority(self):
        """Verifies that high-value business pages are ranked higher (lower score)."""
        high_val = "https://startup.com/team-leadership"
        mid_val = "https://startup.com/products"
        low_val = "https://startup.com/blog/2023-recap"

        # Lower rank = Higher priority
        self.assertLess(UrlHeuristics.rank_url(high_val), UrlHeuristics.rank_url(low_val))
        self.assertEqual(UrlHeuristics.rank_url(mid_val), 1)

    def test_url_normalization_safety(self):
        """Ensures fragments and trailing slashes don't cause duplicate investigations."""
        base = "https://test.com/page"
        target = "about/#contact-section"

        normalized = UrlHeuristics.normalize(base, target)
        self.assertEqual(normalized, "https://test.com/about")