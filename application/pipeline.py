import threading
import queue
from typing import List, Optional, Dict, Any
from enum import StrEnum

from domain.models import Lead
from domain.heuristics import UrlHeuristics
from application.tracker import GraphTracker
from core.interfaces import ILLMProvider, ISearchEngine, IWebBrowser, ILeadRepository
from core.config import PipelineConfig
from core.logger import get_logger
from domain.validators import ApiEmailValidator

logger = get_logger(__name__)


class NodeState(StrEnum):
    PENDING = "pending"
    SKIP = "skip"
    PRUNE = "prune"
    CONVERT = "convert"
    QUERY = "query"


class PipelineConstants:
    DEFAULT_NA = "N/A"
    DECISION_FOLLOW = "FOLLOW"
    DECISION_CONVERT = "CONVERT"
    DECISION_PRUNE = "PRUNE"


class LeadExtractionError(Exception):
    """Raised when lead data fails domain-specific validation."""
    pass


class LeadGenerationPipeline:
    """
    Core orchestration engine for autonomous lead discovery.
    Refactored for high-scale observability and modularity.
    """

    def __init__(
            self,
            llm: ILLMProvider,
            searcher: ISearchEngine,
            browser: IWebBrowser,
            db: ILeadRepository,
            tracker: GraphTracker,
            config: PipelineConfig,
            event_queue: queue.Queue
    ):
        self.llm = llm
        self.searcher = searcher
        self.browser = browser
        self.db = db
        self.tracker = tracker
        self.config = config
        self.event_queue = event_queue

        # Thread safety for shared local resources
        self._db_lock = threading.Lock()
        self._browser_lock = threading.Lock()

    def run_hunt(self, user_intent: str) -> List[Lead]:
        """Entry point for the lead discovery process."""
        found_leads: List[Lead] = []

        try:
            queries = self.llm.generate_search_queries(user_intent)
        except Exception as e:
            logger.critical(f"Query generation failed: {str(e)}", exc_info=True)
            raise

        for query in queries:
            query_id = f"QUERY: {query}"
            self.tracker.update_node(query_id, NodeState.QUERY, "Search Engine Query")

            initial_urls = self.searcher.search(query)

            for url in initial_urls:
                normalized_url = UrlHeuristics.normalize(url, url)
                logger.info(f"Investigating root URL: {normalized_url}")

                try:
                    leads = self.investigate_url(normalized_url, 0, [], query_id)
                    found_leads.extend(leads)
                except Exception as exc:
                    logger.error(f"Pipeline execution error on {normalized_url}: {str(exc)}", exc_info=True)

        return found_leads

    def investigate_url(
            self,
            url: str,
            depth: int,
            ledger: List[str],
            parent_url: Optional[str] = None
    ) -> List[Lead]:
        """Recursive function to explore and qualify URLs."""
        self.tracker.update_node(url, NodeState.PENDING, f"Depth: {depth}", parent_id=parent_url)

        if self._should_skip(url, depth):
            return []

        page_text = self._safe_extract_text(url)
        if not page_text:
            return []

        # Context window management for LLM
        ledger.append(f"[{depth}] {url}")
        context = "\n".join(ledger)[-self.config.max_path_chars:]

        # Execute LLM Analysis
        analysis = self.llm.investigate_page(
            page_text[:self.config.max_observation_chars],
            url,
            context
        )

        return self._process_decision(url, depth, ledger, analysis)

    def _should_skip(self, url: str, depth: int) -> bool:
        """Centralized validation for pruning and deduplication."""
        with self._db_lock:
            if depth > self.config.max_depth or self.db.is_url_visited(url):
                self.tracker.update_node(url, NodeState.SKIP, "Visited or Depth Limit")
                return True
            self.db.mark_url_visited(url)

        if any(junk in url.lower() for junk in self.config.junk_domains):
            self.tracker.update_node(url, NodeState.PRUNE, "Junk Domain Match")
            return True

        return False

    def _safe_extract_text(self, url: str) -> str:
        """Wrapped browser logic with high-level error handling."""
        try:
            with self._browser_lock:
                text = self.browser.extract_text(url)
                if text:
                    return text
        except Exception as e:
            logger.warning(f"Browser failed for {url}: {str(e)}")

        self.tracker.update_node(url, NodeState.PRUNE, "Extraction Failed")
        return ""

    def _process_decision(self, url: str, depth: int, ledger: List[str], res: Dict[str, Any]) -> List[Lead]:
        """Routes the LLM response to the appropriate handler."""
        decision = res.get('decision', PipelineConstants.DECISION_PRUNE)
        summary = res.get('discovery_summary', 'No summary provided')
        data = res.get('lead_data', {})

        if decision == PipelineConstants.DECISION_FOLLOW:
            return self._handle_follow(url, depth, ledger, res, summary)

        if decision == PipelineConstants.DECISION_CONVERT:
            return self._handle_convert(url, data, summary)

        # Handle PRUNE
        self.tracker.update_node(url, NodeState.PRUNE, f"Reason: {summary}")
        return []

    def _handle_follow(self, url: str, depth: int, ledger: List[str], res: dict, summary: str) -> List[Lead]:
        raw_urls = res.get('next_target_urls', [])
        if not isinstance(raw_urls, list):
            raw_urls = [raw_urls] if raw_urls else []

        clean_urls = {UrlHeuristics.normalize(url, n) for n in raw_urls if n}
        targets = sorted(list(clean_urls), key=UrlHeuristics.rank_url)[:self.config.max_leafs]

        if not targets:
            self.tracker.update_node(url, NodeState.SKIP, "No valid links found")
            return []

        enriched_ledger = ledger.copy()
        enriched_ledger[-1] += f" -> [Note: {summary}]"

        branch_leads = []
        for target in targets:
            found = self.investigate_url(target, depth + 1, enriched_ledger.copy(), parent_url=url)
            branch_leads.extend(found)
            if found:
                # Early exit optimization for high-confidence branches
                break

        state = NodeState.CONVERT if branch_leads else NodeState.PRUNE
        self.tracker.update_node(url, state, f"Branch Result: {summary}")
        return branch_leads

    def _handle_convert(self, url: str, data: dict, summary: str) -> List[Lead]:
        try:
            email = str(data.get('email', '')).strip()
            company = str(data.get('company', PipelineConstants.DEFAULT_NA)).strip()
            person = str(data.get('person', PipelineConstants.DEFAULT_NA)).strip()

            if not ApiEmailValidator.is_deliverable(email, self.config.email.verification_api_key):
                logger.warning(f"Invalid email detected via API: {email}. Flagging for enrichment.")
                email = f"NEEDS_ENRICHMENT@{company.replace(' ', '').lower()}.com"

            if not email or "@" not in email:
                logger.warning(f"Qualified lead missing email: {company}. Flagging for enrichment.")
                email = f"NEEDS_ENRICHMENT@{company.replace(' ', '').lower()}.com"

            with self._db_lock:
                if self.db.is_email_contacted(email) and "NEEDS_ENRICHMENT" not in email:
                    self.tracker.update_node(url, NodeState.SKIP, "Already Contacted")
                    return []

                self.db.save_lead(email, company, person, summary)
                lead = Lead(
                    url=url,
                    company_name=company,
                    founder_name=person,
                    email=email,
                    is_qualified=True
                )
                self.event_queue.put(lead)
                self.tracker.update_node(url, NodeState.CONVERT, f"LEAD: {company}")
                return [lead]

        except LeadExtractionError as e:
            logger.debug(f"Lead validation failed at {url}: {str(e)}")
            self.tracker.update_node(url, NodeState.SKIP, "Incomplete Lead Data")
            return []