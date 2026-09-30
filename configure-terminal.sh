#!/usr/bin/env bash
# Appearance only. Never invokes APT, fzf, or the other install.sh steps.
set -euo pipefail
ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
if [[ -n "${WSL_DISTRO_NAME:-}${WSL_INTEROP:-}" ]] || grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    exec bash "$ROOT_DIR/installers/02-configure_windows_terminal.sh" "$@"
else
    exec bash "$ROOT_DIR/installers/03-configure_gnome_terminal.sh" "$@"
fi
