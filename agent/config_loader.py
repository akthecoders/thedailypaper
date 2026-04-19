"""Config loader — merges config.yaml with environment variables.

Paths in config.yaml are resolved relative to the repo root, not the CWD,
so `python agent/run_daily.py` and `cd agent && python run_daily.py` both work.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent

DEFAULT_RANKER_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_EXPLAINER_MODEL = "anthropic/claude-opus-4.1"
DEFAULT_VIDEO_MODEL = "anthropic/claude-opus-4.1"


def _resolve(p: str) -> str:
    """Resolve a config path — if relative, anchor at the repo root, not CWD."""
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return str(path)


def load_config() -> dict:
    # Prefer the user's config.yaml; fall back to the committed example so
    # GitHub Actions (where config.yaml is gitignored) can still run.
    config_path = REPO_ROOT / "config" / "config.yaml"
    if not config_path.exists():
        config_path = REPO_ROOT / "config" / "config.example.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    # Same fallback for interests.md → interests.example.md (also gitignored).
    interests_default = cfg.get("interests_path", "./config/interests.md")
    interests_abs = Path(_resolve(interests_default))
    if not interests_abs.exists():
        cfg["interests_path"] = "./config/interests.example.md"

    cfg["telegram_bot_token"] = os.environ.get(
        "TELEGRAM_BOT_TOKEN", cfg.get("telegram_bot_token", "")
    )
    cfg["telegram_chat_id"] = os.environ.get(
        "TELEGRAM_CHAT_ID", cfg.get("telegram_chat_id", "")
    )
    cfg["site_url"] = os.environ.get("SITE_URL", cfg.get("site_url", ""))

    for key in ["history_path", "interests_path", "site_root"]:
        if key in cfg:
            cfg[key] = _resolve(cfg[key])

    cfg.setdefault("ranker_model", DEFAULT_RANKER_MODEL)
    cfg.setdefault("explainer_model", DEFAULT_EXPLAINER_MODEL)
    cfg.setdefault("video_model", DEFAULT_VIDEO_MODEL)

    assert os.environ.get("OPENROUTER_API_KEY"), (
        "Set OPENROUTER_API_KEY in env. Get a key at https://openrouter.ai/keys"
    )
    return cfg
