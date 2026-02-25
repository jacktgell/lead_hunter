"""
Core Interfaces (Ports) for the Lead Generation Pipeline.
Defines the strict contracts that all external adapters must fulfill.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from domain.models import Lead


class IComputeManager(ABC):
    """Contract for managing external compute infrastructure (e.g., GCP VMs)."""

    @abstractmethod
    def ensure_infrastructure_ready(self) -> str:
        """
        Verifies or provisions the required infrastructure before pipeline execution.

        Returns:
            str: Connection string, IP address, or status indicator.

        Raises:
            InfrastructureError: If the environment cannot be provisioned or reached.
        """
        ...


class ILLMProvider(ABC):
    """Contract for Large Language Model integrations."""

    @abstractmethod
    def generate_search_queries(self, persona_prompt: str) -> List[str]:
        """Translates a user intent into high-yield search engine queries."""
        ...

    @abstractmethod
    def investigate_page(self, page_text: str, url: str, memory_buffer: str) -> Dict[str, Any]:
        """
        Analyzes page content to determine if it contains a qualified lead.
        Must return a strictly formatted dictionary matching pipeline expectations.
        """
        ...

    @abstractmethod
    def draft_outreach(self, lead: Lead) -> str:
        """Generates highly personalized outreach copy for a specific lead."""
        ...


class ISearchEngine(ABC):
    """Contract for web search execution."""

    @abstractmethod
    def search(self, query: str, num_results: int = 5) -> List[str]:
        """
        Executes a search and returns a list of target URLs.
        Implementations should handle pagination and rate-limiting internally.
        """
        ...


class IWebBrowser(ABC):
    """Contract for headless browser automation and scraping."""

    @abstractmethod
    def extract_text(self, url: str) -> str:
        """
        Navigates to a URL and extracts clean, readable text.
        Must handle timeouts gracefully and return an empty string on failure.
        """
        ...

    @abstractmethod
    def take_screenshot(self, url: str, output_path: str) -> bool:
        """Captures a screenshot of the specified URL and saves it to disk."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Safely terminates the browser session and cleans up orphaned processes."""
        ...


class ILeadRepository(ABC):
    """Contract for lead and pipeline state persistence."""

    @abstractmethod
    def is_url_visited(self, url: str) -> bool:
        """Checks if a URL has already been processed (O(1) lookup expected)."""
        ...

    @abstractmethod
    def mark_url_visited(self, url: str) -> None:
        """Records a URL as processed to prevent circular crawling."""
        ...

    @abstractmethod
    def is_email_contacted(self, email: str) -> bool:
        """Verifies if an email address already exists in the contacted ledger."""
        ...

    @abstractmethod
    def save_lead(self, email: str, company: str, founder: str, reason: str) -> None:
        """Persists a newly discovered, qualified lead."""
        ...

    @abstractmethod
    def get_uncontacted_lead(self) -> Optional[Any]:  # Note: Return type should ideally be `Lead`
        """Retrieves the oldest uncontacted lead from the backlog."""
        ...

    @abstractmethod
    def get_random_uncontacted_lead(self) -> Optional[Any]:  # Note: Return type should ideally be `Lead`
        """Retrieves a random uncontacted lead (used for queue fallback injection)."""
        ...

    @abstractmethod
    def mark_failed(self, email: str) -> None:
        """Flags a lead as permanently failed (e.g., bounced email)."""
        ...

    @abstractmethod
    def mark_contacted(self, email: str) -> None:
        """Flags a lead as successfully contacted."""
        ...

    @abstractmethod
    def get_stats(self) -> Dict[str, int]:
        """Aggregates high-level metrics for reporting (e.g., total leads, visited URLs)."""
        ...


class IGraphVisualizer(ABC):
    """Contract for rendering the discovery tree."""

    @abstractmethod
    def add_node(self, node_id: str, label: str, color: str, title: Optional[str] = None) -> None:
        """Registers a new node in the graph state."""
        ...

    @abstractmethod
    def add_edge(self, source_id: str, target_id: str) -> None:
        """Creates a directional connection between two existing nodes."""
        ...

    @abstractmethod
    def render(self) -> None:
        """Compiles the current graph state into a visual format (e.g., HTML file)."""
        ...


class IEmailService(ABC):
    """Contract for dispatching outreach communications."""

    @abstractmethod
    def send_email(self, to_address: str, subject: str, body: str) -> bool:
        """
        Dispatches an email.
        Must return True on success, False on failure, and suppress underlying SMTP exceptions.
        """
        ...


class ITelegramService(ABC):
    """Contract for communicating with the Telegram Bot API."""

    @abstractmethod
    def send_message(self, text: str) -> bool:
        """Dispatches a text message to the configured admin chat."""
        ...

    @abstractmethod
    def send_document(self, file_path: str, caption: str = "") -> bool:
        """Uploads and sends a file attachment."""
        ...

    @abstractmethod
    def send_photo(self, file_path: str, caption: str = "") -> bool:
        """Uploads and sends an image attachment."""
        ...

    @abstractmethod
    def get_updates(self, offset: Optional[int], timeout: int) -> List[Dict[str, Any]]:
        """Long-polls the Telegram API for new user commands."""
        ...