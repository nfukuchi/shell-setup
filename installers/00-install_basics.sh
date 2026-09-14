#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${SHELL_SETUP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# shellcheck source=../lib/apt.sh
. "$ROOT_DIR/lib/apt.sh"

# Basic CLI/development utilities.
# Use apt_install rather than raw `sudo apt install` so an interrupted dpkg
# transaction is repaired automatically before package installation.
apt_install \
    vim \
    ffmpeg \
    wget \
    git \
    git-lfs \
    tmux \
    tree \
    zip \
    unzip \
    fd-find \
    curl
