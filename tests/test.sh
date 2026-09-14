#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT INT TERM

pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_file() { [[ -f "$1" ]] || fail "missing file: $1"; }
assert_contains() { grep -Fq "$2" "$1" || fail "$1 does not contain: $2"; }
assert_count() {
    local got
    got="$(grep -Fxc "$2" "$1" || true)"
    [[ "$got" == "$3" ]] || fail "$1: expected '$2' count $3, got $got"
}

run_install() {
    HOME="$1" XDG_CONFIG_HOME="$1/.config" \
        "$ROOT/install.sh" --skip-packages --skip-fzf --repo-url "$2"
}

# ---------------------------------------------------------------------------
# Scenario 1: Existing ROS ~/.bashrc, no ~/.inputrc, existing fzf source.
# ---------------------------------------------------------------------------
HOME1="$TEST_ROOT/home-ros"
mkdir -p "$HOME1"
cat > "$HOME1/.bashrc" <<'BASHRC'
case $- in
    *i*) ;;
      *) return;;
esac
HISTCONTROL=ignoreboth
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=10
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
. "$HOME/.local/bin/env"
[ -f ~/.fzf.bash ] && source ~/.fzf.bash
BASHRC

run_install "$HOME1" 'file:///tmp/fake-shell-setup.git'
assert_contains "$HOME1/.bashrc" 'source /opt/ros/jazzy/setup.bash'
assert_contains "$HOME1/.bashrc" 'export ROS_DOMAIN_ID=10'
assert_contains "$HOME1/.bashrc" '. "$HOME/.local/bin/env"'
assert_count "$HOME1/.bashrc" '# >>> shell-setup >>>' 1
assert_count "$HOME1/.bashrc" '[ -f ~/.fzf.bash ] && source ~/.fzf.bash' 1
assert_file "$HOME1/.inputrc"
assert_contains "$HOME1/.inputrc" '$include /etc/inputrc'
assert_count "$HOME1/.inputrc" '# >>> shell-setup >>>' 1
assert_file "$HOME1/.config/shell-setup/bashrc.common"
assert_file "$HOME1/.config/shell-setup/inputrc.common"
[[ -x "$HOME1/.config/shell-setup/update.sh" ]] || fail 'installed update.sh is not executable'
find "$HOME1/.shell-setup-backup" -name '.inputrc.WAS_ABSENT' -print -quit | grep -q . || fail 'missing absent-inputrc backup marker'
bash -n "$HOME1/.bashrc"
bash --noprofile --norc -c 'bind -f "$1"' _ "$HOME1/.inputrc" 2>/dev/null
pass 'existing ROS bashrc preserved; absent inputrc created safely'

# Re-run and ensure managed blocks do not duplicate.
run_install "$HOME1" 'file:///tmp/fake-shell-setup.git'
assert_count "$HOME1/.bashrc" '# >>> shell-setup >>>' 1
assert_count "$HOME1/.inputrc" '# >>> shell-setup >>>' 1
assert_contains "$HOME1/.bashrc" 'source /opt/ros/jazzy/setup.bash'
pass 're-install is idempotent for managed blocks'

# ---------------------------------------------------------------------------
# Scenario 2: Existing custom ~/.inputrc and machine-specific CUDA settings.
# ---------------------------------------------------------------------------
HOME2="$TEST_ROOT/home-custom"
mkdir -p "$HOME2"
cat > "$HOME2/.bashrc" <<'BASHRC'
case $- in *i*) ;; *) return;; esac
export CUDA_HOME=/usr/local/cuda
export MY_MACHINE_ONLY=value
BASHRC
cat > "$HOME2/.inputrc" <<'INPUTRC'
$include /etc/inputrc
set bell-style none
INPUTRC

run_install "$HOME2" 'file:///tmp/fake-shell-setup.git'
assert_contains "$HOME2/.bashrc" 'export CUDA_HOME=/usr/local/cuda'
assert_contains "$HOME2/.bashrc" 'export MY_MACHINE_ONLY=value'
assert_contains "$HOME2/.bashrc" '[ -f "$HOME/.fzf.bash" ] && . "$HOME/.fzf.bash"'
assert_contains "$HOME2/.inputrc" 'set bell-style none'
assert_count "$HOME2/.inputrc" '# >>> shell-setup >>>' 1
find "$HOME2/.shell-setup-backup" -name '.inputrc' -print -quit | grep -q . || fail 'existing inputrc was not backed up'
pass 'existing inputrc and CUDA settings preserved'

# ---------------------------------------------------------------------------
# Scenario 3: Installed update.sh fetches a newer Git revision after the
# original clone is gone.
# ---------------------------------------------------------------------------
REPO_WORK="$TEST_ROOT/repo-work"
REPO_BARE="$TEST_ROOT/repo.git"
cp -a "$ROOT" "$REPO_WORK"
rm -rf "$REPO_WORK/.git"
git -C "$REPO_WORK" init -q
git -C "$REPO_WORK" config user.email test@example.invalid
git -C "$REPO_WORK" config user.name shell-setup-test
git -C "$REPO_WORK" add .
git -C "$REPO_WORK" commit -qm 'v1'
git clone -q --bare "$REPO_WORK" "$REPO_BARE"
REPO_URL="file://$REPO_BARE"

HOME3="$TEST_ROOT/home-update"
mkdir -p "$HOME3"
printf '%s\n' 'case $- in *i*) ;; *) return;; esac' > "$HOME3/.bashrc"
HOME="$HOME3" XDG_CONFIG_HOME="$HOME3/.config" \
    "$REPO_WORK/install.sh" --skip-packages --skip-fzf --repo-url "$REPO_URL" >/dev/null

# Publish a changed common file.
printf '\n# regression-test-version-2\n' >> "$REPO_WORK/bashrc.common"
git -C "$REPO_WORK" add bashrc.common
git -C "$REPO_WORK" commit -qm 'v2'
git -C "$REPO_WORK" push -q "$REPO_BARE" HEAD:master

HOME="$HOME3" XDG_CONFIG_HOME="$HOME3/.config" \
    "$HOME3/.config/shell-setup/update.sh" --skip-packages --skip-fzf >/dev/null
assert_contains "$HOME3/.config/shell-setup/bashrc.common" '# regression-test-version-2'
assert_count "$HOME3/.bashrc" '# >>> shell-setup >>>' 1
assert_count "$HOME3/.inputrc" '# >>> shell-setup >>>' 1
pass 'update.sh fetched and installed latest Git revision using remembered URL'

printf '\nALL TESTS PASSED\n'
