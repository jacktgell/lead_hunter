import json
import time
import random
from urllib.parse import urlparse
from typing import List, Tuple, Dict, Any, Final

from ddgs import DDGS  # Updated to fix the RuntimeWarning
from core.interfaces import ISearchEngine
from core.config import SearchConfig
from core.logger import get_logger

logger = get_logger(__name__)


class SearchExecutionError(Exception):
    """Raised when the search engine dependency encounters a fatal failure."""
    pass


class SearchConstants:
    """Centralized constants for search query execution."""
    FETCH_MULTIPLIER: Final[int] = 2
    HREF_KEY: Final[str] = "href"

    # NEW: Hardcoded firewall against Asian Q&A forums
    ASIAN_FORUM_FIREWALL: Final[
        str] = "-site:zhihu.com -site:baidu.com -site:csdn.net -site:chiebukuro.yahoo.co.jp -site:sohu.com"

    # NEW: Comprehensive list of premium, English-friendly business regions
    GLOBAL_REGIONS: Final[List[str]] = [
        "us-en", "ca-en", "uk-en", "ie-en", "au-en", "nz-en",  # West/Oceania
        "sg-en", "my-en", "th-en", "ph-en", "id-en",  # Southeast Asia
        "ae-en", "qa-en", "sa-en",  # Middle East
        "za-en", "hk-en"  # Emerging/Other
    ]


class DuckDuckGoSearch(ISearchEngine):
    """
    Concrete implementation of the ISearchEngine interface using DuckDuckGo.
    Handles rate-limiting, strict domain filtering, safe result extraction, and global routing.
    """

    def __init__(self, config: SearchConfig) -> None:
        self.config = config

        # O(1) Pre-computation: Cast to tuple once at boot to optimize the .endswith() check
        self._blocked_tlds: Tuple[str, ...] = tuple(config.blocked_tlds)

    def search(self, query: str, num_results: int = 10) -> List[str]:
        """
        Executes a search query and returns a filtered list of target URLs.

        Args:
            query: The search string (supports Boolean operators).
            num_results: The maximum number of valid URLs to return.

        Returns:
            List[str]: A list of clean, absolute URLs matching the query.
        """
        # 1. Programmatically inject the negative constraints
        safe_query = f"{query} {SearchConstants.ASIAN_FORUM_FIREWALL}"

        # 2. Pick a random premium region for this specific search
        target_region = random.choice(SearchConstants.GLOBAL_REGIONS)

        logger.info(f"Executing search query in region [{target_region}]: {safe_query}")
        valid_urls: List[str] = []

        try:
            # Fetch surplus results to account for post-fetch pruning attrition
            fetch_limit = num_results * SearchConstants.FETCH_MULTIPLIER

            with DDGS() as ddgs:
                # 3. Pass the region directly into the DDGS backend
                results = ddgs.text(safe_query, region=target_region, max_results=fetch_limit)

                if not results:
                    logger.warning(f"Search yielded no results for query: {safe_query}")
                    return []

                for result in results:
                    if self._process_result(result, valid_urls, num_results):
                        break

            self._log_results(valid_urls)

            # Enforce rate-limiting constraint to prevent IP ban from DDG
            time.sleep(self.config.request_delay_sec)

            return valid_urls

        except Exception as e:
            # We catch generic exceptions here because the DDGS library can throw
            # unpredictable HTTP errors, Timeout errors, or JSON decoding errors.
            logger.error(f"Search engine execution failed for query '{safe_query}': {str(e)}", exc_info=True)
            # Returning an empty list ensures the broader pipeline continues to the next query
            return []

    def _process_result(self, result: Dict[str, Any], valid_urls: List[str], max_results: int) -> bool:
        """
        Validates and filters a single search result against domain heuristics.

        Args:
            result: The raw dictionary payload from the DDGS library.
            valid_urls: The mutated list of successfully validated URLs.
            max_results: The target capacity.

        Returns:
            bool: True if the maximum number of results has been reached.
        """
        url = result.get(SearchConstants.HREF_KEY)
        if not url or not isinstance(url, str):
            return False

        parsed_url = urlparse(url)

        # Domain filtering logic using the pre-computed tuple
        if parsed_url.netloc.endswith(self._blocked_tlds):
            logger.debug(f"Search Guard Triggered: Pruning blocked domain -> {url}")
            return False

        valid_urls.append(url)
        return len(valid_urls) >= max_results

    def _log_results(self, valid_urls: List[str]) -> None:
        """Formats and outputs the final selected URLs for audit traceability."""
        if not valid_urls:
            return

        formatted_urls = json.dumps(valid_urls, indent=2)
        logger.debug(
            f"\n{'=' * 40}\n"
            f"DUCKDUCKGO SEARCH RESULTS:\n"
            f"{'=' * 40}\n"
            f"{formatted_urls}\n"
            f"{'=' * 40}"
        )