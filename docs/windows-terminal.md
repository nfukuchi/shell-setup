# Windows Terminal quick reference - packaged version 2026.10.07.1

This is a packaging quick reference, not the legacy upstream documentation.
For all changes and rollback details, see [dark-palette-codex-tmux.md](dark-palette-codex-tmux.md).

Run without sudo in LOCAL WSL, not through SSH:

```bash
bash configure-terminal.sh --dry-run
bash configure-terminal.sh
```

The intended profile is selected by exact WSL_DISTRO_NAME unless overridden:

```bash
SHELL_SETUP_WT_PROFILE='My Ubuntu Console' bash configure-terminal.sh --dry-run
SHELL_SETUP_WT_PROFILE_GUID='{YOUR-EXISTING-PROFILE-GUID}' bash configure-terminal.sh --dry-run
SHELL_SETUP_WT_SETTINGS='/mnt/c/Users/YourUser/AppData/Local/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json' bash configure-terminal.sh --dry-run
```

Substitute actual names/paths. Repeat without --dry-run to apply. Zero/multiple
settings-file candidates or ambiguous profile selection cause SKIP rather than
guessing. No profile is created. Keep the Settings UI closed while applying.

The shared terminal-palette.json defines ShellSetup Dark, including bright blue.
The windows-terminal.json colorScheme must match that name. Black background,
opacity 75 and useAcrylic false are configured. Other profiles/settings are kept.
Existing foreground/background-image/appearance overrides can affect the result.
The original settings.json is backed up beside itself before a change.
For machine-local options, see the SHELL_SETUP_WT_* variables in the wrapper.
Source basis: https://raw.githubusercontent.com/nfukuchi/shell-setup/main/installers/02-configure_windows_terminal.sh
