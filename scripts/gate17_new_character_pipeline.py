#!/usr/bin/env python3
"""NEW CHARACTER PIPELINE GATE: Parler (isolated) → refs → Qwen3-TTS."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert importlib.util.find_spec("fish_speech") is None, "fish-speech must be absent"

    out = Path(tempfile.mkdtemp(prefix="gate17-newchar-"))
    ref_dir = out / "character_novo"
    ref_dir.mkdir(parents=True)
    parler_py = ROOT / ".venv-parler" / "bin" / "python"
    assert parler_py.is_file(), f"missing {parler_py}; run scripts/bootstrap_parler_venv.sh"

    parler_script = ROOT / "scripts" / "_gate17_parler_gen.py"
    parler_script.write_text(
        '''\
import json
import sys
from pathlib import Path

import soundfile as sf
import torch
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer

out_dir = Path(sys.argv[1])
passage = (
    "Naquela manhã ensolarada, o vento trazia o cheiro do mar até as ruas estreitas."
)
desc = "Um homem adulto brasileiro, voz grave, clara e calma, sotaque do sudeste."
device = "cuda:0"
model_id = "freds0/parler-tts-mini-v1.1-ptbr"
print("transformers", __import__("transformers").__version__, flush=True)
model = ParlerTTSForConditionalGeneration.from_pretrained(model_id).to(device)
tok = AutoTokenizer.from_pretrained("parler-tts/parler-tts-mini-multilingual")
desc_tok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
input_ids = desc_tok(desc, return_tensors="pt").input_ids.to(device)
prompt_ids = tok(passage, return_tensors="pt").input_ids.to(device)
with torch.no_grad():
    gen = model.generate(input_ids=input_ids, prompt_input_ids=prompt_ids)
audio = gen.cpu().numpy().squeeze()
sr = int(model.config.sampling_rate)
max_samples = int(6.0 * sr)
if audio.shape[-1] > max_samples:
    audio = audio[..., :max_samples]
wav = out_dir / "reference.wav"
txt = out_dir / "reference.txt"
sf.write(str(wav), audio, sr)
txt.write_text(passage, encoding="utf-8")
(out_dir / "metadata.json").write_text(
    json.dumps(
        {"language": "pt-BR", "generator": "parler", "model_id": model_id},
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
print("PARLER_OK", wav, "sr", sr, "samples", audio.shape, flush=True)
del model
torch.cuda.empty_cache()
''',
        encoding="utf-8",
    )

    env = {k: v for k, v in __import__("os").environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    print("=== Phase 1: Parler (isolated) ===", flush=True)
    r1 = subprocess.run(
        [str(parler_py), str(parler_script), str(ref_dir)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    print(r1.stdout[-3000:] if r1.stdout else "")
    if r1.returncode != 0:
        print(r1.stderr[-4000:] if r1.stderr else "")
        raise SystemExit(f"Parler phase failed code={r1.returncode}")

    ref_wav = ref_dir / "reference.wav"
    ref_txt = ref_dir / "reference.txt"
    assert ref_wav.is_file() and ref_wav.stat().st_size > 1000, ref_wav
    passage = ref_txt.read_text(encoding="utf-8").strip()
    print("ref ready", ref_wav, ref_wav.stat().st_size, "bytes")

    print("=== Phase 2: Qwen3-TTS Voice Clone ===", flush=True)
    import torch
    import soundfile as sf
    from audiobook_ai.weights.manager import ModelManager
    from audiobook_ai.weights.qwen3_tts import QWEN3_TTS_ID
    from qwen_tts import Qwen3TTSModel

    free_before = torch.cuda.mem_get_info()[0] // (1024 * 1024)
    print("VRAM before load", free_before, "MiB")
    handle = ModelManager().ensure_model(QWEN3_TTS_ID)
    tts = Qwen3TTSModel.from_pretrained(
        str(handle.path), device_map="cuda:0", dtype=torch.bfloat16
    )
    free_after_load = torch.cuda.mem_get_info()[0] // (1024 * 1024)
    wavs, sr = tts.generate_voice_clone(
        text="Olá, sou um personagem novo gerado pelo Parler e clonado pelo Qwen3-TTS.",
        language="Portuguese",
        ref_audio=str(ref_wav),
        ref_text=passage,
    )
    free_after_gen = torch.cuda.mem_get_info()[0] // (1024 * 1024)
    clone = out / "clone.wav"
    sf.write(str(clone), wavs[0], sr)
    assert clone.stat().st_size > 1000
    del tts
    torch.cuda.empty_cache()
    free_after_rel = torch.cuda.mem_get_info()[0] // (1024 * 1024)

    report = {
        "gate": "NEW CHARACTER PIPELINE GATE",
        "result": "PASS",
        "fish_speech": "absent",
        "parler_python": str(parler_py),
        "parler_transformers": "4.46.1",
        "tts_transformers": __import__("transformers").__version__,
        "ref_wav": str(ref_wav),
        "clone_wav": str(clone),
        "vram_mib": {
            "before_load": free_before,
            "after_load": free_after_load,
            "after_gen": free_after_gen,
            "after_release": free_after_rel,
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("NEW CHARACTER PIPELINE GATE: PASS")
    print("artifacts", out)


if __name__ == "__main__":
    main()
