# Tidal Discord RPC

Shows your current Tidal track as a Discord rich presence — song title, artist,
album art, and a live progress bar. Detects pause/resume and scrubbing and
keeps the progress bar accurate automatically.

```
Listening to TIDAL
your eyes
68+1  ━━━━━━━●──────────  1:20 / 2:26
▶ Play on TIDAL
```

---

## Requirements

- Windows 10 / 11
- Tidal desktop app (Microsoft Store or EXE version)
- Discord desktop app
- Python 3.12 or newer (only needed to build — not required to run the exe)

---

## Running from source (development)

### 1 — Discord application

1. Go to https://discord.com/developers/applications
2. Click **New Application** — name it **TIDAL** (shows as "Listening to TIDAL" in status)
3. Copy the **Application ID** from the General Information page
4. *(Optional)* Under **Rich Presence → Art Assets**, upload a fallback image
   named `tidal_logo` — shown when album art can't be fetched

### 2 — Configure

```powershell
copy config.example.toml config.toml
```

Open `config.toml` and fill in your Discord Application ID:

```toml
[discord]
client_id = "YOUR_DISCORD_APP_ID"
```

That's the only required field. Tidal authentication is handled automatically
on first run — no developer credentials needed.

### 3 — Install dependencies

```powershell
pip install -r requirements.txt
```

### 4 — First run

```powershell
python tidal_rpc.py
```

On first launch a URL and code appear in the terminal — open the URL in your
browser, log in with your Tidal account, and enter the code. The session is
saved to `tidal_session.json` and reused automatically from then on.

Play a track in Tidal and your Discord status updates within 5 seconds.

### 5 — Auto-start with Windows

```powershell
python install_startup.py
```

Adds a registry entry under `HKCU\...\Run` so the script starts silently with
Windows. No console window, runs in the background.

```powershell
python install_startup.py --remove    # remove from startup
python install_startup.py --status    # check if installed
```

---

## Building the exe (no Python required to run)

The build produces two exes:

| Exe | Purpose |
|---|---|
| `TidalRPC.exe` | Silent background process — the one you actually run |
| `TidalRPC_Setup.exe` | One-time Tidal OAuth setup with a visible console window |

### Build

```powershell
python build.py
```

For a debug build with a visible console (useful for diagnosing crashes):

```powershell
python build.py --debug
```

### Deploy

```powershell
Copy-Item -Recurse -Force dist\TidalRPC\*       C:\Programs\TidalRPC\
Copy-Item -Recurse -Force dist\TidalRPC_Setup\* C:\Programs\TidalRPC\
Copy-Item -Force config.toml                    C:\Programs\TidalRPC\config.toml
```

### First-time Tidal authentication

```powershell
C:\Programs\TidalRPC\TidalRPC_Setup.exe
```

A console window opens, shows the Tidal URL and code, and waits for you to
authenticate. After that it closes and `TidalRPC.exe` launches automatically.
You never need to run setup again unless you delete `tidal_session.json`.

### Auto-start with Windows

```powershell
C:\Programs\TidalRPC\TidalRPC.exe --install-startup
C:\Programs\TidalRPC\TidalRPC.exe --remove-startup
C:\Programs\TidalRPC\TidalRPC.exe --status
```

### Rebuilding after code changes

Only `TidalRPC.exe` needs replacing on most rebuilds:

```powershell
taskkill /F /IM TidalRPC.exe
python build.py
Copy-Item -Recurse -Force dist\TidalRPC\* C:\Programs\TidalRPC\
```

`config.toml` and `tidal_session.json` are never touched by a rebuild.

---

## File structure

```
Tidal-RPC/
├── tidal_rpc.py          Main entry point and poll loop
├── media_session.py      Windows SMTC reader (title, artist, position, duration)
├── tidal_meta.py         Tidal catalog API wrapper (album art URLs)
├── discord_rpc.py        Discord IPC wrapper (pypresence)
├── setup_tidal.py        Standalone Tidal OAuth setup (built as TidalRPC_Setup.exe)
├── config.py             Config loader
├── logger.py             Rotating log file setup
├── install_startup.py    Windows startup registry helper
├── build.py              PyInstaller build script
├── config.example.toml   Template — copy to config.toml
├── config.toml           Your credentials (gitignored)
├── tidal_session.json    Tidal OAuth token (auto-generated, gitignored)
└── requirements.txt
```

---

## How it works

1. **Media session** — polls Windows SMTC (System Media Transport Controls) every
   5 seconds. Tidal registers with SMTC automatically, so title, artist, album,
   playback position and duration are all available without any Tidal API key.

2. **Album art** — searches the Tidal catalog API for the current track and returns
   a 640×640 CDN image URL. Results are cached in memory so repeated plays of the
   same track don't hit the API again.

3. **Discord presence** — sends updates via the Discord IPC pipe using pypresence.
   Only pushes when the track changes or a position jump is detected (pause/resume,
   scrubbing). Discord animates the progress bar client-side from the timestamps,
   so no periodic updates are needed.

4. **Timestamp correction** — compares the expected playback position (extrapolated
   from the last push) against what SMTC reports. If the drift exceeds 8 seconds
   it resyncs the timestamps, keeping the progress bar accurate after pausing.

---

## Logs

```
%APPDATA%\tidal-rpc\tidal_rpc.log
```

Rotating file, max 2 MB, 3 backups kept. Change verbosity in `config.toml`:

```toml
[logging]
level = "DEBUG"   # DEBUG | INFO | WARNING | ERROR
```

---

## Troubleshooting

**Status not showing / presence not updating**
Make sure Discord is running before launching TidalRPC. Check the log file for
connection errors.

**"No active TIDAL session found in SMTC"**
Tidal must be open and actively playing (not paused) for SMTC to report it.
Try pausing and unpausing.

**Progress bar resets after pause/resume**
The 8-second drift threshold will correct it automatically within one poll cycle.

**Wrong album art**
The matching algorithm requires a confidence score of 3/5 — if nothing scores
high enough it shows no art rather than the wrong art. Very obscure tracks may
not be found. Set `level = "DEBUG"` in config.toml to see the match scores.

**"Tidal login failed" / auth expired**
Delete `tidal_session.json` and run `TidalRPC_Setup.exe` again.

**Exe doesn't start / crashes silently**
Run the debug build to see the error:
```powershell
python build.py --debug
cd dist\TidalRPC
.\TidalRPC.exe
```

**High memory usage**
Normal idle usage is 25–50 MB. If significantly higher, check the log for
errors in the asyncio event loop.