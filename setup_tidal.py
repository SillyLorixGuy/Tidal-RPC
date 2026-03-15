"""
setup_tidal.py — Standalone Tidal OAuth setup.
Built as a separate console exe (TidalRPC_Setup.exe) so it always has
a visible window regardless of how it's launched.
"""

import sys
import os
from pathlib import Path

# ── Find the config next to this exe / script ─────────────────────────────────

def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()

BASE_DIR = _exe_dir()

# ── Reconfigure stdout/stderr for the console window ──────────────────────────
# When spawned from a no-console parent the handles can be None — fix them
# so print() actually works in the cmd window.

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

try:
    import io
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 52)
    print("  Tidal Discord RPC — First Run Setup")
    print("=" * 52)
    print()
    print("This will link your Tidal account.")
    print("You only need to do this once.")
    print()

    # Check config.toml exists
    config_path = BASE_DIR / "config.toml"
    if not config_path.exists():
        print(f"ERROR: config.toml not found at:")
        print(f"  {config_path}")
        print()
        print("Make sure config.toml is in the same folder as TidalRPC.exe")
        input("\nPress Enter to close...")
        sys.exit(1)

    # Load session file path from config
    try:
        import tomllib
        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
        session_file = Path(cfg.get("tidal", {}).get("session_file", str(BASE_DIR / "tidal_session.json")))
    except Exception as e:
        print(f"ERROR reading config.toml: {e}")
        input("\nPress Enter to close...")
        sys.exit(1)

    # Run OAuth
    try:
        import tidalapi
        print("Starting Tidal authentication...")
        print()

        session = tidalapi.Session()

        def _print(msg):
            print(msg)
            sys.stdout.flush()

        session.login_oauth_simple(fn_print=_print)
        session.save_session_to_file(session_file)

        print()
        print("=" * 52)
        print("  SUCCESS! Tidal account linked.")
        print(f"  Session saved to:")
        print(f"  {session_file}")
        print("=" * 52)
        print()
        print("You can now close this window.")
        print("TidalRPC will start automatically.")

    except Exception as e:
        print(f"\nERROR: Authentication failed: {e}")
        print("\nPlease try running TidalRPC_Setup.exe again.")

    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
