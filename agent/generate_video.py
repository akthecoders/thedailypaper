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


MANIM_PROMPT = """You are writing a Manim Community Edition (v0.18+) Python script that renders a long, substantive research paper explainer. Target a 5–10 minute video (300–600 seconds of animation) that actually teaches the method — not a teaser, not a highlight reel.

The script must produce a single `Scene` subclass named `Explainer` that compiles cleanly with `manim -qm`.

# Paper context

Title: {title}
arXiv: {arxiv_id}
TL;DR: {tldr}
Hook: {hook}

# Source material

Below are extracted sections from the paper's explainer. Use them as the substantive source — do not invent claims not supported here. Extract the real equations, real numbers, real failure modes. Do not summarize into platitudes.

---
{excerpt}
---

# What this video must be

A **5–10 minute technical explainer** that a strong ML/SWE reader would rewatch for the visual derivation. It should feel like a whiteboard walkthrough, not a LinkedIn promo. Specifically:

- **No generic intro** beyond a 3–5s title card (title + arxiv id).
- **No "thanks for watching"**, no URLs, no "reference", no outro animation. End on the last substantive frame with a 2s hold.
- **Every beat teaches.** If a beat exists only for polish or transition, cut it.

# Structural plan (aim for this — adjust chapter count to fit the paper)

1. **Title card** (3–5s) — title + arxiv id, nothing else.
2. **The problem** (45–75s) — show *concretely* what breaks in the status quo. Use a diagram (boxes + arrows) or a small worked example. Name the specific failure mode with a number if the paper gives one.
3. **Background setup** (45–75s) — the 2–3 prior works this builds on. One-line visual identity per prior work (a box with its name + key idea + its specific limitation), then group them to show the landscape.
4. **Core idea** (60–90s) — the central insight in one visual metaphor. Build it up in pieces with `FadeIn` / `Transform`. The viewer should be able to pause here and explain the paper in one sentence.
5. **Method part 1** (60–90s) — first technical component. Use `MathTex` to write the key equation, then `Transform` or `ReplacementTransform` to derive / simplify / annotate terms. Color-code variables. Show a concrete numeric example if the paper has one.
6. **Method part 2** (60–90s) — second technical component. Same visual discipline. Often this is the algorithm's loop or the loss function.
7. **How it fits together** (45–75s) — unified diagram showing parts 1 and 2 combined. Use `VGroup` to re-arrange previously shown boxes into the final pipeline.
8. **Key result** (45–60s) — visualize the main quantitative gain. Show a bar chart built with `Rectangle`s + labels, or a before/after comparison. Put real numbers from the paper.
9. **Honest scope** (20–40s) — one ablation or limitation. Don't omit: it makes the video credible.
10. *(Optional)* **Decision heuristic** (15–30s) — one sentence on when a reader would and wouldn't use this method.

Total `self.wait(...)` + animation run_time should sum to **300–600 seconds**. Aim for the middle (~420s / 7 min).

# Hard requirements

1. **Scene class name is `Explainer`**.
2. **Only** these Manim classes: `Text`, `Tex`, `MathTex`, `VGroup`, `Rectangle`, `RoundedRectangle`, `Square`, `Circle`, `Arrow`, `DoubleArrow`, `Line`, `Dot`, `Write`, `Create`, `Transform`, `ReplacementTransform`, `FadeIn`, `FadeOut`, `Indicate`, `Flash`, `Brace`, `SurroundingRectangle`, `NumberLine`.
3. `from manim import *` — no other imports except standard library (`math`, `itertools`). No `numpy` unless essential.
4. `MathTex` must compile with vanilla TeX Live + dvisvgm. Allowed: `\\frac`, `\\sum`, `\\int`, `\\prod`, `\\mathbb{{}}`, `\\mathcal{{}}`, `\\hat{{}}`, `\\bar{{}}`, `\\tilde{{}}`, `\\vec{{}}`, `\\arg\\max`, `\\arg\\min`, `\\log`, `\\ln`, `\\exp`, `\\leq`, `\\geq`, `\\neq`, `\\approx`, `\\cdot`, `\\times`, `\\to`, `\\in`, `\\subset`, `\\partial`, `\\nabla`, Greek letters, subscripts, superscripts. **No `\\text` macros inside `MathTex`** — use `Tex` or `Text` for words. **Escape Python braces** with `{{` and `}}` or use raw strings.
5. **Color discipline:** define at the top of the Scene:
   ```
   PALETTE = {{'primary': BLUE, 'accent': YELLOW, 'ok': GREEN, 'bad': RED, 'muted': GREY_B}}
   ```
   and reuse those 5 colors throughout. Same concept = same color across scenes.
6. **Text readability:** body `Text(...).scale(0.55)` max, chapter headings `Text(...).scale(0.8)`. `MathTex(...)` keep default scale unless it overflows.
7. **Position with layout primitives**: `.to_edge(UP/DOWN/LEFT/RIGHT, buff=0.7)`, `.next_to(other, direction, buff=0.4)`, `VGroup(...).arrange(RIGHT, buff=0.5)`. Do not hardcode coordinates unless essential.
8. **Clear between chapters:** at the end of each chapter, `FadeOut` or `ReplacementTransform` stale elements before introducing the next chapter's anchor object. The screen should not carry leftover text across chapter boundaries.
9. **Camera is static** — no `MovingCameraScene`.
10. **No external assets** — no images, audio, SVG, LaTeX packages beyond the above.
11. End with `self.wait(2)` after the last substantive element. **No closing text card.**

# Animation density expectations

- On-screen at any time: ≥3 visual elements after the 15s mark (title card alone is fine up to that point).
- Equations should be **animated**: `Write` to introduce, then `ReplacementTransform` to show at least one derivation step or annotation per equation.
- Diagrams should be **assembled**, not dropped: add boxes/arrows piece by piece with `Create`, `FadeIn`.
- Every `self.wait(t)` beyond 3s should be justified by something visually changing — either a label update, a color highlight via `Indicate`, or a `Transform`.

# Anti-patterns — DO NOT DO THESE

- Single static title card that lingers >5s.
- Long lists of bullet-point `Text` lines (this isn't a slideshow).
- "Introduction" or "Outro" or "Thanks for watching" slides.
- Repeating the TL;DR at the end.
- Adding arxiv/pdf URLs as on-screen text.
- Showing tables with >4 rows (use bar chart diagrams instead).
- Pauses longer than 5 seconds without visual change.

# Output format — STRICTLY follow this

Output exactly two blocks, in this order, with the literal separator lines shown below. No markdown fences, no prose outside the narration texts, no preamble.

```
===MANIM===
<the full Python script — must start with "from manim import *", end with "self.wait(2)">
===NARRATION===
<a JSON array of narration segments — see below>
===END===
```

# Narration JSON schema

Every segment matches one `self.wait(T)` block in your Manim script. Populate the `t_start` field as the cumulative seconds elapsed since the video began, at the moment the corresponding chapter starts showing visually.

```
[
  {{"scene": 1, "chapter": "title", "t_start": 0.0, "duration": 5.0, "text": "narrator text here"}},
  {{"scene": 2, "chapter": "the_problem", "t_start": 5.0, "duration": 60.0, "text": "..."}},
  ...
]
```

# Narration rules — critical for audio/video sync

The TTS (Piper, `en_GB-alan-medium`) speaks at ~170 words per minute = **2.8 words/second**. Narration that's too short leaves awkward silence; too long bleeds into the next chapter. Target **90% coverage of scene duration**.

1. **Word budget per segment = `round(duration × 2.8 × 0.90)`**. Concrete examples you MUST hit:

   | Scene duration | Target words | What that looks like |
   |---|---|---|
   | 5 s (title) | 12–14 words | one short sentence, no more |
   | 15 s | 36–38 words | 2 short sentences |
   | 30 s | 74–76 words | 3–4 sentences |
   | 45 s | 112–114 words | 5–6 sentences |
   | 60 s | 150–152 words | one tight paragraph |
   | 75 s | 188–190 words | dense paragraph with 1 concrete example |
   | 90 s | 226–228 words | dense paragraph with numeric detail |

   Undershooting by more than 10% creates silence you'll hear. Count your words before finalizing each segment.

2. Narration text is plain English. **No markdown, no LaTeX.** If an equation is on screen, refer to it verbally ("the ratio of accepted tokens to total drafted tokens"), not typographically ("sum from i equals 1 to N").
3. `t_start` values must be strictly increasing. `t_start + duration` of segment N must equal `t_start` of segment N+1 (or the video end).
4. Every Manim chapter (title, problem, background, core idea, method part 1, method part 2, how-it-fits-together, key result, honest scope) gets exactly one narration segment.
5. The title segment narration is **exactly one sentence, 12 words or fewer** — the paper's headline claim in the narrator's own words. Do NOT read the arxiv id aloud.
6. The last narration segment ends on a substantive claim — no "thanks for watching", no "in this video we learned".

Output nothing outside the three-block structure above. The parser will fail on any extra text.
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


def _build_excerpt(body: str, max_chars: int = 18000) -> str:
    """Extract TL;DR, core idea, method, results sections for the LLM prompt."""
    wanted_headings = {
        "tl;dr", "tldr",
        "why this matters",
        "background",
        "the core idea", "core idea",
        "the method", "method",
        "architecture",
        "results",
        "limitations",
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


def _parse_llm_output(raw: str) -> tuple[str, list[dict]]:
    """Split LLM output into (manim_script, narration_segments).

    Expected shape:
        ===MANIM===
        <python>
        ===NARRATION===
        [ {scene, chapter, t_start, duration, text}, ... ]
        ===END===

    If narration block is missing/invalid, returns (script, []) — caller can
    still render a silent MP4.
    """
    import json as _json

    s = raw.strip()
    # Tolerate leading markdown fences if the model slips.
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
        s = s.strip()

    # Split blocks.
    manim_match = re.search(r"===MANIM===\s*\n(.*?)\n===NARRATION===", s, re.DOTALL)
    narr_match = re.search(r"===NARRATION===\s*\n(.*?)\n===END===", s, re.DOTALL)

    if not manim_match:
        # Fallback: no delimiters at all — treat the whole thing as the Manim script.
        return _strip_code_fences(s), []

    script = manim_match.group(1).strip()
    # The script itself might still have stray fences.
    if script.startswith("```"):
        script = _strip_code_fences(script)

    segments: list[dict] = []
    if narr_match:
        narr_raw = narr_match.group(1).strip()
        if narr_raw.startswith("```"):
            narr_raw = _strip_code_fences(narr_raw)
        try:
            parsed = _json.loads(narr_raw)
            if isinstance(parsed, list):
                for seg in parsed:
                    if all(k in seg for k in ("t_start", "duration", "text")):
                        segments.append({
                            "scene": seg.get("scene"),
                            "chapter": seg.get("chapter", ""),
                            "t_start": float(seg["t_start"]),
                            "duration": float(seg["duration"]),
                            "text": str(seg["text"]).strip(),
                        })
        except Exception as e:
            log.warning(f"Narration JSON parse failed: {e}")

    return script, segments


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
        raw = call_llm(model=model, messages=messages, max_tokens=20000)
        script, segments = _parse_llm_output(raw)
        script_path.write_text(script)
        narration_path = workdir / "narration.json"
        narration_path.write_text(__import__("json").dumps(segments, indent=2))
        log.info(
            f"Wrote {len(script)} chars of Manim + {len(segments)} narration segments"
        )

        ok, output, mp4 = _render(script_path, workdir / "media", quality)
        if ok and mp4:
            videos_dir = REPO_ROOT / "site" / "public" / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)
            final_path = videos_dir / f"{_safe_id(arxiv_id)}.mp4"
            shutil.copy2(mp4, final_path)
            log.info(f"✅ Rendered silent MP4 → {final_path.relative_to(REPO_ROOT)} ({final_path.stat().st_size // 1024} KB)")
            # Hand off to narrator if we have narration.
            if segments:
                try:
                    from narrate_video import narrate_and_mux
                    narrate_and_mux(
                        silent_mp4=final_path,
                        segments=segments,
                        voice=cfg.get("narration_voice", "en_GB-alan-medium"),
                        workdir=workdir,
                    )
                    log.info(f"✅ Narrated MP4 → {final_path.relative_to(REPO_ROOT)} ({final_path.stat().st_size // 1024} KB)")
                except Exception as e:
                    log.warning(f"Narration failed, keeping silent MP4: {e}")
            else:
                log.warning("No narration segments — MP4 will be silent")
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
