#!/usr/bin/env python3
"""One named ANSI palette shared by GNOME Terminal and Windows Terminal."""
from __future__ import annotations
import json
from pathlib import Path
import re
from typing import Any

ANSI_KEYS = (
    'black', 'red', 'green', 'yellow', 'blue', 'purple', 'cyan', 'white',
    'brightBlack', 'brightRed', 'brightGreen', 'brightYellow',
    'brightBlue', 'brightPurple', 'brightCyan', 'brightWhite',
)


def validate_palette(data: Any) -> dict[str, str]:
    if not isinstance(data, dict) or set(data) != {'name', *ANSI_KEYS}:
        raise ValueError('Palette must contain name and exactly the 16 ANSI color keys')
    name = data['name']
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('Palette name must be a nonempty printable string of at most 80 characters')
    for key in ANSI_KEYS:
        if not isinstance(data[key], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', data[key]):
            raise ValueError(f'Palette {key} must be a #rrggbb string')
    return dict(data)


def load_palette(path: Path) -> dict[str, str]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate palette key: {key}')
            result[key] = value
        return result
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError(f'Expected a palette JSON file no larger than 64 KiB: {path}')
    return validate_palette(json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique))


def ansi_palette(data: dict[str, str]) -> list[str]:
    data = validate_palette(data)
    return [data[key] for key in ANSI_KEYS]


def windows_scheme(data: dict[str, str], background: str = '#000000') -> dict[str, str]:
    data = validate_palette(data)
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', background):
        raise ValueError('Scheme background must be a #rrggbb string')
    return {**data, 'background': background, 'foreground': data['white'],
            'cursorColor': data['brightWhite'], 'selectionBackground': data['brightBlack']}
