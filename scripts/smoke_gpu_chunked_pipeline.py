#!/usr/bin/env python3
"""Empirical RX 7900 XTX smoke for gpu-memory-safe-chunked-pipeline (tasks 7.1–7.5).

Runs generate with VRAM telemetry, forces mid-Fish interrupt + resume, then
writes a JSON report under the work dir for calibration evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from audiobook_ai import config

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class VramSample:
    t: float
    free_mib: float | None
    used_mib: float | None
    total_mib: float | None
    note: str = ""


@dataclass
class SmokeReport:
    started_at: str
    finished_at: str | None = None
    pdf: str = ""
    work_dir: str = ""
    book_id: str | None = None
    exit_code_phase1: int | None = None
    exit_code_phase2: int | None = None
    interrupted_after_chunks: int | None = None
    samples: list[dict] = field(default_factory=list)
    gpu_log_events: list[str] = field(default_factory=list)
    manifest_summary: dict = field(default_factory=dict)
    min_free_mib: float | None = None
    hard_floor_mib: int = 300
    fish_before_load_target_mib: int = config.FISH_BEFORE_LOAD_TARGET_MIB
    parler_before_load_target_mib: int = config.PARLER_BEFORE_LOAD_TARGET_MIB
    tts_max_chunk_chars: int = config.TTS_MAX_CHUNK_CHARS
    progressive_k: int = 3
    progressive_n: int = 256
    hyprland_note: str = "observer: confirm compositor stayed responsive during run"
    calibration: dict = field(default_factory=dict)
    ok: bool = False
    errors: list[str] = field(default_factory=list)


def _rocm_vram() -> tuple[float | None, float | None, float | None]:
    """Return (free, used, total) MiB from rocm-smi JSON when possible."""
    try:
        proc = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            # Shape varies; walk for total/used bytes-like fields.
            def walk(obj: object) -> dict[str, float]:
                found: dict[str, float] = {}
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        kl = str(k).lower()
                        if isinstance(v, (int, float)):
                            if "total" in kl and "vram" in kl:
                                found["total"] = float(v)
                            elif kl in {"vram total memory (b)", "vram total memory"}:
                                found["total"] = float(v)
                            elif "used" in kl and "vram" in kl:
                                found["used"] = float(v)
                            elif kl in {"vram total used memory (b)", "vram total used memory"}:
                                found["used"] = float(v)
                        else:
                            found.update(walk(v))
                elif isinstance(obj, list):
                    for item in obj:
                        found.update(walk(item))
                return found

            vals = walk(data)
            total = vals.get("total")
            used = vals.get("used")
            if total is not None:
                # rocm-smi JSON often reports bytes
                if total > 100_000:
                    total_mib = total / (1024 * 1024)
                    used_mib = (used or 0) / (1024 * 1024)
                else:
                    total_mib = total
                    used_mib = used or 0
                return total_mib - used_mib, used_mib, total_mib
    except Exception:  # noqa: BLE001
        pass

    # Fallback: concise parse
    try:
        proc = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        text = proc.stdout
        total_m = re.search(r"Total Memory[^0-9]*([0-9]+)", text)
        used_m = re.search(r"Total Used Memory[^0-9]*([0-9]+)", text)
        if total_m and used_m:
            total_b = float(total_m.group(1))
            used_b = float(used_m.group(1))
            total_mib = total_b / (1024 * 1024)
            used_mib = used_b / (1024 * 1024)
            return total_mib - used_mib, used_mib, total_mib
    except Exception:  # noqa: BLE001
        pass
    return None, None, None


class VramMonitor:
    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self.samples: list[VramSample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.min_free: float | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="vram-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def mark(self, note: str) -> None:
        free, used, total = _rocm_vram()
        sample = VramSample(time.time(), free, used, total, note=note)
        self.samples.append(sample)
        if free is not None:
            self.min_free = free if self.min_free is None else min(self.min_free, free)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            free, used, total = _rocm_vram()
            self.samples.append(VramSample(time.time(), free, used, total))
            if free is not None:
                self.min_free = free if self.min_free is None else min(self.min_free, free)


def _find_book_root(work_dir: Path) -> Path | None:
    if not work_dir.is_dir():
        return None
    candidates = [p for p in work_dir.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    if candidates:
        return max(candidates, key=lambda p: (p / "manifest.json").stat().st_mtime)
    # Prefer dirs with story.json (post-interpret, pre-tts)
    with_story = [p for p in work_dir.iterdir() if p.is_dir() and (p / "story.json").exists()]
    if with_story:
        return max(with_story, key=lambda p: (p / "story.json").stat().st_mtime)
    dirs = [p for p in work_dir.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _manifest_completed_count(book_root: Path) -> int:
    path = book_root / "manifest.json"
    if not path.is_file():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return sum(1 for c in data.get("chunks", []) if c.get("status") == "completed")


def _manifest_summary(book_root: Path) -> dict:
    path = book_root / "manifest.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    chunks = data.get("chunks", [])
    by_status: dict[str, int] = {}
    for c in chunks:
        st = c.get("status", "?")
        by_status[st] = by_status.get(st, 0) + 1
    return {
        "chunk_count": len(chunks),
        "by_status": by_status,
        "chunk_ids": [c.get("id") for c in chunks],
        "fingerprint": data.get("chunking_fingerprint") or data.get("fingerprint"),
    }


def _parse_gpu_events(log_path: Path) -> list[str]:
    if not log_path.is_file():
        return []
    lines = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[gpu]" in line:
            lines.append(line)
    return lines


def _mtime_map(audio_dir: Path) -> dict[str, float]:
    if not audio_dir.is_dir():
        return {}
    return {p.name: p.stat().st_mtime for p in audio_dir.glob("*.wav")}


def build_generate_cmd(
    pdf: Path,
    *,
    output: Path,
    work_dir: Path,
    model: str,
    tts_max_chunk_chars: int,
    parler_load: int,
    fish_load: int,
    hard_floor: int,
    before_chunk: int,
) -> list[str]:
    return [
        "uv",
        "run",
        "audiobook-ai",
        "generate",
        str(pdf),
        "--output",
        str(output),
        "--work-dir",
        str(work_dir),
        "--model",
        model,
        "--tts-max-chunk-chars",
        str(tts_max_chunk_chars),
        "--parler-before-load-target-mib",
        str(parler_load),
        "--fish-before-load-target-mib",
        str(fish_load),
        "--hard-floor-mib",
        str(hard_floor),
        "--before-chunk-target-mib",
        str(before_chunk),
    ]


def run_with_interrupt(
    cmd: list[str],
    *,
    cwd: Path,
    work_dir: Path,
    interrupt_after_completed: int,
    monitor: VramMonitor,
    timeout_s: float,
) -> tuple[int, int]:
    """Run generate; interrupt after N completed chunks during Fish. Returns (rc, completed_at_interrupt)."""
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    monitor.mark("phase1_start")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    assert proc.stdout is not None
    completed_at_interrupt = 0
    interrupted = False
    deadline = time.time() + timeout_s
    log_lines: list[str] = []

    def _reader() -> None:
        for line in proc.stdout:
            log_lines.append(line.rstrip())
            print(line, end="")

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    while proc.poll() is None:
        if time.time() > deadline:
            monitor.mark("phase1_timeout_kill")
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=30)
            return 124, completed_at_interrupt

        book_root = _find_book_root(work_dir)
        if book_root is not None:
            n = _manifest_completed_count(book_root)
            if n >= interrupt_after_completed and not interrupted:
                completed_at_interrupt = n
                monitor.mark(f"interrupt_after_{n}_chunks")
                print(
                    f"\n[smoke] Interrupting after {n} completed chunk(s) "
                    f"(SIGTERM process group)…\n",
                    flush=True,
                )
                os.killpg(proc.pid, signal.SIGTERM)
                interrupted = True
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=30)
                break
        time.sleep(0.5)

    reader.join(timeout=5)
    rc = proc.returncode if proc.returncode is not None else -1
    monitor.mark("phase1_end")
    return rc, completed_at_interrupt


def run_to_completion(
    cmd: list[str],
    *,
    cwd: Path,
    monitor: VramMonitor,
    timeout_s: float,
    label: str,
) -> int:
    monitor.mark(f"{label}_start")
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            timeout=timeout_s,
            check=False,
        )
        monitor.mark(f"{label}_end_rc_{proc.returncode}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        monitor.mark(f"{label}_timeout")
        return 124


def calibrate(report: SmokeReport, events: list[str]) -> dict:
    """Derive calibration recommendations from empirical telemetry only."""
    frees = [s["free_mib"] for s in report.samples if s.get("free_mib") is not None]
    min_free = min(frees) if frees else None
    # Free around Parler / Fish load markers
    parler_load_frees = [
        s["free_mib"]
        for s in report.samples
        if s.get("free_mib") is not None and "parler" in (s.get("note") or "").lower()
    ]
    # From [gpu] logs parse free_mib
    load_frees: list[float] = []
    reclaim_frees: list[float] = []
    before_chunk_frees: list[float] = []
    for line in events:
        m = re.search(
            r"\[gpu\].*event=(\S+).*free_mib=([0-9.]+).*allocated_mib=([0-9.]+|None)"
            r".*reserved_mib=([0-9.]+|None)",
            line,
        )
        if not m:
            # looser
            m2 = re.search(r"event=(\S+).*free_mib=([0-9.]+)", line)
            if not m2:
                continue
            event, free_s = m2.group(1), m2.group(2)
            free = float(free_s)
        else:
            event, free_s = m.group(1), m.group(2)
            free = float(free_s)
        if event in {"load", "before_load"}:
            load_frees.append(free)
        if event in {"after_reclaim", "reclaim"}:
            reclaim_frees.append(free)
        if event in {"before_chunk", "can_start_chunk"}:
            before_chunk_frees.append(free)

    progressive_hits = sum(1 for e in events if "progressive_growth" in e)
    oom_hits = sum(1 for e in events if re.search(r"\boom\b", e, re.I))
    controlled_restarts = sum(1 for e in events if "controlled_restart" in e)

    # Parler before_load: keep if load succeeded with current gate; else raise.
    # Empirical: use min free observed just before/during parler phase from samples
    # with margin — only adjust if we have measurements.
    parler_target = report.parler_before_load_target_mib
    fish_target = report.fish_before_load_target_mib
    tts_chars = report.tts_max_chunk_chars
    k, n = report.progressive_k, report.progressive_n

    notes: list[str] = []
    if min_free is not None and min_free < report.hard_floor_mib:
        notes.append(
            f"FAIL: min free {min_free:.1f} MiB below hard floor {report.hard_floor_mib}"
        )
    elif min_free is not None:
        notes.append(f"min free observed {min_free:.1f} MiB (>= hard floor {report.hard_floor_mib})")

    if progressive_hits == 0 and reclaim_frees:
        # No progressive growth — keep K/N
        notes.append(f"no progressive_growth events; keep K={k} N={n}")
    elif progressive_hits:
        notes.append(
            f"progressive_growth events={progressive_hits}; controlled_restarts={controlled_restarts}"
        )

    if oom_hits:
        notes.append(f"unexpected OOM-like log lines={oom_hits}")
    else:
        notes.append("no OOM used as control in logs")

    # Chunk size: if run completed with >=5 chunks and no progressive growth / floor breach,
    # keep empirical value used in smoke.
    chunk_count = report.manifest_summary.get("chunk_count", 0)
    if chunk_count >= 5 and progressive_hits == 0 and (
        min_free is None or min_free >= report.hard_floor_mib
    ):
        notes.append(
            f"tts_max_chunk_chars={tts_chars} held for {chunk_count} chunks without "
            "progressive growth / floor breach — keep"
        )
    elif chunk_count < 5:
        notes.append(f"chunk_count={chunk_count} < 5 — smoke incomplete for sizing")

    # Parler load target: if smoke passed with placeholder, record measured headroom
    # before load from samples marked phase boundaries; do not invent a new number
    # without a measured peak residency.
    if parler_load_frees:
        notes.append(f"parler-related sample frees={parler_load_frees}")

    reclaim_delta = None
    if len(reclaim_frees) >= 2:
        reclaim_delta = reclaim_frees[0] - reclaim_frees[-1]
        notes.append(
            f"reclaim free first={reclaim_frees[0]:.1f} last={reclaim_frees[-1]:.1f} "
            f"delta={reclaim_delta:.1f} MiB over window"
        )

    return {
        "tts_max_chunk_chars": tts_chars,
        "parler_before_load_target_mib": parler_target,
        "fish_before_load_target_mib": fish_target,
        "progressive_window_k": k,
        "progressive_drop_mib": n,
        "min_free_mib": min_free,
        "reclaim_frees_mib": reclaim_frees,
        "before_chunk_frees_mib": before_chunk_frees,
        "load_frees_mib": load_frees,
        "progressive_growth_events": progressive_hits,
        "controlled_restart_events": controlled_restarts,
        "oom_like_events": oom_hits,
        "notes": notes,
        "adjust_knobs": {
            "tts_max_chunk_chars": "keep" if chunk_count >= 5 and progressive_hits == 0 else "review",
            "parler_before_load_target_mib": "keep_if_load_ok_else_raise_from_measured_peak",
            "progressive_k_n": "keep" if progressive_hits == 0 else "review",
            "hard_floor_mib": "unchanged",
            "fish_before_load_target_mib": "unchanged_without_contrary_evidence",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        type=Path,
        default=ROOT / "samples" / "smoke_gpu_chunked.pdf",
    )
    parser.add_argument("--work-dir", type=Path, default=ROOT / "out" / "smoke_gpu")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "out" / "smoke_gpu" / "smoke_gpu_chunked.m4b",
    )
    parser.add_argument("--model", default=config.DEFAULT_OLLAMA_MODEL)
    parser.add_argument(
        "--tts-max-chunk-chars",
        type=int,
        default=config.TTS_MAX_CHUNK_CHARS,
        help=f"SpeechChunk max chars (default {config.TTS_MAX_CHUNK_CHARS} from config)",
    )
    parser.add_argument("--parler-before-load-target-mib", type=int, default=8192)
    parser.add_argument(
        "--fish-before-load-target-mib",
        type=int,
        default=config.FISH_BEFORE_LOAD_TARGET_MIB,
    )
    parser.add_argument("--hard-floor-mib", type=int, default=300)
    parser.add_argument("--before-chunk-target-mib", type=int, default=768)
    parser.add_argument("--interrupt-after-chunks", type=int, default=2)
    parser.add_argument("--phase1-timeout-s", type=float, default=7200)
    parser.add_argument("--phase2-timeout-s", type=float, default=7200)
    parser.add_argument(
        "--skip-interrupt",
        action="store_true",
        help="Run a single uninterrupted generate (no resume validation)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete work-dir book artifacts before starting",
    )
    args = parser.parse_args()

    if not args.pdf.is_file():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    args.work_dir.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        # Remove prior book dirs under work-dir but keep the root
        for child in list(args.work_dir.iterdir()):
            if child.is_dir() and child.name != ".git":
                import shutil

                shutil.rmtree(child)
            elif child.suffix in {".m4b", ".mp3", ".log", ".json"}:
                child.unlink(missing_ok=True)

    report = SmokeReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        pdf=str(args.pdf),
        work_dir=str(args.work_dir),
        hard_floor_mib=args.hard_floor_mib,
        fish_before_load_target_mib=args.fish_before_load_target_mib,
        parler_before_load_target_mib=args.parler_before_load_target_mib,
        tts_max_chunk_chars=args.tts_max_chunk_chars,
    )

    cmd = build_generate_cmd(
        args.pdf,
        output=args.output,
        work_dir=args.work_dir,
        model=args.model,
        tts_max_chunk_chars=args.tts_max_chunk_chars,
        parler_load=args.parler_before_load_target_mib,
        fish_load=args.fish_before_load_target_mib,
        hard_floor=args.hard_floor_mib,
        before_chunk=args.before_chunk_target_mib,
    )
    print("[smoke] command:", " ".join(cmd), flush=True)

    monitor = VramMonitor(interval_s=1.0)
    monitor.start()
    audio_before: dict[str, float] = {}
    try:
        if args.skip_interrupt:
            rc2 = run_to_completion(
                cmd,
                cwd=ROOT,
                monitor=monitor,
                timeout_s=args.phase2_timeout_s,
                label="full",
            )
            report.exit_code_phase2 = rc2
            report.exit_code_phase1 = None
        else:
            rc1, n_int = run_with_interrupt(
                cmd,
                cwd=ROOT,
                work_dir=args.work_dir,
                interrupt_after_completed=args.interrupt_after_chunks,
                monitor=monitor,
                timeout_s=args.phase1_timeout_s,
            )
            report.exit_code_phase1 = rc1
            report.interrupted_after_chunks = n_int
            book_root = _find_book_root(args.work_dir)
            if book_root:
                audio_before = _mtime_map(book_root / "audio")
                print(
                    f"[smoke] After interrupt: completed={_manifest_completed_count(book_root)} "
                    f"wavs={list(audio_before)}",
                    flush=True,
                )
            print("[smoke] Resuming generate (phase 2)…", flush=True)
            rc2 = run_to_completion(
                cmd,
                cwd=ROOT,
                monitor=monitor,
                timeout_s=args.phase2_timeout_s,
                label="phase2_resume",
            )
            report.exit_code_phase2 = rc2
    finally:
        monitor.stop()

    book_root = _find_book_root(args.work_dir)
    if book_root:
        report.book_id = book_root.name
        report.manifest_summary = _manifest_summary(book_root)
        log_path = args.work_dir / "logs" / "generate.log"
        # also book-local logs if any
        alt = book_root / "logs" / "generate.log"
        events = _parse_gpu_events(log_path) + _parse_gpu_events(alt)
        # worker logs
        for lp in (book_root / "logs").glob("*.log") if (book_root / "logs").is_dir() else []:
            events.extend(_parse_gpu_events(lp))
        for lp in (args.work_dir / "logs").glob("*.log") if (args.work_dir / "logs").is_dir() else []:
            events.extend(_parse_gpu_events(lp))
        # de-dupe preserve order
        seen: set[str] = set()
        uniq: list[str] = []
        for e in events:
            if e not in seen:
                seen.add(e)
                uniq.append(e)
        report.gpu_log_events = uniq

        audio_after = _mtime_map(book_root / "audio")
        regenerated = [
            name
            for name, mt in audio_before.items()
            if name in audio_after and audio_after[name] > mt + 0.05
        ]
        resume_info = {
            "wavs_at_interrupt": sorted(audio_before),
            "wavs_final": sorted(audio_after),
            "regenerated": regenerated,
            "ok": (not regenerated) if not args.skip_interrupt else True,
        }
        if regenerated and not args.skip_interrupt:
            report.errors.append(
                f"resume regenerated completed wavs unexpectedly: {regenerated}"
            )
    else:
        resume_info = {"ok": args.skip_interrupt, "wavs_at_interrupt": [], "wavs_final": [], "regenerated": []}

    report.samples = [asdict(s) for s in monitor.samples]
    report.min_free_mib = monitor.min_free
    calib = calibrate(report, report.gpu_log_events)
    calib["resume"] = resume_info
    report.calibration = calib

    chunk_count = report.manifest_summary.get("chunk_count", 0)
    completed = report.manifest_summary.get("by_status", {}).get("completed", 0)
    output_ok = args.output.is_file()
    min_ok = report.min_free_mib is None or report.min_free_mib >= report.hard_floor_mib
    resume_ok = report.calibration.get("resume", {}).get("ok", args.skip_interrupt)
    report.ok = (
        report.exit_code_phase2 == 0
        and output_ok
        and completed >= 5
        and chunk_count >= 5
        and min_ok
        and bool(resume_ok)
        and not report.errors
    )
    if report.exit_code_phase2 != 0:
        report.errors.append(f"phase2 exit_code={report.exit_code_phase2}")
    if not output_ok:
        report.errors.append(f"missing output {args.output}")
    if completed < 5:
        report.errors.append(f"completed chunks={completed} < 5")
    if not min_ok:
        report.errors.append(
            f"min free {report.min_free_mib} < hard floor {report.hard_floor_mib}"
        )

    report.finished_at = datetime.now(timezone.utc).isoformat()
    out_json = args.work_dir / "smoke_report.json"
    out_json.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print(f"\n[smoke] report → {out_json}")
    print(f"[smoke] ok={report.ok} min_free_mib={report.min_free_mib}")
    print(f"[smoke] manifest={report.manifest_summary}")
    for note in report.calibration.get("notes", []):
        print(f"[smoke] calib: {note}")
    for err in report.errors:
        print(f"[smoke] ERROR: {err}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
