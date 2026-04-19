"""Add narration audio to a silent Manim MP4, synced to chapter timestamps.

Pipeline:
  1. For each narration segment: synthesize speech with Piper (open, CPU-only TTS).
  2. Compare TTS actual duration vs scene duration from the LLM:
       - shorter → pad with silence at the end of the segment
       - slightly longer (≤15%) → compress with ffmpeg atempo
       - much longer → accept overflow into next scene (log a warning)
  3. Concatenate all segments into a single audio track with gap silence where needed.
  4. Mux the audio into the MP4 via ffmpeg.

Called from generate_video.py after a successful Manim render. Can also be run
stand-alone for re-narration:
    python agent/narrate_video.py <arxiv_id> [--voice en_GB-alan-medium]
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from config_loader import REPO_ROOT

log = logging.getLogger(__name__)

# --- Piper voice management -------------------------------------------------

PIPER_VOICE_URLS = {
    # Each voice requires both the .onnx model and its .json config.
    # Hosted by the Piper project on HuggingFace.
    "en_GB-alan-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json",
    ),
    "en_US-ryan-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json",
    ),
    "en_US-lessac-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    ),
    "en_US-amy-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
    ),
}


def _ensure_voice(voice: str) -> Path:
    """Download voice model if not already cached in REPO_ROOT/.piper-voices/."""
    if voice not in PIPER_VOICE_URLS:
        raise RuntimeError(
            f"Unknown Piper voice '{voice}'. Supported: {list(PIPER_VOICE_URLS)}"
        )
    voices_dir = REPO_ROOT / ".piper-voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    model_path = voices_dir / f"{voice}.onnx"
    config_path = voices_dir / f"{voice}.onnx.json"
    if model_path.exists() and config_path.exists():
        return model_path

    import urllib.request
    model_url, config_url = PIPER_VOICE_URLS[voice]
    log.info(f"Downloading Piper voice model: {voice}")
    urllib.request.urlretrieve(model_url, model_path)
    urllib.request.urlretrieve(config_url, config_path)
    log.info(f"Voice cached at {model_path.relative_to(REPO_ROOT)}")
    return model_path


# --- ffmpeg helpers ---------------------------------------------------------

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({' '.join(cmd[:3])}...): {proc.stderr[-500:]}"
        )
    return proc


def _probe_duration(audio_path: Path) -> float:
    proc = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
    ])
    return float(proc.stdout.strip())


def _silence(seconds: float, out: Path, sample_rate: int = 22050) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl=mono",
        "-t", f"{seconds:.3f}",
        "-q:a", "9", "-acodec", "libmp3lame",
        str(out),
    ])


def _atempo(in_path: Path, out_path: Path, ratio: float) -> None:
    """Speed up audio by `ratio` (>1 = faster). ffmpeg's atempo clamps to 0.5–100.
    For our range (1.0–1.15) one pass is fine."""
    _run([
        "ffmpeg", "-y", "-i", str(in_path),
        "-filter:a", f"atempo={ratio:.4f}",
        "-q:a", "9", str(out_path),
    ])


# --- Piper synthesis --------------------------------------------------------

def _piper_synthesize(text: str, voice_model: Path, out_path: Path) -> None:
    """Run piper CLI to synthesize `text` into a WAV at `out_path`."""
    if shutil.which("piper") is None:
        raise RuntimeError(
            "`piper` not found on PATH. Install: pip install piper-tts"
        )
    # piper reads text on stdin, writes WAV on --output_file.
    proc = subprocess.run(
        ["piper", "--model", str(voice_model), "--output_file", str(out_path)],
        input=text,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Piper failed: {proc.stderr[-500:]}")


# --- Main alignment logic ---------------------------------------------------

def narrate_and_mux(
    silent_mp4: Path,
    segments: list[dict],
    voice: str,
    workdir: Path,
) -> Path:
    """Rebuild `silent_mp4` with narration audio track. Overwrites in place."""
    if not segments:
        log.info("No narration segments; leaving MP4 silent.")
        return silent_mp4

    voice_model = _ensure_voice(voice)
    audio_dir = workdir / "audio"
    audio_dir.mkdir(exist_ok=True)

    # Probe video to know total duration — we clip audio to this.
    video_duration = _probe_duration(silent_mp4)
    log.info(f"Silent video duration: {video_duration:.2f}s, aligning {len(segments)} segments")

    # Synthesize each segment, then adjust to its target duration.
    aligned_segments: list[Path] = []
    for i, seg in enumerate(segments):
        raw_wav = audio_dir / f"seg_{i:02d}_raw.wav"
        aligned = audio_dir / f"seg_{i:02d}_aligned.mp3"

        _piper_synthesize(seg["text"], voice_model, raw_wav)
        tts_dur = _probe_duration(raw_wav)
        target = float(seg["duration"])
        log.info(
            f"  seg {i+1}/{len(segments)} [{seg.get('chapter','?')}] "
            f"tts={tts_dur:.2f}s target={target:.2f}s "
            f"ratio={tts_dur/target:.2f}"
        )

        if tts_dur <= target:
            # Pad with silence at the end.
            pad = audio_dir / f"seg_{i:02d}_pad.mp3"
            _silence(max(0.01, target - tts_dur), pad)
            list_file = audio_dir / f"seg_{i:02d}_concat.txt"
            list_file.write_text(f"file '{raw_wav.resolve()}'\nfile '{pad.resolve()}'\n")
            _run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c:a", "libmp3lame", "-q:a", "9",
                str(aligned),
            ])
        else:
            ratio = tts_dur / target
            if ratio <= 1.15:
                _atempo(raw_wav, aligned, ratio)
            else:
                log.warning(
                    f"Segment {i+1} narration is {ratio:.2f}× too long; "
                    "accepting overflow. Consider shorter narration in prompt."
                )
                _atempo(raw_wav, aligned, min(ratio, 1.5))

        aligned_segments.append(aligned)

    # Concatenate all aligned segments into one audio track matching video duration.
    full_audio = workdir / "narration_full.mp3"
    list_file = workdir / "narration_concat.txt"
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in aligned_segments))
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:a", "libmp3lame", "-q:a", "5",
        str(full_audio),
    ])

    # Mux into video. -shortest clips audio to video length; -t ensures we
    # don't create a longer output than the silent video.
    muxed = workdir / "narrated.mp4"
    _run([
        "ffmpeg", "-y",
        "-i", str(silent_mp4),
        "-i", str(full_audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-t", f"{video_duration:.3f}",
        "-movflags", "+faststart",
        str(muxed),
    ])

    # Overwrite the original silent MP4 with the narrated one.
    shutil.copy2(muxed, silent_mp4)
    return silent_mp4


# --- Stand-alone entry ------------------------------------------------------

def _find_paper_mp4(arxiv_id: str) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in arxiv_id)
    p = REPO_ROOT / "site" / "public" / "videos" / f"{safe}.mp4"
    if not p.exists():
        raise FileNotFoundError(
            f"No silent MP4 at {p}. Run `python agent/generate_video.py {arxiv_id}` first."
        )
    return p


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("arxiv_id")
    parser.add_argument("--voice", default="en_GB-alan-medium",
                        choices=list(PIPER_VOICE_URLS))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    safe = "".join(c if c.isalnum() else "_" for c in args.arxiv_id)
    workdir = REPO_ROOT / ".video-work" / safe
    narration_path = workdir / "narration.json"
    if not narration_path.exists():
        log.error(f"No narration JSON at {narration_path}.")
        return 1
    segments = json.loads(narration_path.read_text())
    silent_mp4 = _find_paper_mp4(args.arxiv_id)

    narrate_and_mux(silent_mp4, segments, args.voice, workdir)
    log.info(f"Narrated MP4 at {silent_mp4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
