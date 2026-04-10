from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from pachong.analyze import run_analyze
from pachong.runner import run_crawl
from pachong.sites.jjjshop_batch import run_jjjshop_batch
from pachong.utils.log import setup_logging

app = typer.Typer(help="Dynamic website crawler MVP")


@app.callback()
def main() -> None:
    """Pachong command group."""


@app.command()
def crawl(
    url: str = typer.Argument(..., help="Target URL to crawl."),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to a site config YAML file.",
    ),
) -> None:
    """Crawl a single URL and persist HTML, markdown, screenshot and JSON."""
    setup_logging()
    result = asyncio.run(run_crawl(url, config))

    typer.echo(f"status: {result.status}")
    typer.echo(f"task_id: {result.task_id}")
    typer.echo(f"title: {result.title or ''}")
    typer.echo(f"final_url: {result.final_url}")
    if result.artifacts.html_path:
        typer.echo(f"html: {result.artifacts.html_path}")
    if result.artifacts.markdown_path:
        typer.echo(f"markdown: {result.artifacts.markdown_path}")
    if result.artifacts.json_path:
        typer.echo(f"json: {result.artifacts.json_path}")
    if result.artifacts.screenshot_path:
        typer.echo(f"screenshot: {result.artifacts.screenshot_path}")
    if result.error_message:
        typer.echo(f"error: {result.error_message}")

@app.command("batch")
def batch(
    url: str = typer.Argument(..., help="A jjjshop document URL within the target category."),
    config: Optional[Path] = typer.Option(
        Path("configs/sites/jjjshop_doc.yaml"),
        "--config",
        "-c",
        help="Path to the jjjshop site config YAML file.",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Optional output directory for the batch crawl.",
    ),
) -> None:
    """Batch crawl all left-menu pages for the current jjjshop category."""
    setup_logging()
    result = asyncio.run(run_jjjshop_batch(url, config, output_dir))

    typer.echo(f"site_name: {result.site_name}")
    typer.echo(f"page_count: {result.page_count}")
    typer.echo(f"output_dir: {result.output_dir}")
    typer.echo(f"toc: {result.toc_path}")
    typer.echo(f"toc_markdown: {result.toc_markdown_path}")


@app.command()
def analyze(
    url: str = typer.Argument(..., help="Target URL to analyze before building a site config."),
    site_name: Optional[str] = typer.Option(
        None,
        "--site-name",
        help="Optional site name override for the generated config.",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Optional output directory for analysis artifacts.",
    ),
) -> None:
    """Analyze a new site page and generate a site config draft."""
    setup_logging()
    result = asyncio.run(run_analyze(url, output_dir=output_dir, site_name=site_name))

    typer.echo(f"site_name: {result.site_name}")
    typer.echo(f"url: {result.url}")
    typer.echo(f"output_dir: {result.output_dir}")
    typer.echo(f"html: {result.html_path}")
    typer.echo(f"screenshot: {result.screenshot_path}")
    typer.echo(f"report: {result.report_path}")
    typer.echo(f"config: {result.config_path}")


if __name__ == "__main__":
    app()
