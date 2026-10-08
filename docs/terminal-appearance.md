# Terminal appearance quick reference - packaged version 2026.10.07.1

This is a packaging quick reference, not the legacy upstream documentation.
Read [dark-palette-codex-tmux.md](dark-palette-codex-tmux.md) for the patch's full
implementation and rollback guide. For Windows see [windows-terminal.md](windows-terminal.md).

On Ubuntu, run in the logged-in desktop user's GNOME Terminal (including a
remote-viewed desktop), NOT in an SSH shell and NOT with sudo. The native wrapper
requires the display, reachable desktop D-Bus, gsettings/gdbus and GNOME schemas.
It intentionally skips unsupported/headless/root/SSH/WSLg sessions.

```bash
bash configure-terminal.sh --dry-run
bash configure-terminal.sh
```

By default, the existing GNOME Terminal default profile is used, which may not
be the profile of the current tab. Select an existing profile explicitly:

```bash
gsettings get org.gnome.Terminal.ProfilesList list
gsettings get org.gnome.Terminal.ProfilesList default
SHELL_SETUP_GT_PROFILE='YOUR-EXISTING-PROFILE-UUID' bash configure-terminal.sh --dry-run
```

Edit gnome-terminal.json for background, foreground and opacity; edit
terminal-palette.json for ANSI colors. Opacity is percent opaque (75 means
25 percent transparent). Fonts and other profiles are not modified. Existing
bold/cursor/selection colors are not removed. Settings writes do not constitute
a GUI visual test. No compositor/GPU/remote-desktop configuration is changed.

Restore only from a trusted backup created on the same host/user:

```bash
bash configure-terminal.sh --restore '/actual/path/backup.json' --dry-run
bash configure-terminal.sh --restore '/actual/path/backup.json'
```

Use the backup path printed by the helper. Restoring reinstates saved effective
values as explicit overrides, not the old inherited/unset status. Future
installs reapply the JSON defaults unless opted out or customized.
Source basis: https://raw.githubusercontent.com/nfukuchi/shell-setup/main/lib/gnome_terminal.py
