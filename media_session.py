"""
media_session.py — Reads the currently playing track from the OS.

Windows: uses Windows.Media.Control (SMTC) via the winrt package.
Linux:   Stubbed — returns None gracefully.
"""

import sys
import asyncio
import logging

log = logging.getLogger("tidal_rpc.media_session")


class MediaSessionError(Exception):
    pass


if sys.platform.startswith("win"):

    try:
        from winrt.windows.media.control import (  # type: ignore
            GlobalSystemMediaTransportControlsSessionManager as _MediaManager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlaybackStatus,
        )
        _WINRT_AVAILABLE = True
    except ImportError:
        _WINRT_AVAILABLE = False
        log.warning("winrt-Windows.Media.Control not installed. Run: pip install winrt-Windows.Media.Control")

    _TIDAL_IDENTIFIERS = ("tidal",)

    def _is_tidal(source_app_id: str) -> bool:
        return any(k in source_app_id.lower() for k in _TIDAL_IDENTIFIERS)

    async def _fetch_track():
        if not _WINRT_AVAILABLE:
            return None

        # Re-request the manager every cycle — caching it across calls causes
        # the session manager to go stale after Tidal restarts or pauses,
        # which is the root cause of the silent death after stop/start cycles.
        try:
            manager  = await _MediaManager.request_async()
            sessions = manager.get_sessions()
        except Exception as e:
            raise MediaSessionError(f"Failed to get media sessions: {e}") from e

        tidal_session = None
        current = manager.get_current_session()
        if current and _is_tidal(current.source_app_user_model_id):
            tidal_session = current
        else:
            for s in sessions:
                if _is_tidal(s.source_app_user_model_id):
                    tidal_session = s
                    break

        if tidal_session is None:
            log.debug("No TIDAL session in SMTC")
            return None

        playback = tidal_session.get_playback_info()
        if playback is None or playback.playback_status != _PlaybackStatus.PLAYING:
            log.debug("TIDAL not playing")
            return None

        try:
            props = await tidal_session.try_get_media_properties_async()
        except Exception as e:
            raise MediaSessionError(f"Failed to get media properties: {e}") from e

        if props is None:
            return None

        title  = (props.title  or "").strip()
        artist = (props.artist or "").strip()

        if not title or not artist:
            return None

        timeline         = tidal_session.get_timeline_properties()
        position_seconds = 0.0
        duration_seconds = 0.0
        if timeline is not None:
            try:
                position_seconds = timeline.position.total_seconds()
                duration_seconds = timeline.end_time.total_seconds()
            except Exception:
                pass

        return {
            "title":            title,
            "artist":           artist,
            "album":            (props.album_title or "").strip(),
            "position_seconds": max(0.0, position_seconds),
            "duration_seconds": max(0.0, duration_seconds),
        }

    # ── Persistent event loop ──────────────────────────────────────────────────
    # One long-lived loop for the whole process.
    # pypresence also creates an event loop internally — to prevent the two
    # from conflicting, we create ours first and let pypresence share it by
    # passing it as a constructor arg (see discord_rpc.py).

    _loop = None

    def _get_loop():
        global _loop
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            log.debug("Created new asyncio event loop")
        return _loop

    def reset_loop():
        """Called externally if the loop needs to be rebuilt."""
        global _loop
        if _loop is not None:
            try:
                _loop.close()
            except Exception:
                pass
        _loop = None

    def get_event_loop():
        """Expose the persistent loop so other modules can share it."""
        return _get_loop()

    def get_current_track():
        loop = _get_loop()
        try:
            return loop.run_until_complete(_fetch_track())
        except MediaSessionError:
            raise
        except RuntimeError as e:
            # 'Event loop is closed' or 'This event loop is already running'
            log.warning("Event loop runtime error (%s) — rebuilding", e)
            reset_loop()
            return None
        except Exception as e:
            log.warning("Unexpected error in media session (%s) — rebuilding loop", e)
            reset_loop()
            return None

else:
    def get_current_track():  # type: ignore
        return None

    def get_event_loop():  # type: ignore
        return None

    def reset_loop():  # type: ignore
        pass