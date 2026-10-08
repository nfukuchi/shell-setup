#!/usr/bin/env bash
# Configuration only: no APT/npm/network/login. Apply on the Codex execution host.
set -euo pipefail
ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
if [[ "${SHELL_SETUP_CODEX_CONFIGURE:-1}" == 0 ]]; then
    echo 'Codex: SKIP - disabled by SHELL_SETUP_CODEX_CONFIGURE=0'
    exit 0
fi
if [[ -n "${SUDO_USER:-}" ]]; then
    echo 'Codex: ERROR - run as the intended user, not with sudo.' >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1 ||
   ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo 'Codex: ERROR - Python 3.11+ is required (Ubuntu 24.04 provides Python 3.12).' >&2
    exit 1
fi
args=(--template "${SHELL_SETUP_CODEX_TEMPLATE:-$ROOT_DIR/codex-config.toml}")
[[ "${SHELL_SETUP_CODEX_DRY_RUN:-0}" == 1 ]] && args+=(--dry-run)
exec python3 "$ROOT_DIR/lib/codex_config.py" "${args[@]}" "$@"
