"""
logger.py — Configures root logger for the whole app.
Writes to both stderr (for manual runs) and a rotating file in %APPDATA%.
"""

import os
import sys
import logging
import logging.handlers
from pathlib import Path


def setup_logger(level_override: str | None = None) -> None:
    """
    Call once at startup.  level_override lets the config layer pass in
    the user's chosen level after load_config() runs; before that we
    default to INFO so early boot messages aren't lost.
    """

    # ── Log file location ──────────────────────────────────────────────────────
    if sys.platform.startswith("win"):
        app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        log_dir  = app_data / "tidal-rpc"
    else:
        log_dir = Path.home() / ".local" / "share" / "tidal-rpc"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "tidal_rpc.log"

    # ── Level ──────────────────────────────────────────────────────────────────
    level_name = (level_override or "INFO").upper()
    level      = getattr(logging, level_name, logging.INFO)

    # ── Formatters ─────────────────────────────────────────────────────────────
    fmt_detail  = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
    fmt_console = "%(asctime)s  %(levelname)-8s  %(message)s"
    date_fmt    = "%H:%M:%S"

    # ── Handlers ───────────────────────────────────────────────────────────────
    # Rotating file: max 2 MB, keep 3 backups — tiny footprint
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(fmt_detail, datefmt=date_fmt))

    # Console: only when a TTY is attached (i.e. not running via pythonw.exe)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stderr and sys.stderr.isatty():
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(logging.Formatter(fmt_console, datefmt=date_fmt))
        handlers.append(console_handler)

    # ── Root logger ────────────────────────────────────────────────────────────
    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Silence noisy third-party loggers
    for noisy in ("urllib3", "requests", "tidalapi", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("tidal_rpc").info(
        "Logging to %s  (level: %s)", log_file, level_name
    )
