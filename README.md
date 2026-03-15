# Tidal Discord RPC

Shows your current Tidal track as a Discord rich presence — song title, artist,
album art, and a live progress bar — exactly like Spotify does natively.

```
Listening to TIDAL
Weightless — Marconi Union
━━━━━━━━━━━━●──────────  2:14 / 8:09
```

---

## Requirements

- Windows 10 / 11 (primary support)
- Python 3.11 or newer
- Tidal desktop app (Store or EXE version)
- Discord desktop app

---

## Setup

### 1 — Discord application

1. Go to https://discord.com/developers/applications
2. Click **New Application** — name it **TIDAL** (this is what shows in your status)
3. Copy the **Application ID** from the General Information page
4. *(Optional)* Under **Rich Presence → Art Assets**, upload a fallback image
   named `tidal_logo` — shown when album art can't be fetched

### 2 — Tidal API credentials

1. Go to https://developer.tidal.com and sign in with your Tidal account
2. Create a new application
3. Copy the **Client ID** and **Client Secret**

### 3 — Configure

```bash
cp config.example.toml config.toml
```

Open `config.toml` and fill in:

```toml
[discord]
client_id = "YOUR_DISCORD_APP_ID"

[tidal]
client_id     = "YOUR_TIDAL_CLIENT_ID"
client_secret = "YOUR_TIDAL_CLIENT_SECRET"
```

### 4 — Install dependencies

```bash
pip install -r requirements.txt
```

### 5 — First run

```bash
python tidal_rpc.py
```

On first launch, a browser tab opens for Tidal OAuth login.
After you approve it, the session is saved to `tidal_session.json` —
you won't see this prompt again.

Play a track in Tidal and your Discord status should update within 5 seconds.

### 6 — Auto-start with Windows

```bash
python install_startup.py
```

This adds a registry entry under `HKCU\...\Run` so the RPC starts silently
with Windows (no console window, runs in background).

To remove it:
```bash
python install_startup.py --remove
```

To check if it's installed:
```bash
python install_startup.py --status
```

---

## Logs

Logs are written to:
```
%APPDATA%\tidal-rpc\tidal_rpc.log
```

Change the verbosity in `config.toml`:
```toml
[logging]
level = "DEBUG"   # DEBUG | INFO | WARNING | ERROR
```

---

## File structure

```
tidal-rpc/
├── tidal_rpc.py          Main entry point / poll loop
├── media_session.py      OS media session reader (Windows SMTC)
├── tidal_meta.py         Tidal catalog API wrapper (art URLs)
├── discord_rpc.py        Discord IPC / pypresence wrapper
├── config.py             Config loader
├── logger.py             Logging setup
├── install_startup.py    Windows startup registry helper
├── config.example.toml   Template — copy to config.toml
├── config.toml           Your credentials (gitignored)
├── tidal_session.json    OAuth token cache (auto-generated)
└── requirements.txt
```

---

## Troubleshooting

**"No active TIDAL session found"**
Tidal must be open and actively playing (not paused) for SMTC to report it.
Try pausing and unpausing the track.

**Progress bar jumps / is wrong**
This happens if you scrub in Tidal.  The poll loop corrects it within 5 seconds.

**Discord status not showing**
Make sure Discord is running *before* the RPC script.
Check `tidal_rpc.log` for connection errors.

**"Tidal login failed"**
Delete `tidal_session.json` and restart — this forces a fresh OAuth flow.

**High CPU / memory**
The script is a simple poll loop sleeping for 5 seconds between ticks.
Idle RAM usage should be ~25–40 MB.  If higher, check for runaway asyncio
tasks in the log.
