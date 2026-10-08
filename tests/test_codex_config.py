#!/usr/bin/env python3
"""Codex settings tests: temporary files only; no Codex execution or login."""
from __future__ import annotations
from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import codex_config as cc
from toml_edit import EditError, equivalent, merge_scalars

TEMPLATE = ROOT / 'codex-config.toml'


class MergeTests(unittest.TestCase):
    def check(self, source: str) -> str:
        result = merge_scalars(source, cc.CHANGES)
        self.assertEqual(merge_scalars(result, cc.CHANGES), result)
        parsed = tomllib.loads(result)
        self.assertEqual(parsed['approval_policy'], 'never')
        self.assertEqual(parsed['sandbox_mode'], 'workspace-write')
        self.assertIs(parsed['sandbox_workspace_write']['network_access'], False)
        return result

    def test_empty(self):
        self.check('')

    def test_comment_only_no_newline(self):
        self.assertTrue(self.check('# Keep this comment').startswith('# Keep this comment\n'))

    def test_existing_scalar_comment_spacing(self):
        source = 'approval_policy  =  "on-request" # keep\nsandbox_mode="read-only"\n'
        result = self.check(source)
        self.assertIn('approval_policy  =  "never" # keep', result)
        self.assertIn('sandbox_mode="workspace-write"', result)

    def test_preserve_models_mcp_project(self):
        source = ('# header\nmodel="my-model"\nmodel_reasoning_effort="high"\n'
                  '[mcp_servers.example]\ncommand="example"\nargs=["x", "y"]\n'
                  '[projects."/home/test/project"]\ntrust_level="trusted"\n')
        result = self.check(source)
        self.assertIn(source[source.index('[mcp_servers'):], result)
        data = tomllib.loads(result)
        self.assertEqual(data['model'], 'my-model')
        self.assertEqual(data['model_reasoning_effort'], 'high')
        self.assertEqual(data['mcp_servers']['example']['args'], ['x', 'y'])

    def test_existing_sandbox_table_and_roots(self):
        source = '[sandbox_workspace_write] # keep header\nwritable_roots=["/tmp/demo"]\n'
        result = self.check(source)
        self.assertIn('# keep header', result)
        self.assertEqual(tomllib.loads(result)['sandbox_workspace_write']['writable_roots'], ['/tmp/demo'])

    def test_dotted_and_quoted_keys(self):
        source = ('"approval_policy" = "on-request"\n'
                  "'sandbox_workspace_write'.'network_access' = true # net\n")
        result = self.check(source)
        self.assertIn("'sandbox_workspace_write'.'network_access' = false # net", result)

    def test_quoted_table_key(self):
        self.check('["sandbox_workspace_write"]\nnetwork_access = true\n')

    def test_unrelated_nested_key_not_changed(self):
        source = '[mcp_servers.example]\napproval_policy="keep-me"\nnetwork_access=true\n'
        result = self.check(source)
        self.assertIn(source, result)

    def test_multiline_basic_string_fake_settings(self):
        source = ('instructions = """\n[sandbox_workspace_write]\nnetwork_access=true\n'
                  'approval_policy="fake"\n# not a comment\n"""\n')
        result = self.check(source)
        self.assertIn(source, result)

    def test_multiline_literal_string(self):
        source = "instructions = '''\napproval_policy=\"fake\"\n# body\n'''\n"
        self.assertIn(source, self.check(source))

    def test_multiline_string_four_five_quotes(self):
        for n in (4, 5):
            source = 'x = """hello' + '"' * n + '\n'
            with self.subTest(n=n):
                self.assertIn(source, self.check(source))

    def test_arrays_comments_and_array_tables(self):
        source = ('args=[\n"#x", # comment\n"[sandbox_workspace_write]",\n]\n'
                  '[[tasks]]\napproval_policy="keep"\n[[tasks]]\nname="second"\n')
        self.assertIn(source, self.check(source))

    def test_eof_table(self):
        self.check('[sandbox_workspace_write]')

    def test_crlf(self):
        result = self.check('# h\r\napproval_policy="on-request"\r\n[sandbox_workspace_write]\r\n')
        self.assertNotIn('\n', result.replace('\r\n', ''))

    def test_inline_sandbox_fails_closed(self):
        with self.assertRaisesRegex(EditError, 'inline table'):
            self.check('sandbox_workspace_write = { network_access = true }\n')

    def test_already_correct_inline_sandbox(self):
        source = ('approval_policy="never"\nsandbox_mode="workspace-write"\n'
                  'sandbox_workspace_write = { network_access = false }\n')
        self.assertEqual(self.check(source), source)

    def test_bad_parent_type(self):
        with self.assertRaises(EditError):
            self.check('sandbox_workspace_write = 1\n')

    def test_managed_table_needs_explicit_migration(self):
        with self.assertRaisesRegex(EditError, 'declared as a table'):
            self.check('[approval_policy.reject]\nsandbox_approval=true\n')

    def test_granular_inline_policy_replace(self):
        result = self.check('approval_policy = { reject = { sandbox_approval = true } } # policy\n')
        self.assertIn('approval_policy = "never" # policy', result)

    def test_nan_unknown_value_preserved(self):
        result = self.check('unknown = nan\n')
        self.assertTrue(equivalent(tomllib.loads('x=nan'), tomllib.loads('x=nan')))
        self.assertIn('unknown = nan', result)

    def test_invalid_toml_rejected(self):
        for source in ('a=', 'a=1\na=2', 'approval_policy="unclosed'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.check(source)

    def test_implicit_parent_table(self):
        self.check('[sandbox_workspace_write.extra]\nname="retain"\n')


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.path = self.base / 'codex/config.toml'
        self.out, self.err = io.StringIO(), io.StringIO()

    def apply(self, **kwargs):
        with redirect_stdout(self.out), redirect_stderr(self.err):
            return cc.apply_file(self.path, TEMPLATE, **kwargs)

    def write(self, text):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(text)

    def test_new_file_and_private_marker(self):
        marker = self.apply()
        self.assertTrue(marker.name.endswith('.WAS_ABSENT'))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        self.assertEqual(tomllib.loads(self.path.read_text()), cc.EXPECTED)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_exact_backup_preserve_bom_crlf(self):
        self.path.parent.mkdir()
        before = b'\xef\xbb\xbf# mine\r\nmodel="custom"\r\napproval_policy="on-request"\r\n'
        self.path.write_bytes(before)
        backup = self.apply()
        self.assertEqual(backup.read_bytes(), before)
        after = self.path.read_bytes()
        self.assertTrue(after.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', after.replace(b'\r\n', b''))

    def test_idempotent_no_extra_backups(self):
        self.apply()
        before = self.path.stat()
        self.assertIsNone(self.apply())
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(len(list(self.path.parent.glob('*.shell-setup-backup-*'))), 1)

    def test_dry_run_new_no_directory(self):
        self.assertIsNone(self.apply(dry_run=True))
        self.assertFalse(self.path.parent.exists())
        self.assertIn('DRY RUN', self.out.getvalue())

    def test_dry_run_existing_no_leak(self):
        text = '[mcp_servers.demo.env]\nTOKEN="secret-value-not-for-output"\n'
        self.write(text)
        self.apply(dry_run=True)
        self.assertEqual(self.path.read_text(), text)
        self.assertNotIn('secret-value', self.out.getvalue() + self.err.getvalue())
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_symlink_refused(self):
        self.path.parent.mkdir()
        original = self.base / 'real.toml'
        original.write_text('model="keep"')
        self.path.symlink_to(original)
        with self.assertRaises(cc.SettingsError):
            self.apply()
        self.assertEqual(original.read_text(), 'model="keep"')

    def test_hardlink_refused(self):
        self.write('model="keep"')
        os.link(self.path, self.base / 'hard.toml')
        with self.assertRaises(cc.SettingsError):
            self.apply()

    def test_parent_symlink_refused(self):
        real = self.base / 'real'
        real.mkdir()
        self.path.parent.symlink_to(real, target_is_directory=True)
        with self.assertRaises(cc.SettingsError):
            self.apply()
        self.assertEqual(list(real.iterdir()), [])

    def test_malformed_no_write(self):
        self.write('not valid TOML')
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.path.read_text(), 'not valid TOML')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_default_permissions_conflict(self):
        self.write('default_permissions="custom"\n')
        with self.assertRaisesRegex(cc.SettingsError, 'default_permissions'):
            self.apply()
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_selected_legacy_profile_conflict(self):
        self.write('profile="fast"\n[profiles.fast]\napproval_policy="on-request"\n')
        with self.assertRaisesRegex(cc.SettingsError, 'selected legacy profile'):
            self.apply()

    def test_inactive_profile_preserved(self):
        self.write('[profiles.other]\napproval_policy="on-request"\n')
        self.apply()
        self.assertEqual(tomllib.loads(self.path.read_text())['profiles']['other']['approval_policy'], 'on-request')

    def test_existing_roots_warning(self):
        self.write('[sandbox_workspace_write]\nwritable_roots=["/work/extra"]\n')
        self.apply()
        self.assertIn('writable_roots', self.err.getvalue())
        self.assertEqual(tomllib.loads(self.path.read_text())['sandbox_workspace_write']['writable_roots'], ['/work/extra'])

    def test_concurrent_change_no_overwrite(self):
        self.write('model="original"\n')
        original_check = cc.assert_unchanged
        calls = 0
        def changed(path, before):
            nonlocal calls
            calls += 1
            if calls == 2:
                path.write_text('model="external-change"\n')
            return original_check(path, before)
        with mock.patch.object(cc, 'assert_unchanged', changed):
            with self.assertRaisesRegex(cc.SettingsError, 'Concurrent'):
                self.apply()
        self.assertEqual(self.path.read_text(), 'model="external-change"\n')
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_new_concurrent_create_preserved(self):
        original_write = cc.private_write
        def changed(path, raw):
            original_write(path, raw)
            self.path.write_text('model="created-externally"\n')
        with mock.patch.object(cc, 'private_write', changed):
            with self.assertRaisesRegex(cc.SettingsError, 'Concurrent'):
                self.apply()
        self.assertEqual(self.path.read_text(), 'model="created-externally"\n')

    def test_bad_template_no_directory(self):
        bad = self.base / 'bad.toml'
        bad.write_text('sandbox_mode="danger-full-access"')
        with self.assertRaises(cc.SettingsError), redirect_stdout(self.out):
            cc.apply_file(self.path, bad)
        self.assertFalse(self.path.parent.exists())

    def test_default_target_custom_codex_home(self):
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(self.base / 'custom')}):
            self.assertEqual(cc.default_target(), self.base / 'custom/config.toml')
        with mock.patch.dict(os.environ, {'CODEX_HOME': 'relative'}):
            with self.assertRaises(cc.SettingsError):
                cc.default_target()

    def test_wrapper_ssh_allowed_dry_run(self):
        env = dict(os.environ, CODEX_HOME=str(self.path.parent), SSH_CONNECTION='a b c d')
        env.pop('SUDO_USER', None)
        env.pop('SHELL_SETUP_ROOT', None)
        p = subprocess.run(['bash', str(ROOT / 'configure-codex.sh'), '--dry-run'],
                           env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('DRY RUN', p.stdout)
        self.assertFalse(self.path.parent.exists())

    def test_wrapper_sudo_rejected(self):
        p = subprocess.run(['bash', str(ROOT / 'configure-codex.sh')],
                           env={**os.environ, 'SUDO_USER': 'test'},
                           text=True, capture_output=True, timeout=10)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('not with sudo', p.stderr)

    def test_wrapper_optout(self):
        p = subprocess.run(['bash', str(ROOT / 'configure-codex.sh')],
                           env={**os.environ, 'SHELL_SETUP_CODEX_CONFIGURE': '0'},
                           text=True, capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 0)
        self.assertIn('SKIP', p.stdout)


if __name__ == '__main__':
    unittest.main()
