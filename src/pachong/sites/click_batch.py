from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Browser, Page, Playwright, async_playwright

from pachong.extractors.article_extractor import ArticleExtractor
from pachong.models.task import FetchConfig, SiteConfig
from pachong.runner import load_site_config
from pachong.utils.hash import sha256_text

logger = logging.getLogger(__name__)


@dataclass
class BatchItemResult:
    index: int
    path: list[str]
    title: str
    summary: str
    url: str
    markdown_path: str
    html_path: str | None
    content_hash: str


@dataclass
class BatchRunResult:
    site_name: str
    source_url: str
    output_dir: str
    toc_path: str
    toc_markdown_path: str
    page_count: int


class ClickBatchCrawler:
    def __init__(self, config: SiteConfig):
        self.config = config
        self.extractor = ArticleExtractor()
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None

    async def __aenter__(self) -> "ClickBatchCrawler":
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.config.fetch.headless)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.browser is not None:
            await self.browser.close()
        if self.playwright is not None:
            await self.playwright.stop()

    async def crawl(self, url: str, output_dir: Path | None = None) -> BatchRunResult:
        if self.browser is None:
            raise RuntimeError("Browser has not been started")

        started_at = datetime.now(timezone.utc)
        base_output = output_dir or self._build_default_output_dir(url)
        markdown_dir = base_output / "markdown"
        html_dir = base_output / "html"
        markdown_dir.mkdir(parents=True, exist_ok=True)
        html_dir.mkdir(parents=True, exist_ok=True)

        context = await self.browser.new_context()
        page = await context.new_page()
        items: list[BatchItemResult] = []

        try:
            await page.goto(url, wait_until=self.config.fetch.wait_until, timeout=self.config.fetch.timeout_ms)
            await self._wait_for_ready(page, self.config.fetch)
            menu_paths = await self._extract_menu_paths(page)

            for index, path in enumerate(menu_paths, start=1):
                logger.info("batch crawling %s/%s: %s", index, len(menu_paths), " > ".join(path))
                await self._open_menu_path(page, path, self.config.fetch)

                html = await page.content()
                title, markdown = self.extractor.extract(html, self.config.extract)
                resolved_title = title or path[-1]
                summary = self._build_summary(markdown)
                file_stem = f"{index:03d}-{self._slugify('-'.join(path))}"

                markdown_path = markdown_dir / f"{file_stem}.md"
                markdown_path.write_text(markdown or "", encoding="utf-8")

                html_path: Path | None = None
                if self.config.output.save_html:
                    html_path = html_dir / f"{file_stem}.html"
                    html_path.write_text(html, encoding="utf-8")

                items.append(
                    BatchItemResult(
                        index=index,
                        path=path,
                        title=resolved_title,
                        summary=summary,
                        url=page.url,
                        markdown_path=str(markdown_path),
                        html_path=str(html_path) if html_path else None,
                        content_hash=sha256_text(markdown or html),
                    )
                )
        finally:
            await page.close()
            await context.close()

        toc_path = base_output / "toc.json"
        toc_markdown_path = base_output / "目录总览.md"
        toc_path.write_text(
            json.dumps(
                {
                    "site_name": self.config.site_name,
                    "source_url": url,
                    "started_at": started_at.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "page_count": len(items),
                    "items": [
                        {
                            "index": item.index,
                            "path": item.path,
                            "title": item.title,
                            "summary": item.summary,
                            "url": item.url,
                            "markdown_path": item.markdown_path,
                            "html_path": item.html_path,
                            "content_hash": item.content_hash,
                        }
                        for item in items
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        toc_markdown_path.write_text(
            self._build_toc_markdown(
                source_url=url,
                page_count=len(items),
                items=items,
            ),
            encoding="utf-8",
        )

        return BatchRunResult(
            site_name=self.config.site_name,
            source_url=url,
            output_dir=str(base_output),
            toc_path=str(toc_path),
            toc_markdown_path=str(toc_markdown_path),
            page_count=len(items),
        )

    def _build_default_output_dir(self, url: str) -> Path:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        category_id = (params.get("category_id") or [None])[0]
        category_part = f"category_{category_id}" if category_id else "default"
        return self.config.output.base_dir / "batch" / self.config.site_name / category_part

    async def _wait_for_ready(self, page: Page, fetch: FetchConfig) -> None:
        if fetch.wait_selector:
            await page.wait_for_selector(fetch.wait_selector, timeout=fetch.timeout_ms)
        if fetch.wait_for_text_selector:
            await page.wait_for_function(
                """
                ({ selector, minLength }) => {
                    const el = document.querySelector(selector);
                    if (!el) return false;
                    const text = (el.innerText || el.textContent || "").trim();
                    const hasImage = el.querySelector('img') !== null;
                    return text.length >= minLength || hasImage;
                }
                """,
                arg={
                    "selector": fetch.wait_for_text_selector,
                    "minLength": fetch.wait_for_text_min_length,
                },
                timeout=fetch.timeout_ms,
            )
        if fetch.delay_after_load_ms > 0:
            await page.wait_for_timeout(fetch.delay_after_load_ms)

    async def _extract_menu_paths(self, page: Page) -> list[list[str]]:
        paths = await page.evaluate(
            """
            () => {
                function walk(ul, prefix) {
                    const items = [];
                    const children = Array.from(ul.children).filter((el) => el.tagName === 'LI');
                    for (const li of children) {
                        const label = li.querySelector(':scope > .el-sub-menu__title span')?.textContent?.trim();
                        if (!label) continue;
                        const currentPath = [...prefix, label];
                        const childList = li.querySelector(':scope > ul');
                        const hasChild = !!childList && childList.querySelector(':scope > li');
                        if (hasChild) {
                            items.push(...walk(childList, currentPath));
                        } else {
                            items.push(currentPath);
                        }
                    }
                    return items;
                }

                const root = document.querySelector('.left-menu-wrapper ul.el-menu--vertical');
                if (!root) return [];
                return walk(root, []);
            }
            """
        )
        unique_paths: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for path in paths:
            key = tuple(path)
            if key not in seen:
                seen.add(key)
                unique_paths.append(path)
        return unique_paths

    async def _open_menu_path(self, page: Page, path: list[str], fetch: FetchConfig) -> None:
        container = page.locator(".left-menu-wrapper ul.el-menu--vertical").first

        for index, label in enumerate(path):
            target = container.locator(
                f"xpath=./li[./div[contains(@class,'el-sub-menu__title')]//span[normalize-space()={self._xpath_literal(label)}]]"
            ).first
            title_div = target.locator("xpath=./div[contains(@class,'el-sub-menu__title')]").first
            class_name = await target.get_attribute("class") or ""
            is_last = index == len(path) - 1

            if is_last:
                if "active" not in class_name:
                    old_state = await self._read_content_state(page)
                    await title_div.click()
                    await self._wait_for_content_change(page, fetch, old_state)
                else:
                    await self._wait_for_ready(page, fetch)
            else:
                if "is-opened" not in class_name:
                    await title_div.click()
                    await page.wait_for_timeout(200)
                container = target.locator("xpath=./ul[contains(@class,'el-menu')]").first

    async def _read_content_state(self, page: Page) -> dict[str, str]:
        return await page.evaluate(
            """
            () => ({
                href: window.location.href,
                title: document.querySelector('.wdbox .bt h4')?.textContent?.trim() || '',
                content: document.querySelector('#preview-only-preview')?.innerText?.trim() || '',
            })
            """
        )

    async def _wait_for_content_change(
        self,
        page: Page,
        fetch: FetchConfig,
        old_state: dict[str, str],
    ) -> None:
        await page.wait_for_function(
            """
            ({ selector, minLength, oldState }) => {
                const contentEl = document.querySelector(selector);
                if (!contentEl) return false;
                const text = (contentEl.innerText || contentEl.textContent || '').trim();
                const title = (document.querySelector('.wdbox .bt h4')?.innerText || '').trim();
                const href = window.location.href;
                const hasImage = contentEl.querySelector('img') !== null;
                if (text.length < minLength && !hasImage) return false;
                return href !== oldState.href || title !== oldState.title || text !== oldState.content;
            }
            """,
            arg={
                "selector": fetch.wait_for_text_selector or fetch.wait_selector or "#preview-only-preview",
                "minLength": fetch.wait_for_text_min_length,
                "oldState": old_state,
            },
            timeout=fetch.timeout_ms,
        )
        if fetch.delay_after_load_ms > 0:
            await page.wait_for_timeout(fetch.delay_after_load_ms)

    def _slugify(self, value: str) -> str:
        allowed = []
        for char in value:
            if char.isalnum() or char in {"-", "_"}:
                allowed.append(char)
            elif char.isspace():
                allowed.append("-")
            else:
                allowed.append("_")
        slug = "".join(allowed).strip("-_")
        return slug or "page"

    def _xpath_literal(self, value: str) -> str:
        if "'" not in value:
            return f"'{value}'"
        if '"' not in value:
            return f'"{value}"'
        parts = value.split("'")
        return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"

    def _build_toc_markdown(
        self,
        source_url: str,
        page_count: int,
        items: list[BatchItemResult],
    ) -> str:
        grouped: dict[str, list[BatchItemResult]] = {}
        for item in items:
            group = item.path[0] if item.path else "未分类"
            grouped.setdefault(group, []).append(item)

        lines = [
            "# 文档总目录",
            "",
            f"- 来源页面：`{source_url}`",
            f"- 页面总数：`{page_count}`",
            "",
            "### 文档清单",
            "",
        ]

        for group_name, group_items in grouped.items():
            lines.append(f"### {group_name}")
            lines.append("")
            for item in group_items:
                markdown_name = Path(item.markdown_path).name
                article_label = item.title
                if len(item.path) > 1:
                    article_label = " / ".join(item.path[1:])
                lines.append(
                    f"**第{item.index}页：{article_label}**："
                    f"[文章](./markdown/{markdown_name}) | [原页面]({item.url})"
                )
                lines.append(f"摘要：{item.summary}")
            lines.append("")
        return "\n".join(lines)

    def _build_summary(self, markdown: str | None) -> str:
        if not markdown:
            return "暂无摘要"

        lines: list[str] = []
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            if line.startswith("![") or line.startswith("<img"):
                continue
            cleaned = line.lstrip("-* ").strip()
            if cleaned:
                lines.append(cleaned)
            if len(lines) >= 2:
                break

        if not lines:
            return "暂无摘要"

        summary = " ".join(lines)
        summary = " ".join(summary.split())
        if len(summary) > 80:
            summary = summary[:77].rstrip() + "..."
        return summary or "暂无摘要"


async def run_click_batch(
    url: str,
    config_path: Path | None = None,
    output_dir: Path | None = None,
) -> BatchRunResult:
    config = load_site_config(config_path)
    async with ClickBatchCrawler(config) as crawler:
        return await crawler.crawl(url, output_dir=output_dir)
