# Dark palette, Codex sandbox defaults, and tmux selection

Add-on version: **2026.10.07.1**. This is a shell-setup patch identifier, not an
upstream product release. Supported target: Ubuntu 24.04 / Ubuntu 24.04 in WSL.
Python 3.11+ is required for Codex's TOML validation; no pip/TOML package is needed.

## What changes

- `terminal-palette.json` defines one shared ANSI 16-color palette. Normal blue
  is `#6EA8FF`; bright blue is `#9CCAFF`. GNOME's selected/default profile and
  the existing WSL Windows Terminal profile use it. The source defaults remain
  black background, 75% opacity; Windows acrylic remains off. As before,
  applying appearance settings reapplies those source defaults (it does not
  preserve a different manually set opacity). Edit the JSON files first to
  keep another opacity. RGB/extra-256-color themes in apps are not overridden.
- `codex-config.toml` manages only `approval_policy = "never"`,
  `sandbox_mode = "workspace-write"`, and
  `[sandbox_workspace_write] network_access = false`.
- tmux starts with `mouse off`. Prefix then `m` toggles capture. With capture
  off use terminal drag-selection and its Copy action (GNOME: Ctrl+Shift+C).
  With capture on, Shift+drag normally bypasses application mouse capture.
  Prefix is Ctrl+b unless you changed it. Prefix+m replaces tmux's default
  mark-pane binding. Mouse pane selection/resizing/wheel history require capture
  on; keyboard copy-mode remains available (Prefix+[). tmux buffers and the OS
  clipboard are different; this patch does not install clipboard synchronization.
  Native selection can span adjacent panes: zoom the pane with Prefix+z first
  or use copy-mode when necessary.
- shell-setup no longer forces Vim `mouse=a`. To opt in, define
  `SHELL_SETUP_VIM_MOUSE=1` before loading `bashrc.common`. An existing `.vimrc`
  or a different Vim alias can still enable mouse capture. Open a fresh shell
  after changing this setting; an already defined alias is not silently removed.

## Apply only these settings (no APT/npm/fzf installation)

Run as the normal target user, **not with sudo**, in the patched repository:

```bash
bash configure-codex.sh --dry-run
bash configure-terminal.sh --dry-run
bash install.sh --skip-packages --skip-fzf --skip-installers
bash configure-codex.sh
bash configure-terminal.sh
```

The install step persists common Bash/Readline/tmux settings and configuration
tools into `${XDG_CONFIG_HOME:-$HOME/.config}/shell-setup`. It skips every
installer, so the two explicit configuration commands after it are required.
It does not install tmux: use a normal full install first on a new system.

`bash install.sh` is the full alternative: existing package/fzf/agent installers
run, followed by the appearance and new `04-configure_codex.sh` installer.
It is not the configuration-only command and may access the network.

**Where to run:** GNOME appearance must run inside the Ubuntu graphical user's
terminal with a reachable desktop D-Bus, not an SSH shell. Windows appearance
must run in the local WSL shell, not on an SSH server. The display/backend guards
are intentional; `SKIP` is not evidence that appearance was changed. Codex/tmux
settings are installed on each host where Codex/tmux runs, including SSH servers.
A remote server's palette setting does not recolor your local Windows Terminal.

Reload an existing tmux server without stopping sessions:

```bash
# Run on the tmux host, in a tmux session:
tmux source-file "$HOME/.tmux.conf"
tmux show-options -gv mouse     # expected: off
```

Close the terminal Preferences editor while applying. New tabs/sessions may be
needed to see appearance changes. Start a **new Codex session** after applying.

## Codex boundaries and existing settings

The target is `${CODEX_HOME:-$HOME/.codex}/config.toml`. A custom CODEX_HOME must
be an absolute path. WSL and an SSH server have separate homes/configs.
`never` suppresses approval prompts; it does not grant unrestricted host access
or permission to exceed the sandbox. An operation needing denied access should
fail or be handled another way. Do not add `--yolo` / dangerous bypass flags.
The network setting concerns commands inside the sandbox, not the Codex service
connection or necessarily every built-in tool.

Comments, model/effort choices, MCP servers, project records and unrelated fields
are preserved. Credentials/history are neither copied nor checked into Git.
No automatic trust entries are added. Existing additional `writable_roots` are
preserved **with a warning**; audit them before interpreting workspace-write as
cwd-only. Initial login, workspace trust prompts and application onboarding are
not command-approval prompts and may still occur.

This patch edits user defaults. CLI overrides, named profiles, trusted project
`.codex/config.toml`, session changes and organization requirements may override
or constrain them. Check the active session's `/permissions` screen. A root
`default_permissions` setting conflicts with the legacy sandbox configuration:
the helper refuses to mix them. A selected legacy `[profiles.NAME]` containing
permission overrides is also refused; review that profile explicitly.

The format-preserving editor understands ordinary/quoted/dotted keys, comments,
arrays and multiline strings. It verifies the full TOML before/after every edit.
For a managed nested key inside an inline table, e.g.
`sandbox_workspace_write = { network_access = true }`, it stops **without
writing**. Expand that declaration manually to a regular table first:

```toml
[sandbox_workspace_write]
network_access = true
# Keep other fields originally in the inline table here.
```

Then rerun the helper. A managed policy declared as its own table (rather than a
scalar/inline assignment) also needs explicit migration. Invalid TOML, ambiguous
structures, symlink/hardlink targets and concurrent changes cause an error, not
a wholesale rewrite. Close other editors while applying: this is optimistic
concurrency protection, not locking that other applications honor.

Dry runs write no settings, backups or directories and do not print the whole
Codex config (which may contain secrets). New/modified configs and backups are
mode 0600. Already-correct configs are not rewritten. The helper can be disabled
in a full install with `SHELL_SETUP_CODEX_CONFIGURE=0`.

## Persistent tools and customization

After installing, the repository clone is no longer needed for these commands:

```bash
CONFIG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/shell-setup"
bash "$CONFIG_ROOT/configure-terminal.sh" --dry-run
bash "$CONFIG_ROOT/configure-codex.sh" --dry-run
```

Edit `terminal-palette.json` for color changes. Keep its name and the
`windows-terminal.json` colorScheme name equal. Change opacity independently in
`gnome-terminal.json` / `windows-terminal.json` (0=transparent, 100=opaque).
The GNOME helper converts opacity to GNOME's transparency percentage.
`SHELL_SETUP_PALETTE_CONFIG=/absolute/path/palette.json` selects a different
palette file. Existing backend-specific settings/profile overrides remain
available (`SHELL_SETUP_GT_PROFILE`, `SHELL_SETUP_WT_PROFILE`, etc.).
Editing persistent copies works locally but subsequent installs overwrite them
from the repository; commit portable customizations to the repository itself.

The updater downloads the remote default branch, NOT your current local patch
branch. Commit and merge/push this patch to that remote branch before using
`~/.config/shell-setup/update.sh`. The patched updater refuses an incomplete or
old checkout missing this add-on rather than partially removing the feature.

## Backups and rollback

- Shell files: each install prints its `$HOME/.shell-setup-backup/...` directory.
  Restore only the intended file from that run; a `WAS_ABSENT` marker records a
  file that did not originally exist. Back up any later edits before restoring.
- GNOME: the helper prints a JSON backup path under
  `${XDG_STATE_HOME:-$HOME/.local/state}/shell-setup/terminal-backups`. Run:
  `bash configure-terminal.sh --restore /absolute/path/backup.json --dry-run`,
  then the same command without `--dry-run`, in the Ubuntu desktop session.
  This restores effective values as explicit overrides, including the palette.
- Windows: the helper writes `settings.json.shell-setup-backup-*.bak` beside the
  original. Close Terminal before restoring the chosen file. Restoration is
  whole-file; back up newer settings first.
- Codex: `config.toml.shell-setup-backup-*.bak` is beside the config and contains
  the exact previous bytes. Close Codex before restoring the chosen backup:
  `install -m 0600 /absolute/path/chosen-backup.bak "$CODEX_HOME/config.toml"`
  (substitute `$HOME/.codex` if CODEX_HOME is unset). `*.WAS_ABSENT` is NOT a TOML
  backup: it means this run created the config. Do not copy the marker over the
  config; remove a newly created config only after reviewing later changes.

Reversing the Git patch restores repository code, not settings already installed
in a home directory. Restore runtime settings separately. There is deliberately
no destructive all-host rollback or `tmux kill-server` command.

## Automated checks

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
find . -name '*.sh' -not -path './.git/*' -exec bash -n {} \;
```

New tests use temporary homes, fake settings and, when available, an isolated
GLib keyfile backend. They do not modify the user's desktop or Codex credentials.
A real tmux smoke test is skipped when tmux is unavailable. This is not an
end-to-end test of a live Windows/GNOME/Codex installation.

## Official references

- Codex security: https://developers.openai.com/codex/security/
- Codex configuration: https://developers.openai.com/codex/config-reference/
- GNOME selection: https://help.gnome.org/gnome-terminal/txt-select-text.html
- tmux: https://github.com/tmux/tmux/wiki/Getting-Started
- Windows schemes: https://learn.microsoft.com/en-us/windows/terminal/customize-settings/color-schemes
