from __future__ import annotations

import trafilatura
from markdownify import markdownify as html_to_markdown
from selectolax.parser import HTMLParser

from pachong.models.task import ExtractConfig


class ArticleExtractor:
    def extract(self, html: str, config: ExtractConfig) -> tuple[str | None, str | None]:
        parser = HTMLParser(html)
        self._remove_noise(parser, config)
        title = self._extract_title(parser, html, config)
        markdown = self._extract_markdown(parser, parser.html, config)
        return title, markdown

    def _remove_noise(self, parser: HTMLParser, config: ExtractConfig) -> None:
        for selector in config.remove_selectors:
            for node in parser.css(selector):
                node.decompose()

    def _extract_title(
        self,
        parser: HTMLParser,
        html: str,
        config: ExtractConfig,
    ) -> str | None:
        if config.title_selector:
            node = parser.css_first(config.title_selector)
            if node is not None:
                text = node.text(strip=True)
                if text:
                    return text

        extracted = trafilatura.extract(
            html,
            output_format="txt",
            only_with_metadata=True,
            include_comments=False,
            include_tables=False,
        )
        if extracted:
            return extracted.splitlines()[0].strip() or None
        return None

    def _extract_markdown(
        self,
        parser: HTMLParser,
        html: str,
        config: ExtractConfig,
    ) -> str | None:
        if config.content_selector:
            node = parser.css_first(config.content_selector)
            if node is not None:
                selected_html = node.html
                if selected_html:
                    markdown = self._convert_selected_html(selected_html)
                    if markdown:
                        return markdown.strip()

        markdown = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            favor_precision=True,
        )
        if markdown:
            return markdown.strip()

        if config.use_trafilatura_fallback:
            plain_text = trafilatura.extract(html, output_format="txt")
            if plain_text:
                return plain_text.strip()
        return None

    def _convert_selected_html(self, selected_html: str) -> str | None:
        markdown = html_to_markdown(
            selected_html,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style"],
        ).strip()
        if markdown:
            return markdown
        return None
