"""Playwright renderer for JS-rendered (SPA) sources.

Renders a URL in headless Chromium and returns the post-JS HTML, which the same
discovery/extraction strategies then consume. The browser is launched lazily on
first use, so building a collector for a rendered source is cheap until it runs.

Requires the chromium browser binary: `python -m playwright install chromium`.
"""


class PlaywrightRenderer:
    def __init__(
        self,
        user_agent: str,
        timeout_ms: int = 30000,
        settle_ms: int = 3000,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        # After DOM load, let client-side JS render content. We deliberately avoid
        # "networkidle" — ad/analytics-heavy sites never go idle and time out.
        self.settle_ms = settle_ms
        self._pw = None
        self._browser = None

    def _ensure(self) -> None:
        if self._browser is None:
            from playwright.sync_api import sync_playwright  # lazy: only when rendering

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)

    def render(self, url: str) -> str:
        self._ensure()
        page = self._browser.new_page(user_agent=self.user_agent)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(self.settle_ms)
            return page.content()
        finally:
            page.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None
