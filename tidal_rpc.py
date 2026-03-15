"""
tidal_rpc.py — Main entry point for Tidal Discord Rich Presence.
"""

import sys
import time
import logging

from config import load_config
from logger import setup_logger
from media_session import get_current_track, MediaSessionError
from tidal_meta import TidalMeta, TidalAuthError
from discord_rpc import DiscordRPC, DiscordConnectionError, DiscordPayloadError

# ── CLI flags (used when running as compiled .exe) ────────────────────────────
def _handle_cli_args() -> None:
    """
    Handle --install-startup and --remove-startup flags so the compiled exe
    is fully self-contained — no Python needed after building.
    """
    if len(sys.argv) < 2:
        return
    arg = sys.argv[1].lower()
    if arg in ("--install-startup", "--remove-startup", "--status"):
        from install_startup import install, remove, status
        if arg == "--install-startup":
            install()
        elif arg == "--remove-startup":
            remove()
        else:
            status()
        sys.exit(0)

_handle_cli_args()

setup_logger()
log = logging.getLogger("tidal_rpc")

# How many seconds the reported position can drift before we push a
# timestamp correction. 8s covers normal SMTC jitter without over-firing.
_POSITION_DRIFT_THRESHOLD = 8.0


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

    try:
        tidal = TidalMeta(cfg)
    except TidalAuthError as e:
        log.critical(f"Tidal authentication failed: {e}")
        sys.exit(1)

    rpc = DiscordRPC(cfg["discord"]["client_id"])

    log.info("Entering main poll loop (interval: %ds)", cfg["rpc"]["poll_interval"])

    last_track_key:     str | None   = None
    last_art_url:       str | None   = None
    last_push_time:     float        = 0.0   # wall-clock time of last rpc.update()
    last_push_position: float        = 0.0   # track position at last rpc.update()
    discord_connected:  bool         = False

    while True:
        try:
            # ── 1. Read OS media session ───────────────────────────────────────
            track = get_current_track()

            # ── 2. Connect / reconnect Discord ────────────────────────────────
            if not discord_connected:
                try:
                    rpc.connect()
                    discord_connected   = True
                    last_track_key      = None   # push current track immediately
                    log.info("Connected to Discord IPC pipe")
                except DiscordConnectionError:
                    log.warning("Discord not running — will retry next cycle")
                    time.sleep(cfg["rpc"]["poll_interval"])
                    continue

            # ── 3. Nothing playing ─────────────────────────────────────────────
            if track is None:
                if last_track_key is not None:
                    log.info("Playback stopped — clearing presence")
                    rpc.clear()
                    last_track_key  = None
                    last_art_url    = None
                time.sleep(cfg["rpc"]["poll_interval"])
                continue

            # ── 4. Determine whether to push an update ────────────────────────
            track_key    = f"{track['artist']}::{track['title']}"
            track_changed = track_key != last_track_key

            # Position drift check — compare where Discord thinks we are
            # (extrapolated from last push) vs where SMTC says we actually are.
            # A jump larger than the threshold means the user paused/resumed or
            # scrubbed, and we need to resync the timestamps.
            now           = time.time()
            elapsed_since = now - last_push_time
            expected_pos  = last_push_position + elapsed_since
            actual_pos    = track["position_seconds"]
            drift         = abs(actual_pos - expected_pos)
            position_jumped = (
                last_track_key is not None        # not a fresh start
                and not track_changed             # same track
                and drift > _POSITION_DRIFT_THRESHOLD
            )

            if position_jumped:
                log.debug(
                    "Position drift %.1fs (expected %.1fs, got %.1fs) — resyncing timestamps",
                    drift, expected_pos, actual_pos
                )

            # ── 5. Push update if needed ──────────────────────────────────────
            if track_changed or position_jumped:
                if track_changed:
                    log.info("Now playing: %s — %s", track["artist"], track["title"])
                    last_art_url = tidal.get_art_url(track["title"], track["artist"])

                rpc.update(track, last_art_url)

                last_track_key      = track_key
                last_push_time      = now
                last_push_position  = actual_pos

        except MediaSessionError as e:
            log.warning("Media session error: %s", e)

        except DiscordPayloadError as e:
            # Payload rejected — connection still alive, don't reconnect.
            # Advance last_track_key so we don't retry the same broken payload.
            log.warning("Payload error (connection kept): %s", e)
            if track is not None:
                last_track_key     = f"{track['artist']}::{track['title']}"
                last_push_time     = time.time()
                last_push_position = track["position_seconds"]

        except DiscordConnectionError as e:
            log.warning("Lost Discord IPC connection (%s) — will reconnect", e)
            discord_connected   = False
            last_track_key      = None
            last_art_url        = None
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