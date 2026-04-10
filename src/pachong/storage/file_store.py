from __future__ import annotations

import json
from pathlib import Path

from pachong.models.result import CrawlResult
from pachong.models.task import OutputConfig


class FileStore:
    def __init__(self, config: OutputConfig):
        self.config = config
        self.base_dir = config.base_dir
        self.html_dir = self.base_dir / "html"
        self.markdown_dir = self.base_dir / "markdown"
        self.json_dir = self.base_dir / "json"
        self.screenshot_dir = self.base_dir / "screenshots"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.html_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.json_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def build_path(self, kind: str, task_id: str, suffix: str) -> Path:
        folder = {
            "html": self.html_dir,
            "markdown": self.markdown_dir,
            "json": self.json_dir,
            "screenshot": self.screenshot_dir,
        }[kind]
        return folder / f"{task_id}{suffix}"

    def save_html(self, path: Path, html: str) -> None:
        path.write_text(html, encoding="utf-8")

    def save_markdown(self, path: Path, markdown: str) -> None:
        path.write_text(markdown, encoding="utf-8")

    def save_result_json(self, path: Path, result: CrawlResult) -> None:
        path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
