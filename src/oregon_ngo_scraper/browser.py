"""Production ``Browser`` implementation backed by Playwright.

Playwright is imported lazily so unit tests don't pay its startup cost and can
run without it installed. Use ``PlaywrightBrowser`` only via the ``Browser``
protocol; tests should inject a ``FakeBrowser`` instead.
"""

from __future__ import annotations

from typing import Any


class PlaywrightBrowser:
    """A minimal Playwright wrapper that returns rendered HTML for a URL."""

    def __init__(self, *, headless: bool = True, user_agent: str | None = None) -> None:
        self._headless = headless
        self._user_agent = user_agent
        self._playwright: Any | None = None
        self._browser: Any | None = None

    def _ensure_started(self) -> None:
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright  # local import

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)

    def render(self, url: str, *, timeout: float = 30.0) -> str:
        self._ensure_started()
        assert self._browser is not None
        context = self._browser.new_context(user_agent=self._user_agent)
        try:
            page = context.new_page()
            page.goto(url, timeout=int(timeout * 1000), wait_until="networkidle")
            return page.content()
        finally:
            context.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
