"""
tidal_rpc.py — Main entry point for Tidal Discord Rich Presence.

State logic based on ytmdesktop/ytmdesktop discord-presence integration.
"""

import sys
import time
import logging
import threading
from pathlib import Path

from config import load_config, SCRIPT_DIR
from logger import setup_logger
from media_session import get_current_track, MediaSessionError
from tidal_meta import TidalMeta, TidalAuthError
from discord_rpc import DiscordRPC, DiscordConnectionError, DiscordPayloadError

# ── CLI flags ──────────────────────────────────────────────────────────────────

def _handle_cli_args() -> None:
    if len(sys.argv) < 2:
        return
    arg = sys.argv[1].lower()
    if arg in ("--install-startup", "--remove-startup", "--status"):
        from install_startup import install, remove, status
        if arg == "--install-startup":   install()
        elif arg == "--remove-startup":  remove()
        else:                            status()
        sys.exit(0)

_handle_cli_args()

# ── First-run setup ────────────────────────────────────────────────────────────

def _needs_setup(cfg: dict) -> bool:
    return not Path(cfg["tidal"]["session_file"]).exists()


def _relaunch_with_console(cfg: dict) -> None:
    exe_dir   = Path(sys.executable).parent.resolve()
    setup_exe = exe_dir / "TidalRPC_Setup.exe"

    import ctypes

    if not setup_exe.exists():
        ctypes.windll.user32.MessageBoxW(
            0,
            f"TidalRPC_Setup.exe not found in:\n{exe_dir}\n\n"
            f"Please run TidalRPC_Setup.exe manually to authenticate Tidal.",
            "Tidal RPC — Setup Required",
            0x10
        )
        sys.exit(1)

    shell32 = ctypes.windll.shell32
    SEE_MASK_NOCLOSEPROCESS = 0x00000040

    class _SEI(ctypes.Structure):
        _fields_ = [
            ("cbSize",         ctypes.c_ulong),
            ("fMask",          ctypes.c_ulong),
            ("hwnd",           ctypes.c_void_p),
            ("lpVerb",         ctypes.c_wchar_p),
            ("lpFile",         ctypes.c_wchar_p),
            ("lpParameters",   ctypes.c_wchar_p),
            ("lpDirectory",    ctypes.c_wchar_p),
            ("nShow",          ctypes.c_int),
            ("hInstApp",       ctypes.c_void_p),
            ("lpIDList",       ctypes.c_void_p),
            ("lpClass",        ctypes.c_wchar_p),
            ("hkeyClass",      ctypes.c_void_p),
            ("dwHotKey",       ctypes.c_ulong),
            ("hIconOrMonitor", ctypes.c_void_p),
            ("hProcess",       ctypes.c_void_p),
        ]

    sei          = _SEI()
    sei.cbSize   = ctypes.sizeof(_SEI)
    sei.fMask    = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb   = "open"
    sei.lpFile   = str(setup_exe)
    sei.nShow    = 1

    shell32.ShellExecuteExW(ctypes.byref(sei))

    if sei.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)

    if Path(cfg["tidal"]["session_file"]).exists():
        shell32.ShellExecuteW(
            None, "open", str(Path(sys.executable).resolve()),
            None, str(exe_dir), 1
        )
    sys.exit(0)


# ── Bootstrap ──────────────────────────────────────────────────────────────────

setup_logger()
log = logging.getLogger("tidal_rpc")

# How long to wait after playback stops before clearing presence.
# Covers track-to-track gaps, brief pauses, and skip stutters.
# Matches ytmdesktop's 30-second pause timeout.
_PAUSE_CLEAR_DELAY = 30.0

# Minimum character length Discord requires for details/state fields.
_DISCORD_MIN_LEN = 2


def _pad(text: str) -> str:
    """
    Pad short strings to Discord's 2-char minimum using zero-width spaces.
    Technique from ytmdesktop — invisible to the user but satisfies validation.
    """
    if len(text) < _DISCORD_MIN_LEN:
        return text + "\u200b" * (_DISCORD_MIN_LEN - len(text))
    return text


def main() -> None:
    log.info("═" * 50)
    log.info("Tidal Discord RPC starting up")
    log.info(f"Python {sys.version.split()[0]}  |  Platform: {sys.platform}")
    log.info("═" * 50)

    if sys.platform.startswith("linux"):
        log.warning("Linux detected — Tidal desktop not supported. Exiting.")
        sys.exit(0)

    if not sys.platform.startswith("win"):
        log.error(f"Unsupported platform: {sys.platform}.")
        sys.exit(1)

    cfg = load_config()

    if _needs_setup(cfg):
        if getattr(sys, "frozen", False):
            _relaunch_with_console(cfg)
            return
        else:
            log.info("No Tidal session found — starting OAuth flow")

    try:
        tidal = TidalMeta(cfg)
    except TidalAuthError as e:
        log.critical(f"Tidal authentication failed: {e}")
        sys.exit(1)

    rpc = DiscordRPC(cfg["discord"]["client_id"])

    log.info("Entering main poll loop (interval: %ds)", cfg["rpc"]["poll_interval"])

    # ── State vars ─────────────────────────────────────────────────────────────
    last_track_key:    str | None = None   # "artist::title" of last pushed track
    last_art_url:      str | None = None   # cached art URL for current track
    track_start_ts:    float      = 0.0    # wall-clock start time, set once per track
    last_position:     float      = -1.0   # SMTC position from previous cycle
    discord_connected: bool       = False

    # Pause timeout — mirrors ytmdesktop's pauseTimeout.
    # When playback stops we don't clear immediately; we schedule a clear
    # 30 seconds later. If playback resumes before that, we cancel it.
    pause_timer: threading.Timer | None = None

    def _schedule_clear() -> threading.Timer:
        """Start a 30s timer that clears presence if not cancelled first."""
        def _do_clear():
            nonlocal last_track_key, last_art_url, pause_timer
            log.info("Pause timeout — clearing presence")
            try:
                rpc.clear()
            except Exception:
                pass
            last_track_key = None
            last_art_url   = None
            pause_timer    = None
        t = threading.Timer(_PAUSE_CLEAR_DELAY, _do_clear)
        t.daemon = True
        t.start()
        return t

    def _cancel_clear():
        nonlocal pause_timer
        if pause_timer is not None:
            pause_timer.cancel()
            pause_timer = None

    # ── Main loop ──────────────────────────────────────────────────────────────
    while True:
        try:
            track = get_current_track()

            # Connect / reconnect
            if not discord_connected:
                try:
                    rpc.connect()
                    discord_connected = True
                    last_track_key    = None
                    log.info("Connected to Discord IPC pipe")
                except DiscordConnectionError:
                    log.warning("Discord not running — will retry next cycle")
                    time.sleep(cfg["rpc"]["poll_interval"])
                    continue

            # ── Nothing playing (paused or stopped) ───────────────────────────
            if track is None:
                # Schedule a delayed clear if we haven't already.
                # This prevents flicker during track-to-track gaps.
                if last_track_key is not None and pause_timer is None:
                    log.debug("Playback stopped — scheduling clear in %ds", _PAUSE_CLEAR_DELAY)
                    pause_timer = _schedule_clear()
                last_position = -1.0
                time.sleep(cfg["rpc"]["poll_interval"])
                continue

            # ── Playback resumed — cancel any pending clear ───────────────────
            _cancel_clear()

            track_key    = f"{track['artist']}::{track['title']}"
            actual_pos   = track["position_seconds"]
            track_changed = track_key != last_track_key

            # Scrub detection — if position went backwards it's a seek.
            # From ytmdesktop: oldProgress > this.progress means the user scrubbed.
            # We also catch large forward jumps (> poll + 3s tolerance).
            poll = cfg["rpc"]["poll_interval"]
            scrubbed = (
                not track_changed
                and last_position >= 0
                and (
                    actual_pos < last_position                        # scrub backward
                    or actual_pos > last_position + poll + 3.0       # scrub forward
                )
            )

            if track_changed or scrubbed:
                if track_changed:
                    log.info("Now playing: %s — %s", track["artist"], track["title"])
                    last_art_url    = tidal.get_art_url(track["title"], track["artist"])
                    # Calculate start_ts once per track — never recalculate to
                    # avoid resetting the progress bar on subsequent updates
                    track_start_ts  = time.time() - actual_pos
                else:
                    log.debug("Scrub detected: %.1fs → %.1fs — resyncing", last_position, actual_pos)
                    track_start_ts = time.time() - actual_pos

                rpc.update(
                    track     = track,
                    art_url   = last_art_url,
                    start_ts  = track_start_ts,
                    title     = _pad(track["title"]),
                    artist    = _pad(track["artist"]),
                )
                last_track_key = track_key

            last_position = actual_pos

        except MediaSessionError as e:
            log.warning("Media session error: %s", e)

        except DiscordPayloadError as e:
            log.warning("Payload error (connection kept): %s", e)
            if track is not None:
                last_track_key = f"{track['artist']}::{track['title']}"

        except DiscordConnectionError as e:
            log.warning("Lost Discord IPC connection (%s) — will reconnect", e)
            _cancel_clear()
            discord_connected = False
            last_track_key    = None
            last_art_url      = None
            rpc.close()

        except KeyboardInterrupt:
            log.info("Shutting down — clearing Discord presence")
            _cancel_clear()
            rpc.close(clear_first=True)
            log.info("Goodbye.")
            sys.exit(0)

        except Exception as e:
            log.exception("Unexpected error: %s", e)

        time.sleep(cfg["rpc"]["poll_interval"])


if __name__ == "__main__":
    main()