#!/usr/bin/env python3
"""Deploy only Codex's managed permission defaults, preserving all other settings.

No packages, credentials, trust entries or CLI login sessions are created.
Requires Python 3.11+. Close other config editors while applying.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import sys
import tempfile
import tomllib
import uuid

from toml_edit import EditError, merge_scalars

CHANGES = {
    ('approval_policy',): 'on-request',
    ('sandbox_mode',): 'workspace-write',
    ('sandbox_workspace_write', 'network_access'): True,
}
EXPECTED = {'approval_policy': 'on-request', 'sandbox_mode': 'workspace-write',
            'sandbox_workspace_write': {'network_access': True}}
MAX_SIZE = 4 * 1024 * 1024


class SettingsError(ValueError):
    pass


def default_target() -> Path:
    home = Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex')).expanduser()
    if not home.is_absolute():
        raise SettingsError('CODEX_HOME must be an absolute path')
    return home / 'config.toml'


def validate_template(path: Path) -> str:
    if path.stat().st_size > 65536:
        raise SettingsError('Template exceeds 64 KiB')
    text = path.read_text(encoding='utf-8')
    parsed = tomllib.loads(text)
    if parsed != EXPECTED or type(parsed['sandbox_workspace_write']['network_access']) is not bool:
        raise SettingsError('Template must contain only never, workspace-write and network_access=false')
    return text


def check_permissions(data: dict) -> None:
    if 'default_permissions' in data:
        raise SettingsError('default_permissions conflicts with sandbox_mode; explicitly migrate that '
                            'permission profile first. Existing file was not changed.')
    sandbox = data.get('sandbox_workspace_write', {})
    if not isinstance(sandbox, dict):
        raise SettingsError('sandbox_workspace_write must be a TOML table')
    if sandbox.get('writable_roots'):
        print('Codex: WARNING - existing writable_roots are retained; writes are not limited to cwd.',
              file=sys.stderr)
    profile = data.get('profile')
    if profile:
        profiles = data.get('profiles', {})
        active = profiles.get(profile, {}) if isinstance(profiles, dict) and isinstance(profile, str) else {}
        if not isinstance(active, dict):
            raise SettingsError('Invalid active profile table')
        controlled = {'approval_policy', 'sandbox_mode', 'sandbox_workspace_write', 'default_permissions'}
        if controlled.intersection(active):
            raise SettingsError('The selected legacy profile overrides permission settings. '
                                'Resolve that profile explicitly before applying these user defaults.')
        print('Codex: WARNING - selected profile may override user defaults; check effective permissions.',
              file=sys.stderr)


def snapshot(path: Path) -> tuple[bytes | None, tuple | None]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SettingsError('Config must be a regular file with no symlink/hardlink: ' + str(path))
    if info.st_size > MAX_SIZE:
        raise SettingsError('Config exceeds 4 MiB')
    raw = path.read_bytes()
    after = path.lstat()
    token = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if token != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise SettingsError('Concurrent config change detected while reading')
    return raw, token


def assert_unchanged(path: Path, before: tuple) -> None:
    if snapshot(path) != before:
        raise SettingsError('Concurrent config change detected; refusing to overwrite it')


def private_write(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def apply_file(path: Path, template: Path, dry_run: bool = False) -> Path | None:
    if not path.is_absolute():
        raise SettingsError('Target config path must be absolute')
    new_template = validate_template(template)
    # Do not traverse a redirected Codex directory or one of its symlink parents.
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink():
            raise SettingsError('Symlinked parent directory is not edited automatically: ' + str(parent))
    before = snapshot(path)
    original = before[0]
    has_bom = original is not None and original.startswith(b'\xef\xbb\xbf')
    text = original.decode('utf-8-sig') if original is not None else ''
    check_permissions(tomllib.loads(text))
    edited = merge_scalars(text, CHANGES) if original is not None else new_template
    print('Codex: target=' + str(path))
    print('Codex: approval_policy=never; sandbox_mode=workspace-write; command network_access=false')
    if edited == text:
        print('Codex: unchanged (already configured)')
        return None
    if dry_run:
        print('Codex: DRY RUN - no files or directories written; unrelated settings retained')
        return None
    payload = (b'\xef\xbb\xbf' if has_bom else b'') + edited.encode('utf-8')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert_unchanged(path, before)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex[:8]
    suffix = '.bak' if original is not None else '.WAS_ABSENT'
    backup = path.with_name(path.name + '.shell-setup-backup-' + stamp + suffix)
    fd, name = tempfile.mkstemp(prefix='.shell-setup-codex-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        assert_unchanged(path, before)
        private_write(backup, original if original is not None else b'Config did not exist before this run.\n')
        assert_unchanged(path, before)
        if original is None:
            # A concurrent create cannot be clobbered by an atomic rename.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        if path.read_bytes() != payload:
            raise SettingsError('Read-back mismatch; inspect config and backup before retrying')
    finally:
        temporary.unlink(missing_ok=True)
    print('Codex: backup=' + str(backup))
    print('Codex: UPDATED - start a new Codex session; /permissions can show session permissions')
    return backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--target', type=Path, help='Override the current environment\'s CODEX_HOME/config.toml')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        apply_file(args.target.expanduser() if args.target else default_target(), args.template, args.dry_run)
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print('Codex: ERROR - ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
