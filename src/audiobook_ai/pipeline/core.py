"""End-to-end generate pipeline: Extract → Parse → Interpret → workers → Merge.

The CLI/orchestrator process does NOT load Parler or Qwen3-TTS on the GPU.
Voice Design and TTS run in isolated workers; SpeechChunks persist to
a book-scoped manifest for resume.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.audio.merge import merge_segments
from audiobook_ai.extractors.pdf import PdfExtractor
from audiobook_ai.gpu.lifecycle import LifecycleManager
from audiobook_ai.gpu.orchestrate import (
    build_guardian,
    dialogues_to_chunks,
    enrich_chunk_voices,
    run_tts_phase,
    run_voice_design_phase,
    write_or_merge_manifest,
)
from audiobook_ai.pipeline.async_loop import AsyncPipelineRunner
from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.llm.llama_cpp_backend import LlamaCppBackend
from audiobook_ai.parser.chapters import parse_chapters
from audiobook_ai.preflight import run_preflight
from audiobook_ai.state.interpret_progress import (
    mark_chapter_interpreted,
    resolve_interpret_progress,
    save_interpret_progress,
)
from audiobook_ai.state.store import load_story_state, save_story_state
from audiobook_ai.state.voices import apply_story_updates, resolve_character_id
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.factory import get_tts_backend
from audiobook_ai.tts.qwen3_tts import Qwen3TTSBackend
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.utils.workdir import WorkDirLayout, ensure_work_dir
from audiobook_ai.voice.book_id import compute_book_id
from audiobook_ai.voice.generator import VoiceGenerator, get_voice_generator
from audiobook_ai.weights.manager import ModelManager

logger = get_logger(__name__)

ProgressCallback = Callable[[str, str], None]


def run_generate(
    pdf_path: Path,
    *,
    model: str = config.DEFAULT_LLAMA_MODEL,
    fish_model: str | None = None,
    output: Path | None = None,
    work_dir: Path | str | None = None,
    llama_host: str = config.DEFAULT_LLAMA_HOST,
    llama_model: str = config.DEFAULT_LLAMA_MODEL,
    cache_dir: Path | str | None = None,
    llm: LLMBackend | None = None,
    tts: TTSBackend | None = None,
    voice_generator: VoiceGenerator | None = None,
    progress_callback: ProgressCallback | None = None,
    skip_preflight: bool = False,
    hard_floor_mib: int | None = None,
    before_chunk_target_mib: int | None = None,
    tts_load_target_mib: int | None = None,
    fish_load_target_mib: int | None = None,
    parler_load_target_mib: int | None = None,
    tts_max_chunk_chars: int | None = None,
    tts_chunks_per_worker: int | None = None,
    fish_chunks_per_worker: int | None = None,
    use_gpu_workers: bool | None = None,
    tts_multi_workers: int | None = None,
    tts_same_voice_batch_size: int | None = None,
    tts_async_overlap: int | None = None,
) -> Path:
    """Run the full MVP pipeline and return the final audiobook path."""
    del fish_model  # Fish aliases removed; Qwen3-TTS is the sole actor.

    effective_model = model if model != config.DEFAULT_LLAMA_MODEL else llama_model
    effective_host = llama_host

    load_target = (
        tts_load_target_mib
        if tts_load_target_mib is not None
        else (
            fish_load_target_mib
            if fish_load_target_mib is not None
            else config.TTS_BEFORE_LOAD_TARGET_MIB
        )
    )
    residency = (
        tts_chunks_per_worker
        if tts_chunks_per_worker is not None
        else fish_chunks_per_worker
    )
    if tts_max_chunk_chars is None:
        tts_max_chunk_chars = config.TTS_MAX_CHUNK_CHARS

    layout = ensure_work_dir(work_dir)
    output_path = _resolve_output(output, layout)

    # Injected TTS (unit tests) → in-process synthesis path, no real workers.
    workers_enabled = use_gpu_workers if use_gpu_workers is not None else tts is None

    if not skip_preflight:
        check_tts = workers_enabled or isinstance(tts, Qwen3TTSBackend)
        _notify(progress_callback, "preflight", "checking dependencies")
        run_preflight(
            llama_host=llama_host,
            model=model,
            check_tts_imports=check_tts,
            check_voice_design_runtime=workers_enabled,
        )

    started = time.perf_counter()
    logger.info(
        "pipeline start stage=extract pdf=%s work_dir=%s output=%s tts=qwen3-tts",
        pdf_path,
        layout.root,
        output_path,
    )

    extractor = PdfExtractor()
    extracted = extractor.extract(Path(pdf_path))
    _notify(progress_callback, "extract", extracted.title)

    book_id = compute_book_id(Path(pdf_path))
    book_layout = layout.book_layout(book_id)
    logger.info("pipeline book_id=%s book_root=%s", book_id, book_layout.root)

    book = parse_chapters(extracted)
    _notify(progress_callback, "parse", f"{len(book.chapters)} chapters")

    # Use injected LLM backend for tests, or create real LlamaCppBackend.
    if llm is not None:
        llm_backend = llm
    else:
        llm_backend = LlamaCppBackend(
            model=effective_model,
            host=effective_host,
            cache_dir=layout.cache_dir,
        )
    use_llama_cpp = True

    # Weights-only ensure in orchestrator when using real TTS workers.
    if workers_enabled:
        manager = ModelManager(cache_dir=cache_dir)
        tts_probe = get_tts_backend(
            config.DEFAULT_TTS_BACKEND,
            cache_dir=cache_dir,
            manager=manager,
        )
        if isinstance(tts_probe, Qwen3TTSBackend):
            _notify(progress_callback, "model-ensure", "qwen3-tts")

            def _model_progress(message: str, fraction: float | None) -> None:
                detail = message if fraction is None else f"{message} {fraction:.0%}"
                if message == "cache-hit":
                    _notify(progress_callback, "model-ensure", "cache hit")
                elif message.startswith("download"):
                    _notify(progress_callback, "model-download", detail)
                else:
                    _notify(progress_callback, "model-ensure", detail)

            tts_probe.ensure_weights(progress_callback=_model_progress)
            _notify(progress_callback, "model-ensure", "weights ready")
            tts_probe.release()

    story_path = book_layout.story_path
    if not story_path.is_file() and layout.story_path.is_file():
        story = load_story_state(layout.story_path)
        save_story_state(story, story_path)
    else:
        story = load_story_state(story_path)

    generator = voice_generator or get_voice_generator()
    guardian = build_guardian(
        hard_floor_mib=hard_floor_mib,
        before_chunk_target_mib=before_chunk_target_mib,
        tts_load_target_mib=load_target,
        parler_load_target_mib=parler_load_target_mib,
    )
    lifecycle = LifecycleManager(guardian)
    max_chars = tts_max_chunk_chars or config.TTS_MAX_CHUNK_CHARS
    sequence_cursor = 0
    if book_layout.manifest_path.is_file():
        from audiobook_ai.state.manifest import load_manifest

        existing_manifest = load_manifest(book_layout.manifest_path)
        if existing_manifest.chunks:
            sequence_cursor = max(c.sequence for c in existing_manifest.chunks) + 1

    book_chapter_ids = [chapter.id for chapter in book.chapters]
    interpret_progress = resolve_interpret_progress(
        book_layout.interpret_progress_path,
        model=model,
        book_chapter_ids=book_chapter_ids,
        manifest_path=book_layout.manifest_path,
        book_root=book_layout.root,
    )
    llm_resident = False
    llama_server_proc: subprocess.Popen[bytes] | None = None
    if use_llama_cpp:
        logger.info(
            "pipeline starting llama-server model=%s host=%s",
            effective_model,
            effective_host,
        )
        llama_server_proc = _start_llama_server(
            host=effective_host,
            model=effective_model,
            hf_token=None,  # will be inherited from env
        )
        # Wait for server to become ready
        _wait_for_llama_server(effective_host)

    # Collect new character IDs across all chapters (deferred voice-design).
    all_new_character_ids: list[str] = []

    def _unload_llm(*, chapter_id: str | None, reason: str) -> None:
        nonlocal llm_resident, llama_server_proc
        _vram_handoff(
            progress_callback,
            "unload-llm",
            "pipeline stage=vram-handoff action=unload-llm reason=%s chapter=%s",
            reason,
            chapter_id,
        )
        if isinstance(llm_backend, LlamaCppBackend):
            # For llama-cpp, the server is stopped externally
            _stop_llama_server(llama_server_proc)
            llama_server_proc = None
        else:
            llm_backend.unload()
            lifecycle.guardian.wait_until_free(
                float(load_target),
                backend="ollama",
                event="wait_llm_unload",
            )
        llm_resident = False

    # Pass A — Interpretation (+ Voice Design): build full pending manifest.
    # Story updates remain sequential across chapters; TTS is deferred.
    for chapter in book.chapters:
        chapter_started = time.perf_counter()
        if interpret_progress.contains(chapter.id):
            logger.info(
                "pipeline stage=interpret-skip chapter=%s title=%s",
                chapter.id,
                chapter.title,
            )
            _notify(progress_callback, "interpret-skip", chapter.id)
            continue

        _vram_handoff(
            progress_callback,
            "release-tts",
            "pipeline stage=vram-handoff action=release-tts chapter=%s",
            chapter.id,
        )
        if lifecycle.active_backend is not None:
            raise RuntimeError(
                f"GPU lease still held by {lifecycle.active_backend} before interpret"
            )

        logger.info(
            "pipeline stage=interpret chapter=%s title=%s backend=%s model=%s",
            chapter.id,
            chapter.title,
            "llama-cpp" if use_llama_cpp else "ollama",
            effective_model,
        )
        _notify(progress_callback, "interpret", chapter.id)

        response = llm_backend.interpret_chapter(chapter, story)
        apply_story_updates(story, response.story_updates)

        chapter_character_ids: list[str] = []
        for dialogue in response.dialogues:
            character_id = resolve_character_id(
                story,
                speaker_id=dialogue.speaker_id,
                speaker_name=dialogue.speaker_name,
            )
            if character_id not in chapter_character_ids:
                chapter_character_ids.append(character_id)
            # Collect new characters for batched voice-design after all chapters.
            if character_id not in story.voice_map and character_id not in all_new_character_ids:
                all_new_character_ids.append(character_id)

        used_remote = bool(getattr(llm_backend, "last_used_remote", False))
        if used_remote:
            llm_resident = True

        if response.dialogues:
            chunks = dialogues_to_chunks(
                story,
                response.dialogues,
                chapter_id=chapter.id,
                sequence_start=sequence_cursor,
                max_chars=max_chars,
                book_id=book_id,
                cache_root=cache_dir,
                generator=generator,
            )
            enrich_chunk_voices(
                story,
                chunks,
                book_id=book_id,
                cache_root=cache_dir,
                generator=generator,
            )
            write_or_merge_manifest(book_layout, chunks)
            if chunks:
                sequence_cursor = chunks[-1].sequence + 1

            if book_layout.manifest_path.is_file():
                from audiobook_ai.state.manifest import load_manifest, pending_chunks

                man = load_manifest(book_layout.manifest_path)
                pending = {e.id for e in pending_chunks(man, book_root=book_layout.root)}
                skipped = sum(1 for c in chunks if c.id not in pending)
                if skipped:
                    _notify(
                        progress_callback,
                        "tts-resume",
                        f"skip {skipped} completed chunks",
                    )

        save_story_state(story, story_path)
        interpret_progress = mark_chapter_interpreted(interpret_progress, chapter.id)
        save_interpret_progress(interpret_progress, book_layout.interpret_progress_path)
        elapsed = time.perf_counter() - chapter_started
        logger.info(
            "pipeline chapter interpreted chapter=%s seconds=%.2f",
            chapter.id,
            elapsed,
        )

    # Batched Voice Design — single pass for all characters discovered during
    # interpretation.  On resume, characters from already-interpreted chapters
    # are already in story.voice_map (saved per-chapter), so only genuinely new
    # characters remain to be processed.
    # Voice design ALWAYS runs in the isolated .venv-parler subprocess to avoid
    # the transformers/parler-tts incompatibility in the main .venv.
    _voice_worker = True
    if all_new_character_ids:
        if workers_enabled or llm_resident or _voice_worker:
            _unload_llm(chapter_id=None, reason="before-batch-voice-design")
        _notify(
            progress_callback,
            "voice-design",
            f"{len(all_new_character_ids)} characters (batched)",
        )
        run_voice_design_phase(
            story,
            all_new_character_ids,
            book=book_layout,
            cache_root=cache_dir,
            lifecycle=lifecycle,
            progress_callback=progress_callback,
            use_worker=_voice_worker,
            generator=generator,
            fish_load_target_mib=load_target,
        )
        save_story_state(story, story_path)

    # Pass B — TTS phase: linear or async (overlapped LLM+TTS).
    has_pending_tts = False
    if book_layout.manifest_path.is_file():
        from audiobook_ai.state.manifest import load_manifest, pending_chunks

        man = load_manifest(book_layout.manifest_path)
        has_pending_tts = bool(pending_chunks(man, book_root=book_layout.root))

    if has_pending_tts:
        if llm_resident or bool(getattr(llm_backend, "last_used_remote", False)):
            _unload_llm(chapter_id=None, reason="before-tts")
        _vram_handoff(
            progress_callback,
            "load-tts",
            "pipeline stage=vram-handoff action=spawn-tts phase=continuous",
        )

        # Determine async mode
        effective_overlap = (
            tts_async_overlap
            if tts_async_overlap is not None
            else config.TTS_ASYNC_OVERLAP
        )

        if effective_overlap is not None and effective_overlap > 0:
            # --- Async pipeline: overlapped LLM + TTS ---
            _notify(
                progress_callback,
                "async-pipeline",
                f"starting overlap={effective_overlap} workers={tts_multi_workers}",
            )
            logger.info(
                "async-pipeline enabled overlap=%d multi_workers=%s",
                effective_overlap,
                tts_multi_workers,
            )
            AsyncPipelineRunner(
                llm_backend=llm_backend,
                chapters=book.chapters,
                book_layout=book_layout,
                cache_root=cache_dir,
                lifecycle=lifecycle,
                progress_callback=progress_callback,
                max_chars=max_chars,
                book_id=book_id,
                sequence_start=sequence_cursor,
                hard_floor_mib=hard_floor_mib,
                before_chunk_target_mib=before_chunk_target_mib,
                tts_load_target_mib=load_target,
                tts_chunks_per_worker=residency,
                tts_same_voice_batch_size=tts_same_voice_batch_size,
                tts_multi_workers=tts_multi_workers,
                tts_logical_id="qwen3-tts",
                generator=generator,
                story=story,
                progress=interpret_progress,
            ).run()
        else:
            # --- Linear TTS (single-pass worker) ---
            run_tts_phase(
                book=book_layout,
                cache_root=cache_dir,
                lifecycle=lifecycle,
                progress_callback=progress_callback,
                use_worker=workers_enabled,
                tts=tts,
                hard_floor_mib=hard_floor_mib,
                before_chunk_target_mib=before_chunk_target_mib,
                tts_load_target_mib=load_target,
                tts_chunks_per_worker=residency,
                tts_same_voice_batch_size=tts_same_voice_batch_size,
                tts_multi_workers=tts_multi_workers,
                tts_async_overlap=tts_async_overlap,
                tts_logical_id="qwen3-tts",
            )

        _vram_handoff(
            progress_callback,
            "release-tts",
            "pipeline stage=vram-handoff action=release-tts after=tts-phase",
        )

    # Merge from manifest order (not readdir).
    from audiobook_ai.gpu.orchestrate import _segments_from_manifest

    if book_layout.manifest_path.is_file():
        all_segments = _segments_from_manifest(book_layout)
    else:
        all_segments = []

    logger.info("pipeline stage=merge segments=%s", len(all_segments))
    _notify(progress_callback, "merge", str(output_path))
    result = merge_segments(
        all_segments,
        output_path,
        chapters_dir=book_layout.chapters_dir,
    )

    # Ensure Voice Design model is not left resident in orchestrator.
    unload = getattr(generator, "unload", None)
    if callable(unload):
        try:
            unload()
        except Exception:  # noqa: BLE001
            logger.debug("orchestrator voice generator unload failed", exc_info=True)

    total = time.perf_counter() - started
    logger.info("pipeline complete output=%s seconds=%.2f", result, total)
    return result


def _resolve_output(output: Path | None, layout: WorkDirLayout) -> Path:
    if output is None:
        return layout.default_output_path()
    path = Path(output)
    if path.suffix.lower() not in {".m4b", ".mp3"}:
        path = path.with_suffix(".m4b")
    return path


def _notify(
    callback: ProgressCallback | None,
    stage: str,
    detail: str,
) -> None:
    if callback is not None:
        callback(stage, detail)


def _vram_handoff(
    callback: ProgressCallback | None,
    detail: str,
    log_fmt: str,
    *log_args: object,
) -> None:
    logger.info(log_fmt, *log_args)
    _notify(callback, "vram-handoff", detail)


def _start_llama_server(
    host: str,
    model: str,
    *,
    hf_token: str | None = None,
) -> subprocess.Popen[bytes]:
    """Start llama-server as a subprocess and return the process handle.

    The server is started with the following defaults (overridable via env):
    - Default port: 8080
    - Jinja chat template
    - MTP speculative decoding enabled (draft-mtp, n-max=4)
    """
    import os

    base_url = host.rstrip("/")
    port_str = base_url.split(":")[-1] if ":" in base_url else "8080"

    # Default llama-server command args (can be overridden by environment).
    default_args = [
        "llama-server",
        "--port", port_str,
        "--model", model,
        "--ngl", "999",
        "--flash-attn",
        "--spec-type", "draft-mtp",
        "--spec-draft-n-max", "4",
        "--no-mmap",
        "--ctx-size", "153600",
        "--batch-size", "1024",
        "--ubatch-size", "512",
        "-ctk", "q4_0",
        "-ctv", "q4_0",
        "--parallel", "1",
        "--kv-unified",
        "--ctx-checkpoints", "8",
        "--checkpoint-every-n-tokens", "2048",
        "--cache-ram", "-1",
        "--cache-idle-slots",
        "--metrics",
        "--jinja",
    ]

    # Allow full command override via LlamaCppServerCmd env var.
    # Example: export LlamaCppServerCmd="llama-server --port 8081 --model /path/to/model.gguf --jinja"
    cmd_override = os.environ.get("llamacpp_server_cmd", None)
    if cmd_override:
        import shlex
        args = shlex.split(cmd_override)
    else:
        # Merge user overrides from env vars
        args = list(default_args)
        env_ctx = os.environ.get("llamacpp_ctx_size", None)
        if env_ctx:
            try:
                idx = args.index("--ctx-size")
                args[idx + 1] = env_ctx
            except ValueError:
                pass
        env_ngl = os.environ.get("llamacpp_ngl", None)
        if env_ngl:
            try:
                idx = args.index("--ngl")
                args[idx + 1] = env_ngl
            except ValueError:
                pass
        env_spec = os.environ.get("llamacpp_spec_type", None)
        if env_spec:
            try:
                idx = args.index("--spec-type")
                args[idx + 1] = env_spec
                idx2 = args.index("--spec-draft-n-max")
                n_max = os.environ.get("llamacpp_spec_n_max", "4")
                args[idx2 + 1] = n_max
            except ValueError:
                pass
        env_port = os.environ.get("llamacpp_port", None)
        if env_port:
            try:
                idx = args.index("--port")
                args[idx + 1] = env_port
            except ValueError:
                pass
        env_model = os.environ.get("llamacpp_model", None)
        if env_model:
            try:
                idx = args.index("--model")
                args[idx + 1] = env_model
            except ValueError:
                pass

    # Set up environment
    env = os.environ.copy()
    if hf_token:
        env["HF_TOKEN"] = hf_token

    logger.info("starting llama-server args=%s", " ".join(args[:5]) + " ...")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    logger.info(
        "llama-server started pid=%d port=%s", proc.pid, port_str
    )
    return proc


def _wait_for_llama_server(
    host: str,
    *,
    timeout: float = 60.0,
) -> None:
    """Wait for llama-server to become ready via GET /health."""
    import httpx

    base_url = host.rstrip("/")
    deadline = time.perf_counter() + timeout
    attempt = 0
    with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        while time.perf_counter() < deadline:
            attempt += 1
            try:
                resp = client.get(f"{base_url}/health")
                if resp.status_code == 200:
                    logger.info(
                        "llama-server ready after %.1fs (attempt %d)",
                        time.perf_counter() - deadline + timeout,
                        attempt,
                    )
                    return
            except httpx.ConnectError:
                pass
            time.sleep(0.5)
    raise RuntimeError(
        f"llama-server did not become ready within {timeout}s "
        f"(tried {base_url}/health {attempt} times)"
    )


def _stop_llama_server(
    proc: subprocess.Popen[bytes] | None,
    *,
    timeout: float = 30.0,
) -> None:
    """Stop a previously started llama-server process."""
    if proc is None or proc.poll() is not None:
        return
    logger.info("stopping llama-server pid=%d", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(
            "llama-server did not terminate gracefully, killing pid=%d", proc.pid
        )
        proc.kill()
        proc.wait()
    logger.info("llama-server stopped pid=%d", proc.pid)
