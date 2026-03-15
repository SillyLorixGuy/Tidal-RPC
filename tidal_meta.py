"""
tidal_meta.py — Fetches album art URLs from the Tidal catalog API.
"""

import re
import logging
from pathlib import Path

log = logging.getLogger("tidal_rpc.tidal_meta")


class TidalAuthError(Exception):
    pass


class TidalMeta:

    ART_SIZE = 640

    def __init__(self, cfg: dict) -> None:
        try:
            import tidalapi  # type: ignore
        except ImportError as e:
            raise TidalAuthError("tidalapi not installed. Run: pip install tidalapi") from e

        self._tidalapi  = tidalapi
        session_path    = Path(cfg["tidal"]["session_file"])
        self._session   = tidalapi.Session()

        # Plain dict cache — unlike lru_cache we can invalidate individual entries
        # Key: (title_lower, artist_lower)  Value: art_url str or sentinel None
        self._cache: dict = {}

        if session_path.exists():
            log.info("Loading saved Tidal session from %s", session_path)
            try:
                loaded = self._session.login_session_file(session_path)
                if loaded and self._session.check_login():
                    log.info("Tidal session restored successfully")
                    self._session_path = session_path
                    return
                log.warning("Saved session invalid — re-authenticating")
            except Exception as e:
                log.warning("Could not load session (%s) — re-authenticating", e)

        log.info("Tidal OAuth: follow the instructions below. This only happens once.")
        try:
            self._session.login_oauth_simple(fn_print=log.info)
            self._session.save_session_to_file(session_path)
            log.info("Tidal session saved to %s", session_path)
        except Exception as e:
            raise TidalAuthError(f"Tidal login failed: {e}") from e

        self._session_path = session_path

    # ── Public interface ───────────────────────────────────────────────────────

    def get_art_url(self, title: str, artist: str) -> str | None:
        key = (_norm(title), _norm(artist))

        if key in self._cache:
            cached = self._cache[key]
            log.debug("Cache hit for %s / %s → %s", artist, title, cached or "None")
            return cached

        result = self._lookup(title, artist)
        self._cache[key] = result
        return result

    def clear_cache(self) -> None:
        """Wipe the art URL cache entirely. Useful if wrong art was shown."""
        count = len(self._cache)
        self._cache.clear()
        log.info("Art cache cleared (%d entries removed)", count)

    def invalidate(self, title: str, artist: str) -> None:
        """Remove a single entry from the cache."""
        key = (_norm(title), _norm(artist))
        if key in self._cache:
            del self._cache[key]
            log.info("Cache entry invalidated: %s / %s", artist, title)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _lookup(self, title: str, artist: str) -> str | None:
        log.debug("Art lookup: %s — %s", artist, title)
        try:
            results = self._session.search(
                f"{title} {artist}",
                models=[self._tidalapi.Track],
                limit=10,
            )
            tracks = results.get("tracks") or []

            if not tracks:
                log.debug("No results for: %s / %s", artist, title)
                return None

            chosen = _best_match(tracks, title, artist)
            if chosen is None:
                log.debug("No confident match for: %s / %s — skipping art", artist, title)
                return None

            art_url = chosen.album.image(self.ART_SIZE)
            log.debug("Matched '%s' by '%s' → %s", chosen.name,
                      chosen.artist.name if chosen.artist else "?", art_url)
            return art_url

        except self._tidalapi.exceptions.TooManyRequests:
            log.warning("Tidal API rate-limited — skipping art this cycle")
            return None
        except Exception as e:
            log.warning("Tidal art lookup failed: %s", e)
            return None


# ── Matching helpers ───────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Lowercase + strip bracketed annotations and extra whitespace."""
    s = s.lower().strip()
    s = re.sub(r'\s*[\(\[](feat|ft|with|prod)\.?.*?[\)\]]', '', s)
    s = re.sub(r'\s*[\(\[](remaster(?:ed)?|live|version|edit|radio\s*edit|deluxe|acoustic|instrumental).*?[\)\]]', '', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _title_score(candidate: str, query: str) -> int:
    c, q = _norm(candidate), _norm(query)
    if c == q:           return 3
    if q in c or c in q: return 2
    if c.startswith(q) or q.startswith(c): return 1
    return 0


def _artist_score(candidate: str, query: str) -> int:
    c, q = _norm(candidate), _norm(query)
    if c == q:           return 2
    if q in c or c in q: return 1
    return 0


def _best_match(tracks, title: str, artist: str):
    """
    Score every result and return the best only if it clears the threshold.
    Max score = 5 (title=3 + artist=2). Threshold = 3.
    Returning None is better than returning wrong art.
    """
    best_score = 0
    best_track = None

    for track in tracks:
        t_title  = track.name or ""
        t_artist = track.artist.name if track.artist else ""

        ts  = _title_score(t_title, title)
        as_ = _artist_score(t_artist, artist)
        score = ts + as_

        log.debug("  Candidate: '%s' by '%s'  title=%d artist=%d total=%d",
                  t_title, t_artist, ts, as_, score)

        if score > best_score:
            best_score = score
            best_track = track

    if best_score < 3:
        log.debug("Best score %d < threshold 3 — no art", best_score)
        return None

    return best_track