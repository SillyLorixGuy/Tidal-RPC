"""
discord_rpc.py — Thin wrapper around pypresence.Presence.

Requires pypresence >= 4.5.0 for StatusDisplayType support.
Run: pip install --upgrade pypresence
"""

import time
import logging
from urllib.parse import quote
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from media_session import TrackInfo

log = logging.getLogger("tidal_rpc.discord_rpc")


class DiscordConnectionError(Exception):
    """Discord IPC pipe is down — triggers reconnect."""

class DiscordPayloadError(Exception):
    """Payload was rejected by Discord — do NOT reconnect, just skip."""


class DiscordRPC:

    def __init__(self, client_id: str) -> None:
        try:
            from pypresence import Presence, InvalidID, DiscordNotFound  # type: ignore
            from pypresence.types import ActivityType, StatusDisplayType  # type: ignore
            _ = StatusDisplayType.STATE   # fails on pypresence < 4.5.0
        except ImportError as e:
            raise ImportError("pypresence not installed. Run: pip install pypresence") from e
        except AttributeError:
            raise ImportError(
                "pypresence too old — StatusDisplayType requires >= 4.5.0.\n"
                "Run: pip install --upgrade pypresence"
            )

        self._client_id         = client_id
        self._Presence          = Presence
        self._InvalidID         = InvalidID
        self._DiscordNotFound   = DiscordNotFound
        self._ActivityType      = ActivityType
        self._StatusDisplayType = StatusDisplayType
        self._rpc               = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._rpc = None
        try:
            rpc = self._Presence(self._client_id)
            rpc.connect()
            self._rpc = rpc
        except (self._DiscordNotFound, self._InvalidID, Exception) as e:
            self._rpc = None
            raise DiscordConnectionError(f"Cannot connect to Discord: {e}") from e

    def close(self, clear_first: bool = False) -> None:
        if self._rpc is None:
            return
        rpc       = self._rpc
        self._rpc = None
        if clear_first:
            try:
                rpc.clear()
                log.debug("Presence cleared on shutdown")
                time.sleep(1.0)
            except Exception as e:
                log.debug("Clear on shutdown failed (harmless): %s", e)
        try:
            rpc.close()
        except Exception as e:
            log.debug("Close failed (harmless): %s", e)

    # ── Presence updates ───────────────────────────────────────────────────────

    def update(self, track: "TrackInfo", art_url: str | None) -> None:
        self._assert_connected()

        start_ts = time.time() - track["position_seconds"]
        end_ts   = (start_ts + track["duration_seconds"]
                    if track["duration_seconds"] > 0 else None)

        payload = self._build_payload(track, art_url, start_ts, end_ts)
        log.debug("Sending payload: %s", payload)

        try:
            self._rpc.update(**payload)
            log.debug("RPC updated: %s — %s", track["artist"], track["title"])
        except Exception as e:
            err = str(e)
            # Discord validation errors mention "fails because" or "must be a valid"
            # These are payload problems, not connection drops — don't reconnect.
            if "fails because" in err or "must be a valid" in err or "validation" in err.lower():
                raise DiscordPayloadError(f"Payload rejected: {e}") from e
            raise DiscordConnectionError(f"RPC update failed: {e}") from e

    def clear(self) -> None:
        if self._rpc is None:
            return
        try:
            self._rpc.clear()
            log.debug("Presence cleared")
        except Exception as e:
            raise DiscordConnectionError(f"RPC clear failed: {e}") from e

    # ── Payload builder ────────────────────────────────────────────────────────

    def _build_payload(
        self,
        track:   "TrackInfo",
        art_url: str | None,
        start:   float,
        end:     float | None,
    ) -> dict:
        title  = _truncate(track["title"],  128)
        artist = _truncate(track["artist"], 128)
        album  = _truncate(track["album"],  128) if track.get("album") else None

        payload: dict = {
            "activity_type":       self._ActivityType.LISTENING,
            "status_display_type": self._StatusDisplayType.STATE,
            "details": title,    # song title — top line of presence card
            "state":   artist,   # artist name — bottom line of presence card
            "start":   int(start),
        }

        if end is not None:
            payload["end"] = int(end)

        if art_url:
            payload["large_image"] = art_url
        if album:
            payload["large_text"] = album

        # urllib.parse.quote handles ALL special characters including unicode,
        # symbols (⚸, +, &, #, etc.) and multi-byte UTF-8 sequences.
        # safe='' means even '/' gets encoded, which is correct for a query param.
        search_query = quote(f"{track['artist']} {track['title']}", safe="")
        button_url   = f"https://tidal.com/search?q={search_query}"

        # Sanity-check the URL — if it somehow still contains illegal chars,
        # drop the button entirely rather than letting it kill the whole update.
        if _is_valid_url(button_url):
            payload["buttons"] = [{"label": "Play on TIDAL", "url": button_url}]
        else:
            log.warning("Button URL failed validation check — omitting button. URL was: %s", button_url)

        return payload

    def _assert_connected(self) -> None:
        if self._rpc is None:
            raise DiscordConnectionError("Not connected to Discord IPC")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _is_valid_url(url: str) -> bool:
    """
    Basic URI sanity check before sending to Discord.
    Discord requires http/https, a host, and no unencoded spaces or brackets.
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        # Unencoded spaces or curly braces are always wrong in a URI
        for bad in (" ", "{", "}", "|", "\\", "^", "`"):
            if bad in url:
                return False
        return True
    except Exception:
        return False