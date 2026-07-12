"""VoiceGenerator protocol, bank (dev), and Parler generative MVP."""

from __future__ import annotations

import gc
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Protocol

from audiobook_ai import config
from audiobook_ai.models.voice import (
    CANONICAL_VOICE_LANGUAGE,
    CharacterProfile,
    GeneratedVoice,
    VoiceProfile,
)
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.voice.catalog import (
    BaseVoice,
    character_pool,
    discover_base_voices,
    score_base_for_profile,
)
from audiobook_ai.voice.errors import VoiceGenerationError, VoiceLanguageError
from audiobook_ai.voice.registry import VoiceRegistry

logger = get_logger(__name__)

BANK_GENERATOR_NAME = "bank"
BANK_GENERATOR_VERSION = "1"
PARLER_GENERATOR_NAME = "parler"

# MVP narrator profile (same VoiceProfile domain as characters).
NARRATOR_VOICE_PROFILE = VoiceProfile(
    gender="male",
    age_range="adult",
    pitch="medium",
    pace="moderate",
    energy="calm",
    texture="clear",
    personality=["narrative", "steady", "warm"],
)

# Canonical pt-BR passage for generative refs (~short end for 24GB Fish clone).
CANONICAL_PASSAGE_PT_BR = (
    "Naquela manhã ensolarada, o vento trazia o cheiro do mar até as ruas "
    "estreitas do bairro antigo. As crianças corriam entre as bancas da feira."
)


class VoiceGenerator(Protocol):
    """Independent of TTSBackend; produces reusable reference identities."""

    def generate_voice(
        self,
        character: CharacterProfile,
        *,
        book_id: str,
        language: str = CANONICAL_VOICE_LANGUAGE,
    ) -> GeneratedVoice: ...

    def unload(self) -> None:
        """Release GPU weights if any are loaded."""
        ...


def canonical_profile_payload(profile: VoiceProfile | None) -> dict[str, object]:
    if profile is None:
        return {}
    payload = profile.model_dump(mode="json", exclude_none=True)
    payload = dict(sorted(payload.items()))
    if "personality" in payload and isinstance(payload["personality"], list):
        payload["personality"] = sorted(str(item) for item in payload["personality"])
    return payload


def derive_seed(
    *,
    book_id: str,
    character_id: str,
    profile: VoiceProfile | None,
    model_id: str,
    generator_version: str,
    language: str = CANONICAL_VOICE_LANGUAGE,
) -> int:
    """Stable BLAKE2b-derived seed (never Python ``hash()``)."""
    profile_payload = canonical_profile_payload(profile)
    material = (
        f"{book_id}|{character_id}|"
        f"{json.dumps(profile_payload, ensure_ascii=False, sort_keys=True)}|"
        f"{model_id}|{generator_version}|{language}"
    )
    digest = hashlib.blake2b(material.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % (2**31)


def _free_vram_mib() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free, _total = torch.cuda.mem_get_info()
        return free / (1024 * 1024)
    except Exception:
        return None


def _purge_cuda() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
            gc.collect()
            torch.cuda.empty_cache()
    except Exception:
        pass


def _require_min_free_vram(min_mib: int = config.MIN_FREE_VRAM_MIB) -> None:
    free = _free_vram_mib()
    if free is not None and free < min_mib:
        raise VoiceGenerationError(
            "<gpu>",
            f"VRAM free={free:.1f} MiB < hard floor {min_mib} MiB",
        )


def voice_profile_to_parler_description(
    character: CharacterProfile,
    profile: VoiceProfile | None,
) -> str:
    """Translate semantic VoiceProfile → Parler English description (no LLM)."""
    cid = character.character_id
    # Prefer a capitalized speaker cue; Parler BR checkpoint knows named speakers.
    speaker = (character.name or cid).strip().split()[0]
    speaker = speaker[:1].upper() + speaker[1:] if speaker else "Speaker"

    gender = (profile.gender if profile else None) or "neutral"
    pitch = (profile.pitch if profile else None) or "medium"
    pace = (profile.pace if profile else None) or "moderate"
    energy = (profile.energy if profile else None) or "calm"
    he_she = "He" if gender == "male" else "She" if gender == "female" else "They"

    return (
        f"{speaker}'s speech is {pace} paced with a {pitch} pitch. "
        f"{he_she} speaks clearly in a {energy}, natural tone with a steady delivery. "
        f"The recording is of very clear audio quality, close and dry."
    )


def get_voice_generator(
    name: str | None = None,
    *,
    registry: VoiceRegistry | None = None,
    assets_root: Path | None = None,
) -> VoiceGenerator:
    """Factory for the configured VoiceGenerator (MVP default: parler)."""
    selected = (name or config.VOICE_GENERATOR_DEFAULT).strip().casefold()
    if selected in {"parler", "parler_tts", "parlervoices"}:
        return ParlerVoiceGenerator(registry=registry)
    if selected in {"bank", "bankvoice", "bank_voice_generator"}:
        return BankVoiceGenerator(registry=registry, assets_root=assets_root)
    raise ValueError(f"unknown voice generator: {name!r}")


class ParlerVoiceGenerator:
    """Generative Voice Design via Parler-TTS pt-BR (not a finite bank)."""

    def __init__(
        self,
        *,
        registry: VoiceRegistry | None = None,
        model_id: str = config.PARLER_MODEL_ID,
        generator_version: str = config.PARLER_GENERATOR_VERSION,
        device: str | None = None,
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.generator_version = generator_version
        self.device = device
        self._model = None
        self._tokenizer = None
        self._description_tokenizer = None

    def unload(self) -> None:
        """Drop Parler weights and try to reclaim VRAM (≥ floor after purge)."""
        for attr in ("_model", "_tokenizer", "_description_tokenizer"):
            obj = getattr(self, attr, None)
            if obj is not None and hasattr(obj, "to"):
                try:
                    obj.to("cpu")
                except Exception:
                    pass
            setattr(self, attr, None)
        _purge_cuda()
        free = _free_vram_mib()
        if free is not None and free < config.MIN_FREE_VRAM_MIB:
            raise RuntimeError(
                f"after Parler unload free VRAM={free:.1f} MiB < "
                f"{config.MIN_FREE_VRAM_MIB} MiB floor"
            )
        logger.info(
            "voice-design unload generator=parler free_mib=%s",
            f"{free:.1f}" if free is not None else "n/a",
        )

    def generate_voice(
        self,
        character: CharacterProfile,
        *,
        book_id: str,
        language: str = CANONICAL_VOICE_LANGUAGE,
    ) -> GeneratedVoice:
        if language != CANONICAL_VOICE_LANGUAGE:
            raise VoiceLanguageError(character.character_id, language)
        if not book_id:
            raise VoiceGenerationError(character.character_id, "book_id is required")

        if self.registry is not None:
            existing = self.registry.get(book_id, character.character_id)
            if existing is not None:
                return existing

        profile = character.voice_profile
        if character.character_id == config.NARRATOR_VOICE_ID or (
            character.name and character.name.strip().casefold() == "narrator"
        ):
            profile = profile or NARRATOR_VOICE_PROFILE

        seed = derive_seed(
            book_id=book_id,
            character_id=character.character_id,
            profile=profile,
            model_id=self.model_id,
            generator_version=self.generator_version,
            language=language,
        )
        description = voice_profile_to_parler_description(character, profile)

        try:
            wav_path, text_path = self._synthesize_reference(
                prompt=CANONICAL_PASSAGE_PT_BR,
                description=description,
                seed=seed,
                character_id=character.character_id,
            )
        except VoiceGenerationError:
            raise
        except Exception as exc:
            self.unload()
            raise VoiceGenerationError(
                character.character_id,
                f"parler generation failed: {exc}",
            ) from exc

        return GeneratedVoice(
            voice_id=character.character_id,
            character_id=character.character_id,
            book_id=book_id,
            language=CANONICAL_VOICE_LANGUAGE,
            reference_wav=wav_path,
            reference_text=text_path,
            generator=PARLER_GENERATOR_NAME,
            generator_version=self.generator_version,
            model_id=self.model_id,
            seed=seed,
            voice_profile=profile,
            metadata={"description": description},
        )

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        _require_min_free_vram(config.MIN_FREE_VRAM_MIB)
        try:
            import torch
            from parler_tts import ParlerTTSForConditionalGeneration
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise VoiceGenerationError(
                "<parler>",
                "parler-tts is not installed. "
                'uv pip install --no-deps "parler-tts @ git+https://github.com/huggingface/parler-tts.git"',
            ) from exc

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("voice-design load generator=parler model=%s device=%s", self.model_id, device)
        self._model = ParlerTTSForConditionalGeneration.from_pretrained(self.model_id).to(
            device
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            "parler-tts/parler-tts-mini-multilingual"
        )
        self._description_tokenizer = AutoTokenizer.from_pretrained(
            self._model.config.text_encoder._name_or_path
        )
        self.device = device
        free = _free_vram_mib()
        if free is not None and free < config.MIN_FREE_VRAM_MIB:
            self.unload()
            raise VoiceGenerationError(
                "<parler>",
                f"after Parler load free VRAM={free:.1f} MiB < "
                f"{config.MIN_FREE_VRAM_MIB} MiB floor",
            )

    def _synthesize_reference(
        self,
        *,
        prompt: str,
        description: str,
        seed: int,
        character_id: str,
    ) -> tuple[Path, Path]:
        import torch
        from transformers import set_seed

        self._ensure_model()
        assert self._model is not None
        assert self._tokenizer is not None
        assert self._description_tokenizer is not None

        set_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

        device = self.device or "cpu"
        input_ids = self._description_tokenizer(
            description, return_tensors="pt"
        ).input_ids.to(device)
        prompt_input_ids = self._tokenizer(
            prompt, return_tensors="pt"
        ).input_ids.to(device)

        with torch.inference_mode():
            generation = self._model.generate(
                input_ids=input_ids,
                prompt_input_ids=prompt_input_ids,
                do_sample=True,
            )
        audio_arr = generation.detach().cpu().numpy().squeeze()
        sample_rate = int(self._model.config.sampling_rate)

        # Truncate for Fish Speech headroom on 24GB.
        max_samples = int(config.VOICE_REF_MAX_SECONDS * sample_rate)
        if audio_arr.shape[0] > max_samples:
            audio_arr = audio_arr[:max_samples]

        out_dir = Path(tempfile.mkdtemp(prefix=f"parler-{character_id}-"))
        wav_path = out_dir / "reference.wav"
        text_path = out_dir / "reference.txt"
        try:
            import soundfile as sf

            sf.write(str(wav_path), audio_arr, sample_rate)
        except ImportError as exc:
            raise VoiceGenerationError(
                character_id, "soundfile is required to write reference.wav"
            ) from exc
        text_path.write_text(prompt + "\n", encoding="utf-8")
        (out_dir / "reference.lab").write_text(prompt + "\n", encoding="utf-8")
        return wav_path, text_path


class BankVoiceGenerator:
    """Dev/test: select a packaged pt-BR base voice (NOT product success path)."""

    def __init__(
        self,
        *,
        registry: VoiceRegistry | None = None,
        assets_root: Path | None = None,
        bank_version: str = config.VOICE_BANK_VERSION,
    ) -> None:
        self.registry = registry
        self.assets_root = assets_root
        self.bank_version = bank_version

    def unload(self) -> None:
        return

    def generate_voice(
        self,
        character: CharacterProfile,
        *,
        book_id: str,
        language: str = CANONICAL_VOICE_LANGUAGE,
        used_base_voice_ids: set[str] | None = None,
    ) -> GeneratedVoice:
        if language != CANONICAL_VOICE_LANGUAGE:
            raise VoiceLanguageError(character.character_id, language)
        if not book_id:
            raise VoiceGenerationError(character.character_id, "book_id is required")

        if self.registry is not None:
            existing = self.registry.get(book_id, character.character_id)
            if existing is not None:
                return existing

        bases = discover_base_voices(assets_root=self.assets_root, require_pt_br=True)
        if character.character_id == config.NARRATOR_VOICE_ID or (
            character.name and character.name.strip().casefold() == "narrator"
        ):
            return self._narrator_voice(bases, character, book_id=book_id)

        pool = character_pool(bases)
        if not pool:
            raise VoiceGenerationError(
                character.character_id,
                "no pt-BR character base voices available in the catalog",
            )

        used = set(used_base_voice_ids or ())
        selected = self._select_base(
            pool, character.voice_profile, used, character.character_id, book_id
        )
        seed = derive_seed(
            book_id=book_id,
            character_id=character.character_id,
            profile=character.voice_profile,
            model_id=f"bank:{self.bank_version}",
            generator_version=BANK_GENERATOR_VERSION,
            language=language,
        )
        return GeneratedVoice(
            voice_id=character.character_id,
            character_id=character.character_id,
            book_id=book_id,
            language=CANONICAL_VOICE_LANGUAGE,
            reference_wav=selected.reference_wav,
            reference_text=selected.reference_text,
            generator=BANK_GENERATOR_NAME,
            generator_version=BANK_GENERATOR_VERSION,
            model_id=f"bank:{self.bank_version}",
            seed=seed,
            voice_profile=character.voice_profile,
            base_voice_id=selected.voice_id,
            metadata={
                "bank_version": self.bank_version,
                "gender": selected.gender,
                "age_range": selected.age_range,
                "tags": list(selected.tags),
                "license": selected.license,
            },
        )

    def _narrator_voice(
        self, bases: list[BaseVoice], character: CharacterProfile, *, book_id: str
    ) -> GeneratedVoice:
        narrator = next((base for base in bases if base.is_narrator), None)
        if narrator is None:
            raise VoiceGenerationError(
                character.character_id,
                "packaged narrator pt-BR voice is missing",
            )
        seed = derive_seed(
            book_id=book_id,
            character_id=config.NARRATOR_VOICE_ID,
            profile=NARRATOR_VOICE_PROFILE,
            model_id=f"bank:{self.bank_version}",
            generator_version=BANK_GENERATOR_VERSION,
        )
        return GeneratedVoice(
            voice_id=config.NARRATOR_VOICE_ID,
            character_id=config.NARRATOR_VOICE_ID,
            book_id=book_id,
            language=CANONICAL_VOICE_LANGUAGE,
            reference_wav=narrator.reference_wav,
            reference_text=narrator.reference_text,
            generator=BANK_GENERATOR_NAME,
            generator_version=BANK_GENERATOR_VERSION,
            model_id=f"bank:{self.bank_version}",
            seed=seed,
            voice_profile=NARRATOR_VOICE_PROFILE,
            base_voice_id=narrator.voice_id,
            metadata={
                "bank_version": self.bank_version,
                "role": "narrator",
                "license": narrator.license,
            },
        )

    def _select_base(
        self,
        pool: list[BaseVoice],
        profile: VoiceProfile | None,
        used: set[str],
        character_id: str,
        book_id: str,
    ) -> BaseVoice:
        scored = sorted(
            pool,
            key=lambda base: (
                -score_base_for_profile(base, profile),
                base.voice_id,
            ),
        )
        best_score = score_base_for_profile(scored[0], profile) if scored else 0
        compatible = [
            base for base in scored if score_base_for_profile(base, profile) == best_score
        ]
        unused = [base for base in compatible if base.voice_id not in used]
        candidates = unused if unused else compatible
        if not candidates:
            unused_all = [base for base in pool if base.voice_id not in used]
            candidates = unused_all if unused_all else list(pool)

        seed = derive_seed(
            book_id=book_id,
            character_id=character_id,
            profile=profile,
            model_id=f"bank:{self.bank_version}",
            generator_version=BANK_GENERATOR_VERSION,
        )
        index = seed % len(candidates)
        return candidates[index]
