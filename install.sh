#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/shell-setup"
BASHRC="$HOME/.bashrc"
INPUTRC="$HOME/.inputrc"
TMUX_CONF="$HOME/.tmux.conf"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$HOME/.shell-setup-backup/${TIMESTAMP}-$$"

BASH_BEGIN='# >>> shell-setup >>>'
BASH_END='# <<< shell-setup <<<'
INPUT_BEGIN='# >>> shell-setup >>>'
INPUT_END='# <<< shell-setup <<<'
TMUX_BEGIN='# >>> shell-setup >>>'
TMUX_END='# <<< shell-setup <<<'

SKIP_PACKAGES=0
SKIP_FZF=0
REPO_URL="${SHELL_SETUP_REPO_URL:-}"
SKIP_INSTALLERS=0

# shellcheck source=lib/apt.sh
. "$SCRIPT_DIR/lib/apt.sh"

usage() {
    cat <<'USAGE'
Usage: ./install.sh [options]

Options:
  --repo-url URL       Save the Git repository URL for future update.sh runs.
                       Normally auto-detected from the current git checkout.
  --skip-packages      Skip apt package installation (mainly for testing).
  --skip-fzf           Skip fzf install/update (mainly for testing).
  --skip-installers     Skip installers/*.sh (mainly for testing).
  -h, --help           Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-url)
            [[ $# -ge 2 ]] || { echo 'ERROR: --repo-url requires a URL.' >&2; exit 2; }
            REPO_URL="$2"
            shift 2
            ;;
        --skip-packages)
            SKIP_PACKAGES=1
            shift
            ;;
        --skip-fzf)
            SKIP_FZF=1
            shift
            ;;
        --skip-installers)
            SKIP_INSTALLERS=1
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

# Auto-detect origin when install.sh is run from a git clone.
if [[ -z "$REPO_URL" ]] && git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    REPO_URL="$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || true)"
fi

log() { printf '%s\n' "$*"; }

backup_one_config() {
    local file="$1"
    local name="$2"

    if [[ -L "$file" ]]; then
        echo "ERROR: $file is a symbolic link." >&2
        echo "To avoid modifying an unexpected target, this installer stops here." >&2
        exit 1
    elif [[ -e "$file" ]]; then
        cp -a "$file" "$BACKUP_DIR/$name"
        log "Backed up: $file -> $BACKUP_DIR/$name"
    else
        : > "$BACKUP_DIR/${name}.WAS_ABSENT"
        log "Recorded: $file did not exist"
    fi
}

backup_existing_configs() {
    mkdir -p "$BACKUP_DIR"
    backup_one_config "$BASHRC" '.bashrc'
    backup_one_config "$INPUTRC" '.inputrc'
    backup_one_config "$TMUX_CONF" '.tmux.conf'
}

strip_managed_block() {
    local src="$1"
    local dst="$2"
    local begin="$3"
    local end="$4"

    awk -v begin="$begin" -v end="$end" '
        $0 == begin { skip = 1; next }
        $0 == end   { skip = 0; next }
        !skip       { print }
    ' "$src" > "$dst"
}

install_packages() {
    [[ "$SKIP_PACKAGES" -eq 1 ]] && { log '[1/9] Skipping core package installation.'; return; }

    log '[1/9] Checking/installing core packages...'
    if ! command -v apt-get >/dev/null 2>&1; then
        echo 'ERROR: This installer currently supports Debian/Ubuntu (apt).' >&2
        exit 1
    fi

    # apt_install repairs an interrupted dpkg transaction first, including the
    # common "dpkg was interrupted ... dpkg --configure -a" state.
    apt_install git curl ca-certificates bash-completion tmux
}

install_shared_files() {
    log '[3/9] Installing shared configuration...'
    mkdir -p "$INSTALL_DIR"
    install -m 0644 "$SCRIPT_DIR/bashrc.common" "$INSTALL_DIR/bashrc.common"
    install -m 0644 "$SCRIPT_DIR/inputrc.common" "$INSTALL_DIR/inputrc.common"
    install -m 0644 "$SCRIPT_DIR/tmux.conf.common" "$INSTALL_DIR/tmux.conf.common"
    install -m 0755 "$SCRIPT_DIR/update.sh" "$INSTALL_DIR/update.sh"
    mkdir -p "$INSTALL_DIR/lib"
    install -m 0755 "$SCRIPT_DIR/lib/apt.sh" "$INSTALL_DIR/lib/apt.sh"

    if [[ -n "$REPO_URL" ]]; then
        printf '%s\n' "$REPO_URL" > "$INSTALL_DIR/repo-url"
        chmod 0600 "$INSTALL_DIR/repo-url"
        log "Saved update repository: $REPO_URL"
    elif [[ ! -f "$INSTALL_DIR/repo-url" ]]; then
        log 'NOTE: Git origin was not detected. Future update.sh needs --repo-url URL once.'
    fi
}

install_fzf() {
    [[ "$SKIP_FZF" -eq 1 ]] && { log '[4/9] Skipping fzf installation/update.'; return; }

    log '[4/9] Installing/updating official fzf from GitHub...'
    if [[ -e "$HOME/.fzf" && ! -d "$HOME/.fzf/.git" ]]; then
        echo 'ERROR: ~/.fzf exists but is not a git checkout.' >&2
        echo 'Move or remove it manually before installing the official GitHub version.' >&2
        exit 1
    fi

    if [[ -d "$HOME/.fzf/.git" ]]; then
        local origin
        origin="$(git -C "$HOME/.fzf" remote get-url origin 2>/dev/null || true)"
        case "$origin" in
            *github.com/junegunn/fzf*|*github.com:junegunn/fzf*) ;;
            *)
                echo "ERROR: Existing ~/.fzf points to an unexpected origin: $origin" >&2
                exit 1
                ;;
        esac
        git -C "$HOME/.fzf" pull --ff-only
    else
        git clone --depth 1 https://github.com/junegunn/fzf.git "$HOME/.fzf"
    fi

    # Generate ~/.fzf.bash with key bindings and fuzzy completion, but do not
    # let the upstream installer edit ~/.bashrc. Our managed block owns that.
    "$HOME/.fzf/install" --all --no-update-rc
}

update_bashrc() {
    log '[5/9] Merging shell-setup into ~/.bashrc...'

    # If ~/.bashrc does not exist, create a safe minimal interactive Bash file.
    if [[ ! -e "$BASHRC" ]]; then
        cat > "$BASHRC" <<'BASHRC_EOF'
# ~/.bashrc
# If not running interactively, do not continue.
case $- in
    *i*) ;;
      *) return ;;
esac
BASHRC_EOF
    fi

    local tmp
    tmp="$(mktemp "$HOME/.bashrc.shell-setup.XXXXXX")"
    trap 'rm -f "${tmp:-}"' RETURN

    strip_managed_block "$BASHRC" "$tmp" "$BASH_BEGIN" "$BASH_END"

    # Detect fzf integration already owned by the user's existing ~/.bashrc.
    local fzf_already_configured=0
    if grep -Eq '(\.fzf\.bash|fzf[[:space:]]+--bash|/fzf/shell/(key-bindings|completion)\.bash)' "$tmp"; then
        fzf_already_configured=1
    fi

    {
        printf '\n%s\n' "$BASH_BEGIN"
        printf '%s\n' '# Portable history/completion/fzf options managed by shell-setup.'
        printf '[ -f %q ] && . %q\n' "$INSTALL_DIR/bashrc.common" "$INSTALL_DIR/bashrc.common"
        if [[ "$fzf_already_configured" -eq 0 ]]; then
            printf '\n%s\n' '# Official fzf Bash integration (Ctrl-R, Ctrl-T, Alt-C, **<TAB>.)'
            printf '%s\n' '[ -f "$HOME/.fzf.bash" ] && . "$HOME/.fzf.bash"'
        fi
        printf '%s\n' "$BASH_END"
    } >> "$tmp"

    if ! bash -n "$tmp"; then
        echo 'ERROR: Merged ~/.bashrc failed bash -n validation; original file was not changed.' >&2
        exit 1
    fi

    chmod --reference="$BASHRC" "$tmp" 2>/dev/null || chmod 0644 "$tmp"
    mv -f "$tmp" "$BASHRC"
    trap - RETURN
    log 'Merged ~/.bashrc validated successfully.'
}

update_inputrc() {
    log '[6/9] Merging shell-setup into ~/.inputrc...'

    # ~/.inputrc is often absent on a fresh Ubuntu installation. Create one
    # that inherits the distro-wide defaults before adding our managed block.
    if [[ ! -e "$INPUTRC" ]]; then
        cat > "$INPUTRC" <<'INPUTRC_EOF'
# ~/.inputrc created by shell-setup.
# Keep Debian/Ubuntu's system-wide Readline defaults.
$include /etc/inputrc
INPUTRC_EOF
    fi

    local tmp
    tmp="$(mktemp "$HOME/.inputrc.shell-setup.XXXXXX")"
    trap 'rm -f "${tmp:-}"' RETURN

    strip_managed_block "$INPUTRC" "$tmp" "$INPUT_BEGIN" "$INPUT_END"

    {
        printf '\n%s\n' "$INPUT_BEGIN"
        cat "$INSTALL_DIR/inputrc.common"
        printf '%s\n' "$INPUT_END"
    } >> "$tmp"

    # Parse with Readline before replacing the user's file. bind emits a
    # harmless warning in non-interactive mode, so suppress stderr here.
    if ! bash --noprofile --norc -c 'bind -f "$1"' _ "$tmp" 2>/dev/null; then
        echo 'ERROR: Merged ~/.inputrc failed Readline parsing; original file was not changed.' >&2
        exit 1
    fi

    chmod --reference="$INPUTRC" "$tmp" 2>/dev/null || chmod 0644 "$tmp"
    mv -f "$tmp" "$INPUTRC"
    trap - RETURN
    log 'Merged ~/.inputrc validated successfully.'
}

update_tmux_conf() {
    log '[7/9] Merging shell-setup into ~/.tmux.conf...'

    # ~/.tmux.conf is often absent. Keep it as a small loader so machine-local
    # tmux settings outside our managed block remain untouched.
    if [[ ! -e "$TMUX_CONF" ]]; then
        cat > "$TMUX_CONF" <<'TMUX_EOF'
# ~/.tmux.conf created by shell-setup.
TMUX_EOF
    fi

    local tmp
    tmp="$(mktemp "$HOME/.tmux.conf.shell-setup.XXXXXX")"
    trap 'rm -f "${tmp:-}"' RETURN

    strip_managed_block "$TMUX_CONF" "$tmp" "$TMUX_BEGIN" "$TMUX_END"

    {
        printf '\n%s\n' "$TMUX_BEGIN"
        printf '%s\n' '# Portable tmux settings managed by shell-setup.'
        printf 'source-file "%s"\n' "$INSTALL_DIR/tmux.conf.common"
        printf '%s\n' "$TMUX_END"
    } >> "$tmp"

    chmod --reference="$TMUX_CONF" "$tmp" 2>/dev/null || chmod 0644 "$tmp"
    mv -f "$tmp" "$TMUX_CONF"
    trap - RETURN
    log 'Merged ~/.tmux.conf successfully.'
}

validate_tmux_conf() {
    # Use a private tmux socket/server so validation cannot affect an existing
    # interactive tmux server. When --skip-packages is used in a test machine
    # without tmux, content checks below still run and parser validation skips.
    if command -v tmux >/dev/null 2>&1; then
        local socket="shell-setup-validate-$$-$RANDOM"
        if ! HOME="$HOME" tmux -L "$socket" -f "$TMUX_CONF" new-session -d -s shell-setup-validation 2>/dev/null; then
            echo 'ERROR: ~/.tmux.conf failed tmux validation.' >&2
            tmux -L "$socket" kill-server >/dev/null 2>&1 || true
            exit 1
        fi
        tmux -L "$socket" kill-server >/dev/null 2>&1 || true
    fi
}

run_installers() {
    [[ "$SKIP_INSTALLERS" -eq 1 ]] && { log '[8/9] Skipping installers/*.sh.'; return; }

    log '[8/9] Running installers/*.sh...'

    local installers=()
    local installer

    if [[ -d "$SCRIPT_DIR/installers" ]]; then
        while IFS= read -r -d '' installer; do
            installers+=("$installer")
        done < <(find "$SCRIPT_DIR/installers" -maxdepth 1 -type f -name '*.sh' -print0 | sort -z)
    fi

    if [[ ${#installers[@]} -eq 0 ]]; then
        log 'No installers/*.sh files found; skipping.'
        return
    fi

    for installer in "${installers[@]}"; do
        if ! bash -n "$installer"; then
            echo "ERROR: Installer has invalid Bash syntax: $installer" >&2
            exit 1
        fi

        # Repair pending dpkg state before every installer. This protects even
        # an older/custom installer that still uses raw `sudo apt install ...`.
        if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
            apt_repair
        fi

        echo
        echo '========================================'
        echo "Running: $(basename "$installer")"
        echo '========================================'

        SHELL_SETUP_ROOT="$SCRIPT_DIR" \
        SHELL_SETUP_SKIP_PACKAGES="$SKIP_PACKAGES" \
        bash "$installer"
    done
}

final_validation() {
    log '[9/9] Running final validation...'
    bash -n "$BASHRC"
    bash --noprofile --norc -c 'bind -f "$1"' _ "$INPUTRC" 2>/dev/null
    validate_tmux_conf

    local bash_blocks input_blocks tmux_blocks
    bash_blocks="$(grep -Fxc "$BASH_BEGIN" "$BASHRC" || true)"
    input_blocks="$(grep -Fxc "$INPUT_BEGIN" "$INPUTRC" || true)"
    tmux_blocks="$(grep -Fxc "$TMUX_BEGIN" "$TMUX_CONF" || true)"
    [[ "$bash_blocks" == 1 ]] || { echo "ERROR: Expected exactly one managed block in ~/.bashrc, found $bash_blocks." >&2; exit 1; }
    [[ "$input_blocks" == 1 ]] || { echo "ERROR: Expected exactly one managed block in ~/.inputrc, found $input_blocks." >&2; exit 1; }
    [[ "$tmux_blocks" == 1 ]] || { echo "ERROR: Expected exactly one managed block in ~/.tmux.conf, found $tmux_blocks." >&2; exit 1; }

    [[ -f "$INSTALL_DIR/bashrc.common" ]]
    [[ -f "$INSTALL_DIR/inputrc.common" ]]
    [[ -f "$INSTALL_DIR/tmux.conf.common" ]]
    [[ -x "$INSTALL_DIR/update.sh" ]]
    [[ -x "$INSTALL_DIR/lib/apt.sh" ]]
    log 'Final validation: OK'
}

log '========================================'
log ' shell-setup installer'
log '========================================'
install_packages
log '[2/9] Backing up existing shell/tmux configuration...'
backup_existing_configs
install_shared_files
install_fzf
update_bashrc
update_inputrc
update_tmux_conf
run_installers
final_validation

log
log 'Installation completed successfully.'
log "Backup: $BACKUP_DIR"
log "Installed common files: $INSTALL_DIR"
log "  Bash: $INSTALL_DIR/bashrc.common"
log "  Readline: $INSTALL_DIR/inputrc.common"
log "  tmux: $INSTALL_DIR/tmux.conf.common"
log "Future update command: $INSTALL_DIR/update.sh"
if [[ -z "$REPO_URL" && ! -f "$INSTALL_DIR/repo-url" ]]; then
    log 'To enable remote updates later, run update.sh once with: --repo-url <git-url>'
fi
log 'The original downloaded/cloned setup directory may now be deleted.'
log 'Open a new terminal to apply Bash/Readline settings.'
log 'For an existing tmux server, run: tmux source-file ~/.tmux.conf'
