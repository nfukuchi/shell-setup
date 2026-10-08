#!/usr/bin/env python3
"""GNOME Terminal appearance via gsettings, using only Python's standard library.

The Bash wrapper enforces local desktop/WSL/SSH/root/session guards. This module
is platform-independent for tests. Only appearance keys in ONE existing
profile are managed; no profiles are created and no defaults are reassigned.
Backups capture effective values, not whether each key was explicitly set.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import uuid
from typing import Any
from terminal_palette import ansi_palette, load_palette
LIST_SCHEMA = 'org.gnome.Terminal.ProfilesList'
PROFILE_SCHEMA = 'org.gnome.Terminal.Legacy.Profile'
KEYS = {
    'use-theme-colors', 'background-color', 'foreground-color',
    'use-theme-transparency', 'use-transparent-background',
    'background-transparency-percent', 'palette',
}
BOOL_KEYS = {'use-theme-colors', 'use-theme-transparency', 'use-transparent-background'}


class SettingsError(ValueError):
    """Invalid data or a write that could not be verified."""

class Skip(SettingsError):
    """Unsupported environment or profile; no changes should be made."""


def checked_uuid(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}', value
    ):
        raise SettingsError(f'Invalid GNOME Terminal profile UUID: {value!r}')
    return value


def target_schema(profile: str) -> str:
    return f'{PROFILE_SCHEMA}:/org/gnome/terminal/legacy/profiles:/:{checked_uuid(profile)}/'

def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result

def read_json(path: Path) -> Any:
    if not path.is_file() or path.stat().st_size > 65536:
        raise SettingsError(f'Expected a JSON file no larger than 64 KiB: {path}')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)

def validate_config(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {'background', 'foreground', 'opacity'}:
        raise SettingsError('gnome-terminal.json must contain exactly background, foreground, opacity; useAcrylic is Windows-only')
    for key in ('background', 'foreground'):
        if not isinstance(data[key], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', data[key]):
            raise SettingsError(f'{key} must be a #rrggbb string')
    if type(data['opacity']) is not int or not 0 <= data['opacity'] <= 100:
        raise SettingsError('opacity must be an integer from 0 through 100')
    return data

def desired_values(config: dict[str, Any]) -> dict[str, str]:
    config = validate_config(config)
    # Both configuration files use percent OPAQUE. GNOME's key is percent TRANSPARENT.
    return {
        'use-theme-colors': 'false',
        'background-color': repr(config['background']),
        'foreground-color': repr(config['foreground']),
        'use-theme-transparency': 'false',
        'background-transparency-percent': str(100 - config['opacity']),
        'use-transparent-background': 'true' if config['opacity'] < 100 else 'false',
    }

def literal(value: str) -> Any:
    if value.startswith('@as '):
        value = value[4:]
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise SettingsError(f'Unexpected gsettings value: {value!r}') from exc

def validate_values(values: Any) -> dict[str, str]:
    if not isinstance(values, dict) or not values or set(values) - KEYS:
        raise SettingsError('Backup must contain only supported appearance keys')
    for key, raw in values.items():
        if not isinstance(raw, str) or len(raw) > 4096 or '\x00' in raw:
            raise SettingsError(f'Invalid value for {key}')
        if key in BOOL_KEYS:
            if raw not in ('true', 'false'):
                raise SettingsError(f'Expected boolean for {key}')
        elif key == 'background-transparency-percent':
            if not re.fullmatch(r'(?:100|[1-9]?[0-9])', raw):
                raise SettingsError('Invalid background-transparency-percent')
        elif key == 'palette':
            colors = literal(raw)
            # Existing effective values may be empty or use rgb()/rgba(); keep
            # backups restorable. New palettes are validated strictly as 16 hex colors.
            if not isinstance(colors, list) or len(colors) > 256 or any(
                not isinstance(c, str) or len(c) > 128 or any(ord(ch) < 32 for ch in c)
                for c in colors
            ):
                raise SettingsError('Expected an array of color strings for palette')
        elif not isinstance(literal(raw), str):
            raise SettingsError(f'Expected a color string for {key}')
    return values

def same_value(key: str, first: str, second: str) -> bool:
    # gsettings may change string quoting or emit an @as type annotation.
    return literal(first) == literal(second) if key == 'palette' else first == second


class GSettings:
    def run(self, *args: str) -> str:
        try:
            completed = subprocess.run(
                ['gsettings', *args], text=True, capture_output=True, timeout=15,
                env={**os.environ, 'LC_ALL': 'C'},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SettingsError(f'gsettings could not run: {exc}') from exc
        # dconf can emit a failure on stderr even when an operation exits zero.
        if completed.returncode or completed.stderr.strip():
            raise SettingsError(f'gsettings {args[0]} failed: {completed.stderr.strip() or completed.stdout.strip()}')
        return completed.stdout.strip()
    def get(self, schema: str, key: str) -> str:
        return self.run('get', schema, key)

    def set(self, schema: str, key: str, value: str) -> None:
        self.run('set', schema, key, value)
        # A separate process reads back from the backend, rather than an in-process cache.
        if not same_value(key, self.get(schema, key), value):
            raise SettingsError(f'Read-back mismatch for {key}; value was not confirmed')

def choose_profile(client: GSettings, explicit: str | None = None) -> str:
    if LIST_SCHEMA not in client.run('list-schemas').splitlines():
        raise Skip('GNOME Terminal schemas are missing; this does not configure Ptyxis, Console, Konsole, or VS Code')
    if PROFILE_SCHEMA not in client.run('list-relocatable-schemas').splitlines():
        raise Skip('GNOME Terminal profile schema is missing')
    profiles = literal(client.get(LIST_SCHEMA, 'list'))
    if not isinstance(profiles, list) or any(not isinstance(p, str) for p in profiles):
        raise SettingsError('Unexpected GNOME Terminal profile list')
    selected = explicit if explicit is not None else literal(client.get(LIST_SCHEMA, 'default'))
    checked_uuid(selected)
    if profiles.count(selected) != 1:
        raise Skip('Selected/default profile is not in the profile list exactly once; open GNOME Terminal once or select --profile UUID')
    return selected

def ensure_keys(client: GSettings, schema: str, keys: set[str]) -> None:
    available = set(client.run('list-keys', schema).splitlines())
    missing = keys - available
    if missing:
        raise Skip('This GNOME Terminal build lacks required appearance keys: ' + ', '.join(sorted(missing)) + '; nothing changed')
    locked = [key for key in sorted(keys) if client.run('writable', schema, key) != 'true']
    if locked:
        raise Skip('Appearance keys are locked: ' + ', '.join(locked) + '; nothing changed')

def backup_root() -> Path:
    base = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    if not base.is_absolute():
        raise SettingsError('XDG_STATE_HOME must be an absolute path')
    return base / 'shell-setup/terminal-backups'

def write_backup(directory: Path, profile: str, before: dict[str, str]) -> Path:
    # No backup/dir creation happens until a change is both needed and requested.
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise SettingsError('Backup directory must not be a symlink')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    path = directory / f'gnome-terminal-{profile}-{stamp}-{uuid.uuid4().hex[:8]}.json'
    payload = {
        'format': 'shell-setup-gnome-terminal-v1',
        'profile': profile, 'uid': os.getuid(), 'hostname': socket.gethostname(),
        'created_utc': stamp,
        'note': 'Effective values only; restore makes them explicit user overrides.',
        'values': before,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    return path

def apply_values(client: GSettings, profile: str, wanted: dict[str, str],
                 directory: Path, dry_run: bool = False) -> Path | None:
    wanted = validate_values(wanted)
    schema = target_schema(profile)
    ensure_keys(client, schema, set(wanted))
    before = {key: client.get(schema, key) for key in wanted}
    validate_values(before)
    changes = {key: value for key, value in wanted.items() if not same_value(key, value, before[key])}
    print(f'GNOME Terminal: profile={profile}')
    if not changes:
        print('GNOME Terminal: unchanged (already configured)')
        return None
    for key, value in changes.items():
        print(f'  {key}: {before[key]} -> {value}')
    if dry_run:
        print('GNOME Terminal: DRY RUN - no settings or backup files written')
        return None
    # Optimistic concurrency checks; keep the Preferences UI closed while applying.
    if any(not same_value(key, client.get(schema, key), before[key]) for key in wanted):
        raise SettingsError('Concurrent settings edit; nothing was written')
    backup = write_backup(directory, profile, {key: before[key] for key in changes})
    print(f'GNOME Terminal: backup={backup}')
    attempted: list[str] = []
    try:
        for key, value in changes.items():
            if not same_value(key, client.get(schema, key), before[key]):
                raise SettingsError(f'Concurrent edit to {key}; stopped')
            attempted.append(key)
            client.set(schema, key, value)
        if any(not same_value(key, client.get(schema, key), value) for key, value in wanted.items()):
            raise SettingsError('Final verification failed')
    except (SettingsError, OSError, KeyboardInterrupt) as exc:
        failures = []
        for key in reversed(attempted):
            try:
                current = client.get(schema, key)
                if same_value(key, current, changes[key]):
                    client.set(schema, key, before[key])
                elif not same_value(key, current, before[key]):
                    failures.append(key + ' (changed externally; left untouched)')
            except (SettingsError, OSError):
                failures.append(key)
        if failures:
            raise SettingsError(f'Write failed: {exc}. Rollback incomplete: {failures}. Backup: {backup}') from exc
        raise SettingsError(f'Write failed: {exc}. Attempted changes rolled back; backup: {backup}') from exc
    print('GNOME Terminal: UPDATED - managed settings read back successfully; check the desktop appearance')
    return backup

def restore_values(path: Path) -> tuple[str, dict[str, str]]:
    data = read_json(path)
    if not isinstance(data, dict) or data.get('format') != 'shell-setup-gnome-terminal-v1':
        raise SettingsError('Not a GNOME Terminal backup created by this add-on')
    if data.get('uid') != os.getuid() or data.get('hostname') != socket.gethostname():
        raise SettingsError('Backup belongs to another user or host; refusing automatic restore')
    return checked_uuid(data.get('profile')), validate_values(data.get('values'))

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--palette-config', type=Path)
    parser.add_argument('--profile', help='Existing profile UUID; defaults to the GNOME Terminal default profile')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--restore', type=Path, help='Restore effective values from this add-on backup')
    args = parser.parse_args(argv)
    try:
        client = GSettings()
        if args.restore:
            profile, values = restore_values(args.restore)
            if args.profile and args.profile != profile:
                raise SettingsError('--profile differs from the backup profile')
            choose_profile(client, profile)
        else:
            if args.config is None:
                raise SettingsError('--config is required when not restoring')
            values = desired_values(read_json(args.config))
            if args.palette_config:
                values['palette'] = repr(ansi_palette(load_palette(args.palette_config)))
            profile = choose_profile(client, args.profile)
        apply_values(client, profile, values, backup_root(), args.dry_run)
        return 0
    except Skip as exc:
        print(f'GNOME Terminal: SKIP - {exc}')
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print(f'GNOME Terminal: ERROR - {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
