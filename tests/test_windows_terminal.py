#!/usr/bin/env python3
"""Run with: python3 -m unittest discover -s tests -p 'test_windows_terminal.py' -v"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import windows_terminal as wt

GUID = "{f9c0a133-b768-5d5b-b900-41c2b1960376}"
APPEARANCE = {"colorScheme": "Tango Dark", "background": "#000000", "opacity": 75, "useAcrylic": False}
FIXTURE = r'''// This header must survive.
{
    "$schema": "https://aka.ms/terminal-profiles-schema",
    "profiles": {
        "defaults": {"font": {"face": "Example Mono", "size": 13}},
        "list": [
            {"name": "Windows PowerShell", "opacity": 95, "background": "#111111"},
            {
                // Keep this Ubuntu comment.
                "guid": "{f9c0a133-b768-5d5b-b900-41c2b1960376}",
                "name": "Ubuntu-24.04",
                "source": "Windows.Terminal.Wsl",
                "commandline": "wsl.exe -d Ubuntu-24.04",
                "startingDirectory": "C:\\Users\\Sample User",
                "opacity": 100, // Keep the end-of-line comment too.
                "custom": "// Not a comment: /* sample */ and \"quoted\"",
            },
            {"name": "Ubuntu-22.04", "opacity": 90},
        ],
    },
    "actions": [{"command": "copy", "keys": "ctrl+c"}],
}
'''


class JsoncTests(unittest.TestCase):
    def test_comments_and_trailing_commas(self):
        result = wt.Jsonc('/*x*/ {"a": [1, true, null,], // y\n "b": {},}').parse().value
        self.assertEqual(result, {"a": [1, True, None], "b": {}})

    def test_strings_with_comment_markers(self):
        value = wt.Jsonc(FIXTURE).parse().value
        self.assertEqual(value["$schema"], "https://aka.ms/terminal-profiles-schema")
        self.assertIn('/* sample */', value["profiles"]["list"][1]["custom"])

    def test_reject_ambiguous_or_malformed_json(self):
        for text in ['{"a":1,"a":2}', '{"a":1,,}', '{"a":}', '[,]', '{',
                     '{"a":1} garbage', '{"a":NaN}', '{"a":Infinity}', '{"a":01}',
                     '{unquoted: 1}', '// comment only', '{"a":1 /*never closed']:
            with self.subTest(text=text), self.assertRaises(wt.SettingsError):
                wt.Jsonc(text).parse()

    def test_reject_excessive_nesting(self):
        with self.assertRaises(wt.SettingsError):
            wt.Jsonc('[' * 140 + '0' + ']' * 140).parse()


class EditTests(unittest.TestCase):
    def test_target_only_and_comments_retained(self):
        result, _ = wt.update_text(FIXTURE, APPEARANCE, "Ubuntu-24.04")
        before = wt.Jsonc(FIXTURE).parse().value
        after = wt.Jsonc(result).parse().value
        expected = json.loads(json.dumps(before))
        expected["profiles"]["list"][1].update(APPEARANCE)
        self.assertEqual(after, expected)
        for comment in ["// This header must survive.", "// Keep this Ubuntu comment.",
                        "// Keep the end-of-line comment too."]:
            self.assertIn(comment, result)
        self.assertIn('"$schema": "https://aka.ms/terminal-profiles-schema"', result)
        self.assertIn('"name": "Windows PowerShell", "opacity": 95', result)

    def test_idempotent(self):
        once, _ = wt.update_text(FIXTURE, APPEARANCE, "Ubuntu-24.04")
        twice, _ = wt.update_text(once, APPEARANCE, "Ubuntu-24.04")
        self.assertEqual(once, twice)

    def test_guid_for_renamed_profile(self):
        source = FIXTURE.replace('"name": "Ubuntu-24.04"', '"name": "My GPU Console"')
        result, target = wt.update_text(source, APPEARANCE, "does-not-exist", GUID.upper())
        self.assertEqual(target["name"], "My GPU Console")
        self.assertEqual(wt.Jsonc(result).parse().value["profiles"]["list"][1]["opacity"], 75)

    def test_dont_guess_missing_profile(self):
        with self.assertRaises(wt.SelectionError):
            wt.update_text(FIXTURE, APPEARANCE, "Ubuntu")

    def test_dont_guess_duplicate_profile_names(self):
        source = '{"profiles":{"list":[{"name":"Ubuntu"},{"name":"Ubuntu"}]}}'
        with self.assertRaises(wt.SelectionError):
            wt.update_text(source, APPEARANCE, "Ubuntu")

    def test_legacy_profile_array(self):
        source = '{"profiles":[{"name":"Ubuntu","opacity":100,}],"other":42}'
        result, _ = wt.update_text(source, APPEARANCE, "Ubuntu")
        after = wt.Jsonc(result).parse().value
        self.assertEqual(after["profiles"][0]["opacity"], 75)
        self.assertEqual(after["other"], 42)

    def test_crlf_remains_crlf(self):
        source = FIXTURE.replace('\n', '\r\n')
        result, _ = wt.update_text(source, APPEARANCE, "Ubuntu-24.04")
        self.assertNotIn('\n', result.replace('\r\n', ''))

    def test_unicode_path_and_name_preserved(self):
        source = '{"profiles":{"list":[{"name":"Ubuntu", "directory":"C:\\\\Users\\\\\u5c71\u7530"}]}}'
        result, _ = wt.update_text(source, APPEARANCE, "Ubuntu")
        self.assertIn('\u5c71\u7530', result)

    def test_only_existing_keys_changed(self):
        source = '{"profiles":{"list":[{"name":"Ubuntu","opacity":100,"useAcrylic":false}]}}'
        result, _ = wt.update_text(source, {"opacity": 75}, "Ubuntu")
        self.assertEqual(result, source.replace('"opacity":100', '"opacity":75'))

    def test_invalid_appearance(self):
        for config in [{}, {"opacity": True}, {"opacity": 0.75}, {"opacity": 101},
                       {"opacity": -1}, {"background": "black"}, {"useAcrylic": 1},
                       {"colorScheme": ""}, {"commandline": "unwanted.exe"}]:
            with self.subTest(config=config), self.assertRaises(wt.SettingsError):
                wt.validate_appearance(config)

    def test_invalid_profiles_shape(self):
        for source in ['{}', '{"profiles":null}', '{"profiles":{"list":{}}}',
                       '{"profiles":{"list":[null]}}']:
            with self.subTest(source=source), self.assertRaises(wt.SettingsError):
                wt.update_text(source, APPEARANCE, "Ubuntu")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "settings.json"
        self.original = b'\xef\xbb\xbf' + FIXTURE.replace('\n', '\r\n').encode('utf-8')
        self.path.write_bytes(self.original)
        self.config = self.root / "appearance.json"
        self.config.write_text(json.dumps(APPEARANCE), encoding="utf-8")

    def quiet_apply(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return wt.apply_file(self.path, APPEARANCE, "Ubuntu-24.04", **kwargs)

    def test_backup_and_bom(self):
        backup = self.quiet_apply()
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertTrue(self.path.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_second_run_does_not_backup_again(self):
        self.quiet_apply()
        self.assertIsNone(self.quiet_apply())
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_dry_run_writes_nothing(self):
        self.assertIsNone(self.quiet_apply(dry_run=True))
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('*.bak')))
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_symlink_refused(self):
        link = self.root / 'symlink.json'
        link.symlink_to(self.path)
        with self.assertRaises(wt.SettingsError):
            wt.apply_file(link, APPEARANCE, "Ubuntu-24.04")
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_corrupt_json_not_written_or_backed_up(self):
        self.path.write_bytes(b'{ broken')
        with self.assertRaises(wt.SettingsError):
            self.quiet_apply()
        self.assertEqual(self.path.read_bytes(), b'{ broken')
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_detect_concurrent_edit(self):
        edited_externally = self.original + b'\r\n// another editor\r\n'
        real_read = Path.read_bytes
        count = 0
        def read(path):
            nonlocal count
            if path == self.path:
                count += 1
                if count == 2:
                    self.path.write_bytes(edited_externally)
            return real_read(path)
        with mock.patch.object(Path, 'read_bytes', read):
            with self.assertRaises(wt.SettingsError):
                self.quiet_apply()
        self.assertEqual(self.path.read_bytes(), edited_externally)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_missing_settings_not_created(self):
        with redirect_stdout(io.StringIO()):
            code = wt.main(['--local-app-data', str(self.root), '--config', str(self.config),
                            '--profile', 'Ubuntu-24.04'])
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_multiple_terminal_installations_not_guessed(self):
        for relative in ['Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json',
                         'Packages/Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe/LocalState/settings.json']:
            file = self.root / relative
            file.parent.mkdir(parents=True)
            file.write_bytes(self.original)
        with redirect_stdout(io.StringIO()):
            code = wt.main(['--local-app-data', str(self.root), '--config', str(self.config),
                            '--profile', 'Ubuntu-24.04'])
        self.assertEqual(code, 0)
        self.assertEqual(len(wt.find_settings(self.root)), 2)
        self.assertFalse(list(self.root.rglob('*.bak')))

    def test_main_validation_failure_returns_nonzero(self):
        self.path.write_bytes(b'not json')
        with redirect_stderr(io.StringIO()):
            code = wt.main(['--settings', str(self.path), '--config', str(self.config),
                            '--profile', 'Ubuntu-24.04'])
        self.assertEqual(code, 1)


class BashIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(('SHELL_SETUP_', 'WSL_')) or key in {'SSH_CONNECTION', 'SSH_TTY', 'SSH_CLIENT'}:
                del self.env[key]
        self.env['PATH'] = str(self.bin) + os.pathsep + self.env['PATH']
        self.script = ROOT / 'installers/02-configure_windows_terminal.sh'

    def run_script(self, *args):
        return subprocess.run(['bash', str(self.script), *args], env=self.env,
                              text=True, capture_output=True, timeout=15)

    def test_non_wsl_skips(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('not a local WSL', result.stdout)

    def test_ssh_skips_even_when_wsl_variable_exists(self):
        self.env['WSL_DISTRO_NAME'] = 'Ubuntu-24.04'
        self.env['SSH_CONNECTION'] = '127.0.0.1 123 127.0.0.1 22'
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('SSH session', result.stdout)

    def test_opt_out(self):
        self.env['SHELL_SETUP_WINDOWS_TERMINAL'] = '0'
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('disabled', result.stdout)

    def test_unknown_argument_fails(self):
        self.assertEqual(self.run_script('--wrong-flag').returncode, 2)

    def test_mocked_wsl_apply_and_dry_run_with_spaced_path(self):
        # Replace only WSL kernel detection; no Windows executable is needed when
        # an explicit settings path is provided. This is not a Windows GUI test.
        grep = self.bin / 'grep'
        grep.write_text('#!/bin/sh\nexit 0\n')
        grep.chmod(0o755)
        self.env['WSL_DISTRO_NAME'] = 'Ubuntu-24.04'
        settings = self.root / 'folder with spaces' / 'settings.json'
        settings.parent.mkdir()
        settings.write_text(FIXTURE)
        self.env['SHELL_SETUP_WT_SETTINGS'] = str(settings)
        result = self.run_script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DRY RUN', result.stdout)
        self.assertEqual(settings.read_text(), FIXTURE)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('UPDATED', result.stdout)
        self.assertEqual(wt.Jsonc(settings.read_text()).parse().value['profiles']['list'][1]['opacity'], 75)
        result = self.run_script()
        self.assertIn('already configured', result.stdout)

    def test_mocked_windows_appdata_discovery(self):
        for name, text in {
            'grep': '#!/bin/sh\nexit 0\n',
            'powershell.exe': '#!/bin/sh\nprintf "C:\\\\Users\\\\Sample\\\\AppData\\\\Local"\n',
            'wslpath': '#!/bin/sh\nprintf "%s" "$MOCK_LOCALAPPDATA"\n',
        }.items():
            file = self.bin / name
            file.write_text(text)
            file.chmod(0o755)
        self.env['WSL_DISTRO_NAME'] = 'Ubuntu-24.04'
        self.env['MOCK_LOCALAPPDATA'] = str(self.root / 'Windows LocalAppData')
        settings = Path(self.env['MOCK_LOCALAPPDATA']) / 'Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(FIXTURE)
        result = self.run_script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DRY RUN', result.stdout)
        self.assertEqual(settings.read_text(), FIXTURE)


if __name__ == '__main__':
    unittest.main()
