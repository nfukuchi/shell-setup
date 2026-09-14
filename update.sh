#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/shell-setup"
REPO_URL="${SHELL_SETUP_REPO_URL:-}"
PASS_ARGS=()

usage() {
    cat <<'USAGE'
Usage: update.sh [options]

Fetch the latest shell-setup repository into a temporary directory and run
its latest install.sh. The temporary clone is removed automatically.

Options:
  --repo-url URL       Use and remember this repository URL.
  --skip-packages      Pass through to install.sh (mainly for testing).
  --skip-fzf           Pass through to install.sh (mainly for testing).
  -h, --help           Show this help.

Normally, after the first git-clone based installation, simply run:
  ~/.config/shell-setup/update.sh
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-url)
            [[ $# -ge 2 ]] || { echo 'ERROR: --repo-url requires a URL.' >&2; exit 2; }
            REPO_URL="$2"
            shift 2
            ;;
        --skip-packages|--skip-fzf)
            PASS_ARGS+=("$1")
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

# Prefer an explicit URL; otherwise use the URL remembered during install.
if [[ -z "$REPO_URL" && -f "$INSTALL_DIR/repo-url" ]]; then
    REPO_URL="$(head -n 1 "$INSTALL_DIR/repo-url")"
fi

# If this copy of update.sh happens to be run from a live git checkout,
# use that checkout's origin as a final fallback.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$REPO_URL" ]] && git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    REPO_URL="$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || true)"
fi

if [[ -z "$REPO_URL" ]]; then
    cat >&2 <<'ERROR_EOF'
ERROR: No shell-setup Git repository URL is known.

If the first installation came from a ZIP/download instead of `git clone`, run:
  ~/.config/shell-setup/update.sh --repo-url https://github.com/USER/REPO.git

The URL will be saved for subsequent updates.
ERROR_EOF
    exit 1
fi

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT INT TERM

printf 'Updating shell-setup from:\n  %s\n' "$REPO_URL"
git clone --depth 1 "$REPO_URL" "$TMP_DIR/repo"

[[ -x "$TMP_DIR/repo/install.sh" ]] || {
    echo 'ERROR: Latest repository does not contain an executable install.sh.' >&2
    exit 1
}

"$TMP_DIR/repo/install.sh" --repo-url "$REPO_URL" "${PASS_ARGS[@]}"
printf '\nUpdate completed successfully.\n'
