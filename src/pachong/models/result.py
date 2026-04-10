from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CrawlArtifacts(BaseModel):
    html_path: str | None = None
    markdown_path: str | None = None
    json_path: str | None = None
    screenshot_path: str | None = None


class CrawlResult(BaseModel):
    task_id: str
    url: str
    final_url: str
    site_name: str
    status: str
    title: str | None = None
    markdown: str | None = None
    html_length: int = 0
    content_hash: str | None = None
    started_at: datetime
    finished_at: datetime
    error_type: str | None = None
    error_message: str | None = None
    artifacts: CrawlArtifacts
