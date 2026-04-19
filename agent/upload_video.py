"""Upload a rendered MP4 to Cloudflare R2 and stamp the paper's frontmatter
with the resulting public URL so the static site picks it up on next build.

Run:
    python agent/upload_video.py <arxiv_id> <path/to/local.mp4>

Env:
    R2_ACCOUNT_ID         — Cloudflare account ID
    R2_ACCESS_KEY_ID      — R2 API token access key
    R2_SECRET_ACCESS_KEY  — R2 API token secret
    R2_BUCKET             — bucket name, e.g. "thedailypaper-videos"
    R2_PUBLIC_BASE_URL    — public base URL for the bucket, e.g.
                            "https://pub-<hash>.r2.dev" or a custom domain
                            like "https://videos.thedailypaper.akshaykumar.me"

Requires: boto3 (R2 is S3-compatible).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

from config_loader import REPO_ROOT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def _r2_client():
    for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL"):
        if not os.environ.get(key):
            raise RuntimeError(f"Missing env var: {key}")

    endpoint = f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _find_paper_md(arxiv_id: str) -> Path:
    papers_dir = REPO_ROOT / "site" / "src" / "content" / "papers"
    matches = list(papers_dir.glob(f"*-{arxiv_id}.md"))
    if not matches:
        raise FileNotFoundError(f"No paper .md for arxiv_id={arxiv_id}")
    return matches[0]


def _set_frontmatter_field(md_path: Path, key: str, value: str) -> None:
    """Idempotent frontmatter insert. Adds or replaces `key: "value"`."""
    text = md_path.read_text()
    m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"No frontmatter in {md_path}")
    head, fm, mid, body = m.groups()
    # Replace if exists, else append.
    pattern = re.compile(rf'^{re.escape(key)}:\s*.*$', re.MULTILINE)
    new_line = f'{key}: "{value}"'
    if pattern.search(fm):
        fm_new = pattern.sub(new_line, fm)
    else:
        fm_new = fm.rstrip() + "\n" + new_line
    md_path.write_text(head + fm_new + mid + body)


def upload(arxiv_id: str, mp4_path: Path) -> str:
    """Upload the MP4 to R2 under a timestamped key and return its public URL.

    Versioned keys dodge browser/CDN cache completely — every re-render gets a
    fresh URL. Old versions remain on R2 until manually cleaned (cheap).
    """
    s3 = _r2_client()
    bucket = os.environ["R2_BUCKET"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"videos/{arxiv_id}/{stamp}.mp4"
    size_kb = mp4_path.stat().st_size // 1024
    log.info(
        f"Uploading {mp4_path.name} ({size_kb} KB) → r2://{bucket}/{key}"
    )
    try:
        s3.upload_file(
            Filename=str(mp4_path),
            Bucket=bucket,
            Key=key,
            ExtraArgs={
                "ContentType": "video/mp4",
                # Safe long cache — the URL itself is new on every render.
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
    except Exception as e:
        raise RuntimeError(
            f"R2 upload failed (bucket={bucket}, key={key}): {e}"
        ) from e

    base = os.environ["R2_PUBLIC_BASE_URL"].rstrip("/")
    url = f"{base}/{key}"
    log.info(f"Uploaded: {url}")
    return url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("arxiv_id")
    parser.add_argument("mp4_path", type=Path)
    args = parser.parse_args()

    if not args.mp4_path.exists():
        log.error(f"MP4 not found: {args.mp4_path}")
        return 1

    url = upload(args.arxiv_id, args.mp4_path)

    md_path = _find_paper_md(args.arxiv_id)
    _set_frontmatter_field(md_path, "videoUrl", url)
    log.info(f"Stamped videoUrl into {md_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
