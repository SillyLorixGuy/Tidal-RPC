"""
build.py — Packages Tidal RPC into a standalone .exe using PyInstaller.

Usage:
    python build.py

Output:
    dist/TidalRPC.exe   — single file, no console window, ~30-50 MB

After building:
    1. Copy dist/TidalRPC.exe somewhere permanent (e.g. C:\Programs\TidalRPC\)
    2. Copy config.toml to the same folder
    3. Run: TidalRPC.exe   (first run opens Tidal OAuth in browser)
    4. Run: TidalRPC.exe --install-startup   (adds to Windows startup)

The --install-startup and --remove-startup flags are baked into the exe
so you don't need Python at all after building.
"""

import sys
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def check_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa
    except ImportError:
        print("PyInstaller not found — installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("PyInstaller installed.\n")


def build() -> None:
    check_pyinstaller()

    # Hidden imports that PyInstaller misses because they're loaded dynamically
    hidden = [
        "winrt.windows.media.control",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.storage.streams",
        "pypresence",
        "pypresence.types",
        "tidalapi",
        "tidalapi.exceptions",
        "tomllib",
        "logging.handlers",
    ]

    hidden_args = []
    for h in hidden:
        hidden_args += ["--hidden-import", h]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                        # single .exe
        "--noconsole",                      # no terminal window
        "--name", "TidalRPC",
        "--distpath", str(SCRIPT_DIR / "dist"),
        "--workpath", str(SCRIPT_DIR / "build_tmp"),
        "--specpath", str(SCRIPT_DIR),
        *hidden_args,
        str(SCRIPT_DIR / "tidal_rpc.py"),
    ]

    print("Building TidalRPC.exe...")
    print(f"Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)

    if result.returncode != 0:
        print("\n✗ Build failed — check output above for errors.")
        sys.exit(1)

    exe = SCRIPT_DIR / "dist" / "TidalRPC.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\n✓ Built successfully: {exe}  ({size_mb:.1f} MB)")
        print("\nNext steps:")
        print("  1. Copy dist\\TidalRPC.exe to a permanent folder")
        print("     e.g.  C:\\Programs\\TidalRPC\\TidalRPC.exe")
        print("  2. Copy config.toml to the SAME folder")
        print("  3. Double-click TidalRPC.exe (first run: Tidal OAuth in browser)")
        print("  4. To auto-start with Windows:")
        print("     TidalRPC.exe --install-startup")
        print("  5. To remove from startup:")
        print("     TidalRPC.exe --remove-startup")
    else:
        print("\n✗ Build finished but exe not found — something went wrong.")
        sys.exit(1)


if __name__ == "__main__":
    build()