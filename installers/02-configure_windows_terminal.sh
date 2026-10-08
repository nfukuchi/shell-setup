#!/usr/bin/env bash
# Run inside the local WSL distro, never on an SSH destination.
set -euo pipefail
ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
dry_run="${SHELL_SETUP_WT_DRY_RUN:-${SHELL_SETUP_TERMINAL_DRY_RUN:-0}}"
for arg in "$@"; do
    case "$arg" in
        --dry-run) dry_run=1 ;;
        --help|-h)
            printf '%s\n' \
                'Usage: bash installers/02-configure_windows_terminal.sh [--dry-run]' \
                'See docs/windows-terminal.md for settings and recovery.'
            exit 0 ;;
        *) printf 'ERROR: Unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done
skip() { printf 'Windows Terminal: SKIP - %s\n' "$*"; exit 0; }
[[ "${SHELL_SETUP_TERMINAL_APPEARANCE:-1}" != 0 ]] || skip 'disabled by SHELL_SETUP_TERMINAL_APPEARANCE=0'
[[ "${SHELL_SETUP_WINDOWS_TERMINAL:-1}" != 0 ]] || skip 'disabled by SHELL_SETUP_WINDOWS_TERMINAL=0'
[[ -z "${SSH_CONNECTION:-}${SSH_CLIENT:-}${SSH_TTY:-}" ]] || skip 'SSH session; run from local WSL instead'
if [[ -z "${WSL_DISTRO_NAME:-}" ]] || ! grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    skip 'not a local WSL session with WSL_DISTRO_NAME'
fi
# This appearance-only installer does not install packages, including on dry-run.
command -v python3 >/dev/null 2>&1 || skip 'python3 is missing; install it and rerun this installer'
args=(--config "${SHELL_SETUP_WT_CONFIG:-$ROOT_DIR/windows-terminal.json}"
      --profile "${SHELL_SETUP_WT_PROFILE:-$WSL_DISTRO_NAME}"
      --palette-config "${SHELL_SETUP_PALETTE_CONFIG:-$ROOT_DIR/terminal-palette.json}")
if [[ -n "${SHELL_SETUP_WT_PROFILE_GUID:-}" ]]; then
    args+=(--guid "$SHELL_SETUP_WT_PROFILE_GUID")
fi
if [[ -n "${SHELL_SETUP_WT_SETTINGS:-}" ]]; then
    # Explicit setting paths must use WSL/Linux notation; use wslpath if needed.
    args+=(--settings "$SHELL_SETUP_WT_SETTINGS")
else
    command -v powershell.exe >/dev/null 2>&1 || skip 'powershell.exe unavailable; check WSL Windows interop/PATH'
    command -v wslpath >/dev/null 2>&1 || skip 'wslpath unavailable'
    if ! win_localappdata="$(powershell.exe -NoLogo -NoProfile -NonInteractive -Command \
        '[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); [Console]::Write([Environment]::GetFolderPath("LocalApplicationData"))')"; then
        skip 'cannot determine the current Windows user LocalAppData'
    fi
    win_localappdata="${win_localappdata//$'\r'/}"
    [[ -n "$win_localappdata" ]] || skip 'Windows LocalAppData path was empty'
    if ! localappdata="$(wslpath -u "$win_localappdata")"; then
        skip 'cannot translate the Windows LocalAppData path'
    fi
    [[ -d "$localappdata" ]] || skip 'Windows LocalAppData is not accessible from WSL'
    args+=(--local-app-data "$localappdata")
fi
[[ "$dry_run" != 1 ]] || args+=(--dry-run)
python3 "$ROOT_DIR/lib/windows_terminal.py" "${args[@]}"
