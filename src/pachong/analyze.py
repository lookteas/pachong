from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml
from selectolax.parser import HTMLParser, Node

from pachong.fetchers.playwright_fetcher import PlaywrightFetcher
from pachong.models.task import FetchConfig
from pachong.utils.hash import sha256_text


@dataclass
class SelectorCandidate:
    selector: str
    score: float
    reason: str
    preview: str


@dataclass
class AnalyzeResult:
    site_name: str
    url: str
    output_dir: str
    html_path: str
    screenshot_path: str | None
    report_path: str
    config_path: str


class SiteAnalyzer:
    def analyze_html(self, url: str, html: str, page_title: str) -> dict:
        parser = HTMLParser(html)
        title_selector = self._find_title_selector(parser)
        content_candidates = self._find_content_candidates(parser)
        menu_candidates = self._find_menu_candidates(parser)
        content_selector = content_candidates[0].selector if content_candidates else None
        content_node = parser.css_first(content_selector) if content_selector else None
        remove_selectors = self._find_remove_selectors(
            parser,
            content_node=content_node,
            menu_candidates=menu_candidates,
        )

        menu_selector = menu_candidates[0].selector if menu_candidates else None
        site_name = self._derive_site_name(url)

        config_payload = {
            "site_name": site_name,
            "fetch": {
                "headless": True,
                "timeout_ms": 45000,
                "wait_until": "domcontentloaded",
                "wait_selector": content_selector,
                "wait_for_text_selector": content_selector,
                "wait_for_text_min_length": 20,
                "auto_scroll": False,
                "delay_after_load_ms": 1200,
            },
            "extract": {
                "type": "article",
                "title_selector": title_selector,
                "content_selector": content_selector,
                "remove_selectors": remove_selectors,
                "use_trafilatura_fallback": True,
            },
            "output": {
                "save_html": True,
                "save_markdown": True,
                "save_json": True,
                "save_screenshot": True,
            },
        }

        return {
            "site_name": site_name,
            "url": url,
            "page_title": page_title,
            "config": config_payload,
            "analysis": {
                "title_selector": title_selector,
                "content_candidates": [candidate.__dict__ for candidate in content_candidates[:5]],
                "menu_candidates": [candidate.__dict__ for candidate in menu_candidates[:5]],
                "remove_selectors": remove_selectors,
            },
        }

    def _derive_site_name(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace(".", "_")
        path_parts = [part for part in parsed.path.split("/") if part]
        suffix = f"_{path_parts[0]}" if path_parts else ""
        return f"{host}{suffix}"

    def _find_title_selector(self, parser: HTMLParser) -> str | None:
        for selector in ["h1", ".title h1", "main h1", "article h1"]:
            node = parser.css_first(selector)
            if node is not None and node.text(strip=True):
                return self._build_selector(node)

        meta_title = parser.css_first("meta[property='og:title']")
        if meta_title is not None:
            return None
        return None

    def _find_content_candidates(self, parser: HTMLParser) -> list[SelectorCandidate]:
        candidates: list[SelectorCandidate] = []
        for node in parser.css("main, article, section, div"):
            if not isinstance(node, Node):
                continue
            text = self._clean_text(node.text(separator=" ", strip=True))
            if len(text) < 80:
                continue
            if self._is_noise_node(node):
                continue

            p_count = len(node.css("p"))
            li_count = len(node.css("li"))
            img_count = len(node.css("img"))
            heading_count = len(node.css("h1, h2, h3, h4"))
            link_text_len = sum(len(self._clean_text(link.text(separator=" ", strip=True))) for link in node.css("a"))
            text_len = len(text)
            link_ratio = link_text_len / max(text_len, 1)

            score = (
                text_len
                + p_count * 120
                + img_count * 40
                + heading_count * 80
                - li_count * 15
                - link_ratio * 400
            )
            score += self._semantic_content_bonus(node)
            if score < 150:
                continue

            selector = self._build_selector(node)
            preview = text[:120]
            reason = (
                f"text={text_len}, p={p_count}, h={heading_count}, img={img_count}, "
                f"li={li_count}, link_ratio={link_ratio:.2f}"
            )
            candidates.append(
                SelectorCandidate(
                    selector=selector,
                    score=round(score, 2),
                    reason=reason,
                    preview=preview,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        deduped: list[SelectorCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.selector in seen:
                continue
            seen.add(candidate.selector)
            deduped.append(candidate)
        return deduped

    def _find_menu_candidates(self, parser: HTMLParser) -> list[SelectorCandidate]:
        candidates: list[SelectorCandidate] = []
        for node in parser.css("nav, aside, div, ul"):
            if not isinstance(node, Node):
                continue
            items = node.css("li, a")
            if len(items) < 5:
                continue

            item_texts = []
            for item in items[:80]:
                text = self._clean_text(item.text(separator=" ", strip=True))
                if 0 < len(text) <= 40:
                    item_texts.append(text)

            if len(item_texts) < 5:
                continue

            unique_count = len(set(item_texts))
            avg_len = sum(len(text) for text in item_texts) / max(len(item_texts), 1)
            score = unique_count * 15 + len(item_texts) * 4 - avg_len
            selector = self._build_selector(node)
            preview = " | ".join(item_texts[:6])
            reason = f"items={len(item_texts)}, unique={unique_count}, avg_len={avg_len:.1f}"
            candidates.append(
                SelectorCandidate(
                    selector=selector,
                    score=round(score, 2),
                    reason=reason,
                    preview=preview,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        deduped: list[SelectorCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.selector in seen:
                continue
            seen.add(candidate.selector)
            deduped.append(candidate)
        return deduped

    def _find_remove_selectors(
        self,
        parser: HTMLParser,
        content_node: Node | None,
        menu_candidates: list[SelectorCandidate],
    ) -> list[str]:
        selectors: list[str] = []

        common_patterns = [
            "#leftCon",
            ".left-menu-wrapper",
            ".right_mulu",
            ".sidebar",
            ".comment-box",
            ".comments",
            ".isSupport",
            ".box-handle",
            ".breadcrumb",
            "footer",
            "header",
            "aside",
        ]
        for selector in common_patterns:
            node = parser.css_first(selector)
            if node is None:
                continue
            if content_node is not None and self._contains_node(node, content_node):
                continue
            selectors.append(selector)

        for candidate in menu_candidates[:2]:
            node = parser.css_first(candidate.selector)
            if node is None:
                continue
            if content_node is not None and self._contains_node(node, content_node):
                continue
            selectors.append(candidate.selector)

        deduped: list[str] = []
        seen: set[str] = set()
        for selector in selectors:
            if selector in seen:
                continue
            seen.add(selector)
            deduped.append(selector)
        return deduped[:8]

    def _is_noise_node(self, node: Node) -> bool:
        attrs = " ".join(
            value for value in [node.tag, node.attributes.get("id", ""), node.attributes.get("class", "")] if value
        ).lower()
        noise_keywords = [
            "comment",
            "footer",
            "header",
            "sidebar",
            "breadcrumb",
            "copyright",
            "advert",
            "recommend",
            "catalog",
            "menu",
            "nav",
            "mulu",
        ]
        return any(keyword in attrs for keyword in noise_keywords)

    def _build_selector(self, node: Node) -> str:
        node_id = node.attributes.get("id")
        if node_id:
            return f"#{node_id}"

        classes = [class_name for class_name in (node.attributes.get("class") or "").split() if class_name]
        if classes:
            useful_classes = [class_name for class_name in classes if not re.match(r"^(is-|el-)", class_name)]
            if useful_classes:
                return f"{node.tag}." + ".".join(useful_classes[:2])
            return f"{node.tag}." + ".".join(classes[:2])

        parent = node.parent
        if parent is not None and isinstance(parent, Node):
            siblings = [child for child in parent.iter() if isinstance(child, Node) and child.tag == node.tag]
            if len(siblings) > 1:
                index = siblings.index(node) + 1
                return f"{node.tag}:nth-of-type({index})"
        return node.tag

    def _clean_text(self, value: str) -> str:
        return " ".join(value.split())

    def _semantic_content_bonus(self, node: Node) -> float:
        attrs = " ".join(
            value for value in [node.tag, node.attributes.get("id", ""), node.attributes.get("class", "")] if value
        ).lower()
        bonus = 0.0
        for keyword in ["content", "article", "markdown", "doc", "post", "detail", "main", "body"]:
            if keyword in attrs:
                bonus += 60
        for keyword in ["menu", "nav", "left", "right", "sidebar", "comment", "footer", "header"]:
            if keyword in attrs:
                bonus -= 90
        return bonus

    def _contains_node(self, outer: Node, inner: Node) -> bool:
        current: Node | None = inner
        while current is not None:
            if current == outer:
                return True
            parent = current.parent
            current = parent if isinstance(parent, Node) else None
        return False


async def run_analyze(
    url: str,
    output_dir: Path | None = None,
    site_name: str | None = None,
) -> AnalyzeResult:
    fetch_config = FetchConfig(headless=True, timeout_ms=45000, wait_until="domcontentloaded", delay_after_load_ms=1200)
    analyzer = SiteAnalyzer()

    parsed = urlparse(url)
    derived_site_name = site_name or analyzer._derive_site_name(url)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_output = output_dir or Path("data") / "analyze" / derived_site_name / timestamp
    base_output.mkdir(parents=True, exist_ok=True)

    html_path = base_output / "page.html"
    screenshot_path = base_output / "page.png"
    report_path = base_output / "report.json"
    config_path = base_output / "site_config.yaml"

    async with PlaywrightFetcher(fetch_config) as fetcher:
        snapshot = await fetcher.fetch(url, screenshot_path=screenshot_path)

    html_path.write_text(snapshot.html, encoding="utf-8")

    analysis = analyzer.analyze_html(snapshot.final_url, snapshot.html, snapshot.title)
    if site_name:
        analysis["site_name"] = site_name
        analysis["config"]["site_name"] = site_name

    analysis["meta"] = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "final_url": snapshot.final_url,
        "html_length": len(snapshot.html),
        "content_hash": sha256_text(snapshot.html),
        "host": parsed.netloc,
    }

    report_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    config_path.write_text(
        yaml.safe_dump(analysis["config"], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    return AnalyzeResult(
        site_name=analysis["site_name"],
        url=snapshot.final_url,
        output_dir=str(base_output),
        html_path=str(html_path),
        screenshot_path=str(screenshot_path),
        report_path=str(report_path),
        config_path=str(config_path),
    )
