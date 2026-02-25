# tests/test_fuzzing.py
import unittest
from hypothesis import given, strategies as st
from domain.heuristics import UrlHeuristics

class TestHeuristicFuzzing(unittest.TestCase):
    @given(st.text(), st.text())
    def test_normalization_never_crashes(self, base, target):
        """
        Fuzz Test: Ensures that no matter what garbage text is scraped,
        the normalization logic never raises an unhandled exception.
        """
        try:
            UrlHeuristics.normalize(base, target)
        except Exception as e:
            self.fail(f"UrlHeuristics.normalize crashed with input: {base}, {target}. Error: {e}")

    @given(st.text())
    def test_ranking_is_total(self, url):
        """Ensures every possible string results in a valid integer rank."""
        rank = UrlHeuristics.rank_url(url)
        self.assertIsInstance(rank, int)