#!/usr/bin/env python3
"""Palette and install regression tests; real desktop settings are never used."""
from __future__ import annotations
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import terminal_palette as tp
import gnome_terminal as gt
import windows_terminal as wt

PROFILE = 'b1dcc9dd-5262-4d8d-a863-c897e6d979b9'
PALETTE = tp.load_palette(ROOT / 'terminal-palette.json')
GT_CONFIG = json.loads((ROOT / 'gnome-terminal.json').read_text())
WT_CONFIG = json.loads((ROOT / 'windows-terminal.json').read_text())
BEFORE = {
    'use-theme-colors': 'true', 'background-color': "'rgb(46,52,54)'",
    'foreground-color': "'rgb(238,238,236)'", 'use-theme-transparency': 'true',
    'background-transparency-percent': '50', 'use-transparent-background': 'false',
    'palette': "['#000000', '#000080']",
}
FIXTURE = '''// keep header
{
  "profiles": {"defaults": {"font": {"face": "Keep Mono"}}, "list": [
    {"name": "PowerShell", "opacity": 95},
    {"name": "Ubuntu", "opacity": 100, // keep profile comment
     "commandline": "wsl.exe", "custom": "//string /*not a comment*/",},
  ]},
  "actions": [{"command": "copy", "keys": "ctrl+shift+c"}],
}
'''


class PaletteTests(unittest.TestCase):
    def test_blue_order(self):
        colors = tp.ansi_palette(PALETTE)
        self.assertEqual(len(colors), 16)
        self.assertEqual(colors[4], '#6EA8FF')
        self.assertEqual(colors[12], '#9CCAFF')

    def test_same_scheme_name_background_opacity(self):
        self.assertEqual(WT_CONFIG['colorScheme'], PALETTE['name'])
        self.assertEqual(WT_CONFIG['background'], '#000000')
        self.assertFalse(WT_CONFIG['useAcrylic'])
        self.assertEqual(GT_CONFIG['opacity'], WT_CONFIG['opacity'])
        self.assertEqual(WT_CONFIG['opacity'], 75)

    def test_invalid_palette(self):
        for bad in ({}, {**PALETTE, 'blue': 'navy'}, {**PALETTE, 'extra': '#000000'},
                    {**PALETTE, 'name': ''}, {**PALETTE, 'blue': None}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tp.validate_palette(bad)

    def test_duplicate_json_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'p.json'
            path.write_text('{"name":"a", "name":"b"}')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                tp.load_palette(path)


class WindowsPaletteTests(unittest.TestCase):
    def edit(self, source=FIXTURE):
        return wt.update_text(source, WT_CONFIG, 'Ubuntu', palette=PALETTE)[0]

    def test_add_scheme_preserve_unrelated(self):
        result = self.edit()
        before = wt.Jsonc(FIXTURE).parse().value
        after = wt.Jsonc(result).parse().value
        expected = copy.deepcopy(before)
        expected['profiles']['list'][1].update(WT_CONFIG)
        expected['schemes'] = [tp.windows_scheme(PALETTE)]
        self.assertEqual(after, expected)
        self.assertIn('// keep header', result)
        self.assertIn('// keep profile comment', result)
        self.assertIn('"custom": "//string /*not a comment*/"', result)

    def test_idempotence(self):
        once = self.edit()
        self.assertEqual(once, self.edit(once))

    def test_insert_alongside_other_scheme_comments(self):
        source = FIXTURE.replace('"actions":', '"schemes": [// keep scheme comment\n'
                                 '{"name":"Keep","blue":"#111111"},],\n "actions":')
        result = self.edit(source)
        after = wt.Jsonc(result).parse().value
        self.assertIn('// keep scheme comment', result)
        self.assertEqual(after['schemes'][1], {'name': 'Keep', 'blue': '#111111'})

    def test_existing_scheme_updates_without_duplicates(self):
        source = FIXTURE.replace('"actions":', '"schemes": [{"name":"ShellSetup Dark",'
                                 '"blue":"#000080", "custom":"preserve"}],\n "actions":')
        result = self.edit(source)
        schemes = wt.Jsonc(result).parse().value['schemes']
        self.assertEqual(len(schemes), 1)
        self.assertEqual(schemes[0]['blue'], '#6EA8FF')
        self.assertEqual(schemes[0]['custom'], 'preserve')
        self.assertEqual(result, self.edit(result))

    def test_empty_array_with_comment(self):
        result = self.edit(FIXTURE.replace('"actions":', '"schemes": [/*keep*/], "actions":'))
        self.assertIn('/*keep*/', result)
        self.assertEqual(len(wt.Jsonc(result).parse().value['schemes']), 1)

    def test_duplicate_managed_scheme_refused(self):
        source = FIXTURE.replace('"actions":', '"schemes": [{"name":"ShellSetup Dark"},'
                                 '{"name":"ShellSetup Dark"}], "actions":')
        with self.assertRaisesRegex(wt.SettingsError, 'Duplicate managed'):
            self.edit(source)

    def test_invalid_scheme_shape(self):
        for invalid in ('null', '{}', '[1]', '[null]'):
            with self.subTest(invalid=invalid), self.assertRaises(wt.SettingsError):
                self.edit(FIXTURE.replace('"actions":', '"schemes": ' + invalid + ', "actions":'))

    def test_appearance_name_must_match(self):
        with self.assertRaisesRegex(wt.SettingsError, 'must match'):
            wt.update_text(FIXTURE, {**WT_CONFIG, 'colorScheme': 'Mismatch'}, 'Ubuntu', palette=PALETTE)

    def test_legacy_profiles(self):
        result = self.edit('{"profiles":[{"name":"Ubuntu"}]}')
        self.assertEqual(wt.Jsonc(result).parse().value['profiles'][0]['opacity'], 75)

    def test_crlf_bom_file_backup_dryrun(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            path = Path(tmp) / 'settings.json'
            original = b'\xef\xbb\xbf' + FIXTURE.replace('\n', '\r\n').encode()
            path.write_bytes(original)
            self.assertIsNone(wt.apply_file(path, WT_CONFIG, 'Ubuntu', dry_run=True, palette=PALETTE))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(tmp).iterdir()), [path])
            backup = wt.apply_file(path, WT_CONFIG, 'Ubuntu', palette=PALETTE)
            self.assertEqual(backup.read_bytes(), original)
            after = path.read_bytes()
            self.assertTrue(after.startswith(b'\xef\xbb\xbf'))
            self.assertNotIn(b'\n', after.replace(b'\r\n', b''))
            self.assertIsNone(wt.apply_file(path, WT_CONFIG, 'Ubuntu', palette=PALETTE))
            self.assertEqual(len(list(Path(tmp).glob('*.bak'))), 1)

    def test_existing_api_without_palette_still_works(self):
        edited, _ = wt.update_text(FIXTURE, {'opacity': 75}, 'Ubuntu')
        self.assertNotIn('schemes', wt.Jsonc(edited).parse().value)


class FakeSettings:
    def __init__(self):
        self.data = {**BEFORE, 'font': "'Preserve Font 13'"}
        self.writes = []
        self.locked = set()
        self.failure = None
    def run(self, *args):
        if args[0] == 'list-keys':
            return '\n'.join(self.data)
        if args[0] == 'writable':
            return 'false' if args[2] in self.locked else 'true'
        raise AssertionError(args)
    def get(self, schema, key):
        return self.data[key]
    def set(self, schema, key, value):
        self.writes.append((key, value))
        # Simulate GVariant's canonical spelling of an array.
        self.data[key] = json.dumps(gt.literal(value)) if key == 'palette' else value
        if self.failure == key:
            self.failure = None
            raise gt.SettingsError('Injected failure after mutation')


class GnomePaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backups = Path(self.tmp.name) / 'backups'
        self.client = FakeSettings()
        self.wanted = {**gt.desired_values(GT_CONFIG), 'palette': repr(tp.ansi_palette(PALETTE))}
    def apply(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return gt.apply_values(self.client, PROFILE, self.wanted, self.backups, **kwargs)

    def test_apply_backup_restore_and_unchanged_font(self):
        backup = self.apply()
        self.assertEqual(json.loads(backup.read_text())['values']['palette'], BEFORE['palette'])
        self.assertEqual(self.client.data['font'], "'Preserve Font 13'")
        self.assertEqual(gt.literal(self.client.data['palette'])[4], '#6EA8FF')
        self.assertEqual(self.client.data['background-transparency-percent'], '25')
        profile, values = gt.restore_values(backup)
        with redirect_stdout(io.StringIO()):
            gt.apply_values(self.client, profile, values, self.backups)
        self.assertEqual(gt.literal(self.client.data['palette']), gt.literal(BEFORE['palette']))

    def test_gvariant_normalization_idempotent(self):
        self.apply()
        count = len(self.client.writes)
        self.assertIsNone(self.apply())
        self.assertEqual(len(self.client.writes), count)
        self.assertTrue(gt.same_value('palette', '@as []', '[]'))

    def test_dry_run_no_writes(self):
        self.apply(dry_run=True)
        self.assertFalse(self.backups.exists())
        self.assertEqual(self.client.writes, [])

    def test_missing_palette_key_skips_all(self):
        self.client.data.pop('palette')
        with self.assertRaises(gt.Skip):
            self.apply()
        self.assertEqual(self.client.writes, [])

    def test_locked_palette_skips_all(self):
        self.client.locked.add('palette')
        with self.assertRaises(gt.Skip):
            self.apply()
        self.assertEqual(self.client.writes, [])

    def test_palette_failure_rolls_back(self):
        self.client.failure = 'palette'
        with self.assertRaisesRegex(gt.SettingsError, 'rolled back'):
            self.apply()
        for key, value in BEFORE.items():
            self.assertTrue(gt.same_value(key, value, self.client.data[key]))

    def test_invalid_backup_palette(self):
        for value in ('42', "'not an array'", '[1]', "['bad\\ncolor']"):
            with self.subTest(value=value), self.assertRaises(gt.SettingsError):
                gt.validate_values({'palette': value})
        self.assertEqual(gt.validate_values({'palette': '@as []'}), {'palette': '@as []'})

    def test_readback_quote_normalization(self):
        client = gt.GSettings()
        with mock.patch.object(client, 'run', side_effect=['', '["#000000"]']):
            client.set('schema', 'palette', "['#000000']")


@unittest.skipUnless(shutil.which('gsettings') and shutil.which('glib-compile-schemas'), 'GLib CLI tools unavailable')
class GnomeKeyfileIntegration(unittest.TestCase):
    def test_real_glib_palette_apply_restore(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            base = Path(tmp)
            schemas = base / 'schemas'
            schemas.mkdir()
            xml = '<schemalist><schema id="org.gnome.Terminal.ProfilesList" path="/org/gnome/terminal/legacy/profiles:/">'
            xml += '<key name="list" type="as"><default>[\'' + PROFILE + '\']</default></key>'
            xml += '<key name="default" type="s"><default>\'' + PROFILE + '\'</default></key></schema>'
            xml += '<schema id="org.gnome.Terminal.Legacy.Profile">'
            for key, raw in BEFORE.items():
                kind = 'as' if key == 'palette' else ('b' if key in gt.BOOL_KEYS else ('i' if key.endswith('-percent') else 's'))
                xml += f'<key name="{key}" type="{kind}"><default>{escape(raw)}</default></key>'
            xml += '<key name="font" type="s"><default>\'Keep Font 12\'</default></key></schema></schemalist>'
            (schemas / 'test.gschema.xml').write_text(xml)
            subprocess.run(['glib-compile-schemas', '--strict', str(schemas)], check=True, capture_output=True)
            env = {'GSETTINGS_SCHEMA_DIR': str(schemas), 'GSETTINGS_BACKEND': 'keyfile',
                   'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_STATE_HOME': str(base / 'state')}
            with mock.patch.dict(os.environ, env):
                client = gt.GSettings()
                chosen = gt.choose_profile(client)
                target = gt.target_schema(chosen)
                wanted = {**gt.desired_values(GT_CONFIG), 'palette': repr(tp.ansi_palette(PALETTE))}
                before = {k: client.get(target, k) for k in wanted}
                backup = gt.apply_values(client, chosen, wanted, gt.backup_root())
                self.assertEqual(gt.literal(client.get(target, 'palette'))[4], '#6EA8FF')
                self.assertEqual(client.get(target, 'font'), "'Keep Font 12'")
                self.assertIsNone(gt.apply_values(client, chosen, wanted, gt.backup_root()))
                profile, old = gt.restore_values(backup)
                gt.apply_values(client, profile, old, gt.backup_root())
                for key, value in before.items():
                    self.assertTrue(gt.same_value(key, client.get(target, key), value))


class InstallIntegration(unittest.TestCase):
    def test_persistent_tools_temp_home_reinstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / 'home'
            home.mkdir()
            (home / '.bashrc').write_text('# Keep CUDA and ROS\nexport CUSTOM_ROS=keep\n')
            (home / '.tmux.conf').write_text('# Existing customization\nset -g history-limit 5000\n')
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SHELL_SETUP_', 'XDG_', 'WSL_', 'SSH_', 'GSETTINGS_', 'CODEX_'))}
            env.pop('SUDO_USER', None)
            env['HOME'] = str(home)
            env['XDG_CONFIG_HOME'] = str(home / '.config')
            cmd = ['bash', str(ROOT / 'install.sh'), '--skip-packages', '--skip-fzf', '--skip-installers']
            for _ in range(2):
                p = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            installed = home / '.config/shell-setup'
            self.assertIn('export CUSTOM_ROS=keep', (home / '.bashrc').read_text())
            self.assertEqual((home / '.bashrc').read_text().count('# >>> shell-setup >>>'), 1)
            self.assertEqual((home / '.tmux.conf').read_text().count('# >>> shell-setup >>>'), 1)
            self.assertIn('history-limit 5000', (home / '.tmux.conf').read_text())
            for filename in ('configure-codex.sh', 'configure-terminal.sh', 'lib/codex_config.py',
                             'lib/terminal_palette.py', 'lib/toml_edit.py', 'terminal-palette.json',
                             'installers/03-configure_gnome_terminal.sh', 'installers/04-configure_codex.sh'):
                self.assertTrue((installed / filename).is_file(), filename)
            # Execute from the persistent copy, with no repository root override.
            p = subprocess.run(['bash', str(installed / 'configure-codex.sh')], cwd=base,
                               env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertTrue((home / '.codex/config.toml').is_file())
            p = subprocess.run(['bash', str(installed / 'configure-terminal.sh'), '--dry-run'],
                               cwd=base, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('SKIP', p.stdout)

    def test_bash_syntax(self):
        for path in [*ROOT.glob('*.sh'), *ROOT.glob('installers/*.sh'), *ROOT.glob('lib/*.sh'), ROOT / 'bashrc.common']:
            with self.subTest(path=path):
                p = subprocess.run(['bash', '-n', str(path)], text=True, capture_output=True, timeout=10)
                self.assertEqual(p.returncode, 0, p.stderr)

    def test_tmux_and_vim_defaults_static(self):
        tmux = (ROOT / 'tmux.conf.common').read_text()
        self.assertIn('set -g mouse off', tmux)
        self.assertNotIn('set -g mouse on', tmux)
        self.assertIn("bind m set-option -g mouse \\; display-message", tmux)
        bashrc = (ROOT / 'bashrc.common').read_text()
        self.assertIn('"${SHELL_SETUP_VIM_MOUSE:-0}" == 1', bashrc)

    @unittest.skipUnless(shutil.which('tmux'), 'tmux not installed; run on the target host')
    def test_tmux_private_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            socket = str(base / 'socket')
            env = dict(os.environ)
            env.pop('TMUX', None)
            command = ['tmux', '-S', socket]
            try:
                subprocess.run(command + ['-f', str(ROOT / 'tmux.conf.common'), 'new-session', '-d', '-s', 'test'],
                               env=env, check=True, capture_output=True, timeout=10)
                p = subprocess.run(command + ['show-options', '-gv', 'mouse'], env=env,
                                   check=True, text=True, capture_output=True, timeout=10)
                self.assertEqual(p.stdout.strip(), 'off')
                subprocess.run(command + ['set-option', '-g', 'mouse'], env=env, check=True,
                               capture_output=True, timeout=10)
                p = subprocess.run(command + ['show-options', '-gv', 'mouse'], env=env,
                                   check=True, text=True, capture_output=True, timeout=10)
                self.assertEqual(p.stdout.strip(), 'on')
            finally:
                subprocess.run(command + ['kill-server'], env=env, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
