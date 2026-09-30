#!/usr/bin/env bash
# Run as the logged-in desktop user, not through sudo or SSH.
set -euo pipefail
ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
for arg in "$@"; do
    case "$arg" in
        --help|-h)
            printf '%s\n' \
                'Usage: bash configure-terminal.sh [--dry-run] [--profile UUID]' \
                '       bash configure-terminal.sh --restore BACKUP.json [--dry-run]' \
                'Native backend: GNOME Terminal on Ubuntu Desktop (not Ptyxis or Console).' \
                'Run in the Ubuntu desktop session as the intended user, without sudo.' \
                'Configuration: gnome-terminal.json; see docs/terminal-appearance.md.'
            exit 0 ;;
    esac
done
skip() { printf 'GNOME Terminal: SKIP - %s\n' "$*"; exit 0; }
[[ "${SHELL_SETUP_TERMINAL_APPEARANCE:-1}" != 0 ]] || skip 'disabled by SHELL_SETUP_TERMINAL_APPEARANCE=0'
[[ "${SHELL_SETUP_GNOME_TERMINAL:-1}" != 0 ]] || skip 'disabled by SHELL_SETUP_GNOME_TERMINAL=0'
[[ -z "${SSH_CONNECTION:-}${SSH_CLIENT:-}${SSH_TTY:-}" ]] || skip 'SSH session; run in the Ubuntu desktop terminal instead'
if [[ -n "${WSL_DISTRO_NAME:-}${WSL_INTEROP:-}" ]] || grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    skip 'WSL; use the Windows Terminal installer (WSLg terminals are not auto-configured)'
fi
[[ "$(id -u)" != 0 && -z "${SUDO_USER:-}" ]] || skip 'root/sudo session; run as the desktop user without sudo'
[[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || skip 'no graphical display; a desktop login is required'
[[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]] || skip 'no desktop D-Bus session address'
# Reject alternative/nonpersistent backends instead of claiming a desktop change.
[[ -z "${GSETTINGS_BACKEND:-}" || "${GSETTINGS_BACKEND}" == dconf ]] || skip 'non-dconf GSETTINGS_BACKEND; use a normal Ubuntu desktop session'
for tool in python3 gsettings gdbus; do
    command -v "$tool" >/dev/null 2>&1 || skip "$tool is missing; see docs/terminal-appearance.md"
done
# This makes no settings changes. A missing/unreachable desktop bus must not look successful.
if ! gdbus call --timeout 5 --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.GetId >/dev/null 2>&1; then
    skip 'desktop D-Bus session is not reachable'
fi
args=(--config "${SHELL_SETUP_GT_CONFIG:-$ROOT_DIR/gnome-terminal.json}")
[[ -z "${SHELL_SETUP_GT_PROFILE:-}" ]] || args+=(--profile "$SHELL_SETUP_GT_PROFILE")
if [[ "${SHELL_SETUP_GT_DRY_RUN:-${SHELL_SETUP_TERMINAL_DRY_RUN:-0}}" == 1 ]]; then
    args+=(--dry-run)
fi
python3 "$ROOT_DIR/lib/gnome_terminal.py" "${args[@]}" "$@"
