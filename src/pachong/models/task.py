from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class FetchConfig(BaseModel):
    headless: bool = True
    timeout_ms: int = 30_000
    wait_until: str = "domcontentloaded"
    wait_selector: str | None = None
    wait_for_text_selector: str | None = None
    wait_for_text_min_length: int = 20
    auto_scroll: bool = False
    delay_after_load_ms: int = 0


class ExtractConfig(BaseModel):
    type: str = "article"
    title_selector: str | None = None
    content_selector: str | None = None
    remove_selectors: list[str] = []
    use_trafilatura_fallback: bool = True


class OutputConfig(BaseModel):
    base_dir: Path = Path("data")
    save_html: bool = True
    save_markdown: bool = True
    save_json: bool = True
    save_screenshot: bool = True


class SiteConfig(BaseModel):
    site_name: str = "default"
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    extract: ExtractConfig = Field(default_factory=ExtractConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


class CrawlTask(BaseModel):
    url: str
    site_name: str = "default"
