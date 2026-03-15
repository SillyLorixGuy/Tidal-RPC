"""
build.py — Builds TidalRPC.exe (silent) and TidalRPC_Setup.exe (console).

Usage:
    python build.py           → release builds
    python build.py --debug   → debug builds (both have console)
"""

import sys
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()

HIDDEN_IMPORTS = [
    "pypresence", "pypresence.types", "pypresence.baseclient",
    "pypresence.client", "pypresence.exceptions", "pypresence.payloads",
    "pypresence.presence", "pypresence.utils",
    "tidalapi", "tidalapi.exceptions", "tidalapi.models", "tidalapi.session",
    "tomllib", "logging.handlers", "asyncio", "winreg",
    "winrt", "winrt.windows", "winrt.windows.media",
    "winrt.windows.media.control",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.storage.streams",
]

COLLECT_ALL = ["winrt", "tidalapi", "pypresence"]


def find_site_packages() -> Path:
    for p in sys.path:
        c = Path(p)
        if c.name == "site-packages" and c.is_dir():
            return c
    exe = Path(sys.executable)
    for parent in exe.parents:
        c = parent / "Lib" / "site-packages"
        if c.is_dir():
            return c
    raise RuntimeError("Cannot locate site-packages")


def check_pyinstaller():
    try:
        import PyInstaller  # noqa
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def base_cmd(name: str, script: str, console: bool) -> list:
    """Build the base PyInstaller command for a given entry point."""
    site_packages = find_site_packages()
    winrt_dir     = site_packages / "winrt"
    pyd_files     = list(winrt_dir.glob("*.pyd")) if winrt_dir.is_dir() else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", name,
        "--distpath", str(SCRIPT_DIR / "dist"),
        "--workpath", str(SCRIPT_DIR / "build_tmp"),
        "--specpath", str(SCRIPT_DIR),
    ]

    for pyd in pyd_files:
        cmd += ["--add-binary", f"{pyd};winrt"]

    for pkg in COLLECT_ALL:
        cmd += ["--collect-all", pkg]

    for h in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", h]

    if not console:
        cmd.append("--noconsole")

    cmd.append(str(SCRIPT_DIR / script))
    return cmd


def run_build(name: str, script: str, console: bool) -> bool:
    cmd = base_cmd(name, script, console)
    print(f"\nBuilding {name}.exe ({'console' if console else 'no console'})...")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print(f"✗ {name} build failed.")
        return False
    exe = SCRIPT_DIR / "dist" / name / f"{name}.exe"
    if not exe.exists():
        print(f"✗ {name}.exe not found after build.")
        return False
    size = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file()) / (1024**2)
    print(f"✓ {name}.exe  ({size:.0f} MB)")
    return True


def build(debug: bool = False) -> None:
    check_pyinstaller()

    # Main silent exe
    ok1 = run_build("TidalRPC",       "tidal_rpc.py",    console=debug)
    # Setup exe — always has a console so the user can see the OAuth prompt
    ok2 = run_build("TidalRPC_Setup", "setup_tidal.py",  console=True)

    if not (ok1 and ok2):
        sys.exit(1)

    print("\n" + "=" * 52)
    print("Both exes built successfully.")
    print("\nDeploy:")
    print("  xcopy /E /I /Y dist\\TidalRPC       C:\\Programs\\TidalRPC")
    print("  xcopy /E /I /Y dist\\TidalRPC_Setup C:\\Programs\\TidalRPC")
    print("  copy config.toml C:\\Programs\\TidalRPC\\")
    print()
    print("First run (links your Tidal account):")
    print("  C:\\Programs\\TidalRPC\\TidalRPC_Setup.exe")
    print()
    print("Normal launch (silent, background):")
    print("  C:\\Programs\\TidalRPC\\TidalRPC.exe")
    print()
    print("Auto-start with Windows:")
    print("  C:\\Programs\\TidalRPC\\TidalRPC.exe --install-startup")


if __name__ == "__main__":
    build(debug="--debug" in sys.argv)