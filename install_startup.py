"""
install_startup.py — Adds / removes Tidal RPC from Windows startup.

Usage (as Python script):
    python install_startup.py             → install
    python install_startup.py --remove    → uninstall
    python install_startup.py --status    → check

Usage (as compiled exe — flags handled by tidal_rpc.py):
    TidalRPC.exe --install-startup
    TidalRPC.exe --remove-startup
    TidalRPC.exe --status

Writes to: HKCU\Software\Microsoft\Windows\CurrentVersion\Run
No admin rights required.
"""

import sys
import argparse
import logging
from pathlib import Path

log = logging.getLogger("tidal_rpc.install_startup")

_REG_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "TidalDiscordRPC"


def _get_command() -> str:
    """
    Build the startup command string.
    - When running as a PyInstaller .exe: use the exe path directly (no Python needed)
    - When running as a .py script: use pythonw.exe (no console window)
    """
    # PyInstaller sets sys.frozen when running as a compiled exe
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        return f'"{exe_path}"'
    else:
        script_dir  = Path(__file__).parent.resolve()
        main_script = script_dir / "tidal_rpc.py"
        python_exe  = Path(sys.executable)
        pythonw     = python_exe.parent / "pythonw.exe"
        if not pythonw.exists():
            pythonw = python_exe
        return f'"{pythonw}" "{main_script}"'


def install() -> None:
    if sys.platform != "win32":
        print("Startup installation is only supported on Windows.")
        sys.exit(1)

    import winreg  # type: ignore

    cmd = _get_command()
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        print(f"✓ Startup entry added for '{_APP_NAME}'")
        print(f"  Command: {cmd}")
        print(f"  Registry: HKCU\\{_REG_KEY}")
    except OSError as e:
        print(f"✗ Failed to write registry key: {e}")
        sys.exit(1)


def remove() -> None:
    if sys.platform != "win32":
        print("Only supported on Windows.")
        sys.exit(1)

    import winreg  # type: ignore

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, _APP_NAME)
        winreg.CloseKey(key)
        print(f"✓ Startup entry '{_APP_NAME}' removed")
    except FileNotFoundError:
        print(f"  No startup entry found for '{_APP_NAME}' — nothing to remove")
    except OSError as e:
        print(f"✗ Failed to remove registry key: {e}")
        sys.exit(1)


def status() -> None:
    if sys.platform != "win32":
        print("Only supported on Windows.")
        sys.exit(1)

    import winreg  # type: ignore

    try:
        key   = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, _APP_NAME)
        winreg.CloseKey(key)
        print(f"✓ '{_APP_NAME}' is installed in startup")
        print(f"  Command: {value}")
    except FileNotFoundError:
        print(f"  '{_APP_NAME}' is NOT in startup")
    except OSError as e:
        print(f"✗ Could not read registry: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage Tidal RPC Windows startup")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", action="store_true")
    group.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.remove:
        remove()
    elif args.status:
        status()
    else:
        install()