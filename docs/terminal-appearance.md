# Terminal appearance: Windows Terminal + native Ubuntu (version 2)

Version 2 replaces the previous Windows-only add-on. It was prepared against
`nfukuchi/shell-setup`'s installer layout reviewed on 2026-09-30. It does not
replace `install.sh`, `update.sh`, `lib/apt.sh`, or any existing shell/tmux config.
No changes have been pushed to GitHub by preparing this add-on.

## Scope and defaults

| Environment where the command runs | Target | Default |
| --- | --- | --- |
| Local WSL in Windows Terminal | One existing Windows Terminal WSL profile | Black, opacity 75%, acrylic OFF |
| Native Ubuntu 24.04 Desktop session | One existing GNOME Terminal profile | Black, light text, opacity 75%, no blur added |
| SSH, headless/native TTY, missing schemas/session | None | SKIP with a reason |

The native backend targets **GNOME Terminal with Ubuntu's transparency keys**.
It does not configure GNOME Console (`kgx`), Ptyxis, Konsole, Tilix, or VS Code.
It does not install a different terminal, a compositor, a GNOME extension, or
GPU/display drivers. Existing compositor blur extensions are left untouched.
WSLg GUI terminals are not automatically configured.

GNOME Terminal has no Windows `useAcrylic` setting. Its background transparency
is distinct from compositor-side blur. This add-on adjusts the terminal's
background, not the opacity of the whole window/text. No blur extension is
installed or toggled. The actual rendering remains dependent on the desktop.

Windows `useAcrylic: false` gives unblurred transparency only on Windows 11.
For Windows 10, use `true` to request acrylic transparency or use an opaque
background. Do not silently substitute `true` for a user's chosen `false`.

## Files

```text
configure-terminal.sh
windows-terminal.json
gnome-terminal.json
installers/02-configure_windows_terminal.sh
installers/03-configure_gnome_terminal.sh
lib/windows_terminal.py
lib/gnome_terminal.py
tests/test_windows_terminal.py
tests/test_gnome_terminal.py
docs/windows-terminal.md
docs/terminal-appearance.md
```

The existing `install.sh` runs `installers/*.sh` in filename order. On WSL,
02 handles Windows Terminal and 03 skips. On a native desktop, 02 skips and 03
handles GNOME Terminal. The appearance-only entry point dispatches to just the
appropriate backend. It never invokes APT, fzf, or agent installation.

## Add or upgrade in a shell-setup checkout

Save your existing work/config edits first. Run commands from the repository
root, not from `~/.config/shell-setup` (which is an installed subset).
Use exactly ONE of the following alternatives.

### A. Previous five-file Windows-only add-on is already present

Use `shell-setup-terminal-v1-to-v2.patch`:

```bash
git apply --check /actual/path/shell-setup-terminal-v1-to-v2.patch
git apply /actual/path/shell-setup-terminal-v1-to-v2.patch
```

### B. No previous appearance add-on has been applied

Use `shell-setup-terminal-v2.patch`:

```bash
git apply --check /actual/path/shell-setup-terminal-v2.patch
git apply /actual/path/shell-setup-terminal-v2.patch
```

### C. ZIP instead of Git patch

`shell-setup-terminal-v2.zip` contains the eleven files above with paths relative to the repository root.
Extract into the checkout, preserving subdirectories. Back up locally edited
copies of these files before replacing them. Do not apply the patches as well.
The ZIP does not contain `install.sh`: it is an add-on, not a full repository.
No files need to be deleted when upgrading from version 1.

If `git apply --check` fails, stop and inspect the conflicting local files.
Do not force-reset the repository or remove your changes to make a patch apply.
The full patch is not meant to be applied on top of the v1 add-on.

## Preview and apply (same command in both environments)

**WSL:** run in the Windows host's LOCAL WSL Bash, not through SSH.
**Native Ubuntu:** run in a terminal opened in that Ubuntu desktop login, as the
user whose terminal should change, without `sudo`. A terminal inside a remotely
viewed Ubuntu desktop is also an Ubuntu desktop terminal; a WSL SSH shell is not.
Close the terminal's Preferences/Settings UI and other configuration editors
while applying. Do not close terminal tabs containing unsaved work.

```bash
bash configure-terminal.sh --dry-run
bash configure-terminal.sh
```

For native Ubuntu, the default GNOME Terminal profile is selected, which need
not be the profile of the current tab. Its UUID is printed in the preview.
No profile is created, no profile-list/default value is changed, and no other
profiles are edited. To select an existing profile explicitly:

```bash
gsettings get org.gnome.Terminal.ProfilesList list
gsettings get org.gnome.Terminal.ProfilesList default
SHELL_SETUP_GT_PROFILE='paste-existing-profile-uuid-here' bash configure-terminal.sh --dry-run
SHELL_SETUP_GT_PROFILE='paste-existing-profile-uuid-here' bash configure-terminal.sh
```

For Windows, the default match is the exact name `WSL_DISTRO_NAME`; see
[windows-terminal.md](windows-terminal.md) for settings-file/name/GUID overrides.
The script does not assume `WT_PROFILE_ID` refers to the correct Ubuntu profile.
Open Windows Terminal and the intended distro profile at least once before use.

### Status messages

| Output | Interpretation |
| --- | --- |
| `DRY RUN` | Proposed changes only; no settings or backups written |
| `UPDATED` | The backend performed a change; verify the GUI separately |
| `unchanged (already configured)` | Managed values already match; no new backup |
| `SKIP` | Nothing applied; read the reason, fix the prerequisite and rerun |
| `ERROR` | Not a success; inspect the message and backup/rollback status |

On native Ubuntu, all six required keys are checked before making any changes.
Missing transparency keys or locked settings cause a SKIP rather than a partial
"black but not transparent" success. The native writer reads back each write in
a separate `gsettings` process. Warnings on stderr are treated as failures even
when `gsettings` exits zero. Interrupted/failed writes trigger best-effort
rollback; if rollback is incomplete the error identifies this explicitly.

The appearance scripts do not install packages. Native prerequisites are
Python 3, `gsettings`, `gdbus`, GNOME Terminal's schemas, and the logged-in user's
reachable D-Bus/graphical session. If tools are missing and this is an intended
Ubuntu 24.04 desktop, install the appropriate distro packages yourself:

```bash
sudo apt update
sudo apt install python3 libglib2.0-bin gnome-terminal
```

Do not install a GUI stack just to style an SSH-only server: style the local
client terminal instead. Do not invent DISPLAY/DBUS values or use `dbus-launch`
to bypass the guard. Log into the intended Ubuntu desktop and rerun.

## Change the appearance later

### Repository-managed settings (repeatable on new machines)

Edit `windows-terminal.json` for Windows:

```json
{
    "colorScheme": "Tango Dark",
    "background": "#000000",
    "opacity": 75,
    "useAcrylic": false
}
```

`useAcrylic: false` requests clear/unblurred transparency. Set `true` to try blur.
This choice is independent of `opacity`. Existing Mica, background images, or
unfocused appearance overrides are not removed and can affect the visual result.

Edit `gnome-terminal.json` for native Ubuntu:

```json
{
    "background": "#000000",
    "foreground": "#D3D7CF",
    "opacity": 75
}
```

This controls background, normal text color, and background opacity only.
GNOME's ANSI palette and fonts are left unchanged. Disabling theme colors is
necessary to make the explicit background/foreground apply. Existing explicit
bold/cursor/selection overrides are not removed.
Do NOT add `useAcrylic` to this file: it is not a GNOME Terminal option.

| Desired effect | `opacity` in either JSON | GNOME internal transparency percent |
| --- | --- | --- |
| Opaque | 100 | 0 (transparency also disabled) |
| Slightly translucent | 85 | 15 |
| Default | 75 | 25 |
| More translucent | 60 | 40 |
| Half-transparent | 50 | 50 |

The JSON always uses **percent opaque**. The native helper calculates
`background-transparency-percent = 100 - opacity`; you never need to invert the
number yourself when editing the JSON. Identical numbers do not guarantee an
identical perceived appearance across desktops, wallpapers, or blur settings.

After editing, apply again from the checkout:

```bash
bash configure-terminal.sh --dry-run
bash configure-terminal.sh
```

Editing the repository JSON alone does not immediately change the live GUI.

### Native Ubuntu GUI experiments

Open GNOME Terminal's menu -> Preferences -> intended profile -> Colors.
Disable "Use colors from system theme" and choose a black background.
Disable "Use transparency from system theme", enable "Use transparent background",
and adjust the slider. Menu wording can vary with the UI language/build.
GNOME Terminal saves profile settings; this is not just a per-tab temporary
experiment. The Windows-specific "Enable acrylic" checkbox does not exist here.

To inspect the default profile's effective settings (native desktop Bash):

```bash
profile="$(gsettings get org.gnome.Terminal.ProfilesList default | tr -d "'")"
schema="org.gnome.Terminal.Legacy.Profile:/org/gnome/terminal/legacy/profiles:/:${profile}/"
gsettings get "$schema" use-theme-colors
gsettings get "$schema" background-color
gsettings get "$schema" use-theme-transparency
gsettings get "$schema" use-transparent-background
gsettings get "$schema" background-transparency-percent
```

For this add-on's default, expect `false`, `'#000000'`, `false`, `true`, `25`.
The last value is **25% transparent**, equivalent to `opacity: 75` in the JSON.
Close/reopen the appropriate profile if the appearance has not refreshed.
No boot-time task or background service is installed by the add-on.

### Keep GUI experiments during normal shell-setup updates

`install.sh` and future updates reapply the repository JSON. GUI choices for the
same managed keys may therefore be replaced. To keep a favorite setting on all
new machines, copy its values into the appropriate JSON and commit/push it.
To skip appearance while updating the shell configuration:

```bash
SHELL_SETUP_TERMINAL_APPEARANCE=0 ~/.config/shell-setup/update.sh
```

Backend-specific opt-outs are `SHELL_SETUP_WINDOWS_TERMINAL=0` and
`SHELL_SETUP_GNOME_TERMINAL=0`. These environment variables apply only to the
invocation unless you export them persistently in your own environment setup.

For a machine-local JSON instead of repository defaults, set
`SHELL_SETUP_WT_CONFIG=/absolute/path/windows-terminal.json` or
`SHELL_SETUP_GT_CONFIG=/absolute/path/gnome-terminal.json`. Both files need only
be readable when the installer runs. To keep this override on later invocations,
export the variable yourself; the add-on does not modify `.bashrc` for it.

`SHELL_SETUP_TERMINAL_DRY_RUN=1` previews only appearance during `install.sh`;
it does NOT make APT, agent installers, or the rest of install.sh dry-run.

## Backups and restore

Windows backups remain next to its `settings.json`; see windows-terminal.md.
Native backups are created before changes under:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/shell-setup/terminal-backups/
```

The exact path is printed by the installer. Native backup files are mode 0600
and contain only changed appearance keys, the profile UUID, user ID and hostname.
They do not contain shell history or the rest of the dconf database.

To restore on the same host, in the same user's Ubuntu desktop session:

```bash
bash configure-terminal.sh --restore '/actual/path/to/gnome-terminal-backup.json' --dry-run
bash configure-terminal.sh --restore '/actual/path/to/gnome-terminal-backup.json'
```

Restore also backs up any keys it changes. It does not reset fonts or other
profiles. **Native backups restore the old effective values as explicit user
settings**, not their old inherited/unset status. A later change in system theme
or defaults may thus behave differently. This is not a complete dconf backup.
Do not restore an untrusted or manually fabricated backup. Adjust/opt out of the
repository configuration before the next update to avoid reapplying it.

## Publish and reuse

After review, commit these eleven files (only this add-on's changes), push your
branch, and merge it into the branch used by your installer/updater:

```bash
git add configure-terminal.sh windows-terminal.json gnome-terminal.json \
    installers/02-configure_windows_terminal.sh installers/03-configure_gnome_terminal.sh \
    lib/windows_terminal.py lib/gnome_terminal.py \
    tests/test_windows_terminal.py tests/test_gnome_terminal.py \
    docs/windows-terminal.md docs/terminal-appearance.md
git commit -m "Support native GNOME Terminal and default Windows acrylic off"
```

Git push/merge is your action; the provided files do not alter GitHub themselves.
On a new native Ubuntu desktop or local WSL installation, run the normal
repository install after merging. For a native machine first configured via SSH,
rerun `bash configure-terminal.sh` from a checkout in its desktop session later.
The usual installed update command remains `~/.config/shell-setup/update.sh`.
The updater fetches a fresh repository clone; local edits to an unrelated old
checkout are not automatically used unless committed to the fetched branch.

## Verification and limitations

Run from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_*terminal.py' -v
```

70 tests passed in a Linux container. Coverage includes Windows JSONC/comment
preservation and targeted writes; native opacity conversion, unsupported keys,
locked settings, private backups, rollback, restore, idempotence; WSL/SSH/root/
headless/session guards; and the OFF acrylic defaults.
One integration test uses real `gsettings` processes against an isolated keyfile
backend with a minimal schema fixture to verify apply/read-back/restore. The
fixture is NOT the Ubuntu-packaged terminal or dconf service. Other tests use
fakes/mocks; they are not a Windows desktop or Ubuntu desktop visual test.
**Actual Windows/WSL and Ubuntu GNOME desktop GUI verification is still required.**
Start with --dry-run and verify the intended profile on each machine.

## References

- Windows profile appearance / opacity / acrylic:
  https://learn.microsoft.com/en-us/windows/terminal/customize-settings/profile-appearance
- GNOME Terminal color preferences:
  https://help.gnome.org/gnome-terminal/app-colors.html
- Ubuntu 24.04 GNOME Terminal manual:
  https://manpages.ubuntu.com/manpages/noble/man1/gnome-terminal.1.html
- Transparency patch interface (source-code mirror; not a 24.04 binary test):
  https://raw.githubusercontent.com/sean0921/debian-gnome-terminal-transparency/debian-tp/debian/patches/0001-Restore-transparency.patch
- GNOME GSettings API and backend semantics:
  https://docs.gtk.org/gio/class.Settings.html
- Existing shell-setup installer integration:
  https://raw.githubusercontent.com/nfukuchi/shell-setup/main/install.sh
