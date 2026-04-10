from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
        child_links = self._extract_child_links(url, content_node or parser.root)
        page_classification = self._classify_page(
            url=url,
            parser=parser,
            content_node=content_node,
            child_links=child_links,
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
                "content_text_length": page_classification["content_text_length"],
                "page_type": page_classification["page_type"],
                "batch_candidate": page_classification["batch_candidate"],
                "batch_confidence": page_classification["batch_confidence"],
                "child_link_count": len(child_links),
                "child_links": child_links[:50],
                "reasoning": page_classification["reasoning"],
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

    def _extract_child_links(self, base_url: str, node: Node | None) -> list[dict]:
        if node is None:
            return []

        base_parsed = urlparse(base_url)
        current_segments = [segment for segment in base_parsed.path.split("/") if segment]
        current_prefix = "/".join(current_segments[:-1]) if current_segments else ""
        candidates: list[dict] = []
        seen: set[str] = set()

        for link in node.css("a[href]"):
            href = (link.attributes.get("href") or "").strip()
            if not href:
                continue
            absolute_url = urljoin(base_url, href)
            parsed = urlparse(absolute_url)
            if parsed.netloc and parsed.netloc != base_parsed.netloc:
                continue
            if parsed.fragment:
                continue

            text = self._normalize_link_title(link.text(separator=" ", strip=True))
            if not self._is_good_child_link_text(text):
                continue

            path_segments = [segment for segment in parsed.path.split("/") if segment]
            path_prefix = "/".join(path_segments[:-1]) if path_segments else ""
            same_prefix = bool(current_prefix and path_prefix == current_prefix)
            same_host = parsed.netloc == base_parsed.netloc
            score = 0
            if same_host:
                score += 0.3
            if same_prefix:
                score += 0.45
            if len(text) >= 2:
                score += 0.15
            if re.search(r"\d{4,}", parsed.path):
                score += 0.1

            key = absolute_url
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "title": text,
                    "url": absolute_url,
                    "score": round(min(score, 1.0), 2),
                    "same_path_prefix": same_prefix,
                }
            )

        candidates.sort(key=lambda item: (-item["score"], item["title"]))
        return candidates

    def _classify_page(
        self,
        url: str,
        parser: HTMLParser,
        content_node: Node | None,
        child_links: list[dict],
    ) -> dict:
        content_text = self._clean_text(content_node.text(separator=" ", strip=True)) if content_node else ""
        content_len = len(content_text)
        matched_child_links = [item for item in child_links if item["score"] >= 0.6]
        child_link_count = len(matched_child_links)
        has_outline_keyword = any(
            parser.body.text(separator=" ", strip=True).find(keyword) >= 0
            for keyword in ["目录", "大纲", "章节", "目录：", "目录:"]
        )
        same_prefix_count = sum(1 for item in matched_child_links if item["same_path_prefix"])

        reasoning: list[str] = []
        batch_score = 0.0

        if child_link_count >= 8:
            batch_score += 0.45
            reasoning.append(f"检测到 {child_link_count} 个高置信度子链接")
        elif child_link_count >= 5:
            batch_score += 0.3
            reasoning.append(f"检测到 {child_link_count} 个子链接，已达到目录页候选阈值")

        if same_prefix_count >= 5:
            batch_score += 0.25
            reasoning.append(f"{same_prefix_count} 个子链接与当前页面同路径前缀")

        if has_outline_keyword:
            batch_score += 0.15
            reasoning.append("页面出现“目录/大纲/章节”等目录型语义")

        if child_link_count >= 5 and content_len < 300:
            batch_score += 0.25
            reasoning.append(f"正文有效文本较短（约 {content_len} 字），更像目录入口页")
        elif content_len >= 800:
            reasoning.append(f"正文长度较长（约 {content_len} 字），更像详情页")

        if child_link_count == 0 and content_len >= 300:
            page_type = "detail_page"
        elif batch_score >= 0.7 and content_len < 400:
            page_type = "index_page"
        elif batch_score >= 0.45 and content_len >= 300:
            page_type = "hybrid_page"
        elif child_link_count >= 5:
            page_type = "hybrid_page"
        else:
            page_type = "detail_page"

        batch_candidate = batch_score >= 0.45 and child_link_count >= 5
        if batch_candidate and not reasoning:
            reasoning.append("页面满足批量抓取候选条件")
        if not reasoning:
            reasoning.append("未检测到明显目录页特征，默认按详情页处理")

        return {
            "content_text_length": content_len,
            "page_type": page_type,
            "batch_candidate": batch_candidate,
            "batch_confidence": round(min(batch_score, 0.99), 2),
            "reasoning": reasoning,
        }

    def _is_good_child_link_text(self, text: str) -> bool:
        if not text:
            return False
        if len(text) > 40:
            return False
        bad_keywords = [
            "首页",
            "官网",
            "登录",
            "注册",
            "复制链接",
            "评论",
            "点赞",
            "最新",
            "最早",
            "上一篇",
            "下一篇",
        ]
        return not any(keyword in text for keyword in bad_keywords)

    def _normalize_link_title(self, text: str) -> str:
        cleaned = self._clean_text(text)
        cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\b", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|")
        return cleaned

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
