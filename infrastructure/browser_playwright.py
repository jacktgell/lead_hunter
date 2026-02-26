import os
import re
import threading
from typing import List, Any, Final, Optional

from camoufox.sync_api import Camoufox
from langdetect import detect, DetectorFactory

from core.interfaces import IWebBrowser
from core.config import BrowserConfig
from core.logger import get_logger

# Ensure deterministic language detection
DetectorFactory.seed = 0
logger = get_logger(__name__)


class BrowserConstants:
    """Centralized constants and scripts for browser operations."""
    TARGET_LANGUAGE: Final[str] = 'en'
    PHYSICS_SETTLE_MS: Final[int] = 3000

    # JavaScript payload to strip noise (scripts, styles) and format links for LLM ingestion
    DOM_CLEANER_JS: Final[str] = """
        () => {
            document.querySelectorAll('script, style, noscript, svg, iframe').forEach(el => el.remove());
            document.querySelectorAll('a').forEach(a => {
                if (a.href && a.innerText.trim() !== '') {
                    a.innerText = `[${a.innerText.trim()}](${a.href})`;
                }
            });
            return document.body.innerText;
        }
    """


class PlaywrightBrowser(IWebBrowser):
    """
    Thread-safe implementation of the IWebBrowser interface using Camoufox (Playwright).
    Maintains isolated browser contexts per thread to support concurrent scraping.
    """

    def __init__(self, config: BrowserConfig) -> None:
        self.headless: bool = config.headless
        self.timeout: int = config.timeout_ms
        self.local = threading.local()

        # Shared registry to track all thread-local contexts for global teardown
        self.active_contexts: List[Any] = []
        self._registry_lock = threading.Lock()

    def _get_browser(self) -> Any:
        """
        Retrieves or initializes a thread-local browser instance.
        Ensures O(1) lookup for the current thread's active browser.
        """
        if not hasattr(self.local, 'context'):
            thread_id = threading.get_ident()
            logger.debug(f"Booting persistent Camoufox engine for thread {thread_id}...")

            context = Camoufox(headless=self.headless)
            # Booting the context synchronously
            browser = context.__enter__()

            self.local.context = context
            self.local.browser = browser

            with self._registry_lock:
                self.active_contexts.append(context)

        return self.local.browser

    def _resolve_file_url(self, url: str) -> str:
        """Pure function to ensure local file paths are properly formatted for Playwright."""
        if not url.startswith(('http://', 'https://', 'file://')):
            abs_path = os.path.abspath(url).replace('\\', '/')
            return f"file:///{abs_path}"
        return url

    def extract_text(self, url: str) -> str:
        """
        Navigates to a URL, waits for DOM content, strips noise, and returns raw text.
        Includes a language guard to ignore non-English pages.
        Aggressively pre-extracts emails via Regex to guarantee the LLM sees them.
        """
        browser = self._get_browser()
        page = browser.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)

            # 1. Grab raw HTML before the DOM cleaner destroys potentially useful mailto links
            raw_html = page.content()

            # 2. Aggressive Regex Email Extraction
            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            found_emails = list(set(re.findall(email_pattern, raw_html)))

            # Filter out common false positives (image extensions, generic domains, tracking emails)
            ignore_list = (
                '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
                'sentry.io', 'example.com', 'yourdomain.com'
            )
            clean_emails = [
                e for e in found_emails
                if not e.lower().endswith(ignore_list) and not e.startswith(('u00', '12345'))
            ]

            # 3. Clean the DOM to remove noise and save LLM context tokens
            llm_friendly_text = str(page.evaluate(BrowserConstants.DOM_CLEANER_JS))

            if not llm_friendly_text.strip():
                return ""

            # 4. Language Guard
            try:
                lang = detect(llm_friendly_text)
                if lang != BrowserConstants.TARGET_LANGUAGE:
                    logger.warning(f"Language Guard Triggered: Skipping {url} (Detected '{lang}')")
                    return ""
            except Exception as e:
                logger.debug(f"Language detection failed for {url}. Proceeding. Error: {str(e)}")

            # 5. Inject the high-confidence emails at the very top of the LLM prompt
            if clean_emails:
                header = f"--- HIGH CONFIDENCE EMAILS FOUND ON PAGE: {', '.join(clean_emails)} ---\n\n"
                llm_friendly_text = header + llm_friendly_text

            return llm_friendly_text

        except Exception as e:
            logger.error(f"Browser extraction failed for {url}: {str(e)}", exc_info=True)
            return ""

        finally:
            try:
                page.close()
            except Exception as e:
                logger.warning(f"Resource leak warning: Failed to close page for {url}: {str(e)}")

    def take_screenshot(self, url: str, output_path: str) -> bool:
        """Renders a target URL (or local HTML file) to a PNG."""
        browser = self._get_browser()
        page = browser.new_page()

        try:
            target_url = self._resolve_file_url(url)
            page.goto(target_url, wait_until="networkidle", timeout=self.timeout)

            # Allow rendering engines (like Pyvis physics) to settle
            page.wait_for_timeout(BrowserConstants.PHYSICS_SETTLE_MS)

            page.screenshot(path=output_path, full_page=True)
            return True

        except Exception as e:
            logger.error(f"Screenshot rendering failed for {url}: {str(e)}", exc_info=True)
            return False

        finally:
            try:
                page.close()
            except Exception as e:
                logger.warning(f"Resource leak warning: Failed to close screenshot page for {url}: {str(e)}")

    def close(self) -> None:
        """Iterates through all registered thread-local contexts and forces a clean shutdown."""
        with self._registry_lock:
            logger.info(f"Shutting down {len(self.active_contexts)} active browser engine(s)...")
            for context in self.active_contexts:
                try:
                    context.__exit__(None, None, None)
                except Exception as e:
                    logger.error(f"Error during context teardown: {str(e)}", exc_info=True)
            self.active_contexts.clear()