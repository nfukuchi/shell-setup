#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
exec bash "$ROOT_DIR/configure-codex.sh" "$@"
