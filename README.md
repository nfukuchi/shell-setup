# shell-setup

Portable Bash/Readline/fzf/tmux and CLI-tool setup for Ubuntu, WSL, and SSH Linux environments without replacing machine-specific configuration.

## What it changes

- Keeps the existing `~/.bashrc` and preserves ROS, CUDA, conda, proxy, aliases, custom PATHs, etc.
- Adds/replaces only a clearly delimited managed block in `~/.bashrc`.
- Preserves an existing `~/.inputrc`; if absent, creates one that first includes `/etc/inputrc`.
- Preserves an existing `~/.tmux.conf`; if absent, creates a small loader file.
- Creates timestamped backups under `~/.shell-setup-backup/` before every install/update.
- Installs core apt packages through a shared apt helper that repairs interrupted dpkg state first.
- Installs/updates the official `junegunn/fzf` Git checkout in `~/.fzf`.
- Runs `installers/*.sh` in filename order.
- Copies portable common files, the apt helper, and `update.sh` to `~/.config/shell-setup/` so the original clone can be deleted.

## Repository layout

```text
shell-setup/
├── install.sh
├── update.sh
├── bashrc.common
├── inputrc.common
├── tmux.conf.common
├── lib/
│   └── apt.sh
├── installers/
│   ├── 00-install_basics.sh
│   └── 01-install_agents.sh
├── tests/
│   └── test.sh
└── README.md
```

## Initial installation

```bash
git clone https://github.com/YOUR_NAME/YOUR_REPO.git ~/Downloads/shell-setup
cd ~/Downloads/shell-setup
./install.sh
```

`install.sh` automatically remembers `git remote origin`. After a successful installation, the downloaded clone may be removed.

If installing from a ZIP instead of Git, specify the repository URL once:

```bash
./install.sh --repo-url https://github.com/YOUR_NAME/YOUR_REPO.git
```

## Updating later

```bash
~/.config/shell-setup/update.sh
```

The updater creates a temporary clone of the latest repository, executes its latest `install.sh`, and removes the temporary clone afterward. This means changes to `installers/*.sh`, `lib/apt.sh`, Bash settings, Readline settings, and tmux settings all arrive through the same update command.

## APT/dpkg recovery

All project-owned apt installers should use the shared helper instead of writing raw `sudo apt install ...` commands.

Example installer:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
. "$ROOT_DIR/lib/apt.sh"

apt_install vim ffmpeg wget git tmux
```

`apt_install` performs the following sequence:

1. Run `dpkg --configure -a` to finish an interrupted package transaction.
2. If that fails because dependencies need repair, run `apt-get -f install -y`, then retry `dpkg --configure -a`.
3. Run `apt-get update` once per shell-setup execution when packages are actually missing.
4. Install only missing packages with `apt-get install -y`.
5. Run the dpkg repair check again before returning.

This specifically handles the common error:

```text
E: dpkg was interrupted, you must manually run 'sudo dpkg --configure -a' to correct the problem.
```

The top-level `install.sh` also runs `apt_repair` immediately before every `installers/*.sh` file, so an older/custom installer containing raw apt commands is protected from a pre-existing interrupted-dpkg state. New installers should still use `apt_install` because it is safer and reusable when the installer is run by itself.

If a package's own post-install script is genuinely broken, the installer stops instead of hiding that real error.

## Current installers

### `installers/00-install_basics.sh`

Installs:

```text
vim ffmpeg wget git git-lfs tmux tree zip unzip fd-find curl
```

It uses `apt_install`; do not add `sudo` yourself when adding packages to this list.

For example:

```bash
apt_install \
    vim \
    ffmpeg \
    jq \
    ripgrep \
    btop
```

### `installers/01-install_agents.sh`

Installs Claude Code and Codex only when the corresponding command is not already available. User-level installers are used; `sudo` is not added.

### `installers/04-configure_codex_sandbox.sh`

Installs `bubblewrap` for the Codex Linux sandbox. When
`kernel.apparmor_restrict_unprivileged_userns=1` (including Ubuntu 24.04),
it also installs `apparmor-profiles` and `apparmor-utils`, copies the distribution's
`bwrap-userns-restrict` profile into `/etc/apparmor.d/` if absent, and loads it
with `apparmor_parser -r`. Existing profiles are preserved; repeated runs reload
them. No global sysctl restrictions or Codex permission settings are changed.
`--skip-packages` skips this entire installer, including profile configuration.
Systems without the AppArmor restriction only need the bubblewrap package.
If the distribution does not supply the extra profile, installation stops with
an error rather than disabling AppArmor restrictions.

This addresses `bwrap: setting up uid map: Permission denied` when the
AppArmor user namespace restriction blocks sandbox creation. See the
[official sandbox documentation](https://learn.chatgpt.com/docs/sandboxing).
Run the installer through the normal `./install.sh` / update workflow, or alone:

```bash
bash installers/04-configure_codex_sandbox.sh
```

Validate from a normal host terminal (not inside another sandbox):

```bash
bwrap --unshare-user --ro-bind / / /usr/bin/true
echo $?  # 0 means success
```

Nested sandbox creation can be denied even when the outer Codex sandbox works.
Loading the profile requires sudo but does not require a reboot. To undo a profile
newly created by this installer, unload it with
`sudo apparmor_parser -R /etc/apparmor.d/bwrap-userns-restrict`, then remove that
file. Do not remove a pre-existing, administrator-managed profile.

## Adding a new apt-based installer

Create, for example:

```text
installers/02-install_robotics_tools.sh
```

with:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
. "$ROOT_DIR/lib/apt.sh"

apt_install \
    v4l-utils \
    can-utils \
    minicom
```

Installers are executed lexicographically:

```text
00-install_basics.sh
01-install_agents.sh
02-install_robotics_tools.sh
...
```

## Installed common files

On normal Ubuntu/WSL:

```text
~/.config/shell-setup/
├── bashrc.common
├── inputrc.common
├── tmux.conf.common
├── lib/
│   └── apt.sh
├── update.sh
└── repo-url
```

Check from WSL:

```bash
ls -la ~/.config/shell-setup
cat ~/.config/shell-setup/bashrc.common
```

Open in Windows Explorer:

```bash
cd ~/.config/shell-setup
explorer.exe .
```

## tmux pane navigation

`tmux.conf.common` contains:

```tmux
bind h select-pane -L
bind j select-pane -D
bind k select-pane -U
bind l select-pane -R
```

With the default tmux prefix, use `Ctrl-b`, release it, then `h/j/k/l`.

Reload an already-running tmux server with:

```bash
tmux source-file ~/.tmux.conf
```

## Readline completion

The managed `.inputrc` settings provide:

- Prefix-aware `Up` / `Down` history search.
- `Tab` to cycle completion candidates.
- `Shift-Tab` to cycle backwards.
- Case-insensitive/colored completion.
- `set mark-directories off` so selecting a directory candidate does not immediately append `/` and change the next Tab completion context.

## fzf

Official fzf shell integration provides:

- `Ctrl-R`: fuzzy history search
- `Ctrl-T`: fuzzy file selection
- `Alt-C`: fuzzy directory selection
- `**<Tab>`: fuzzy completion

## Useful options

```text
--skip-packages     Skip apt/dpkg package operations.
--skip-fzf          Skip fzf install/update.
--skip-installers   Skip installers/*.sh entirely.
--repo-url URL      Set/save the repository used by update.sh.
```

## Validation and rollback

Before modifying files, backups are written to:

```text
~/.shell-setup-backup/YYYYMMDD-HHMMSS-PID/
```

The installer validates Bash and Readline configuration and loads tmux configuration on a private tmux server when tmux is available.

Run regression tests with:

```bash
./tests/test.sh
```

The regression tests include a simulated interrupted-dpkg condition and verify that `dpkg --configure -a` occurs before installer `apt-get install`.
