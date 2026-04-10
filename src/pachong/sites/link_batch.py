from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from pachong.analyze import SiteAnalyzer
from pachong.extractors.article_extractor import ArticleExtractor
from pachong.fetchers.playwright_fetcher import PlaywrightFetcher
from pachong.models.task import SiteConfig
from pachong.runner import load_site_config
from pachong.utils.hash import sha256_text

logger = logging.getLogger(__name__)


@dataclass
class WikiBatchItemResult:
    index: int
    path: list[str]
    title: str
    summary: str
    url: str
    markdown_path: str
    html_path: str | None
    content_hash: str


@dataclass
class WikiBatchRunResult:
    site_name: str
    source_url: str
    output_dir: str
    toc_path: str
    toc_markdown_path: str
    page_count: int
    page_type: str
    batch_confidence: float


class LinkBatchCrawler:
    def __init__(self, config: SiteConfig):
        self.config = config
        self.extractor = ArticleExtractor()
        self.analyzer = SiteAnalyzer()

    async def crawl(self, url: str, output_dir: Path | None = None) -> WikiBatchRunResult:
        started_at = datetime.now(timezone.utc)
        async with PlaywrightFetcher(self.config.fetch) as fetcher:
            source_snapshot = await fetcher.fetch(url)
            analysis = self.analyzer.analyze_html(
                url=source_snapshot.final_url,
                html=source_snapshot.html,
                page_title=source_snapshot.title,
            )

            page_type = analysis["analysis"]["page_type"]
            batch_candidate = analysis["analysis"]["batch_candidate"]
            batch_confidence = analysis["analysis"]["batch_confidence"]
            child_links = analysis["analysis"]["child_links"]

            if not batch_candidate:
                raise RuntimeError(
                    f"Current page is classified as {page_type} and is not recommended for batch crawling."
                )

            base_output = output_dir or self._build_default_output_dir(source_snapshot.final_url)
            markdown_dir = base_output / "markdown"
            html_dir = base_output / "html"
            markdown_dir.mkdir(parents=True, exist_ok=True)
            html_dir.mkdir(parents=True, exist_ok=True)

            crawl_targets: list[dict[str, str]] = []
            if page_type == "hybrid_page":
                crawl_targets.append({"title": analysis["page_title"] or "当前页面", "url": source_snapshot.final_url})
            crawl_targets.extend({"title": item["title"], "url": item["url"]} for item in child_links)

            items: list[WikiBatchItemResult] = []
            seen: set[str] = set()
            for target in crawl_targets:
                if target["url"] in seen:
                    continue
                seen.add(target["url"])

                index = len(items) + 1
                logger.info("link batch crawling %s/%s: %s", index, len(crawl_targets), target["title"])
                snapshot = source_snapshot if target["url"] == source_snapshot.final_url else await fetcher.fetch(target["url"])

                title, markdown = self.extractor.extract(snapshot.html, self.config.extract)
                resolved_title = title or target["title"] or f"page-{index}"
                if target["url"] == source_snapshot.final_url and page_type in {"index_page", "hybrid_page"}:
                    summary = f"目录入口页，包含 {len(child_links)} 个候选子页面。"
                else:
                    summary = self._build_summary(markdown)
                file_stem = f"{index:03d}-{self._slugify(resolved_title)}"

                markdown_path = markdown_dir / f"{file_stem}.md"
                markdown_path.write_text(markdown or "", encoding="utf-8")

                html_path: Path | None = None
                if self.config.output.save_html:
                    html_path = html_dir / f"{file_stem}.html"
                    html_path.write_text(snapshot.html, encoding="utf-8")

                items.append(
                    WikiBatchItemResult(
                        index=index,
                        path=[resolved_title],
                        title=resolved_title,
                        summary=summary,
                        url=snapshot.final_url,
                        markdown_path=str(markdown_path),
                        html_path=str(html_path) if html_path else None,
                        content_hash=sha256_text(markdown or snapshot.html),
                    )
                )

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
                    "page_type": page_type,
                    "batch_confidence": batch_confidence,
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
            self._build_toc_markdown(source_url=url, page_count=len(items), items=items),
            encoding="utf-8",
        )

        return WikiBatchRunResult(
            site_name=self.config.site_name,
            source_url=url,
            output_dir=str(base_output),
            toc_path=str(toc_path),
            toc_markdown_path=str(toc_markdown_path),
            page_count=len(items),
            page_type=page_type,
            batch_confidence=batch_confidence,
        )

    def _build_default_output_dir(self, url: str) -> Path:
        parsed = urlparse(url)
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        entry_part = f"entry_{path_segments[-1]}" if path_segments else "entry_default"
        return self.config.output.base_dir / "batch" / self.config.site_name / entry_part

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
            if line.startswith("```"):
                continue
            if line.startswith("![") or line.startswith("<img"):
                continue
            cleaned = line.lstrip("-* ").strip()
            if cleaned.startswith("[") and "](" in cleaned:
                continue
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

    def _build_toc_markdown(
        self,
        source_url: str,
        page_count: int,
        items: list[WikiBatchItemResult],
    ) -> str:
        lines = [
            "# 文档总目录",
            "",
            f"- 来源页面：`{source_url}`",
            f"- 页面总数：`{page_count}`",
            "",
            "### 文档清单",
            "",
        ]
        for item in items:
            markdown_name = Path(item.markdown_path).name
            lines.append(
                f"**第{item.index}页：{item.title}**：[文章](./markdown/{markdown_name}) | [原页面]({item.url})"
            )
            lines.append(f"摘要：{item.summary}")
            lines.append("")
        return "\n".join(lines)


async def run_link_batch(
    url: str,
    config_path: Path | None = None,
    output_dir: Path | None = None,
) -> WikiBatchRunResult:
    config = load_site_config(config_path)
    crawler = LinkBatchCrawler(config)
    return await crawler.crawl(url, output_dir=output_dir)
