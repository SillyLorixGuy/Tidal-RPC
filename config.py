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

def _exe_dir() -> Path:
    """
    Return the directory that should contain config.toml and tidal_session.json.

    When running as a PyInstaller .exe:
        sys.executable = C:\Programs\TidalRPC\TidalRPC.exe
        __file__       = C:\...\AppData\Local\Temp\_MEIxxxxx\config.py  ← WRONG
    So we use sys.executable's parent when frozen.

    When running as a plain .py script:
        __file__ is reliable — use its parent as before.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


SCRIPT_DIR  = _exe_dir()
CONFIG_PATH = SCRIPT_DIR / "config.toml"

# ── Defaults ───────────────────────────────────────────────────────────────────

DEFAULTS: dict = {
    "discord": {
        "client_id": "",
    },
    "tidal": {
        "session_file": str(SCRIPT_DIR / "tidal_session.json"),
    },
    "rpc": {
        "poll_interval":          5,
        "timestamp_refresh_secs": 30,
        "button_label":           "Play on TIDAL",
        "button_url":             "https://tidal.com",
        "fallback_art_key":       "tidal_logo",
    },
    "logging": {
        "level": "INFO",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
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

    errors = []
    if not cfg["discord"]["client_id"]:
        errors.append("discord.client_id is required")

    if errors:
        for e in errors:
            log.critical("Config error: %s", e)
        sys.exit(1)

    return cfg