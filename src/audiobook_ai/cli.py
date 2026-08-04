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

app = typer.Typer(
    name="audiobook-ai",
    help=(
        "Generate an audiobook (M4B) from a PDF via llama-server + isolated "
        "Qwen3-TTS / Voice Design workers."
    ),
    no_args_is_help=True,
    invoke_without_command=False,
)
console = Console(stderr=True)

ENV_HARD_FLOOR = "AUDIOBOOK_AI_HARD_FLOOR_MIB"
ENV_CHUNK_TARGET = "AUDIOBOOK_AI_BEFORE_CHUNK_TARGET_MIB"
ENV_TTS_LOAD = "AUDIOBOOK_AI_TTS_BEFORE_LOAD_TARGET_MIB"
ENV_PARLER_LOAD = "AUDIOBOOK_AI_PARLER_BEFORE_LOAD_TARGET_MIB"
ENV_TTS_MAX_CHARS = "AUDIOBOOK_AI_TTS_MAX_CHUNK_CHARS"
ENV_TTS_CHUNKS = "AUDIOBOOK_AI_TTS_CHUNKS_PER_WORKER"
ENV_TTS_MULTI_WORKERS = "AUDIOBOOK_AI_TTS_MULTI_WORKERS"
ENV_TTS_ASYNC_OVERLAP = "AUDIOBOOK_AI_TTS_ASYNC_OVERLAP"


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
        typer.Option("--model", "--llama-model", help="LLM model name (gguf file path or name)"),
    ] = config.DEFAULT_LLAMA_MODEL,
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
    llama_host: Annotated[
        Optional[str],
        typer.Option("--llama-host", help="LLM server base URL"),
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
    tts_before_load_target_mib: Annotated[
        Optional[int],
        typer.Option(
            "--tts-before-load-target-mib",
            help=(
                "Free VRAM required before spawning TTS "
                f"(default {config.TTS_BEFORE_LOAD_TARGET_MIB}). "
                "Changing TTS_MAX_CHUNK_CHARS alters chunking_fingerprint "
                "and invalidates TTS-phase resume."
            ),
            envvar=ENV_TTS_LOAD,
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
            help=(
                f"Max characters per SpeechChunk (default {config.TTS_MAX_CHUNK_CHARS}). "
                "Changing this alters chunking_fingerprint and invalidates TTS resume."
            ),
            envvar=ENV_TTS_MAX_CHARS,
        ),
    ] = None,
    tts_chunks_per_worker: Annotated[
        Optional[int],
        typer.Option(
            "--tts-chunks-per-worker",
            help=(
                "Optional residency ceiling (escape hatch). Default 0 = guardian-driven "
                "reclaim only (progressive/headroom). >0 forces worker EXIT after N chunks."
            ),
            envvar=ENV_TTS_CHUNKS,
        ),
    ] = None,
    tts_multi_workers: Annotated[
        Optional[int],
        typer.Option(
            "--tts-multi-workers",
            help=(
                "Number of parallel TTS worker processes (1-4). Default from config "
                f"(usually {config.TTS_MULTI_WORKER_COUNT}). Use 1 for linear pipeline."
            ),
            envvar=ENV_TTS_MULTI_WORKERS,
        ),
    ] = None,
    tts_async_overlap: Annotated[
        Optional[int],
        typer.Option(
            "--tts-async-overlap",
            help=(
                "Chapters of LLM-ahead-of-TTS overlap (0 = linear, 1 = default). "
                f"LLM interprets cap N+1 while TTS synthesizes cap N. Max {config.TTS_ASYNC_OVERLAP_MAX}."
            ),
            envvar=ENV_TTS_ASYNC_OVERLAP,
        ),
    ] = None,
) -> None:
    """Extract, interpret, synthesize (workers), and merge a PDF into an audiobook."""
    if not pdf.is_file():
        console.print(f"[red]PDF not found:[/red] {pdf}")
        raise typer.Exit(code=1)

    layout = ensure_work_dir(work_dir)
    setup_logging(level=logging.INFO, log_file=layout.logs_dir / "generate.log")

    resolved_llama_host = (
        llama_host
        or os.environ.get("LLAMA_HOST")
        or config.DEFAULT_LLAMA_HOST
    )
    resolved_model = (
        model
        if model != config.DEFAULT_LLAMA_MODEL
        else (
            os.environ.get("LLAMA_MODEL")
            or os.environ.get("OLLAMA_MODEL")
            or config.DEFAULT_LLAMA_MODEL
        )
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
                model=resolved_model,
                output=output,
                work_dir=work_dir,
                llama_host=resolved_llama_host,
                llama_model=resolved_model,
                cache_dir=resolved_cache,
                progress_callback=on_progress,
                hard_floor_mib=hard_floor_mib,
                before_chunk_target_mib=before_chunk_target_mib,
                tts_load_target_mib=tts_before_load_target_mib,
                parler_load_target_mib=parler_before_load_target_mib,
                tts_max_chunk_chars=tts_max_chunk_chars,
                tts_chunks_per_worker=tts_chunks_per_worker,
                tts_multi_workers=tts_multi_workers,
                tts_same_voice_batch_size=None,  # use config default
                tts_async_overlap=tts_async_overlap,
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
