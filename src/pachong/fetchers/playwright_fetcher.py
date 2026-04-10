from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, Page, Playwright, async_playwright

from pachong.models.task import FetchConfig


@dataclass
class PageSnapshot:
    final_url: str
    title: str
    html: str


class PlaywrightFetcher:
    def __init__(self, config: FetchConfig):
        self.config = config
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None

    async def __aenter__(self) -> "PlaywrightFetcher":
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.config.headless)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.browser is not None:
            await self.browser.close()
        if self.playwright is not None:
            await self.playwright.stop()

    async def fetch(self, url: str, screenshot_path: Path | None = None) -> PageSnapshot:
        if self.browser is None:
            raise RuntimeError("Browser has not been started")

        context = await self.browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(
                url,
                wait_until=self.config.wait_until,
                timeout=self.config.timeout_ms,
            )

            await self._wait_for_ready(page)

            if self.config.auto_scroll:
                await self._auto_scroll(page)

            if screenshot_path is not None:
                await page.screenshot(path=str(screenshot_path), full_page=True)

            html = await page.content()
            title = await page.title()
            return PageSnapshot(final_url=page.url, title=title, html=html)
        finally:
            await page.close()
            await context.close()

    async def _wait_for_ready(self, page: Page) -> None:
        if self.config.wait_selector:
            await page.wait_for_selector(self.config.wait_selector, timeout=self.config.timeout_ms)
        if self.config.wait_for_text_selector:
            await page.wait_for_function(
                """
                ({ selector, minLength }) => {
                    const el = document.querySelector(selector);
                    if (!el) return false;
                    const text = (el.innerText || el.textContent || "").trim();
                    return text.length >= minLength;
                }
                """,
                arg={
                    "selector": self.config.wait_for_text_selector,
                    "minLength": self.config.wait_for_text_min_length,
                },
                timeout=self.config.timeout_ms,
            )
        if self.config.delay_after_load_ms > 0:
            await page.wait_for_timeout(self.config.delay_after_load_ms)

    async def _auto_scroll(self, page: Page) -> None:
        last_height = await page.evaluate("document.body.scrollHeight")
        while True:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
