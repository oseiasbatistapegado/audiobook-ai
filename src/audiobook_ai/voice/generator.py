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


def _patch_parler_tts_config() -> None:
    """Fix ParlerTTSConfig for transformers >= 4.54 where nested configs are
    consumed during PretrainedConfig.__init__() before ParlerTTSConfig can
    validate them.

    The original __init__ calls super().__init__(**kwargs) which consumes the
    nested config dicts, then checks for them and raises ValueError.
    This patch completely replaces __init__ to save the nested configs before
    super() and instantiate them afterward.
    """
    try:
        from parler_tts.configuration_parler_tts import ParlerTTSConfig
    except ImportError:
        return

    if getattr(ParlerTTSConfig, "_patched", False):
        return

    from parler_tts.configuration_parler_tts import ParlerTTSDecoderConfig
    from parler_tts.modeling_parler_tts import ParlerTTSForConditionalGeneration
    from transformers import (
        AutoConfig,
        GenerationConfig,
        GenerationMixin,
        PretrainedConfig,
    )
    from packaging.version import Version
    import torch

    transformers_version = Version(
        __import__("transformers", fromlist=["__version__"]).__version__
    )
    _TRANSFORMERS_457 = transformers_version >= Version("4.57")

    if _TRANSFORMERS_457:
        # Make ParlerTTSForConditionalGeneration inherit from GenerationMixin so
        # that all generation-related methods (_get_logits_processor,
        # _get_stopping_criteria, _prepare_cache_for_generation, etc.) are
        # available.  In transformers >= 4.57 PreTrainedModel no longer inherits
        # from GenerationMixin, but parler_tts still expects these methods.
        if GenerationMixin not in ParlerTTSForConditionalGeneration.__mro__:
            _ParlerTTSForConditionalGeneration = type(
                "ParlerTTSForConditionalGeneration",
                (ParlerTTSForConditionalGeneration, GenerationMixin),
                {},
            )
            # Patch the module so imported references also get the new class.
            import parler_tts.modeling_parler_tts as _parler_module
            _parler_module.ParlerTTSForConditionalGeneration = (
                _ParlerTTSForConditionalGeneration
            )
            # Also update the local reference.
            ParlerTTSForConditionalGeneration = _ParlerTTSForConditionalGeneration
            # Patch the parler_tts top-level package so `from parler_tts import
            # ParlerTTSForConditionalGeneration` also resolves to the patched class.
            import parler_tts as _parler_pkg
            _parler_pkg.ParlerTTSForConditionalGeneration = (
                _ParlerTTSForConditionalGeneration
            )
            # Override methods that have incompatible signatures with the
            # GenerationMixin version.  parler_tts defines _get_initial_cache_position
            # with a different signature, but GenerationMixin.generate() calls it
            # with the GenerationMixin signature (cur_len, device, model_kwargs).
            _ParlerTTSForConditionalGeneration._get_initial_cache_position = (
                GenerationMixin._get_initial_cache_position
            )

    # Register ParlerTTSConfig with AutoConfig.
    # parler_tts package does not register "parler_tts" model type (relies on
    # auto_map from config.json), but newer transformers dropped auto_map
    # support for some checkpoints. This ensures AutoConfig.from_pretrained()
    # can load ParlerTTSConfig when the config.json has model_type="parler_tts".
    AutoConfig.register("parler_tts", ParlerTTSConfig)

    def _new_init(
        self,
        vocab_size: int = 1024,
        prompt_cross_attention: bool = False,
        **kwargs,
    ) -> None:
        # Handle no-args construction (used by transformers' to_diff_dict for defaults).
        # In this case, just call PretrainedConfig.__init__ and set minimal defaults.
        if not kwargs:
            PretrainedConfig.__init__(self, **kwargs)
            self.text_encoder = None
            self.audio_encoder = None
            self.decoder = None
            self.vocab_size = vocab_size
            self.prompt_cross_attention = prompt_cross_attention
            self.is_encoder_decoder = True
            return

        # Save nested config values BEFORE super() consumes them.
        text_encoder_config = kwargs.pop("text_encoder", {})
        audio_encoder_config = kwargs.pop("audio_encoder", {})
        decoder_config = kwargs.pop("decoder", {})

        PretrainedConfig.__init__(self, **kwargs)

        # Handle both dict (old transformers) and PretrainedConfig (new transformers >= 4.54)
        # forms of nested config values.
        if isinstance(text_encoder_config, dict):
            text_encoder_model_type = text_encoder_config.pop("model_type")
            self.text_encoder = AutoConfig.for_model(
                text_encoder_model_type, **text_encoder_config
            )
        else:
            self.text_encoder = text_encoder_config

        if isinstance(audio_encoder_config, dict):
            audio_encoder_model_type = audio_encoder_config.pop("model_type")

            # Handle DAC version edge case (mirrors original logic)
            model_version = kwargs.get("transformers_version", None)
            try:
                from parler_tts.modeling_parler_tts import (  # pyright: ignore[reportAttributeAccessIssue]
                    use_dac_on_the_hub,
                )
            except Exception:
                use_dac_on_the_hub = False

            if (
                model_version is not None
                and Version(model_version) <= Version("4.44.2dev")
                and use_dac_on_the_hub  # pyright: ignore[reportAttributeAccessIssue]
                and audio_encoder_model_type == "dac"
            ):
                audio_encoder_model_type = "dac_on_the_hub"

            self.audio_encoder = AutoConfig.for_model(
                audio_encoder_model_type, **audio_encoder_config
            )
        else:
            self.audio_encoder = audio_encoder_config

        if isinstance(decoder_config, dict):
            self.decoder = ParlerTTSDecoderConfig(**decoder_config)
        else:
            self.decoder = decoder_config

        self.vocab_size = vocab_size
        self.prompt_cross_attention = prompt_cross_attention
        self.is_encoder_decoder = True

         # Ensure generation_config is set (transformers 4.57+ doesn't set it
        # automatically from config dict if the key is missing).
        # The ParlerTTS model's generate() requires self.config.generation_config.
        # Inherit decoder_start_token_id from the top-level config or decoder
        # nested config so GenerationMixin.generate() validation passes.
        if not hasattr(self, "generation_config") or self.generation_config is None:
            gen_kwargs: dict = {}
            if kwargs.get("decoder_start_token_id") is not None:
                gen_kwargs["decoder_start_token_id"] = kwargs["decoder_start_token_id"]
            else:
                decoder = kwargs.get("decoder")
                if isinstance(decoder, dict):
                    gen_kwargs["decoder_start_token_id"] = decoder.get("decoder_start_token_id")
                elif hasattr(decoder, "decoder_start_token_id"):
                    gen_kwargs["decoder_start_token_id"] = decoder.decoder_start_token_id
            # Propagate eos/pad/bos from top-level or decoder config.
            for _token_key in ("eos_token_id", "pad_token_id", "bos_token_id"):
                if gen_kwargs.get(_token_key) is None:
                    val = kwargs.get(_token_key)
                    if val is None and isinstance(decoder_config, dict):
                        val = decoder_config.get(_token_key)
                    if val is not None:
                        gen_kwargs[_token_key] = val
            self.generation_config = GenerationConfig(**gen_kwargs)

    # Patch to_dict so it serializes nested config objects (required by
    # transformers' to_json_string → to_diff_dict → to_dict chain).
    _orig_to_dict = ParlerTTSConfig.to_dict

    def _new_to_dict(self, *args, **kwargs):
        d = _orig_to_dict(self, *args, **kwargs)
        # Ensure generation_config is serializable (dict, not object)
        gc = getattr(self, "generation_config", None)
        if gc is not None and not isinstance(gc, dict):
            d["generation_config"] = gc.to_dict()
        return d

    ParlerTTSConfig.to_dict = _new_to_dict  # type: ignore[assignment]

    # Patch _validate_model_kwargs removed in transformers >= 4.50 but still
    # called by parler_tts's generate wrapper (parler-tts#395).
    # Returns empty dict so generated_kwargs stays {} (no validation).
    if not hasattr(ParlerTTSForConditionalGeneration, "_validate_model_kwargs"):
        ParlerTTSForConditionalGeneration._validate_model_kwargs = (  # type: ignore[attr-defined]
            lambda self, kwargs: None
        )

    if _TRANSFORMERS_457:
        # Patch ParlerTTSForConditionalGeneration.generate to fall back to
        # config.generation_config when self.generation_config is None.
        # In transformers 4.57, self.generation_config on the model may remain
        # None even when config.generation_config is properly set.
        _orig_generate = ParlerTTSForConditionalGeneration.generate

        def _new_generate(self, *args, **kwargs):
            if self.generation_config is None and hasattr(self, "config"):
                gc = getattr(self.config, "generation_config", None)
                if gc is not None:
                    self.generation_config = gc
            return _orig_generate(self, *args, **kwargs)

        ParlerTTSForConditionalGeneration.generate = _new_generate  # type: ignore[assignment]

    ParlerTTSConfig.__init__ = _new_init  # type: ignore[assignment]

    if _TRANSFORMERS_457:
        # Patch _prepare_model_inputs — removed from PreTrainedModel in
        # transformers >= 4.50 (moved to GenerationMixin) but parler_tts calls
        # it directly (parler-tts#395). Forward to GenerationMixin impl.
        if not hasattr(ParlerTTSForConditionalGeneration, "_prepare_model_inputs"):
            ParlerTTSForConditionalGeneration._prepare_model_inputs = (  # type: ignore[attr-defined]
                GenerationMixin._prepare_model_inputs
            )

        # Patch _prepare_attention_mask_for_generation — signature changed in
        # transformers >= 4.57 (now takes generation_config + model_kwargs as
        # separate args, not pad/eos token ids). Parler-tts calls the OLD
        # signature, so we wrap GenerationMixin's version to adapt.
        _orig_prepare_attn_mask = GenerationMixin._prepare_attention_mask_for_generation

        def _adapter_prepare_attn_mask(
            self,
            inputs_or_tensor,
            second,
            third=None,
            model_kwargs=None,
        ):
            """Adapt old parler_tts call signature to new transformers signature.

            Old signature (parler_tts calls):
                _prepare_attention_mask_for_generation(self, input_ids, pad_token_id, eos_token_id)
            New signature (transformers >= 4.57):
                _prepare_attention_mask_for_generation(self, inputs_tensor, generation_config, model_kwargs)
            """
            # Detect old-style call: if second arg is an int/None/Tensor (token id or pre-computed tensor), it's old style.
            # parler_tts passes generation_config._pad_token_tensor (a Tensor) as second arg.
            is_old_style = isinstance(second, (int, type(None))) or (
                isinstance(second, torch.Tensor) and third is not None
            )
            if is_old_style:
                pad_token_id = second
                eos_token_id = third if third is not None else second
                # Build a minimal generation_config-like object.
                # Ensure tensors are on the model's device.
                model_device = next(self.parameters(), None)
                if model_device is not None:
                    model_device = model_device.device
                else:
                    model_device = None
                pad_tensor = pad_token_id
                if isinstance(pad_tensor, torch.Tensor):
                    pad_tensor = pad_tensor.to(model_device) if model_device is not None else pad_tensor
                else:
                    pad_tensor = torch.tensor(pad_token_id, device=model_device) if isinstance(pad_token_id, int) else None
                eos_tensor = eos_token_id
                if isinstance(eos_tensor, torch.Tensor):
                    eos_tensor = eos_tensor.to(model_device) if model_device is not None else eos_tensor
                else:
                    eos_tensor = torch.tensor(eos_token_id, device=model_device) if isinstance(eos_token_id, int) else None
                class _FakeGc:
                    _pad_token_tensor = pad_tensor
                    _eos_token_tensor = eos_tensor
                fake_gc = _FakeGc()
                # Call with new signature.
                return _orig_prepare_attn_mask(self, inputs_or_tensor, fake_gc, {})
            else:
                # Already new-style call (from elsewhere).
                return _orig_prepare_attn_mask(self, inputs_or_tensor, second, third)

        ParlerTTSForConditionalGeneration._prepare_attention_mask_for_generation = (  # type: ignore[attr-defined]
            _adapter_prepare_attn_mask
        )

        # Patch _prepare_special_tokens and _prepare_generated_length — also moved
        # Patch _prepare_special_tokens and _prepare_generated_length — also moved
        # from PreTrainedModel to GenerationMixin in transformers >= 4.50.
        for _method in ("_prepare_special_tokens", "_prepare_generated_length"):
            if not hasattr(ParlerTTSForConditionalGeneration, _method):
                setattr(ParlerTTSForConditionalGeneration, _method, getattr(GenerationMixin, _method))

        # Patch _supports_* methods — added to GenerationMixin in transformers >=
        # 4.57 but not inherited by PreTrainedModel-based models.
        for _method in ("_supports_default_dynamic_cache", "_supports_logits_to_keep"):
            if not hasattr(ParlerTTSForConditionalGeneration, _method):
                setattr(
                    ParlerTTSForConditionalGeneration,
                    _method,
                    classmethod(lambda cls: getattr(GenerationMixin, _method)(cls)),
                )

    # Monkey-patch DynamicCache to provide key_cache/value_cache as properties.
    # Parler-TTS attention layers (modeling_parler_tts.py lines 532, 659, 874)
    # access past_key_value.key_cache[self.layer_idx] after unwrapping
    # EncoderDecoderCache.self_attention_cache (or cross_attention_cache).
    # In transformers 4.46+, DynamicCache stores data in self.layers (list of
    # DynamicLayer). The legacy key_cache[layer_idx] access pattern must work
    # regardless of which Cache subclass is unwrapped.
    from transformers.cache_utils import DynamicCache

    if not hasattr(DynamicCache, "key_cache"):  # type: ignore[operator]
        # type: ignore suppresses "Cannot assign to attribute" for dynamic attrs

        @property
        def _dc_key_cache(self):
            if hasattr(self, "layers") and self.layers:
                return [layer.keys for layer in self.layers]
            return []

        @property
        def _dc_value_cache(self):
            if hasattr(self, "layers") and self.layers:
                return [layer.values for layer in self.layers]
            return []

        DynamicCache.key_cache = _dc_key_cache  # type: ignore[assignment]
        DynamicCache.value_cache = _dc_value_cache  # type: ignore[assignment]

    ParlerTTSConfig._patched = True  # type: ignore[attr-defined]


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
            raise VoiceGenerationError(
                character.character_id,
                f"parler-tts not available: install with\n"
                '    uv sync --extra voice-parler --extra tts-qwen\n'
                '    uv pip install --no-deps "parler-tts @ '
                'git+https://github.com/huggingface/parler-tts.git"\n'
                "or skip Voice Design by setting\n"
                "    export VOICE_GENERATOR=bank",
            )
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
            # Patch ParlerTTSConfig BEFORE importing ParlerTTSForConditionalGeneration
            # so the local import gets the patched class (with GenerationMixin
            # in MRO).  In the voice-design subprocess this ensures the patch
            # applies even though _patch_parler_tts_config() is only defined
            # here and not called at module load time.
            _patch_parler_tts_config()
            from parler_tts import ParlerTTSForConditionalGeneration
            from parler_tts.configuration_parler_tts import ParlerTTSConfig
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise VoiceGenerationError(
                "<parler>",
                "parler-tts is not installed. "
                'uv pip install --no-deps "parler-tts @ '
                'git+https://github.com/huggingface/parler-tts.git"',
            ) from exc

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        load_dtype = torch.float32 if device == "cpu" else torch.float16
        logger.info("voice-design load generator=parler model=%s device=%s", self.model_id, device)
        if device == "cpu":
            logger.info(
                "voice-design load generator=parler dtype=float32 "
                "expected_weights_mib=~2456 (0.6B params)",
            )
        else:
            logger.info(
                "voice-design load generator=parler dtype=float16 "
                "expected_weights_mib=~1228 (0.6B params)",
            )
        self._model = ParlerTTSForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=load_dtype
        ).to(device)
        # Sync model.generation_config from config.generation_config.
        # Transformers 4.57 from_pretrained only sets model.generation_config
        # from a generation_config.json file, which parler models lack.
        if self._model.generation_config is None and hasattr(
            self._model.config, "generation_config"
        ):
            self._model.generation_config = self._model.config.generation_config
        # Pre-compute _*_token_tensor attributes that parler_tts's generate
        # expects to exist (transformers >= 4.50 sets them lazily during
        # the first generate() call, but parler_tts reads them before
        # calling the parent generate).
        gc = self._model.generation_config
        if gc is not None:
            for _attr, _id_name in (
                ("_pad_token_tensor", "pad_token_id"),
                ("_decoder_start_token_tensor", "decoder_start_token_id"),
                ("_bos_token_tensor", "bos_token_id"),
                ("_eos_token_tensor", "eos_token_id"),
            ):
                if not hasattr(gc, _attr):
                    _id_val = getattr(gc, _id_name, None)
                    setattr(
                        gc,
                        _attr,
                           torch.tensor(_id_val, dtype=torch.long, device=device)
                        if _id_val is not None
                        else None,
                    )
        logger.info(
            "voice-design model loaded generation_config=%s",
            type(self._model.config.generation_config).__name__
            if hasattr(self._model.config, "generation_config")
            else "MISSING",
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
