from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from pachong.extractors.article_extractor import ArticleExtractor
from pachong.fetchers.playwright_fetcher import PlaywrightFetcher
from pachong.models.result import CrawlArtifacts, CrawlResult
from pachong.models.task import CrawlTask, SiteConfig
from pachong.storage.file_store import FileStore
from pachong.utils.hash import sha256_text

logger = logging.getLogger(__name__)


def load_site_config(config_path: Path | None) -> SiteConfig:
    if config_path is None:
        return SiteConfig()

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return SiteConfig.model_validate(payload)


async def run_crawl(url: str, config_path: Path | None = None) -> CrawlResult:
    config = load_site_config(config_path)
    task = CrawlTask(url=url, site_name=config.site_name)
    task_id = uuid4().hex
    started_at = datetime.now(timezone.utc)
    store = FileStore(config.output)

    html_path = store.build_path("html", task_id, ".html") if config.output.save_html else None
    markdown_path = (
        store.build_path("markdown", task_id, ".md") if config.output.save_markdown else None
    )
    json_path = store.build_path("json", task_id, ".json") if config.output.save_json else None
    screenshot_path = (
        store.build_path("screenshot", task_id, ".png") if config.output.save_screenshot else None
    )

    try:
        async with PlaywrightFetcher(config.fetch) as fetcher:
            snapshot = await fetcher.fetch(task.url, screenshot_path=screenshot_path)

        if html_path is not None:
            store.save_html(html_path, snapshot.html)

        extractor = ArticleExtractor()
        extracted_title, markdown = extractor.extract(snapshot.html, config.extract)
        title = extracted_title or snapshot.title or None

        if markdown_path is not None and markdown:
            store.save_markdown(markdown_path, markdown)

        result = CrawlResult(
            task_id=task_id,
            url=task.url,
            final_url=snapshot.final_url,
            site_name=task.site_name,
            status="success",
            title=title,
            markdown=markdown,
            html_length=len(snapshot.html),
            content_hash=sha256_text(markdown or snapshot.html),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            artifacts=CrawlArtifacts(
                html_path=str(html_path) if html_path else None,
                markdown_path=str(markdown_path) if markdown_path and markdown else None,
                json_path=str(json_path) if json_path else None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            ),
        )
    except Exception as exc:
        logger.exception("crawl failed for %s", task.url)
        result = CrawlResult(
            task_id=task_id,
            url=task.url,
            final_url=task.url,
            site_name=task.site_name,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            error_type=type(exc).__name__,
            error_message=str(exc),
            artifacts=CrawlArtifacts(
                html_path=str(html_path) if html_path and html_path.exists() else None,
                markdown_path=str(markdown_path) if markdown_path and markdown_path.exists() else None,
                json_path=str(json_path) if json_path else None,
                screenshot_path=str(screenshot_path)
                if screenshot_path and screenshot_path.exists()
                else None,
            ),
        )

    if json_path is not None:
        store.save_result_json(json_path, result)

    return result
