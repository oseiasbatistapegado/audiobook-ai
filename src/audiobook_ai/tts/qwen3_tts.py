"""Qwen3-TTS in-process Voice Clone backend (no HTTP / no cloud)."""

from __future__ import annotations

import gc
import io
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from audiobook_ai import config
from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.voices import resolve_voice_dir
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.weights.manager import ModelHandle, ModelManager
from audiobook_ai.weights.qwen3_tts import QWEN3_TTS_ID, QWEN3_TTS_LANGUAGE

logger = get_logger(__name__)


class Qwen3TTSError(RuntimeError):
    """Raised when in-process Qwen3-TTS load or synthesis fails."""


class _Qwen3Engine(Protocol):
    def generate_voice_clone(self, **kwargs: Any) -> tuple[Any, int]: ...


EngineFactory = Callable[[Path, str], _Qwen3Engine]


class Qwen3TTSBackend(TTSBackend):
    """Load Qwen3-TTS Base once via ModelManager and synthesize via Voice Clone."""

    def __init__(
        self,
        *,
        manager: ModelManager | None = None,
        cache_dir: Path | str | None = None,
        output_dir: Path | None = None,
        device: str | None = None,
        require_gpu: bool = True,
        engine_factory: EngineFactory | None = None,
        references_dir: Path | None = None,
        language: str = QWEN3_TTS_LANGUAGE,
    ) -> None:
        self.manager = manager or ModelManager(cache_dir=cache_dir)
        self.output_dir = output_dir
        self.device = device
        self.require_gpu = require_gpu
        self._engine_factory = engine_factory
        self.references_dir = references_dir
        self.language = language
        self.book_id: str | None = None
        self._engine: _Qwen3Engine | None = None
        self._model_handle: ModelHandle | None = None
        self._loaded = False
        self._voice_prompts: dict[str, Any] = {}

    def ensure_weights(
        self,
        *,
        progress_callback: Callable[[str, float | None], None] | None = None,
    ) -> ModelHandle:
        """Download/validate weights on disk without loading the GPU engine."""
        handle = self.manager.ensure_model(
            QWEN3_TTS_ID,
            progress_callback=progress_callback,
        )
        self._model_handle = handle
        return handle

    def ensure_ready(
        self,
        *,
        progress_callback: Callable[[str, float | None], None] | None = None,
        load_engine: bool = True,
    ) -> ModelHandle:
        """Ensure weights on disk; optionally load the in-process engine."""
        handle = self.ensure_weights(progress_callback=progress_callback)
        if load_engine:
            self._ensure_engine(handle)
        return handle

    def release(self) -> None:
        """Drop the in-process engine and try to free GPU memory."""
        if self._engine is None and not self._loaded:
            return
        logger.info("TTS release backend=qwen3-tts")
        self._engine = None
        self._voice_prompts.clear()
        self._loaded = False
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                if hasattr(torch.cuda, "ipc_collect"):
                    torch.cuda.ipc_collect()
        except Exception as exc:
            logger.warning("TTS release empty_cache failed: %s", exc)

    def synthesize(self, request: TTSRequest) -> AudioSegment:
        """Synthesize ``request`` using Voice Clone (emotion is metadata only)."""
        segments = self.synthesize_batch([request])
        return segments[0]

    def synthesize_batch(self, requests: list[TTSRequest]) -> list[AudioSegment]:
        """Synthesize one or more requests; batches same-voice texts via official API."""
        if not requests:
            return []
        if not self._loaded or self._engine is None:
            self.ensure_ready(load_engine=True)
        assert self._engine is not None

        # Partition into consecutive same-voice runs (API batches one prompt + N texts).
        results: list[AudioSegment] = []
        index = 0
        while index < len(requests):
            voice_id = requests[index].voice_id
            run: list[TTSRequest] = []
            while (
                index < len(requests)
                and requests[index].voice_id == voice_id
                and len(run) < config.TTS_SAME_VOICE_BATCH_SIZE
            ):
                run.append(requests[index])
                index += 1
            results.extend(self._synthesize_same_voice(run))
        return results

    def _synthesize_same_voice(self, requests: list[TTSRequest]) -> list[AudioSegment]:
        assert self._engine is not None
        if not requests:
            return []
        first = requests[0]
        logger.info(
            "TTS synthesize backend=qwen3-tts mode=voice-clone voice=%s "
            "batch=%s emotion=%s chapter=%s language=%s",
            first.voice_id,
            len(requests),
            first.emotion.value,
            first.chapter_id,
            self.language,
        )
        try:
            effective_voice, voice_dir = resolve_voice_dir(
                first.voice_id,
                references_dir=self.references_dir,
                cache_root=self.manager.cache_root,
                book_id=self.book_id,
            )
            texts = [r.text for r in requests]
            wav_list = _run_voice_clone(
                self._engine,
                text=texts if len(texts) > 1 else texts[0],
                language=self.language,
                voice_id=effective_voice,
                voice_dir=voice_dir,
                prompt_cache=self._voice_prompts,
            )
        except FileNotFoundError as exc:
            raise Qwen3TTSError(str(exc)) from exc
        except Qwen3TTSError:
            raise
        except Exception as exc:
            raise Qwen3TTSError(
                f"Qwen3-TTS synthesis failed chapter={first.chapter_id} "
                f"voice={first.voice_id}: {exc}"
            ) from exc

        if isinstance(wav_list, bytes):
            wav_list = [wav_list]
        if len(wav_list) != len(requests):
            raise Qwen3TTSError(
                f"Batch size mismatch: texts={len(requests)} wavs={len(wav_list)}"
            )

        segments: list[AudioSegment] = []
        for request, audio_bytes in zip(requests, wav_list, strict=True):
            if not audio_bytes:
                raise Qwen3TTSError(
                    f"Empty audio from Qwen3-TTS chapter={request.chapter_id}"
                )
            path: Path | None = None
            if self.output_dir is not None:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                chapter = request.chapter_id or "chapter"
                idx = request.segment_index if request.segment_index is not None else 0
                path = self.output_dir / f"{chapter}_{idx:04d}.wav"
                path.write_bytes(audio_bytes)
            segments.append(
                AudioSegment(
                    path=path,
                    data=audio_bytes,
                    format="wav",
                    chapter_id=request.chapter_id,
                    segment_index=request.segment_index,
                )
            )
        return segments

    def _ensure_engine(self, handle: ModelHandle) -> None:
        if self._loaded and self._engine is not None:
            return

        factory = self._engine_factory or _default_engine_factory
        device = self.device or _resolve_device(require_gpu=self.require_gpu)
        logger.info(
            "model-init id=%s path=%s device=%s",
            handle.logical_id,
            handle.path,
            device,
        )
        try:
            from audiobook_ai.gpu.memory import apply_process_vram_reserve

            apply_process_vram_reserve()
            self._engine = factory(handle.path, device)
        except Qwen3TTSError:
            raise
        except ImportError as exc:
            raise Qwen3TTSError(
                "Qwen3-TTS Python package is not installed. "
                "Install the tts-qwen extra (see README). "
                f"Original error: {exc}"
            ) from exc
        except Exception as exc:
            raise Qwen3TTSError(
                f"Failed to load Qwen3-TTS weights from {handle.path}: {exc}"
            ) from exc
        self._loaded = True


def _resolve_device(*, require_gpu: bool) -> str:
    try:
        import torch
    except ImportError as exc:
        raise Qwen3TTSError(
            "PyTorch is required for Qwen3-TTS. "
            "Install with: uv sync --extra tts-qwen"
        ) from exc

    if torch.cuda.is_available():
        return "cuda:0"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    if require_gpu:
        raise Qwen3TTSError(
            "No usable GPU detected (CUDA/ROCm/MPS). "
            "Qwen3-TTS requires a GPU for this MVP. "
            "Install ROCm/CUDA drivers and a matching torch build."
        )
    return "cpu"


def _reference_wav(voice_dir: Path) -> Path:
    wav = voice_dir / "reference.wav"
    if wav.is_file():
        return wav
    matches = sorted(voice_dir.glob("*.wav"))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"No reference.wav (or *.wav) under voice directory {voice_dir}"
    )


def _reference_transcript(voice_dir: Path) -> str:
    for name in ("reference.txt", "reference.lab"):
        path = voice_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise FileNotFoundError(
        f"No reference.txt / reference.lab transcript under {voice_dir}"
    )


def _run_voice_clone(
    engine: _Qwen3Engine,
    *,
    text: str | list[str],
    language: str,
    voice_id: str,
    voice_dir: Path,
    prompt_cache: dict[str, Any],
) -> bytes | list[bytes]:
    ref_audio = str(_reference_wav(voice_dir))
    ref_text = _reference_transcript(voice_dir)
    texts = text if isinstance(text, list) else [text]

    kwargs: dict[str, Any] = {
        "text": texts if len(texts) > 1 else texts[0],
        "language": language,
    }
    # Reuse prompt features across chunks for the same voice when supported.
    if hasattr(engine, "create_voice_clone_prompt"):
        if voice_id not in prompt_cache:
            prompt_cache[voice_id] = engine.create_voice_clone_prompt(
                ref_audio=ref_audio,
                ref_text=ref_text,
                x_vector_only_mode=False,
            )
        kwargs["voice_clone_prompt"] = prompt_cache[voice_id]
    else:
        kwargs["ref_audio"] = ref_audio
        kwargs["ref_text"] = ref_text

    wavs, sample_rate = engine.generate_voice_clone(**kwargs)
    if wavs is None:
        raise Qwen3TTSError("No audio generated; check input text and references")

    import numpy as np

    if isinstance(wavs, (list, tuple)):
        if not wavs:
            raise Qwen3TTSError("Empty wav list from generate_voice_clone")
        arrays = [np.asarray(w) for w in wavs]
    else:
        arrays = [np.asarray(wavs)]

    if len(texts) > 1 and len(arrays) == 1 and len(texts) != 1:
        raise Qwen3TTSError(
            f"Expected {len(texts)} wavs from batch generate_voice_clone, got 1"
        )

    out: list[bytes] = []
    for arr in arrays:
        if arr.size == 0:
            raise Qwen3TTSError("Empty audio array from generate_voice_clone")
        out.append(_float_or_pcm_to_wav_bytes(arr, int(sample_rate)))

    if isinstance(text, list):
        return out
    return out[0]


def _float_or_pcm_to_wav_bytes(arr: Any, sample_rate: int) -> bytes:
    import numpy as np

    data = np.asarray(arr).squeeze()
    if data.dtype == np.int16:
        pcm = data
    else:
        clipped = np.clip(data.astype(np.float64), -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _default_engine_factory(model_path: Path, device: str) -> _Qwen3Engine:
    try:
        import torch
        from qwen_tts import Qwen3TTSModel
    except ImportError as exc:
        raise Qwen3TTSError(
            "qwen_tts is not installed. Install with: uv sync --extra tts-qwen"
        ) from exc

    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    load_kwargs: dict[str, Any] = {
        "device_map": device,
        "dtype": dtype,
    }
    # flash_attention_2 is optional; fall back quietly on ROCm/unsupported builds.
    try:
        return Qwen3TTSModel.from_pretrained(
            str(model_path),
            attn_implementation="flash_attention_2",
            **load_kwargs,
        )
    except Exception:
        return Qwen3TTSModel.from_pretrained(str(model_path), **load_kwargs)
