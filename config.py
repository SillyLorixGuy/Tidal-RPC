"""
config.py — Loads and validates config.toml.
Falls back to safe defaults for every optional key so the user only needs to
fill in the required fields.
"""

import sys
import tomllib
import logging
from pathlib import Path

log = logging.getLogger("tidal_rpc.config")

# ── Paths ──────────────────────────────────────────────────────────────────────

# Config lives next to this script so it's easy to find and edit
SCRIPT_DIR  = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "config.toml"

# ── Defaults ───────────────────────────────────────────────────────────────────

DEFAULTS: dict = {
    "discord": {
        "client_id": "",          # REQUIRED — your Discord application ID
    },
    "tidal": {
        # No client_id/secret — tidalapi uses its own built-in credentials
        "session_file": str(SCRIPT_DIR / "tidal_session.json"),
    },
    "rpc": {
        # How often (seconds) to poll the OS media session.
        # Discord rate-limits presence updates to 5/min — we only push on
        # track changes so 5s is safe.
        "poll_interval":          5,

        # How often (seconds) to refresh timestamps even when the track
        # hasn't changed (keeps the progress bar accurate).
        "timestamp_refresh_secs": 30,

        # Button shown on the Discord profile card
        "button_label": "Play on TIDAL",
        "button_url":   "https://tidal.com",   # overridden per-track when possible

        # Discord image asset key to show when no album art is found.
        # Upload a fallback image in the Discord developer portal and put its
        # key here.  Leave blank to skip the large_image field entirely.
        "fallback_art_key": "tidal_logo",
    },
    "logging": {
        # "DEBUG" for verbose output, "INFO" for normal, "WARNING" to be quiet
        "level": "INFO",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.critical(
            "config.toml not found at %s\n"
            "Copy config.example.toml to config.toml and fill in your credentials.",
            CONFIG_PATH,
        )
        sys.exit(1)

    with open(CONFIG_PATH, "rb") as f:
        user_cfg = tomllib.load(f)

    cfg = _deep_merge(DEFAULTS, user_cfg)

    # Validate required fields
    errors = []
    if not cfg["discord"]["client_id"]:
        errors.append("discord.client_id is required")

    if errors:
        for e in errors:
            log.critical("Config error: %s", e)
        sys.exit(1)

    return cfg