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

## Command Reference

```text
uv run gaggimate-shot-backup HOST [options]
```

### Required Argument

| Argument | Description |
|---|---|
| `HOST` | Display host or URL. Use `gaggimate.local`, an IP address like `192.168.1.50`, or a full URL like `http://192.168.1.50`. If no scheme is supplied, the tool uses `http://`. |

### Options

| Flag | Default | Description |
|---|---:|---|
| `-o, --output PATH` | `gaggimate-export` | Output directory for the export. The tool creates `backup/`, `sdcard/`, and `manifest.json` inside this folder. Existing files with the same names may be overwritten. |
| `--timeout SECONDS` | `20` | Timeout for each HTTP or WebSocket request. Increase this on slow Wi-Fi, large history exports, or displays that serve `.slog` files slowly. |
| `--skip-settings` | off | Do not fetch `/api/settings`. Use this when you only need SD-card-importable profile/history files. |
| `--skip-profiles` | off | Do not export profiles. This also leaves `sdcard/p/` empty or absent. |
| `--skip-history` | off | Do not export shot history. This also leaves `sdcard/h/` empty or absent. |
| `--skip-notes` | off | Skip per-shot note JSON files. The exporter still downloads `index.bin` and `.slog` files. |
| `--rebuild-index-first` | off | Sends `req:history:rebuild` before downloading history. Use this if the Web UI history list is stale or after manually copying shot files. |
| `--resume` | off | Continue an interrupted export. Existing non-empty files in the output folder are reused, copied into the SD-card tree if needed, and only missing files are fetched. |
| `--zip` | off | Create a ZIP archive next to the output directory after export completes. |
| `-h, --help` | n/a | Print CLI help. |

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

Shot notes are exported as padded JSON filenames like `000001.json` when they exist.

## SD Card Migration

To migrate from internal flash history to an SD card:

1. Remove the SD card from the display, or leave it out if you have not installed one yet.
2. Start the display and make sure the Web UI is reachable.
3. Run:

```bash
uv run gaggimate-shot-backup gaggimate.local -o internal-to-sd
```

4. Copy these generated folders to the root of the SD card:

```text
internal-to-sd/sdcard/p -> /p
internal-to-sd/sdcard/h -> /h
```

5. Insert the SD card and restart the display.

The `sdcard/h` folder contains `index.bin`, `.slog` files, and note `.json` files. The `sdcard/p` folder contains one JSON file per profile.

## Resuming An Interrupted Export

If Wi-Fi drops or the display disconnects during a large history export, rerun the same command with `--resume` and the same output folder:

```bash
uv run gaggimate-shot-backup gaggimate.local -o gaggimate-export --resume
```

Resume mode treats existing non-empty files as complete. It still reads the saved profile/history lists from `backup/` when present, copies reused files into `sdcard/`, and fetches only the missing settings, profile, history, or note files.

History export downloads or reuses `index.bin` and all `.slog` files first. After the shot files are complete, it runs a separate note pass that downloads padded note files like `000001.json` from `/api/history/`, using the same raw file download path as shot logs.

## Examples

```bash
# Rebuild /h/index.bin before downloading history.
uv run gaggimate-shot-backup gaggimate.local --rebuild-index-first

# Export only settings and profiles.
uv run gaggimate-shot-backup gaggimate.local --skip-history

# Export profiles/history without shot notes.
uv run gaggimate-shot-backup gaggimate.local --skip-notes

# Continue a failed export into the same output directory.
uv run gaggimate-shot-backup gaggimate.local -o gaggimate-export --resume

# Export only SD-card-importable profiles and history, skipping settings.
uv run gaggimate-shot-backup gaggimate.local --skip-settings

# Use a longer timeout for unreliable Wi-Fi or large shot files.
uv run gaggimate-shot-backup gaggimate.local --timeout 60
```

## Manifest

Every export writes `manifest.json` at the output root. It records the source URL, export timestamp, tool version, exported counts, saved/missing history-file counts, and short SD-card import instructions.

## APIs Used

- `GET /api/settings` for settings.
- WebSocket `req:profiles:list` for full profiles.
- WebSocket `req:history:list` for shot metadata.
- `GET /api/history/index.bin` and `GET /api/history/<id>.slog` for SD-compatible history files.
- WebSocket `req:history:notes:get` for shot note JSON files.
