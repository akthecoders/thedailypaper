"""Generate a Manim explainer video for an already-published paper.

Flow:
  1. Load the paper's explainer markdown from site/src/content/papers/
  2. Ask `video_model` (via llm.call_llm) to produce a Manim CE script
  3. Run `manim -qm` to render
  4. If render fails, feed stderr back into the model and retry (max 3)
  5. Move the final MP4 into site/public/videos/<safe_id>.mp4

Run:
    python agent/generate_video.py <arxiv_id> [--quality l|m|h]

Requires `manim` and a LaTeX distro (e.g. TeX Live) on the host.
"""
from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config_loader import load_config, REPO_ROOT
from llm import call_llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


MANIM_PROMPT = """You are generating a Manim Community Edition (v0.18+) Python script that renders a short technical explainer video for a research paper. The script must produce a single `Scene` subclass named `Explainer` that compiles cleanly with `manim -qm`.

# Paper context

Title: {title}
arXiv: {arxiv_id}
TL;DR: {tldr}
Hook: {hook}

# Source material

Below are extracted sections from the paper's explainer. Use them to drive the video — do not invent claims not supported here.

---
{excerpt}
---

# Hard requirements

1. **Scene name must be `Explainer`** (e.g. `class Explainer(Scene):`).
2. Target runtime: **60–90 seconds**, 5–7 beats:
   - Title + author beat (~5s)
   - Problem statement beat (~15s)
   - Core idea / intuition beat (~15s)
   - Key equation or algorithm beat with math animation (~20s)
   - Result beat (~10s)
   - Closing tagline / URL (~5s)
3. Use **only vanilla Manim CE classes**: `Text`, `Tex`, `MathTex`, `VGroup`, `Rectangle`, `Arrow`, `Line`, `Dot`, `Circle`, `Write`, `Create`, `Transform`, `FadeIn`, `FadeOut`, `ReplacementTransform`.
4. **Do not import anything beyond `from manim import *`** and standard library.
5. Every `Tex`/`MathTex` must compile with a vanilla TeX Live install — no custom packages. Stick to `\\frac`, `\\sum`, `\\int`, `\\mathbb{{}}`, `\\mathcal{{}}`, `\\hat{{}}`, and standard operators. Escape braces in Python strings (`\\{{` and `\\}}` or use raw strings `r"..."`).
6. Keep text short. Use at most ~8 words on screen at a time. Wrap with `Text(...).scale(0.6)` if needed.
7. Position elements with `.to_edge(UP)`, `.next_to(...)`, or `.move_to(ORIGIN)` — do not hardcode coordinates.
8. Use `self.wait(seconds)` between beats, total wait time should sum to roughly 60–90s.
9. **No external assets** — no images, no SVGs, no audio.
10. End with `self.wait(1)` after the last element.

# Quality guidance

- Prefer one tight animation over many cluttered ones.
- For the equation beat, `Write` the equation, then `ReplacementTransform` highlights or annotations — do not just stack static text.
- Colors: use `BLUE`, `YELLOW`, `GREEN`, `RED`, `WHITE`, `GREY_B`. No hex.
- Keep the camera static (no `MovingCameraScene`).

Output ONLY the Python code — no markdown fences, no explanation, no preamble. The file will be written to disk and run directly.
"""


FIX_PROMPT = """Your previous Manim script failed to render. Fix it.

# The error
```
{error}
```

# Your previous script
```python
{prev_script}
```

Output ONLY the corrected Python code — no markdown fences, no explanation. Keep the `Explainer` scene name. Fix the specific error above without changing the overall structure more than necessary. Do not introduce new external packages or external assets.
"""


def _safe_id(arxiv_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", arxiv_id)


def _find_paper_md(arxiv_id: str) -> Path:
    """Locate site/src/content/papers/*-<arxiv_id>.md for the given ID."""
    papers_dir = REPO_ROOT / "site" / "src" / "content" / "papers"
    matches = list(papers_dir.glob(f"*-{arxiv_id}.md"))
    if not matches:
        raise FileNotFoundError(
            f"No paper markdown found for arxiv_id={arxiv_id} in {papers_dir}. "
            "Run the daily agent first, or check that arxiv_id matches the filename."
        )
    return matches[0]


def _parse_paper_md(path: Path) -> dict:
    """Return {title, arxiv_id, tldr, hook, body} from a paper markdown."""
    text = path.read_text()
    fm_match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not fm_match:
        raise ValueError(f"No YAML frontmatter in {path}")
    fm_raw, body = fm_match.group(1), fm_match.group(2)
    fm: dict = {}
    for line in fm_raw.splitlines():
        m = re.match(r'^([a-zA-Z]+):\s*"?(.*?)"?\s*$', line)
        if m:
            fm[m.group(1)] = m.group(2)
    return {
        "title": fm.get("title", "Untitled"),
        "arxiv_id": fm.get("arxivId", ""),
        "tldr": fm.get("tldr", ""),
        "hook": fm.get("hook", ""),
        "body": body,
    }


def _build_excerpt(body: str, max_chars: int = 6000) -> str:
    """Extract TL;DR, core idea, method, results sections for the LLM prompt."""
    wanted_headings = {
        "tl;dr", "tldr",
        "why this matters",
        "the core idea", "core idea",
        "the method", "method",
        "results",
        "key equations",
    }
    sections: list[str] = []
    current_header = None
    current_lines: list[str] = []

    for line in body.splitlines():
        h = re.match(r"^##+\s+(.*)$", line)
        if h:
            if current_header and current_header.lower().strip() in wanted_headings:
                sections.append(f"## {current_header}\n" + "\n".join(current_lines).strip())
            current_header = h.group(1)
            current_lines = []
        else:
            current_lines.append(line)
    if current_header and current_header.lower().strip() in wanted_headings:
        sections.append(f"## {current_header}\n" + "\n".join(current_lines).strip())

    excerpt = "\n\n".join(sections) or body
    return excerpt[:max_chars]


def _strip_code_fences(raw: str) -> str:
    """LLMs occasionally wrap in ```python ... ``` despite the prompt."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()


def _render(script_path: Path, out_dir: Path, quality: str) -> tuple[bool, str, Path | None]:
    """Run `manim`. Returns (ok, combined_output, mp4_path_or_None)."""
    if shutil.which("manim") is None:
        raise RuntimeError(
            "`manim` not found on PATH. Install with: pip install manim "
            "(also requires a LaTeX distribution — TeX Live on Linux/macOS)."
        )
    q_flag = {"l": "-ql", "m": "-qm", "h": "-qh"}.get(quality, "-qm")
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"manim {q_flag} {script_path.name} Explainer (media_dir={out_dir})")
    proc = subprocess.run(
        ["manim", q_flag, "--media_dir", str(out_dir), str(script_path), "Explainer"],
        capture_output=True,
        text=True,
        timeout=900,  # 15 min per render attempt
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        return False, combined, None
    # Manim writes to media/videos/<script_stem>/<quality>/Explainer.mp4
    mp4_candidates = list(out_dir.rglob("Explainer.mp4"))
    if not mp4_candidates:
        return False, combined + "\n[no MP4 produced]", None
    mp4 = max(mp4_candidates, key=lambda p: p.stat().st_mtime)
    return True, combined, mp4


def generate_video(
    arxiv_id: str,
    model: str | None = None,
    quality: str = "m",
    max_retries: int = 3,
) -> Path:
    """Generate a Manim explainer video for a published paper.

    Returns the path to the final MP4 inside site/public/videos/.
    Raises RuntimeError if all attempts fail.
    """
    cfg = load_config()
    model = model or cfg["video_model"]
    log.info(f"Video model: {model}")

    md_path = _find_paper_md(arxiv_id)
    log.info(f"Paper: {md_path.relative_to(REPO_ROOT)}")
    paper = _parse_paper_md(md_path)
    excerpt = _build_excerpt(paper["body"])
    log.info(f"Excerpt: {len(excerpt)} chars passed to {model}")

    workdir = REPO_ROOT / ".video-work" / _safe_id(arxiv_id)
    workdir.mkdir(parents=True, exist_ok=True)

    script_path = workdir / "explainer.py"
    last_error = ""

    prompt = MANIM_PROMPT.format(
        title=paper["title"],
        arxiv_id=paper["arxiv_id"],
        tldr=paper["tldr"],
        hook=paper["hook"],
        excerpt=excerpt,
    )

    for attempt in range(1, max_retries + 1):
        log.info(f"Attempt {attempt}/{max_retries}: asking {model} for Manim script")
        if attempt == 1:
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = [{"role": "user", "content": FIX_PROMPT.format(
                error=last_error[-4000:],  # tail of error usually has the root cause
                prev_script=script_path.read_text(),
            )}]
        raw = call_llm(model=model, messages=messages, max_tokens=8000)
        script = _strip_code_fences(raw)
        script_path.write_text(script)
        log.info(f"Wrote {len(script)} chars to {script_path.relative_to(REPO_ROOT)}")

        ok, output, mp4 = _render(script_path, workdir / "media", quality)
        if ok and mp4:
            videos_dir = REPO_ROOT / "site" / "public" / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)
            final_path = videos_dir / f"{_safe_id(arxiv_id)}.mp4"
            shutil.copy2(mp4, final_path)
            log.info(f"✅ Rendered → {final_path.relative_to(REPO_ROOT)} ({final_path.stat().st_size // 1024} KB)")
            return final_path

        last_error = output
        log.warning(f"Render failed on attempt {attempt}. Tail of error:\n{output[-600:]}")

    raise RuntimeError(
        f"All {max_retries} render attempts failed for {arxiv_id}. "
        f"Last error (tail):\n{last_error[-1500:]}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("arxiv_id", help="arXiv ID of an already-published paper, e.g. 2604.14885")
    parser.add_argument("--quality", choices=["l", "m", "h"], default="m",
                        help="Manim quality preset: l=480p (fast), m=720p (default), h=1080p")
    parser.add_argument("--retries", type=int, default=3, help="Max render retries")
    args = parser.parse_args()

    try:
        out = generate_video(args.arxiv_id, quality=args.quality, max_retries=args.retries)
        print(out)
        return 0
    except Exception as e:
        log.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
