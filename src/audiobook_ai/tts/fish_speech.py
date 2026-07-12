"""Fish Speech in-process TTS backend (no HTTP / no cloud)."""

from __future__ import annotations

import gc
import io
import os
import tempfile
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from audiobook_ai import config
from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.voices import resolve_voice_dir
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.weights.fish import FISH_SPEECH_ID, resolve_fish_model
from audiobook_ai.weights.manager import ModelHandle, ModelManager

logger = get_logger(__name__)

AMPLITUDE = 32768


class FishSpeechError(RuntimeError):
    """Raised when in-process Fish Speech load or synthesis fails."""


class _InferenceEngine(Protocol):
    def inference(self, req: Any) -> Any: ...


EngineFactory = Callable[[Path, str], _InferenceEngine]


class FishSpeechBackend(TTSBackend):
    """Load Fish Speech once via ModelManager and synthesize in-process."""

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
        fish_model: str | None = None,
        fish_logical_id: str | None = None,
    ) -> None:
        self.manager = manager or ModelManager(cache_dir=cache_dir)
        self.output_dir = output_dir
        self.device = device
        self.require_gpu = require_gpu
        self._engine_factory = engine_factory
        self.references_dir = references_dir
        self.book_id: str | None = None
        if fish_logical_id:
            self.fish_logical_id = fish_logical_id
        else:
            self.fish_logical_id = resolve_fish_model(fish_model).logical_id
        self._engine: _InferenceEngine | None = None
        self._model_handle: ModelHandle | None = None
        self._loaded = False

    def ensure_weights(
        self,
        *,
        progress_callback: Callable[[str, float | None], None] | None = None,
    ) -> ModelHandle:
        """Download/validate weights on disk without loading the GPU engine."""
        handle = self.manager.ensure_model(
            self.fish_logical_id or FISH_SPEECH_ID,
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
        logger.info("TTS release backend=fish-speech")
        self._engine = None
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
        """Synthesize ``request`` using the loaded in-process engine."""
        if not self._loaded or self._engine is None:
            self.ensure_ready(load_engine=True)

        assert self._engine is not None
        text = _text_with_emotion(request.text, request.emotion)
        logger.info(
            "TTS synthesize backend=fish-speech mode=in-process voice=%s emotion=%s chapter=%s",
            request.voice_id,
            request.emotion.value,
            request.chapter_id,
        )
        try:
            effective_voice, voice_dir = resolve_voice_dir(
                request.voice_id,
                references_dir=self.references_dir,
                cache_root=self.manager.cache_root,
                book_id=self.book_id,
            )
            audio_bytes = _run_inference(
                self._engine,
                text=text,
                reference_id=effective_voice,
                voice_dir=voice_dir,
            )
        except FileNotFoundError as exc:
            raise FishSpeechError(str(exc)) from exc
        except FishSpeechError:
            raise
        except Exception as exc:
            raise FishSpeechError(
                f"Fish Speech synthesis failed chapter={request.chapter_id} "
                f"voice={request.voice_id}: {exc}"
            ) from exc

        if not audio_bytes:
            raise FishSpeechError(
                f"Empty audio from Fish Speech chapter={request.chapter_id}"
            )

        path: Path | None = None
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            chapter = request.chapter_id or "chapter"
            index = request.segment_index if request.segment_index is not None else 0
            path = self.output_dir / f"{chapter}_{index:04d}.wav"
            path.write_bytes(audio_bytes)

        return AudioSegment(
            path=path,
            data=audio_bytes,
            format="wav",
            chapter_id=request.chapter_id,
            segment_index=request.segment_index,
        )

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
        except FishSpeechError:
            raise
        except ImportError as exc:
            raise FishSpeechError(
                "Fish Speech Python package is not installed. "
                "Install the tts-fish extra and fish-speech (see README). "
                f"Original error: {exc}"
            ) from exc
        except Exception as exc:
            raise FishSpeechError(
                f"Failed to load Fish Speech weights from {handle.path}: {exc}"
            ) from exc
        self._loaded = True


def _resolve_device(*, require_gpu: bool) -> str:
    try:
        import torch
    except ImportError as exc:
        raise FishSpeechError(
            "PyTorch is required for Fish Speech in-process TTS. "
            "Install with: uv sync --extra tts-fish"
        ) from exc

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    if require_gpu:
        raise FishSpeechError(
            "No usable GPU detected (CUDA/ROCm/MPS). "
            "Fish Speech in-process TTS requires a GPU for this MVP. "
            "Install ROCm/CUDA drivers and a matching torch build."
        )
    return "cpu"


def _text_with_emotion(text: str, emotion: Emotion) -> str:
    """Map closed emotion vocab into S2-style natural-language control."""
    if emotion == Emotion.NEUTRAL:
        return text
    return f"[{emotion.value}] {text}"


def _run_inference(
    engine: _InferenceEngine,
    *,
    text: str,
    reference_id: str,
    voice_dir: Path,
) -> bytes:
    req = _build_serve_request(text=text, reference_id=reference_id)

    # Upstream ReferenceLoader resolves Path("references")/<id> relative to cwd.
    with _temporary_references_cwd(reference_id, voice_dir):
        chunks: list[bytes] = []
        sample_rate: int | None = None
        pcm_segments: list[Any] = []

        for result in engine.inference(req):
            code = getattr(result, "code", None)
            audio = getattr(result, "audio", None)
            if code == "error":
                raise FishSpeechError(str(getattr(result, "error", "inference error")))
            if code == "header" and isinstance(audio, tuple):
                sample_rate = int(audio[0]) if audio[0] else sample_rate
                if isinstance(audio[1], (bytes, bytearray)):
                    chunks.append(bytes(audio[1]))
            elif code in {"segment", "final"} and isinstance(audio, tuple):
                sample_rate = int(audio[0]) if audio[0] else sample_rate
                payload = audio[1]
                if isinstance(payload, (bytes, bytearray)):
                    chunks.append(bytes(payload))
                else:
                    import numpy as np

                    arr = np.asarray(payload)
                    if arr.dtype != np.int16:
                        arr = (arr * AMPLITUDE).astype(np.int16)
                    pcm_segments.append(arr)

        if chunks and not pcm_segments:
            return b"".join(chunks)
        if pcm_segments:
            import numpy as np

            pcm = np.concatenate(pcm_segments)
            return _pcm16_to_wav_bytes(pcm, sample_rate or 44100)
        raise FishSpeechError("No audio generated; check input text and references")


@contextmanager
def _temporary_references_cwd(voice_id: str, voice_dir: Path) -> Iterator[Path]:
    """chdir into a layout with ``references/<voice_id>`` pointing at ``voice_dir``."""
    previous_cwd = Path.cwd()
    voice_dir = voice_dir.resolve()

    # Fast path: voice already lives under .../references/<id>
    if voice_dir.parent.name == "references":
        os.chdir(voice_dir.parent.parent)
        try:
            yield Path.cwd()
        finally:
            os.chdir(previous_cwd)
        return

    with tempfile.TemporaryDirectory(prefix="audiobook-ai-refs-") as tmp:
        root = Path(tmp)
        link_parent = root / "references"
        link_parent.mkdir(parents=True, exist_ok=True)
        link = link_parent / voice_id
        try:
            link.symlink_to(voice_dir, target_is_directory=True)
        except OSError:
            # Fallback when symlinks are unavailable: copy minimal refs.
            link.mkdir(parents=True, exist_ok=True)
            for item in voice_dir.iterdir():
                target = link / item.name
                if item.is_file():
                    target.write_bytes(item.read_bytes())
        os.chdir(root)
        try:
            yield root
        finally:
            os.chdir(previous_cwd)


def _build_serve_request(*, text: str, reference_id: str) -> Any:
    voice = reference_id or config.DEFAULT_VOICE_ID
    try:
        from fish_speech.utils.schema import ServeTTSRequest
    except ImportError:
        # Duck-typed stub for unit tests without fish_speech installed.
        return SimpleNamespace(
            text=text,
            references=[],
            reference_id=voice,
            max_new_tokens=1024,
            chunk_length=200,
            top_p=0.7,
            repetition_penalty=1.2,
            temperature=0.7,
            format="wav",
        )
    return ServeTTSRequest(
        text=text,
        references=[],
        reference_id=voice,
        max_new_tokens=1024,
        chunk_length=200,
        top_p=0.7,
        repetition_penalty=1.2,
        temperature=0.7,
        format="wav",
    )


def _pcm16_to_wav_bytes(pcm: Any, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.astype("int16").tobytes())
    return buffer.getvalue()


def _patch_torchaudio_for_fish_speech() -> None:
    """Compat shim for fish-speech on torchaudio ≥2.9 (esp. ROCm).

    Upstream ``v2.0.0-beta`` still calls ``torchaudio.list_audio_backends()``
    (removed in 2.9) and ``torchaudio.load(..., backend=...)``. On 2.9+,
    ``load`` delegates to TorchCodec, which pulls CUDA libs and fails on ROCm.
    Prefer soundfile for reference WAV I/O used by ReferenceLoader.
    """
    import torch
    import torchaudio

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]  # type: ignore[attr-defined]

    # Idempotent: skip if we already wrapped load.
    if getattr(torchaudio.load, "_audiobook_ai_soundfile", False):
        return

    import soundfile as sf

    def _load_with_soundfile(uri, *args, **kwargs):  # noqa: ANN001
        del args, kwargs  # fish-speech only needs waveform + sample rate
        if hasattr(uri, "read"):
            data, sample_rate = sf.read(uri, dtype="float32")
        else:
            data, sample_rate = sf.read(str(uri), dtype="float32")
        waveform = torch.as_tensor(data)
        if waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)
        else:
            # soundfile: (time, channel) → torchaudio: (channel, time)
            waveform = waveform.transpose(0, 1)
        return waveform, int(sample_rate)

    _load_with_soundfile._audiobook_ai_soundfile = True  # type: ignore[attr-defined]
    torchaudio.load = _load_with_soundfile  # type: ignore[assignment]


def _default_engine_factory(model_path: Path, device: str) -> _InferenceEngine:
    """Build TTSInferenceEngine from a ModelManager path (mirrors upstream server)."""
    try:
        import torch

        _patch_torchaudio_for_fish_speech()
        from fish_speech.inference_engine import TTSInferenceEngine
        from fish_speech.models.dac.inference import load_model as load_decoder_model
        from fish_speech.models.text2semantic.inference import launch_thread_safe_queue
    except ImportError as exc:
        raise ImportError(str(exc)) from exc

    precision = torch.bfloat16
    llama_checkpoint = str(model_path)
    decoder_checkpoint = str(model_path / "codec.pth")
    if not Path(decoder_checkpoint).is_file():
        raise FishSpeechError(
            f"Invalid Fish Speech weights: missing codec.pth under {model_path}"
        )

    llama_queue = launch_thread_safe_queue(
        checkpoint_path=llama_checkpoint,
        device=device,
        precision=precision,
        compile=False,
    )
    decoder_model = load_decoder_model(
        config_name="modded_dac_vq",
        checkpoint_path=decoder_checkpoint,
        device=device,
    )
    engine = TTSInferenceEngine(
        llama_queue=llama_queue,
        decoder_model=decoder_model,
        precision=precision,
        compile=False,
    )

    # Warm-up once (same pattern as upstream ModelManager.warm_up).
    try:
        from fish_speech.utils.schema import ServeTTSRequest

        list(
            engine.inference(
                ServeTTSRequest(
                    text="Hello world.",
                    references=[],
                    reference_id=None,
                    max_new_tokens=64,
                    chunk_length=200,
                    top_p=0.7,
                    repetition_penalty=1.2,
                    temperature=0.7,
                    format="wav",
                )
            )
        )
    except Exception as exc:
        logger.warning("Fish Speech warm-up failed (continuing): %s", exc)

    return engine
