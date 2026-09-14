#!/usr/bin/env bash
# Common APT/dpkg helpers for shell-setup installers.
# Safe to source from install.sh or installers/*.sh.

# Do not enable set -e/-u here; inherit caller policy.

_shell_setup_apt_log() {
    printf '%s\n' "$*"
}

_shell_setup_sudo_cmd() {
    if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        "$@"
    else
        if ! command -v sudo >/dev/null 2>&1; then
            echo 'ERROR: sudo is required for apt/dpkg operations.' >&2
            return 1
        fi
        sudo "$@"
    fi
}

apt_repair() {
    if [[ "${SHELL_SETUP_SKIP_PACKAGES:-0}" == 1 ]]; then
        _shell_setup_apt_log 'Skipping apt/dpkg operation (--skip-packages).'
        return 0
    fi

    if ! command -v dpkg >/dev/null 2>&1 || ! command -v apt-get >/dev/null 2>&1; then
        echo 'ERROR: apt_repair requires Debian/Ubuntu dpkg and apt-get.' >&2
        return 1
    fi

    _shell_setup_apt_log 'Checking dpkg state...'

    # This is the canonical recovery for:
    #   E: dpkg was interrupted, you must manually run 'sudo dpkg --configure -a'
    # It is harmless when there is nothing pending.
    if _shell_setup_sudo_cmd dpkg --configure -a; then
        return 0
    fi

    # If configuration did not complete because dependencies are broken,
    # ask apt to repair them, waiting for an existing apt/dpkg frontend lock.
    _shell_setup_apt_log 'dpkg configuration did not complete; attempting dependency repair...'
    _shell_setup_sudo_cmd apt-get \
        -o DPkg::Lock::Timeout=120 \
        -f install -y

    # Finish any package configuration left after dependency repair.
    _shell_setup_sudo_cmd dpkg --configure -a
}

apt_update_once() {
    if [[ "${SHELL_SETUP_SKIP_PACKAGES:-0}" == 1 ]]; then
        return 0
    fi

    if [[ "${SHELL_SETUP_APT_UPDATED:-0}" == 1 ]]; then
        return 0
    fi

    apt_repair
    _shell_setup_apt_log 'Updating apt package index...'
    _shell_setup_sudo_cmd apt-get \
        -o DPkg::Lock::Timeout=120 \
        update

    # Export so installers started as child shells inherit it.
    export SHELL_SETUP_APT_UPDATED=1
}

_apt_package_installed() {
    local pkg="$1"
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -qx 'install ok installed'
}

apt_install() {
    if [[ "${SHELL_SETUP_SKIP_PACKAGES:-0}" == 1 ]]; then
        _shell_setup_apt_log "Skipping APT packages (--skip-packages): $*"
        return 0
    fi

    if [[ $# -eq 0 ]]; then
        return 0
    fi

    apt_repair

    local missing=()
    local pkg
    for pkg in "$@"; do
        if ! _apt_package_installed "$pkg"; then
            missing+=("$pkg")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        _shell_setup_apt_log "APT packages already installed: $*"
        return 0
    fi

    apt_update_once
    _shell_setup_apt_log "Installing APT packages: ${missing[*]}"
    _shell_setup_sudo_cmd apt-get \
        -o DPkg::Lock::Timeout=120 \
        install -y "${missing[@]}"

    # Complete package post-install configuration before returning control to
    # the next installer. This also makes the next installer robust after an
    # interrupted package transaction.
    apt_repair
}
