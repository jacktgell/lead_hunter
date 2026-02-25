import logging
from typing import Final, FrozenSet
from urllib.parse import urljoin, urldefrag

# Assuming core.logger is available based on previous context, otherwise standard logging is used.
try:
    from core.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


class UrlHeuristics:
    """
    Pure functional utilities for URL intelligence, ranking, and normalization.
    Used to guide the crawler toward high-value lead pages and deduplicate targets.
    """

    # Constants externalized to prevent magic strings and allow single-source updates
    HIGH_VALUE_PATHS: Final[FrozenSet[str]] = frozenset([
        "about", "team", "contact", "people",
        "founder", "leadership", "company"
    ])

    LOW_VALUE_PATHS: Final[FrozenSet[str]] = frozenset([
        "blog", "article", "news", "category", "tag"
    ])

    @staticmethod
    def rank_url(url: str) -> int:
        """
        Assigns a priority score to a URL based on keyword heuristics.

        Args:
            url: The URL string to evaluate.

        Returns:
            int: Priority score (0 = Highest, 1 = Neutral, 2 = Lowest).
        """
        if not url or not isinstance(url, str):
            return 2

        lower_url = url.lower()

        if any(keyword in lower_url for keyword in UrlHeuristics.HIGH_VALUE_PATHS):
            return 0

        if any(low_val in lower_url for low_val in UrlHeuristics.LOW_VALUE_PATHS):
            return 2

        return 1

    @staticmethod
    def normalize(base_url: str, target_url: str) -> str:
        """
        Resolves relative links to absolute URLs and standardizes the format
        by removing fragments and trailing slashes.

        Args:
            base_url: The root URL context (e.g., 'https://example.com').
            target_url: The scraped URL (absolute or relative, e.g., '/team#founders').

        Returns:
            str: A clean, absolute URL safe for deduplication checks, or an empty 
                 string if the inputs are strictly invalid.
        """
        try:
            if not target_url or not isinstance(target_url, str):
                return ""

            # urljoin safely handles cases where target_url is already absolute
            absolute_url = urljoin(str(base_url), target_url)

            # Remove hash fragments (e.g., #section1) which do not change page content
            clean_url, _ = urldefrag(absolute_url)

            # Standardize directory paths to prevent duplicate tracking
            return clean_url.rstrip("/")

        except Exception as e:
            logger.debug(f"Normalization failed for base '{base_url}' and target '{target_url}': {str(e)}")
            return ""