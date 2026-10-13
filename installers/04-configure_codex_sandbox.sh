#!/usr/bin/env bash
# Install Linux sandbox prerequisites without disabling AppArmor globally.
set -euo pipefail
ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
. "$ROOT_DIR/lib/apt.sh"

if [[ "${SHELL_SETUP_SKIP_PACKAGES:-0}" == 1 ]]; then
    echo 'Codex sandbox: skipping packages and system configuration (--skip-packages).'
    exit 0
fi
if ! command -v apt-get >/dev/null 2>&1; then
    echo 'Codex sandbox: skipping non-APT system.'
    exit 0
fi
apt_install bubblewrap

restriction=/proc/sys/kernel/apparmor_restrict_unprivileged_userns
if [[ ! -r "$restriction" ]] || [[ "$(< "$restriction")" != 1 ]]; then
    echo 'Codex sandbox: AppArmor user namespace restriction is not enabled.'
    exit 0
fi

apt_install apparmor-profiles apparmor-utils
profile=/etc/apparmor.d/bwrap-userns-restrict
source_profile=/usr/share/apparmor/extra-profiles/bwrap-userns-restrict
if [[ ! -e "$profile" ]]; then
    if [[ ! -f "$source_profile" ]]; then
        echo "ERROR: distribution bwrap profile is missing: $source_profile" >&2
        echo 'Update the distribution AppArmor packages; no global restrictions were changed.' >&2
        exit 1
    fi
    _shell_setup_sudo_cmd install -m 0644 "$source_profile" "$profile"
else
    echo "Codex sandbox: preserving existing $profile"
fi
# Reload even when the file already exists: it may not be loaded yet.
_shell_setup_sudo_cmd apparmor_parser -r "$profile"
echo 'Codex sandbox: bwrap AppArmor profile loaded (no reboot required).'
