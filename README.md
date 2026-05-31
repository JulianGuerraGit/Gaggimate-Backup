# GaggiMate Backup Export

Exports GaggiMate display settings, profiles, and shot history for backup or SD-card migration.

The exporter pulls whichever storage the display is currently using:

| Display state | Exported source |
|---|---|
| SD card inserted | SD card profiles/history |
| SD card removed | Internal flash profiles/history |

This makes the no-SD to SD-card transition possible: run the export with the SD card removed, then copy the generated `sdcard/p` and `sdcard/h` folders to the root of the SD card as `/p` and `/h`.

## Install

```bash
uv sync
```

## Export Everything

```bash
uv run gaggimate-shot-backup gaggimate.local -o gaggimate-export --zip
```

You can also use an IP address:

```bash
uv run gaggimate-shot-backup http://192.168.1.50 -o gaggimate-export
```

## Output Layout

```text
gaggimate-export/
  manifest.json
  backup/
    settings/
      settings.json
    profiles/
      profiles.json
      <profile-id>.json
    history/
      history.json
      index.bin
      000001.slog
      000001.json
  sdcard/
    p/
      <profile-id>.json
    h/
      index.bin
      000001.slog
      000001.json
```

`backup/` is the human-readable/full archive. `sdcard/` is the import-ready tree for SD-card migration.

Settings are exported as the same JSON the Web UI downloads from `/api/settings`. Current firmware stores settings in device preferences, not on the SD card, so `sdcard/` only contains profile and shot-history folders.

## Useful Options

```bash
# Rebuild /h/index.bin before downloading history.
uv run gaggimate-shot-backup gaggimate.local --rebuild-index-first

# Export only settings and profiles.
uv run gaggimate-shot-backup gaggimate.local --skip-history

# Export profiles/history without shot notes.
uv run gaggimate-shot-backup gaggimate.local --skip-notes
```

## APIs Used

- `GET /api/settings` for settings.
- WebSocket `req:profiles:list` for full profiles.
- WebSocket `req:history:list` for shot metadata.
- `GET /api/history/index.bin` and `GET /api/history/<id>.slog` for SD-compatible history files.
- WebSocket `req:history:notes:get` for shot note JSON files.
