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
    FETCH_MULTIPLIER: Final[int] = 3 # Increased slightly to handle local pruning
    HREF_KEY: Final[str] = "href"

    # Deterministic local filter to replace the query-based -site: rules
    ASIAN_FORUM_FIREWALL: Final[Tuple[str, ...]] = (
        "zhihu.com", "baidu.com", "csdn.net",
        "chiebukuro.yahoo.co.jp", "sohu.com"
    )


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
        """
        safe_query = query

        # Relying on the LLM to inject location text (e.g., "London"),
        # so we use the worldwide region "th-th" to prevent DDG localization conflicts.
        logger.info(f"Executing global search query [th-th]: {safe_query}")
        valid_urls: List[str] = []

        try:
            # ---------------------------------------------------------
            # ANTI-BOT FIREWALL: The "Human Jitter"
            # ---------------------------------------------------------
            jitter_delay = random.uniform(5.0, 10.0)
            logger.info(f"Rate limit avoidance: Sleeping for {jitter_delay:.2f}s...")
            time.sleep(jitter_delay)
            # ---------------------------------------------------------

            fetch_limit = num_results * SearchConstants.FETCH_MULTIPLIER

            with DDGS() as ddgs:
                results = ddgs.text(
                    safe_query,
                    region="th-th",  # Enforces a neutral geographic baseline
                    max_results=fetch_limit,
                    backend="api"
                )

                if not results:
                    logger.warning(f"Search yielded no results for query: {safe_query}")
                    return []

                for result in results:
                    if self._process_result(result, valid_urls, num_results):
                        break

            self._log_results(valid_urls)
            return valid_urls

        except Exception as e:
            logger.error(f"Search engine execution failed for query '{safe_query}': {str(e)}", exc_info=True)

            if "429" in str(e) or "403" in str(e):
                penalty = random.randint(120, 300)
                logger.warning(f"HTTP 429/403 Detected: Emergency cool-down for {penalty}s...")
                time.sleep(penalty)

            return []

    def _process_result(self, result: Dict[str, Any], valid_urls: List[str], max_results: int) -> bool:
        """
        Validates and filters a single search result against domain heuristics.
        """
        url = result.get(SearchConstants.HREF_KEY)
        if not url or not isinstance(url, str):
            return False

        parsed_url = urlparse(url)
        netloc = parsed_url.netloc

        # THE FIREWALL: Pruning bad domains in Python rather than in the search query
        if netloc.endswith(self._blocked_tlds) or netloc.endswith(SearchConstants.ASIAN_FORUM_FIREWALL):
            logger.debug(f"Search Guard Triggered: Pruning forbidden domain -> {url}")
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