# Windows Terminal backend (version 2)

For installation, native Ubuntu support, and common usage, read
[terminal-appearance.md](terminal-appearance.md). This page documents the
Windows-specific settings discovery, selection, and recovery behavior.

## Default configuration

`windows-terminal.json`:

```json
{
    "colorScheme": "Tango Dark",
    "background": "#000000",
    "opacity": 75,
    "useAcrylic": false
}
```

`opacity` means percent opaque: 100 is opaque, 50 is half-transparent, and 0 is
fully transparent. `useAcrylic: false` requests unblurred transparency and requires
Windows 11 for that effect. Change it to `true` to request blurred acrylic.
The palette changes text colors too. Remove `colorScheme` from the config to
stop managing that property (this does not undo a previously written value).

## Apply only this backend

Run in the Windows host's LOCAL WSL Bash, not an SSH destination:

```bash
bash installers/02-configure_windows_terminal.sh --dry-run
bash installers/02-configure_windows_terminal.sh
```

Or use the unified `bash configure-terminal.sh` entry point. Neither standalone
command runs package, fzf, or agent installation. Do not run via sudo.

The wrapper requires local WSL, Python 3, Windows file access, and normally
Windows interop for automatic discovery. It skips SSH/native Linux and respects
`SHELL_SETUP_TERMINAL_APPEARANCE=0` and `SHELL_SETUP_WINDOWS_TERMINAL=0`.

Open Windows Terminal and the intended Ubuntu profile at least once. Close its
Settings UI and any editor holding settings.json before applying. Back up work
before closing terminal tabs. Reopen the target profile after application;
restart Terminal if the appearance has not refreshed.

## Discovery and profile selection

The Windows user's actual LocalAppData is obtained using `powershell.exe` and
translated using `wslpath`. These standard locations are checked:

```text
Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json
Packages/Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe/LocalState/settings.json
Microsoft/Windows Terminal/settings.json
```

Zero or multiple candidate settings files cause a SKIP. Portable/custom layouts
need an explicit WSL/Linux file path. The script does not infer a Windows username.

```bash
SHELL_SETUP_WT_SETTINGS='/mnt/c/Users/YourUser/AppData/Local/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json' \
    bash configure-terminal.sh --dry-run
```

Convert an actual Windows path with `wslpath -u 'C:\actual\path\settings.json'`.
The path above is an example, not a hard-coded implementation assumption.

Within that file, the default profile name match is exactly `WSL_DISTRO_NAME`.
No profile is created. To select a renamed profile:

```bash
SHELL_SETUP_WT_PROFILE='My Ubuntu Console' bash configure-terminal.sh --dry-run
```

Duplicate names require an explicit profile GUID from the target settings file:

```bash
SHELL_SETUP_WT_PROFILE_GUID='{paste-the-intended-profile-guid-here}' \
    bash configure-terminal.sh --dry-run
```

Repeat the same command without `--dry-run` to apply. An explicit GUID takes
precedence over the name match. The script does not blindly trust `WT_PROFILE_ID`,
which might refer to a PowerShell profile from which `wsl.exe` was launched.

Other overrides:

```bash
SHELL_SETUP_WT_CONFIG=/absolute/path/appearance.json bash configure-terminal.sh
SHELL_SETUP_WT_DRY_RUN=1 bash install.sh
```

The latter previews only this appearance step, not the rest of install.sh.
Environment overrides are not persisted automatically.

## Preservation and limitations

Only the configured appearance properties in the one selected profile change.
Other profiles, profiles.defaults, fonts, commands, paths, keybindings and
unrelated values are retained. The JSONC editor retains comments, UTF-8 BOMs and
newline style; malformed JSONC and duplicate properties are rejected.

Existing background images, explicit foreground overrides, Mica,
unfocusedAppearance and global transparency restrictions are not removed. They
can affect the result. Configuration writes do not prove that a GUI rendered
transparency. This backend does not style native Ubuntu GNOME Terminal; that is
the separate backend described in terminal-appearance.md.

## Backups and rollback

Before a changed settings file is replaced, the original bytes are written
beside it as:

```text
settings.json.shell-setup-backup-<UTC timestamp>-<random suffix>.bak
```

Dry-run and no-op runs create no backup. Backups may contain profile commands
and paths; keep them private. The writer checks for concurrent edits, but keep
other settings editors closed while applying.

To undo, use the exact backup path reported for that settings.json:

```bash
cp -- '/actual/path/settings.json.shell-setup-backup-TIMESTAMP-SUFFIX.bak' \
    '/actual/path/settings.json'
```

This restores the whole Windows Terminal file, including undoing unrelated
changes made after that backup. It differs from the native Ubuntu backup, which
contains only changed appearance keys. Reopen Terminal to inspect the result.
Opt out or adjust the repository JSON before updating again.

## Validation

The Windows backend's 30 automated tests pass in a Linux container. They cover
JSONC, comments, targeted edits, BOM/CRLF, dry-run, idempotence, backups, symlink
refusal, concurrent-edit detection, settings discovery and mocked WSL guards.
They do not constitute Windows/WSL GUI testing. See terminal-appearance.md for
the total suite, native tests, and outstanding real-desktop checks.

Reference: https://learn.microsoft.com/en-us/windows/terminal/customize-settings/profile-appearance
