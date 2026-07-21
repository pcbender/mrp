from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from mrp.video.workspace import (
    MRPVideoAdapterError,
    align_track,
    analyze_track,
    prepare_track,
    preview_track,
    render_track,
)

track_app = typer.Typer(
    no_args_is_help=True,
    help="Run the MRP-owned workflow for one release track.",
)
console = Console()
error_console = Console(stderr=True)


def _emit(value: dict[str, Any], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True))
        return
    status = value.get("status") or "passed"
    key = value.get("track_key") or value.get("preflight", {}).get("track_key")
    console.print(f"[bold green]{status.title()}:[/bold green] {key}")
    console.print_json(json.dumps(value))


def _fail(exc: MRPVideoAdapterError, json_output: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {"status": "failed", "errors": list(exc.problems)},
                indent=2,
                sort_keys=True,
            ),
            err=True,
        )
    else:
        error_console.print(f"[bold red]Track video workflow failed:[/bold red] {exc}")
    raise typer.Exit(code=1) from exc


@track_app.command("prepare")
def prepare_command(
    release: Annotated[str, typer.Argument(help="Release slug below content/releases.")],
    track: Annotated[
        str | None,
        typer.Option("--track", help="Track slug; required for an EP or album."),
    ] = None,
    repo: Annotated[
        Path,
        typer.Option("--repo", help="MRP repository root.", file_okay=False),
    ] = Path("."),
    font: Annotated[
        Path | None,
        typer.Option("--font", help="Local TrueType/OpenType lyric font."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Reset the tracked project to adapter defaults."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write the preparation report as JSON."),
    ] = False,
) -> None:
    """Create or refresh the tracked project and ignored runtime workspace."""
    try:
        prepared = prepare_track(
            repo,
            release,
            track,
            font_path=font,
            force_project=force,
        )
    except MRPVideoAdapterError as exc:
        _fail(exc, json_output)
    _emit(prepared.summary(), json_output)


@track_app.command("preflight")
def preflight_command(
    release: Annotated[str, typer.Argument(help="Release slug below content/releases.")],
    track: Annotated[str | None, typer.Option("--track")] = None,
    repo: Annotated[Path, typer.Option("--repo", file_okay=False)] = Path("."),
    font: Annotated[Path | None, typer.Option("--font")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate exact inputs and report stale generated artifacts."""
    try:
        prepared = prepare_track(
            repo,
            release,
            track,
            font_path=font,
            update_release=False,
        )
    except MRPVideoAdapterError as exc:
        _fail(exc, json_output)
    _emit(prepared.summary(), json_output)


@track_app.command("analyze")
def analyze_command(
    release: Annotated[str, typer.Argument(help="Release slug below content/releases.")],
    track: Annotated[str | None, typer.Option("--track")] = None,
    repo: Annotated[Path, typer.Option("--repo", file_okay=False)] = Path("."),
    font: Annotated[Path | None, typer.Option("--font")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Prepare and analyze one MRP track on the shared semantic timeline."""
    try:
        result = analyze_track(
            repo,
            release,
            track,
            font_path=font,
            force=force,
        )
    except MRPVideoAdapterError as exc:
        _fail(exc, json_output)
    _emit(result, json_output)


@track_app.command("align")
def align_command(
    release: Annotated[str, typer.Argument(help="Release slug below content/releases.")],
    track: Annotated[str | None, typer.Option("--track")] = None,
    repo: Annotated[Path, typer.Option("--repo", file_okay=False)] = Path("."),
    font: Annotated[Path | None, typer.Option("--font")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    retranscribe: Annotated[bool, typer.Option("--retranscribe")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Prepare and align lyrics, writing the tracked aligned artifact."""
    try:
        result = align_track(
            repo,
            release,
            track,
            font_path=font,
            force=force,
            retranscribe=retranscribe,
        )
    except MRPVideoAdapterError as exc:
        _fail(exc, json_output)
    _emit(result, json_output)


@track_app.command("preview")
def preview_command(
    release: Annotated[str, typer.Argument(help="Release slug below content/releases.")],
    track: Annotated[str | None, typer.Option("--track")] = None,
    repo: Annotated[Path, typer.Option("--repo", file_okay=False)] = Path("."),
    font: Annotated[Path | None, typer.Option("--font")] = None,
    time_seconds: Annotated[float, typer.Option("--time")] = 0,
    draft: Annotated[bool, typer.Option("--draft/--full-size")] = True,
    force: Annotated[bool, typer.Option("--force")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Render one ignored MRP track preview frame."""
    try:
        result = preview_track(
            repo,
            release,
            track,
            font_path=font,
            time_seconds=time_seconds,
            draft=draft,
            force=force,
        )
    except MRPVideoAdapterError as exc:
        _fail(exc, json_output)
    _emit(result, json_output)


@track_app.command("render")
def render_command(
    release: Annotated[str, typer.Argument(help="Release slug below content/releases.")],
    track: Annotated[str | None, typer.Option("--track")] = None,
    repo: Annotated[Path, typer.Option("--repo", file_okay=False)] = Path("."),
    font: Annotated[Path | None, typer.Option("--font")] = None,
    draft: Annotated[bool, typer.Option("--draft")] = False,
    start_seconds: Annotated[float | None, typer.Option("--from")] = None,
    end_seconds: Annotated[float | None, typer.Option("--to")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Render and verify one ignored MRP track MP4."""
    try:
        result = render_track(
            repo,
            release,
            track,
            font_path=font,
            draft=draft,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            force=force,
            dry_run=dry_run,
        )
    except MRPVideoAdapterError as exc:
        _fail(exc, json_output)
    _emit(result, json_output)
