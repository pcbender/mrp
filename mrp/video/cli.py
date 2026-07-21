import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from mrp.video.alignment import SpirophonicAlignmentError, align_project
from mrp.video.analysis import SpirophonicAnalysisError, analyze_project
from mrp.video.cards import SpirophonicCardError
from mrp.video.encoder import SpirophonicCancelledError, SpirophonicEncodingError
from mrp.video.pipeline import (
    SpirophonicPipelineError,
    plan_project_video,
    render_project_video,
)
from mrp.video.presets import preset_catalog
from mrp.video.project import SpirophonicValidationError, validate_project
from mrp.video.render_manifest import SpirophonicManifestError
from mrp.video.renderer import (
    SpirophonicRendererError,
    load_render_context,
    plan_frame_range,
    render_frame_file,
    render_frame_sequence,
)
from mrp.video.track_cli import track_app
from mrp.video.verification import (
    SpirophonicVerificationError,
    verify_with_render_manifest,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Render deterministic music videos from audio, lyrics, and spirographs.",
)
console = Console()
error_console = Console(stderr=True)
app.add_typer(track_app, name="track")


@app.callback()
def main() -> None:
    """MRP headless music-video renderer command-line entry point."""


@app.command()
def presets(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write the preset catalog as JSON."),
    ] = False,
) -> None:
    """List measured mapping and palette presets."""
    catalog = preset_catalog()
    if json_output:
        console.print_json(json.dumps(catalog))
        return
    console.print("[bold]Mapping presets[/bold]")
    for preset in catalog["mapping"]:
        console.print(f"  {preset['name']}: {preset['description']}")
    console.print("[bold]Palette presets[/bold]")
    for preset in catalog["palette"]:
        console.print(f"  {preset['name']}: {preset['description']}")


@app.command()
def validate(
    manifest: Annotated[
        Path,
        typer.Argument(
            help="Path to the project YAML manifest.",
            dir_okay=False,
            resolve_path=True,
        ),
    ],
) -> None:
    """Validate a project manifest and every required local input."""
    try:
        report = validate_project(manifest)
    except SpirophonicValidationError as exc:
        error_console.print("[bold red]Project validation failed[/bold red]")
        for problem in exc.problems:
            error_console.print(f"  - {problem}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold green]Valid project:[/bold green] {report.project.title}")
    console.print(f"Manifest: {report.manifest_path}")
    console.print(f"Master duration: {report.master_duration:.3f} seconds")
    console.print(f"Declared stems: {len(report.stem_durations)}")


@app.command()
def analyze(
    manifest: Annotated[
        Path,
        typer.Argument(
            help="Path to the project YAML manifest.",
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Recompute analysis even when a cache exists."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write the inspection summary as JSON."),
    ] = False,
) -> None:
    """Analyze the master and stems on one shared, cached timeline."""
    progress = None
    if not json_output:
        def show_progress(message: str) -> None:
            error_console.print(f"[dim]{message}[/dim]")

        progress = show_progress
    try:
        run = analyze_project(manifest, force=force, progress=progress)
    except (SpirophonicValidationError, SpirophonicAnalysisError) as exc:
        error_console.print(f"[bold red]Audio analysis failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    summary = run.summary()
    if json_output:
        console.print_json(json.dumps(summary))
        return

    cache_state = "hit" if run.cache_hit else "written"
    console.print(
        f"[bold green]Analysis cache {cache_state}:[/bold green] "
        f"{run.cache_path}"
    )
    console.print(
        f"Timeline: {run.bundle.duration:.3f}s at "
        f"{run.bundle.sample_rate} Hz / hop {run.bundle.hop_length}"
    )
    for name, timeline in run.bundle.tracks.items():
        console.print(
            f"  {name}: {timeline.frame_count} frames, "
            f"{timeline.tempo_bpm:.2f} BPM, {len(timeline.beat_times)} beats"
        )
    for warning in run.warnings:
        error_console.print(f"[yellow]Warning:[/yellow] {warning}")


@app.command()
def align(
    manifest: Annotated[
        Path,
        typer.Argument(
            help="Path to the project YAML manifest.",
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing editable aligned-lyrics artifact.",
        ),
    ] = False,
    retranscribe: Annotated[
        bool,
        typer.Option(
            "--retranscribe",
            help="Ignore a cached transcription and request fresh timestamps.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write the alignment summary as JSON."),
    ] = False,
) -> None:
    """Align canonical lyric lines to timestamped isolated vocals."""
    progress = None
    if not json_output:

        def show_progress(message: str) -> None:
            error_console.print(f"[dim]{message}[/dim]")

        progress = show_progress
    try:
        run = align_project(
            manifest,
            force=force,
            retranscribe=retranscribe,
            progress=progress,
        )
    except (
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicAlignmentError,
    ) as exc:
        error_console.print(f"[bold red]Lyric alignment failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    summary = run.summary()
    if json_output:
        console.print_json(json.dumps(summary))
        return

    cache_state = "hit" if run.transcription.cache_hit else "written"
    console.print(f"[bold green]Aligned lyrics written:[/bold green] {run.output_path}")
    console.print(
        f"Transcription cache {cache_state}: {run.transcription.cache_path}"
    )
    counts = summary["status_counts"]
    console.print(
        "Lines: "
        f"{counts['matched']} matched, "
        f"{counts['uncertain']} uncertain, "
        f"{counts['unmatched']} unmatched"
    )
    for warning in run.warnings:
        error_console.print(f"[yellow]Review:[/yellow] {warning}")


@app.command()
def frame(
    manifest: Annotated[
        Path,
        typer.Argument(
            help="Path to the project YAML manifest.",
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    time_seconds: Annotated[
        float,
        typer.Option("--time", help="Song time in seconds to inspect."),
    ] = 0,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination PNG path."),
    ] = None,
    draft: Annotated[
        bool,
        typer.Option("--draft", help="Use the draft resolution and frame rate."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing preview PNG."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write the frame summary as JSON."),
    ] = False,
) -> None:
    """Render one deterministic visual frame for inspection."""
    progress = None
    if not json_output:

        def show_progress(message: str) -> None:
            error_console.print(f"[dim]{message}[/dim]")

        progress = show_progress
    destination = output or manifest.parent / "build" / "preview.png"
    try:
        context = load_render_context(manifest, progress=progress)
        result = render_frame_file(
            context,
            destination,
            time_seconds=time_seconds,
            draft=draft,
            force=force,
        )
    except (
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicRendererError,
    ) as exc:
        error_console.print(f"[bold red]Frame rendering failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        console.print_json(json.dumps(result.summary()))
        return
    console.print(
        f"[bold green]Preview frame written:[/bold green] {result.output_path}"
    )
    console.print(
        f"Frame {result.frame_index} at {result.time_seconds:.3f}s, "
        f"{result.width}x{result.height}"
    )


@app.command()
def frames(
    manifest: Annotated[
        Path,
        typer.Argument(
            help="Path to the project YAML manifest.",
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    start_seconds: Annotated[
        float,
        typer.Option("--from", help="First requested song time in seconds."),
    ] = 0,
    end_seconds: Annotated[
        float | None,
        typer.Option("--to", help="Exclusive ending song time in seconds."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination frame directory."),
    ] = None,
    draft: Annotated[
        bool,
        typer.Option("--draft", help="Render at up to 960x540 and 15 fps."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing Spirophonic sequence."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write the sequence summary as JSON."),
    ] = False,
) -> None:
    """Render a bounded PNG sequence for Phase 4 visual inspection."""
    progress = None
    if not json_output:

        def show_progress(message: str) -> None:
            error_console.print(f"[dim]{message}[/dim]")

        progress = show_progress
    destination = output or manifest.parent / "build" / "frames"
    try:
        context = load_render_context(manifest, progress=progress)
        plan = plan_frame_range(
            context.project,
            context.analysis.duration,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            draft=draft,
        )
        result = render_frame_sequence(
            context,
            destination,
            plan,
            force=force,
            progress=progress,
        )
    except (
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicRendererError,
    ) as exc:
        error_console.print(f"[bold red]Frame rendering failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        console.print_json(json.dumps(result.summary()))
        return
    console.print(
        f"[bold green]Frame sequence written:[/bold green] {result.output_path}"
    )
    console.print(
        f"{result.plan.frame_count} frames from {result.plan.start_time:.3f}s "
        f"to {result.plan.end_time:.3f}s at {result.plan.fps:g} fps"
    )


@app.command()
def render(
    manifest: Annotated[
        Path,
        typer.Argument(
            help="Path to the project YAML manifest.",
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination MP4 path."),
    ] = None,
    draft: Annotated[
        bool,
        typer.Option("--draft", help="Render at up to 960x540 and 15 fps."),
    ] = False,
    start_seconds: Annotated[
        float | None,
        typer.Option(
            "--from",
            help="Start at this song time and omit cards.",
        ),
    ] = None,
    end_seconds: Annotated[
        float | None,
        typer.Option(
            "--to",
            help="End at this song time and omit cards.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing MP4 and manifest."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate and print the render plan only."),
    ] = False,
    profile_output: Annotated[
        bool,
        typer.Option("--profile", help="Print detailed render performance."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write the verified render summary as JSON."),
    ] = False,
) -> None:
    """Render and verify a finished H.264/AAC music-video MP4."""
    progress = None
    if not json_output:

        def show_progress(message: str) -> None:
            error_console.print(f"[dim]{message}[/dim]")

        progress = show_progress
    destination = output or manifest.parent / "build" / "music-video.mp4"
    try:
        if dry_run:
            plan = plan_project_video(
                manifest,
                draft=draft,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                progress=progress,
            )
            summary = {"output_path": str(destination), **plan.summary()}
            if json_output:
                console.print_json(json.dumps(summary))
            else:
                console.print("[bold green]Valid render plan[/bold green]")
                console.print(
                    f"{plan.timeline.total_frames} frames, "
                    f"{plan.timeline.width}x{plan.timeline.height} at "
                    f"{plan.timeline.fps:g} fps, "
                    f"{plan.timeline.output_duration:.3f}s"
                )
                console.print(
                    f"Raw RGB streamed: {plan.diagnostics.raw_stream_gib:.2f} GiB"
                )
                for warning in plan.diagnostics.warnings:
                    error_console.print(f"[yellow]Warning:[/yellow] {warning}")
            return
        run = render_project_video(
            manifest,
            destination,
            draft=draft,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            force=force,
            progress=progress,
        )
    except (SpirophonicCancelledError, KeyboardInterrupt) as exc:
        error_console.print(
            "[bold yellow]Rendering cancelled; no partial output "
            "published.[/bold yellow]"
        )
        raise typer.Exit(code=130) from exc
    except (
        SpirophonicValidationError,
        SpirophonicAnalysisError,
        SpirophonicRendererError,
        SpirophonicCardError,
        SpirophonicEncodingError,
        SpirophonicVerificationError,
        SpirophonicManifestError,
        SpirophonicPipelineError,
    ) as exc:
        error_console.print(f"[bold red]Video rendering failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    summary = run.summary()
    if json_output:
        console.print_json(json.dumps(summary))
        return
    console.print(f"[bold green]Verified video written:[/bold green] {run.output_path}")
    console.print(f"Render manifest: {run.manifest_path}")
    console.print(
        f"{run.timeline.width}x{run.timeline.height} at {run.timeline.fps:g} fps, "
        f"{run.verification.metadata.duration:.3f}s, "
        f"{run.timeline.total_frames} frames"
    )
    for warning in run.warnings:
        error_console.print(f"[yellow]Warning:[/yellow] {warning}")
    if profile_output:
        profile = run.profile
        console.print(
            "Performance: "
            f"prepare {profile.preparation_seconds:.3f}s, "
            f"encode {profile.encoding_seconds:.3f}s, "
            f"verify {profile.verification_seconds:.3f}s"
        )
        console.print(
            f"Throughput: {profile.frames_per_second:.1f} fps, "
            f"{profile.realtime_factor:.2f}x realtime"
        )


@app.command()
def verify(
    video: Annotated[
        Path,
        typer.Argument(
            help="Path to a rendered Spirophonic MP4.",
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    render_manifest: Annotated[
        Path | None,
        typer.Option(
            "--render-manifest",
            help="Expectation manifest; defaults beside the MP4.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Write verification details as JSON."),
    ] = False,
) -> None:
    """Re-verify a rendered MP4 against its render manifest."""
    try:
        report = verify_with_render_manifest(video, render_manifest)
    except SpirophonicVerificationError as exc:
        error_console.print(f"[bold red]Video verification failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        console.print_json(json.dumps(report.summary()))
        return
    console.print(f"[bold green]Verified video:[/bold green] {report.path}")
    console.print(
        f"{report.metadata.width}x{report.metadata.height} at "
        f"{report.metadata.fps:g} fps, {report.metadata.duration:.3f}s"
    )
    console.print(
        f"{report.metadata.video_codec}/{report.metadata.pixel_format} video, "
        f"{report.metadata.audio_codec} {report.metadata.audio_sample_rate} Hz "
        f"{report.metadata.audio_channels}-channel audio"
    )


if __name__ == "__main__":
    app()
