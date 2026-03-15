"""
tidal_rpc.py — Main entry point for Tidal Discord Rich Presence.
"""

import sys
import time
import logging
import subprocess
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
    """Return True if tidal_session.json doesn't exist yet."""
    return not Path(cfg["tidal"]["session_file"]).exists()


def _relaunch_with_console(cfg: dict) -> None:
    """
    No Tidal session found and we're running as a silent exe.
    Launch TidalRPC_Setup.exe (the dedicated console setup exe) and wait
    for it to finish, then relaunch this exe normally if auth succeeded.
    """
    exe_dir   = Path(sys.executable).parent.resolve()
    setup_exe = exe_dir / "TidalRPC_Setup.exe"

    if not setup_exe.exists():
        # Setup exe missing — show a message box as fallback
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"TidalRPC_Setup.exe not found in:\n{exe_dir}\n\n"
            f"Please run TidalRPC_Setup.exe manually to authenticate Tidal.",
            "Tidal RPC — Setup Required",
            0x10  # MB_ICONERROR
        )
        sys.exit(1)

    import ctypes

    # ShellExecuteW goes through the Windows shell so it always gets a proper
    # window and correct environment — subprocess.Popen inherits the parent's
    # no-console flag which causes silent failures from frozen exes.
    shell32 = ctypes.windll.shell32

    # Launch setup and wait for it to finish (SW_SHOWNORMAL = 1)
    # ShellExecuteW returns immediately so we use WaitForSingleObject via
    # ShellExecuteExW to actually block until the user closes setup.
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
    sei.nShow    = 1   # SW_SHOWNORMAL

    shell32.ShellExecuteExW(ctypes.byref(sei))

    # Block until the setup window is closed
    if sei.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)

    # If auth succeeded, launch main exe via shell so it gets a clean environment
    if Path(cfg["tidal"]["session_file"]).exists():
        shell32.ShellExecuteW(
            None, "open", str(Path(sys.executable).resolve()),
            None, str(exe_dir), 1
        )
    sys.exit(0)


# ── Bootstrap ──────────────────────────────────────────────────────────────────

setup_logger()
log = logging.getLogger("tidal_rpc")

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

    # ── First run check — no session file means OAuth hasn't been done yet ─────
    if _needs_setup(cfg):
        if getattr(sys, "frozen", False):
            # Running as compiled exe with no console — open a setup window
            _relaunch_with_console(cfg)
            return  # _relaunch_with_console calls sys.exit but just in case
        else:
            # Running as a Python script — console is already visible, just proceed
            log.info("No Tidal session found — starting OAuth flow")

    # ── Init subsystems ────────────────────────────────────────────────────────
    try:
        tidal = TidalMeta(cfg)
    except TidalAuthError as e:
        log.critical(f"Tidal authentication failed: {e}")
        sys.exit(1)

    rpc = DiscordRPC(cfg["discord"]["client_id"])

    log.info("Entering main poll loop (interval: %ds)", cfg["rpc"]["poll_interval"])

    last_track_key:     str | None = None
    last_art_url:       str | None = None
    last_push_time:     float      = 0.0
    last_push_position: float      = 0.0
    last_keepalive:     float      = 0.0
    last_position:      float      = -1.0  # -1 = no previous SMTC reading yet
    discord_connected:  bool       = False

    while True:
        try:
            track = get_current_track()

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

            if track is None:
                if last_track_key is not None:
                    log.info("Playback stopped — clearing presence")
                    rpc.clear()
                    last_track_key = None
                    last_art_url   = None
                time.sleep(cfg["rpc"]["poll_interval"])
                continue

            track_key     = f"{track['artist']}::{track['title']}"
            track_changed = track_key != last_track_key
            actual_pos    = track["position_seconds"]
            now           = time.time()

            # Detect pause/resume by checking if the position stopped moving.
            # During normal playback SMTC position advances ~poll_interval seconds
            # between cycles. After a pause+resume the position jumps back or
            # forward by more than the threshold relative to the previous reading.
            # We compare raw SMTC values — no wall-clock math — so loop overhead
            # never causes false positives.
            pos_delta       = abs(actual_pos - last_position)
            poll            = cfg["rpc"]["poll_interval"]
            # A genuine scrub/resume produces a delta outside the expected
            # [0, poll + tolerance] range. Tolerance of 3s covers SMTC jitter.
            position_jumped = (
                last_track_key is not None
                and not track_changed
                and last_position > 0
                and not (0 <= pos_delta <= poll + 3.0)
            )

            if position_jumped:
                log.debug(
                    "Position jump detected: %.1fs → %.1fs (delta %.1fs) — resyncing",
                    last_position, actual_pos, pos_delta
                )

            if track_changed or position_jumped:
                if track_changed:
                    log.info("Now playing: %s — %s", track["artist"], track["title"])
                    last_art_url = tidal.get_art_url(track["title"], track["artist"])

                rpc.update(track, last_art_url)
                last_track_key  = track_key
                last_keepalive  = now

            elif now - last_keepalive >= 15.0 and last_track_key is not None:
                # Send a raw heartbeat ping on the IPC socket.
                # rpc.update() would reset the progress bar — we just want to
                # tell Discord the connection is still alive without changing
                # the displayed activity at all.
                rpc.heartbeat()
                last_keepalive = now

            last_position = actual_pos

        except MediaSessionError as e:
            log.warning("Media session error: %s", e)

        except DiscordPayloadError as e:
            log.warning("Payload error (connection kept): %s", e)
            if track is not None:
                last_track_key = f"{track['artist']}::{track['title']}"

        except DiscordConnectionError as e:
            log.warning("Lost Discord IPC connection (%s) — will reconnect", e)
            discord_connected = False
            last_track_key    = None
            last_art_url      = None
            rpc.close()

        except KeyboardInterrupt:
            log.info("Shutting down — clearing Discord presence")
            rpc.close(clear_first=True)
            log.info("Goodbye.")
            sys.exit(0)

        except Exception as e:
            log.exception("Unexpected error: %s", e)

        time.sleep(cfg["rpc"]["poll_interval"])


if __name__ == "__main__":
    main()