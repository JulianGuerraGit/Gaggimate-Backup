#!/usr/bin/env python3

import argparse
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests
import websocket


TOOL_VERSION = "0.2.0"


class ExportError(RuntimeError):
    pass


def normalize_base_url(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host


def ws_url_from_base(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/ws"


def padded_shot_id(shot_id: object) -> str:
    return str(shot_id).strip().zfill(6)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def ws_request(base_url: str, payload: dict, timeout: float = 10.0) -> dict:
    url = ws_url_from_base(base_url)
    rid = payload.get("rid", f"backup-{int(time.time() * 1000)}")
    payload["rid"] = rid

    ws = websocket.create_connection(url, timeout=timeout)
    try:
        ws.send(json.dumps(payload))

        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ws.recv()
            msg = json.loads(raw)

            # Ignore status/event pushes. Wait for the matching response.
            if msg.get("rid") == rid:
                if msg.get("error"):
                    raise ExportError(f"{payload['tp']} failed: {msg['error']}")
                return msg

        raise TimeoutError(f"Timed out waiting for WebSocket response to {payload['tp']}")
    finally:
        ws.close()


def http_json(base_url: str, path: str, timeout: float) -> dict:
    url = f"{base_url}{path}"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def download_history_file(base_url: str, remote_name: str, out_path: Path, timeout: float) -> bool:
    url = f"{base_url}/api/history/{remote_name}"
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            if response.status_code == 404:
                print(f"missing: history/{remote_name}")
                return False
            response.raise_for_status()

            with tmp_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)

        tmp_path.replace(out_path)
        print(f"saved:   history/{remote_name}")
        return True
    except requests.exceptions.Timeout:
        print(f"timeout: history/{remote_name}")
        tmp_path.unlink(missing_ok=True)
        return False
    except Exception as exc:
        print(f"error:   history/{remote_name}: {exc}")
        tmp_path.unlink(missing_ok=True)
        return False


def export_settings(base_url: str, backup_dir: Path, timeout: float) -> dict | None:
    print("requesting settings...")
    try:
        settings = http_json(base_url, "/api/settings", timeout)
    except Exception as exc:
        print(f"warning: settings export failed: {exc}")
        return None

    write_json(backup_dir / "settings" / "settings.json", settings)
    print("saved:   settings/settings.json")
    return settings


def export_profiles(base_url: str, backup_dir: Path, sdcard_dir: Path, timeout: float) -> list[dict]:
    print("requesting profiles...")
    response = ws_request(base_url, {"tp": "req:profiles:list"}, timeout=timeout)
    profiles = response.get("profiles", [])
    if not isinstance(profiles, list):
        raise ExportError(f"unexpected profiles response: {response}")

    write_json(backup_dir / "profiles" / "profiles.json", profiles)
    print(f"found {len(profiles)} profiles")

    for index, profile in enumerate(profiles):
        profile_id = str(profile.get("id") or f"profile-{index + 1}").strip()
        if not profile_id:
            profile_id = f"profile-{index + 1}"

        filename = f"{profile_id}.json"
        backup_path = backup_dir / "profiles" / filename
        write_json(backup_path, profile)
        copy_file(backup_path, sdcard_dir / "p" / filename)
        print(f"saved:   profiles/{filename}")

    return profiles


def export_history(
    base_url: str,
    backup_dir: Path,
    sdcard_dir: Path,
    timeout: float,
    skip_notes: bool,
    rebuild_index_first: bool,
) -> tuple[list[dict], dict]:
    if rebuild_index_first:
        print("requesting history index rebuild...")
        try:
            response = ws_request(base_url, {"tp": "req:history:rebuild"}, timeout=timeout)
            print(f"rebuild response: {response}")
            print("waiting 5 seconds for rebuild to start/finish...")
            time.sleep(5)
        except Exception as exc:
            print(f"warning: rebuild request failed: {exc}")

    print("requesting history list...")
    response = ws_request(base_url, {"tp": "req:history:list"}, timeout=timeout)
    history = response.get("history", [])
    if not isinstance(history, list):
        raise ExportError(f"unexpected history response: {response}")

    write_json(backup_dir / "history" / "history.json", history)
    print(f"found {len(history)} shot entries")

    stats = {
        "history_files_saved": 0,
        "history_files_failed_or_missing": 0,
        "notes_saved": 0,
        "notes_empty_or_missing": 0,
    }

    if download_history_file(base_url, "index.bin", backup_dir / "history" / "index.bin", timeout):
        copy_file(backup_dir / "history" / "index.bin", sdcard_dir / "h" / "index.bin")
        stats["history_files_saved"] += 1
    else:
        stats["history_files_failed_or_missing"] += 1

    for item in history:
        raw_shot_id = str(item.get("id", "")).strip()
        if not raw_shot_id:
            continue
        shot_id = padded_shot_id(raw_shot_id)

        slog_name = f"{shot_id}.slog"
        slog_path = backup_dir / "history" / slog_name
        if download_history_file(base_url, slog_name, slog_path, timeout):
            copy_file(slog_path, sdcard_dir / "h" / slog_name)
            stats["history_files_saved"] += 1
        else:
            stats["history_files_failed_or_missing"] += 1

        if not skip_notes:
            notes = fetch_notes(base_url, shot_id, timeout)
            if notes:
                notes_path = backup_dir / "history" / f"{shot_id}.json"
                write_json(notes_path, notes)
                copy_file(notes_path, sdcard_dir / "h" / f"{shot_id}.json")
                stats["notes_saved"] += 1
                print(f"saved:   history/{shot_id}.json")
            else:
                stats["notes_empty_or_missing"] += 1

    return history, stats


def fetch_notes(base_url: str, shot_id: str, timeout: float) -> dict | None:
    try:
        response = ws_request(
            base_url,
            {"tp": "req:history:notes:get", "id": shot_id},
            timeout=timeout,
        )
    except Exception:
        return None

    notes = response.get("notes")
    if isinstance(notes, dict) and notes:
        return notes
    return None


def create_zip(export_dir: Path) -> Path:
    zip_path = export_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(export_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(export_dir.parent))

    return zip_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export GaggiMate settings, profiles, and shot history for backup or SD-card migration."
    )
    parser.add_argument(
        "host",
        help="Display host or URL, for example gaggimate.local, 192.168.4.1, or http://192.168.1.50",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="gaggimate-export",
        help="Output folder. Default: gaggimate-export",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP/WebSocket timeout per request in seconds. Default: 20",
    )
    parser.add_argument(
        "--skip-settings",
        action="store_true",
        help="Do not export /api/settings.",
    )
    parser.add_argument(
        "--skip-profiles",
        action="store_true",
        help="Do not export profiles.",
    )
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Do not export shot history.",
    )
    parser.add_argument(
        "--skip-notes",
        action="store_true",
        help="Do not export shot note JSON files.",
    )
    parser.add_argument(
        "--rebuild-index-first",
        action="store_true",
        help="Ask the display to rebuild /h/index.bin before exporting history.",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Create a .zip archive after exporting.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    base_url = normalize_base_url(args.host)
    export_dir = Path(args.output)
    backup_dir = export_dir / "backup"
    sdcard_dir = export_dir / "sdcard"
    backup_dir.mkdir(parents=True, exist_ok=True)
    sdcard_dir.mkdir(parents=True, exist_ok=True)

    print(f"display: {base_url}")
    print(f"output:  {export_dir.resolve()}")
    print()

    manifest: dict[str, object] = {
        "tool": "gaggimate-shot-backup",
        "tool_version": TOOL_VERSION,
        "base_url": base_url,
        "downloaded_at": int(time.time()),
        "backup_dir": "backup",
        "sdcard_dir": "sdcard",
        "sdcard_import": {
            "profiles": "Copy sdcard/p to the SD card root as /p.",
            "shot_history": "Copy sdcard/h to the SD card root as /h.",
            "settings": "settings/settings.json is a Web UI settings export; firmware settings are not loaded from SD card.",
        },
    }

    try:
        if not args.skip_settings:
            settings = export_settings(base_url, backup_dir, args.timeout)
            manifest["settings_exported"] = settings is not None

        if not args.skip_profiles:
            profiles = export_profiles(base_url, backup_dir, sdcard_dir, args.timeout)
            manifest["profile_count"] = len(profiles)

        if not args.skip_history:
            history, stats = export_history(
                base_url,
                backup_dir,
                sdcard_dir,
                args.timeout,
                args.skip_notes,
                args.rebuild_index_first,
            )
            manifest["history_count"] = len(history)
            manifest.update(stats)

        write_json(export_dir / "manifest.json", manifest)
        print()
        print(f"manifest: {export_dir / 'manifest.json'}")

        if args.zip:
            zip_path = create_zip(export_dir)
            print(f"zip:      {zip_path}")

        print()
        print("done")
        print(f"backup:  {backup_dir}")
        print(f"sd card: {sdcard_dir}")
        return 0

    except Exception as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
