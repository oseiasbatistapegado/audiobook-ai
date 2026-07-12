"""Typer CLI for audiobook generation."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from audiobook_ai import config
from audiobook_ai.pipeline import run_generate
from audiobook_ai.preflight import PreflightError
from audiobook_ai.utils.logging import setup_logging
from audiobook_ai.utils.workdir import ensure_work_dir
from audiobook_ai.weights.cache import ENV_CACHE_DIR
from audiobook_ai.weights.fish import list_fish_model_aliases, resolve_fish_model

app = typer.Typer(
    name="audiobook-ai",
    help=(
        "Generate an audiobook (M4B) from a PDF via Ollama + isolated "
        "Fish Speech / Voice Design workers."
    ),
    no_args_is_help=True,
    invoke_without_command=False,
)
console = Console(stderr=True)

ENV_HARD_FLOOR = "AUDIOBOOK_AI_HARD_FLOOR_MIB"
ENV_CHUNK_TARGET = "AUDIOBOOK_AI_BEFORE_CHUNK_TARGET_MIB"
ENV_FISH_LOAD = "AUDIOBOOK_AI_FISH_BEFORE_LOAD_TARGET_MIB"
ENV_PARLER_LOAD = "AUDIOBOOK_AI_PARLER_BEFORE_LOAD_TARGET_MIB"
ENV_TTS_MAX_CHARS = "AUDIOBOOK_AI_TTS_MAX_CHUNK_CHARS"
ENV_FISH_CHUNKS = "AUDIOBOOK_AI_FISH_CHUNKS_PER_WORKER"
ENV_FISH_MODEL = "AUDIOBOOK_AI_FISH_MODEL"


@app.callback()
def _root() -> None:
    """Audiobook AI CLI."""


@app.command("generate")
def generate(
    pdf: Annotated[
        Path,
        typer.Argument(exists=False, help="Path to the input PDF"),
    ],
    model: Annotated[
        str,
        typer.Option("--model", help="Ollama model name"),
    ] = config.DEFAULT_OLLAMA_MODEL,
    fish_model: Annotated[
        Optional[str],
        typer.Option(
            "--fish-model",
            help=(
                "Fish open-weight alias "
                f"(default {config.DEFAULT_FISH_MODEL}; "
                f"valid: {', '.join(list_fish_model_aliases())})"
            ),
            envvar=ENV_FISH_MODEL,
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Output path (.m4b default, .mp3 if requested)"),
    ] = None,
    work_dir: Annotated[
        Path,
        typer.Option(
            "--work-dir",
            help="Artifact root (default out/); resumable state under <work-dir>/<book_id>/",
        ),
    ] = config.DEFAULT_WORK_DIR,
    ollama_host: Annotated[
        Optional[str],
        typer.Option("--ollama-host", help="Ollama base URL"),
    ] = None,
    cache_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--cache-dir",
            help="Weight cache root (overrides AUDIOBOOK_AI_CACHE_DIR / ~/.cache/audiobook-ai)",
        ),
    ] = None,
    hard_floor_mib: Annotated[
        Optional[int],
        typer.Option(
            "--hard-floor-mib",
            help=f"Never start GPU work below this free VRAM (default {config.HARD_FLOOR_MIB})",
            envvar=ENV_HARD_FLOOR,
        ),
    ] = None,
    before_chunk_target_mib: Annotated[
        Optional[int],
        typer.Option(
            "--before-chunk-target-mib",
            help=(
                "Desired free VRAM before each SpeechChunk "
                f"(default {config.BEFORE_CHUNK_TARGET_MIB})"
            ),
            envvar=ENV_CHUNK_TARGET,
        ),
    ] = None,
    fish_before_load_target_mib: Annotated[
        Optional[int],
        typer.Option(
            "--fish-before-load-target-mib",
            help=(
                "Free VRAM required before spawning Fish Speech "
                f"(default {config.FISH_BEFORE_LOAD_TARGET_MIB})"
            ),
            envvar=ENV_FISH_LOAD,
        ),
    ] = None,
    parler_before_load_target_mib: Annotated[
        Optional[int],
        typer.Option(
            "--parler-before-load-target-mib",
            help=(
                "Free VRAM required before spawning Voice Design "
                f"(default {config.PARLER_BEFORE_LOAD_TARGET_MIB})"
            ),
            envvar=ENV_PARLER_LOAD,
        ),
    ] = None,
    tts_max_chunk_chars: Annotated[
        Optional[int],
        typer.Option(
            "--tts-max-chunk-chars",
            help=f"Max characters per SpeechChunk (default {config.TTS_MAX_CHUNK_CHARS})",
            envvar=ENV_TTS_MAX_CHARS,
        ),
    ] = None,
    fish_chunks_per_worker: Annotated[
        Optional[int],
        typer.Option(
            "--fish-chunks-per-worker",
            help=(
                "Optional residency ceiling (escape hatch). Default 0 = guardian-driven "
                "reclaim only (progressive/headroom). >0 forces worker EXIT after N chunks."
            ),
            envvar=ENV_FISH_CHUNKS,
        ),
    ] = None,
) -> None:
    """Extract, interpret, synthesize (workers), and merge a PDF into an audiobook."""
    if not pdf.is_file():
        console.print(f"[red]PDF not found:[/red] {pdf}")
        raise typer.Exit(code=1)

    try:
        fish_alias = resolve_fish_model(fish_model).alias
    except ValueError as exc:
        console.print(f"[red]Invalid --fish-model:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    layout = ensure_work_dir(work_dir)
    setup_logging(level=logging.INFO, log_file=layout.logs_dir / "generate.log")

    resolved_ollama = (
        ollama_host
        or os.environ.get("OLLAMA_HOST")
        or config.DEFAULT_OLLAMA_HOST
    )
    resolved_cache = cache_dir or os.environ.get(ENV_CACHE_DIR)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Starting…", total=None)

        def on_progress(stage: str, detail: str) -> None:
            progress.update(task_id, description=f"{stage}: {detail}")

        try:
            result = run_generate(
                pdf,
                model=model,
                fish_model=fish_alias,
                output=output,
                work_dir=work_dir,
                ollama_host=resolved_ollama,
                cache_dir=resolved_cache,
                progress_callback=on_progress,
                hard_floor_mib=hard_floor_mib,
                before_chunk_target_mib=before_chunk_target_mib,
                fish_load_target_mib=fish_before_load_target_mib,
                parler_load_target_mib=parler_before_load_target_mib,
                tts_max_chunk_chars=tts_max_chunk_chars,
                fish_chunks_per_worker=fish_chunks_per_worker,
            )
        except PreflightError as exc:
            console.print(f"[red]Preflight failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        except Exception as exc:
            console.print(f"[red]Generation failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    console.print(f"[green]Wrote[/green] {result}")


def main() -> None:
    """Entrypoint for the ``audiobook-ai`` console script."""
    app()


if __name__ == "__main__":
    main()
