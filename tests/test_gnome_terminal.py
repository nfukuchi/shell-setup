#!/usr/bin/env python3
"""No desktop settings are touched: unit tests use fakes; integration uses a private keyfile backend."""
from __future__ import annotations
from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import gnome_terminal as gt

PROFILE = 'b1dcc9dd-5262-4d8d-a863-c897e6d979b9'
SECOND = 'cb3ecc22-300d-4453-b9fb-d9d7b29d33c2'
CONFIG = {'background': '#000000', 'foreground': '#D3D7CF', 'opacity': 75}
BEFORE = {
    'use-theme-colors': 'true', 'background-color': "'rgb(46,52,54)'",
    'foreground-color': "'rgb(238,238,236)'", 'use-theme-transparency': 'true',
    'background-transparency-percent': '50', 'use-transparent-background': 'false',
}


class FakeSettings:
    def __init__(self):
        self.data = dict(BEFORE)
        self.data['font'] = "'Unchanged Font 12'"
        self.schemas = [gt.LIST_SCHEMA]
        self.relocatable = [gt.PROFILE_SCHEMA]
        self.available = set(self.data)
        self.profiles = [PROFILE, SECOND]
        self.default = PROFILE
        self.locked = set()
        self.writes = []
        self.failure = None

    def run(self, *args):
        if args[0] == 'list-schemas':
            return '\n'.join(self.schemas)
        if args[0] == 'list-relocatable-schemas':
            return '\n'.join(self.relocatable)
        if args[0] == 'list-keys':
            return '\n'.join(sorted(self.available))
        if args[0] == 'writable':
            return 'false' if args[2] in self.locked else 'true'
        raise AssertionError(args)

    def get(self, schema, key):
        if schema == gt.LIST_SCHEMA:
            return repr(self.profiles if key == 'list' else self.default)
        if schema != gt.target_schema(PROFILE):
            raise AssertionError('Unexpected profile modified: ' + schema)
        return self.data[key]

    def set(self, schema, key, value):
        if schema != gt.target_schema(PROFILE):
            raise AssertionError('Unexpected profile modified: ' + schema)
        self.writes.append((key, value))
        self.data[key] = value
        if self.failure == key:
            self.failure = None
            raise gt.SettingsError('simulated write failure after mutation')


class ConfigTests(unittest.TestCase):
    def test_opacity_conversion(self):
        for opacity in (0, 50, 75, 100):
            with self.subTest(opacity=opacity):
                value = gt.desired_values({**CONFIG, 'opacity': opacity})
                self.assertEqual(value['background-transparency-percent'], str(100 - opacity))
                self.assertEqual(value['use-transparent-background'], 'false' if opacity == 100 else 'true')

    def test_no_acrylic_key_native(self):
        with self.assertRaises(gt.SettingsError):
            gt.validate_config({**CONFIG, 'useAcrylic': False})

    def test_reject_bad_config(self):
        bad = [{}, {**CONFIG, 'opacity': True}, {**CONFIG, 'opacity': 0.75},
               {**CONFIG, 'opacity': -1}, {**CONFIG, 'opacity': 101},
               {**CONFIG, 'background': 'black'}, {**CONFIG, 'foreground': None}]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(gt.SettingsError):
                gt.validate_config(data)

    def test_literal_profile_lists(self):
        self.assertEqual(gt.literal('@as []'), [])
        self.assertEqual(gt.literal(repr([PROFILE])), [PROFILE])
        with self.assertRaises(gt.SettingsError):
            gt.literal('unquoted')

    def test_uuid_validation(self):
        for value in ('', 'Default', '../other', '{' + PROFILE + '}', None):
            with self.subTest(value=value), self.assertRaises(gt.SettingsError):
                gt.checked_uuid(value)
        self.assertIn(PROFILE, gt.target_schema(PROFILE))

    def test_backup_value_validation(self):
        for values in ({'font': "'12'"}, {'use-theme-colors': 'TRUE'},
                       {'background-transparency-percent': '-1'},
                       {'background-transparency-percent': '101'},
                       {'background-color': '42'}, {'foreground-color': None}):
            with self.subTest(values=values), self.assertRaises(gt.SettingsError):
                gt.validate_values(values)
        self.assertEqual(gt.validate_values(BEFORE), BEFORE)

    def test_source_defaults(self):
        native = json.loads((ROOT / 'gnome-terminal.json').read_text())
        windows = json.loads((ROOT / 'windows-terminal.json').read_text())
        self.assertEqual(native['opacity'], 75)
        self.assertEqual(native['background'], '#000000')
        self.assertFalse(windows['useAcrylic'])
        self.assertEqual(windows['opacity'], native['opacity'])


class ProfileTests(unittest.TestCase):
    def test_default_profile(self):
        self.assertEqual(gt.choose_profile(FakeSettings()), PROFILE)

    def test_explicit_profile(self):
        self.assertEqual(gt.choose_profile(FakeSettings(), SECOND), SECOND)

    def test_missing_default_profile_skips(self):
        c = FakeSettings()
        c.profiles = [SECOND]
        with self.assertRaises(gt.Skip):
            gt.choose_profile(c)

    def test_duplicate_profile_skips(self):
        c = FakeSettings()
        c.profiles.append(PROFILE)
        with self.assertRaises(gt.Skip):
            gt.choose_profile(c)

    def test_missing_schema_skips(self):
        c = FakeSettings()
        c.schemas = []
        with self.assertRaises(gt.Skip):
            gt.choose_profile(c)
        c.schemas = [gt.LIST_SCHEMA]
        c.relocatable = []
        with self.assertRaises(gt.Skip):
            gt.choose_profile(c)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'backups'
        self.client = FakeSettings()
        self.wanted = gt.desired_values(CONFIG)
        self.output = io.StringIO()

    def apply(self, **kwargs):
        with redirect_stdout(self.output):
            return gt.apply_values(self.client, PROFILE, self.wanted, self.directory, **kwargs)

    def test_dry_run_no_writes_or_directories(self):
        self.assertIsNone(self.apply(dry_run=True))
        self.assertFalse(self.client.writes)
        self.assertFalse(self.directory.exists())
        self.assertIn('DRY RUN', self.output.getvalue())

    def test_apply_target_keys_and_private_backup(self):
        backup = self.apply()
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        data = json.loads(backup.read_text())
        self.assertEqual(data['values'], BEFORE)
        self.assertEqual(self.client.data['font'], "'Unchanged Font 12'")
        for key, value in self.wanted.items():
            self.assertEqual(self.client.data[key], value)

    def test_idempotent(self):
        self.apply()
        count = len(self.client.writes)
        self.assertIsNone(self.apply())
        self.assertEqual(len(self.client.writes), count)
        self.assertEqual(len(list(self.directory.glob('*.json'))), 1)

    def test_missing_transparency_no_partial_changes(self):
        self.client.available.remove('use-theme-transparency')
        with self.assertRaises(gt.Skip):
            self.apply()
        self.assertFalse(self.client.writes)
        self.assertFalse(self.directory.exists())

    def test_locked_no_changes(self):
        self.client.locked.add('background-color')
        with self.assertRaises(gt.Skip):
            self.apply()
        self.assertFalse(self.client.writes)

    def test_write_failure_rolls_back(self):
        self.client.failure = 'foreground-color'
        with self.assertRaisesRegex(gt.SettingsError, 'rolled back'):
            self.apply()
        for key, value in BEFORE.items():
            self.assertEqual(self.client.data[key], value)
        self.assertEqual(len(list(self.directory.glob('*.json'))), 1)

    def test_concurrent_edit_prevents_write(self):
        original = self.client.get
        count = 0
        def changed(schema, key):
            nonlocal count
            count += 1
            if count == 7:
                self.client.data['use-theme-colors'] = 'false'
            return original(schema, key)
        self.client.get = changed
        with self.assertRaisesRegex(gt.SettingsError, 'Concurrent'):
            self.apply()
        self.assertFalse(self.client.writes)
        self.assertFalse(self.directory.exists())

    def test_backup_failure_prevents_writes(self):
        with mock.patch.object(gt, 'write_backup', side_effect=OSError('read-only')):
            with self.assertRaises(OSError):
                self.apply()
        self.assertFalse(self.client.writes)

    def test_restore_effective_values_only(self):
        backup = self.apply()
        profile, values = gt.restore_values(backup)
        self.assertEqual(profile, PROFILE)
        self.client.data['font'] = "'Another Font 13'"
        with redirect_stdout(self.output):
            gt.apply_values(self.client, profile, values, self.directory)
        for key, value in BEFORE.items():
            self.assertEqual(self.client.data[key], value)
        self.assertEqual(self.client.data['font'], "'Another Font 13'")

    def test_restore_rejects_other_host_or_user(self):
        backup = self.apply()
        data = json.loads(backup.read_text())
        data['uid'] += 1
        backup.write_text(json.dumps(data))
        with self.assertRaises(gt.SettingsError):
            gt.restore_values(backup)

    def test_duplicate_json_refused(self):
        p = Path(self.temp.name) / 'invalid.json'
        p.write_text('{"opacity":75,"opacity":50}')
        with self.assertRaises(gt.SettingsError):
            gt.read_json(p)

    def test_main_invalid_config_nonzero(self):
        p = Path(self.temp.name) / 'invalid.json'
        p.write_text('{"opacity":75}')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(gt.main(['--config', str(p)]), 1)

    def test_relative_state_home_rejected(self):
        with mock.patch.dict(os.environ, {'XDG_STATE_HOME': 'relative/path'}):
            with self.assertRaises(gt.SettingsError):
                gt.backup_root()

    def test_zero_exit_dconf_error_not_success(self):
        result = subprocess.CompletedProcess([], 0, '', 'dconf-WARNING: failed to commit changes')
        with mock.patch.object(subprocess, 'run', return_value=result):
            with self.assertRaises(gt.SettingsError):
                gt.GSettings().run('set', gt.target_schema(PROFILE), 'use-theme-colors', 'false')

    def test_readback_mismatch_not_success(self):
        client = gt.GSettings()
        with mock.patch.object(client, 'run', side_effect=['', 'true']):
            with self.assertRaises(gt.SettingsError):
                client.set(gt.target_schema(PROFILE), 'use-theme-colors', 'false')


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(('SHELL_SETUP_', 'WSL_', 'SSH_', 'GSETTINGS_')) or key in {
                'SUDO_USER', 'DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS'
            }:
                del self.env[key]
        self.env['PATH'] = str(self.bin) + os.pathsep + self.env['PATH']
        self.script = ROOT / 'installers/03-configure_gnome_terminal.sh'
        self.add_tool('id', 'printf 1000')
        self.add_tool('grep', 'exit 1')

    def add_tool(self, name, body):
        p = self.bin / name
        p.write_text('#!/usr/bin/env bash\n' + body + '\n')
        p.chmod(0o755)

    def run_script(self, *args):
        return subprocess.run(['bash', str(self.script), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def test_headless_skip(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('no graphical display', result.stdout)

    def test_ssh_skip(self):
        self.env['SSH_CONNECTION'] = 'a b c d'
        self.assertIn('SSH session', self.run_script().stdout)

    def test_wsl_skip(self):
        self.env['WSL_DISTRO_NAME'] = 'Ubuntu-24.04'
        self.assertIn('WSL;', self.run_script().stdout)

    def test_root_skip(self):
        self.add_tool('id', 'printf 0')
        self.assertIn('root/sudo session', self.run_script().stdout)

    def test_sudo_user_skip(self):
        self.env['SUDO_USER'] = 'another'
        self.assertIn('root/sudo session', self.run_script().stdout)

    def test_global_optout(self):
        self.env['SHELL_SETUP_TERMINAL_APPEARANCE'] = '0'
        self.assertIn('disabled', self.run_script().stdout)

    def test_native_optout(self):
        self.env['SHELL_SETUP_GNOME_TERMINAL'] = '0'
        self.assertIn('disabled', self.run_script().stdout)

    def test_missing_bus_skip(self):
        self.env['DISPLAY'] = ':1'
        self.assertIn('no desktop D-Bus', self.run_script().stdout)

    def test_unreachable_bus_skip(self):
        self.env.update(DISPLAY=':1', DBUS_SESSION_BUS_ADDRESS='unix:path=/example')
        self.add_tool('gdbus', 'exit 1')
        self.assertIn('not reachable', self.run_script().stdout)

    def test_nonpersistent_backend_skip(self):
        self.env.update(DISPLAY=':1', DBUS_SESSION_BUS_ADDRESS='example', GSETTINGS_BACKEND='memory')
        self.assertIn('non-dconf', self.run_script().stdout)

    def test_x11_and_wayland_dispatch(self):
        self.add_tool('gdbus', 'exit 0')
        self.add_tool('python3', 'printf "CALLED %s\\n" "$@"')
        for display in ('DISPLAY', 'WAYLAND_DISPLAY'):
            with self.subTest(display=display):
                self.env.pop('DISPLAY', None)
                self.env.pop('WAYLAND_DISPLAY', None)
                self.env[display] = 'test-display'
                self.env['DBUS_SESSION_BUS_ADDRESS'] = 'test-bus'
                result = self.run_script('--dry-run')
                self.assertEqual(result.returncode, 0)
                self.assertIn('gnome_terminal.py', result.stdout)
                self.assertIn('--dry-run', result.stdout)

    def test_dispatcher_native(self):
        self.script = ROOT / 'configure-terminal.sh'
        self.assertIn('no graphical display', self.run_script().stdout)


@unittest.skipUnless(shutil.which('gsettings') and shutil.which('glib-compile-schemas'), 'GLib CLI tools unavailable')
class PrivateBackendIntegrationTests(unittest.TestCase):
    """Uses actual gsettings processes with an isolated, non-desktop keyfile backend.

    The fixture mirrors the relevant interface; it is not Ubuntu's packaged binary/schema.
    """
    def test_real_gsettings_apply_restore_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            schemas = base / 'schemas'
            schemas.mkdir()
            xml = '<schemalist><schema id="org.gnome.Terminal.ProfilesList" path="/org/gnome/terminal/legacy/profiles:/">'
            xml += '<key name="list" type="as"><default>[\'' + PROFILE + '\']</default></key>'
            xml += '<key name="default" type="s"><default>\'' + PROFILE + '\'</default></key></schema>'
            xml += '<schema id="org.gnome.Terminal.Legacy.Profile">'
            for key, raw in BEFORE.items():
                kind = 'b' if key in gt.BOOL_KEYS else ('i' if key.endswith('-percent') else 's')
                xml += f'<key name="{key}" type="{kind}"><default>{raw}</default></key>'
            xml += '<key name="font" type="s"><default>\'Unchanged Font 12\'</default></key></schema></schemalist>'
            (schemas / 'test.gschema.xml').write_text(xml)
            subprocess.run(['glib-compile-schemas', '--strict', str(schemas)], check=True, capture_output=True)
            env = {'GSETTINGS_SCHEMA_DIR': str(schemas), 'GSETTINGS_BACKEND': 'keyfile',
                   'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_STATE_HOME': str(base / 'state')}
            with mock.patch.dict(os.environ, env), redirect_stdout(io.StringIO()):
                client = gt.GSettings()
                selected = gt.choose_profile(client)
                target = gt.target_schema(selected)
                wanted = gt.desired_values(CONFIG)
                before = {k: client.get(target, k) for k in wanted}
                backup = gt.apply_values(client, selected, wanted, gt.backup_root())
                self.assertIsNotNone(backup)
                self.assertEqual(client.get(target, 'background-transparency-percent'), '25')
                self.assertEqual(client.get(target, 'font'), "'Unchanged Font 12'")
                self.assertIsNone(gt.apply_values(client, selected, wanted, gt.backup_root()))
                profile, old = gt.restore_values(backup)
                gt.apply_values(client, profile, old, gt.backup_root())
                self.assertEqual({k: client.get(target, k) for k in wanted}, before)


if __name__ == '__main__':
    unittest.main()
