#!/usr/bin/env python3
"""Targeted Windows Terminal JSONC edits using Python's standard library.

Only existing, unambiguously selected profiles are modified. Comments,
unknown settings, BOM and newline conventions are retained. This module is
platform-independent for testing; the Bash installer enforces WSL/SSH guards.
"""
from __future__ import annotations
import argparse
import copy
import difflib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid
from terminal_palette import load_palette, windows_scheme


class SettingsError(ValueError):
    """Unsafe or unsupported input: do not write anything."""


class SelectionError(SettingsError):
    """The requested profile could not be selected unambiguously."""

@dataclass
class Node:
    start: int
    end: int
    value: Any
    children: Any = None
    key_starts: dict[str, int] = field(default_factory=dict)


def reject_constant(value: str) -> None:
    raise SettingsError(f"Non-JSON constant: {value}")


class Jsonc:
    """Small span-preserving parser for JSON plus comments/trailing commas.
    Duplicate properties and other JSON5 extensions are deliberately rejected.
    Strings are parsed by Python's JSON decoder, not by comment-removal regexes.
    """
    trivia = re.compile(r"[ \t\r\n]+|//[^\r\n]*|/\*.*?\*/", re.DOTALL)

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.decoder = json.JSONDecoder(parse_constant=reject_constant)
    def skip(self) -> None:
        while match := self.trivia.match(self.text, self.pos):
            self.pos = match.end()

    def parse(self) -> Node:
        result = self.node()
        self.skip()
        if self.pos != len(self.text):
            raise SettingsError(f"Unexpected content at character {self.pos}")
        return result
    def node(self, depth: int = 0) -> Node:
        if depth > 128:
            raise SettingsError("JSON nesting exceeds 128 levels")
        self.skip()
        start = self.pos
        if start >= len(self.text):
            raise SettingsError("Unexpected end of JSON")
        char = self.text[start]
        if char not in "{[":
            if char not in '"-0123456789tfn':
                raise SettingsError(f"Unexpected token at character {start}")
            try:
                value, self.pos = self.decoder.raw_decode(self.text, start)
            except ValueError as exc:
                raise SettingsError(str(exc)) from exc
            return Node(start, self.pos, value)
        is_object = char == "{"
        closing = "}" if is_object else "]"
        values: Any = {} if is_object else []
        children: Any = {} if is_object else []
        key_starts: dict[str, int] = {}
        self.pos += 1
        self.skip()
        while self.pos < len(self.text) and self.text[self.pos] != closing:
            if is_object:
                key_start = self.pos
                key = self.node(depth + 1)
                if not isinstance(key.value, str):
                    raise SettingsError("Object keys must be quoted strings")
                if key.value in values:
                    raise SettingsError(f"Duplicate JSON property: {key.value!r}")
                self.skip()
                if self.text[self.pos:self.pos + 1] != ":":
                    raise SettingsError("Expected ':' after a property name")
                self.pos += 1
                child = self.node(depth + 1)
                values[key.value] = child.value
                children[key.value] = child
                key_starts[key.value] = key_start
            else:
                child = self.node(depth + 1)
                values.append(child.value)
                children.append(child)
            self.skip()
            if self.text[self.pos:self.pos + 1] == closing:
                break
            if self.text[self.pos:self.pos + 1] != ",":
                raise SettingsError(f"Expected ',' or '{closing}' at character {self.pos}")
            self.pos += 1
            self.skip()
            # A single trailing comma is accepted; repeated commas are not.
        if self.text[self.pos:self.pos + 1] != closing:
            raise SettingsError(f"Missing closing '{closing}'")
        self.pos += 1
        return Node(start, self.pos, values, children, key_starts)

def validate_appearance(data: Any) -> dict[str, Any]:
    allowed = {"colorScheme", "background", "opacity", "useAcrylic"}
    if not isinstance(data, dict) or not data or data.keys() - allowed:
        raise SettingsError("Appearance config must contain only colorScheme/background/opacity/useAcrylic")
    if "colorScheme" in data and (not isinstance(data["colorScheme"], str) or not data["colorScheme"]):
        raise SettingsError("colorScheme must be a nonempty string")
    if "background" in data and (not isinstance(data["background"], str) or
            re.fullmatch(r"#[0-9a-fA-F]{6}", data["background"]) is None):
        raise SettingsError("background must be a #rrggbb string")
    if "opacity" in data and (type(data["opacity"]) is not int or not 0 <= data["opacity"] <= 100):
        raise SettingsError("opacity must be an integer from 0 through 100")
    if "useAcrylic" in data and type(data["useAcrylic"]) is not bool:
        raise SettingsError("useAcrylic must be true or false")
    return data

def profile_list(root: Node) -> Node:
    if not isinstance(root.value, dict) or "profiles" not in root.children:
        raise SettingsError("Expected a top-level profiles property")
    profiles = root.children["profiles"]
    if isinstance(profiles.value, dict):
        profiles = profiles.children.get("list")
    if profiles is None or not isinstance(profiles.value, list):
        raise SettingsError("Expected profiles.list to be an array")
    if any(not isinstance(node.value, dict) for node in profiles.children):
        raise SettingsError("Every profile must be an object")
    return profiles

def normalized_guid(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise SettingsError(f"Invalid profile GUID: {value!r}") from exc

def choose_profile(root: Node, name: str, guid: str | None = None) -> tuple[int, Node]:
    entries = profile_list(root).children
    if guid:
        wanted = normalized_guid(guid)
        matches = [(i, node) for i, node in enumerate(entries)
                   if node.value.get("guid") and normalized_guid(node.value["guid"]) == wanted]
    else:
        matches = [(i, node) for i, node in enumerate(entries) if node.value.get("name") == name]
    if len(matches) != 1:
        raise SelectionError(
            f"Expected one existing profile for {guid or name!r}; found {len(matches)}. "
            "Open its WSL profile in Windows Terminal first. For renamed or duplicate profiles, "
            "set SHELL_SETUP_WT_PROFILE or SHELL_SETUP_WT_PROFILE_GUID explicitly. "
            "No profiles were created or changed."
        )
    return matches[0]

def edit_object(text: str, node: Node, values: dict[str, Any]) -> str:
    """Change only requested value spans; retain existing comments and other keys."""
    edits = []
    missing = {}
    for key, value in values.items():
        if key not in node.children:
            missing[key] = value
        elif type(node.value[key]) is not type(value) or node.value[key] != value:
            child = node.children[key]
            edits.append((child.start, child.end, json.dumps(value, ensure_ascii=False)))
    if missing:
        nl = "\r\n" if "\r\n" in text else "\n"
        block = nl + ("," + nl).join(
            "    " + json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False)
            for k, v in missing.items()) + ("," if node.children else "") + nl
        edits.append((node.start + 1, node.start + 1, block))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def upsert_scheme(text: str, scheme: dict[str, str]) -> tuple[str, list[Any]]:
    root = Jsonc(text).parse()
    if 'schemes' not in root.children:
        return edit_object(text, root, {'schemes': [scheme]}), [scheme]
    schemes = root.children['schemes']
    if not isinstance(schemes.value, list) or any(not isinstance(n.value, dict) for n in schemes.children):
        raise SettingsError('schemes must be an array of objects')
    matches = [(i, n) for i, n in enumerate(schemes.children) if n.value.get('name') == scheme['name']]
    if len(matches) > 1:
        raise SettingsError('Duplicate managed color scheme name; resolve it before applying')
    expected = copy.deepcopy(schemes.value)
    if matches:
        index, node = matches[0]
        expected[index].update(scheme)
        return edit_object(text, node, scheme), expected
    nl = "\r\n" if "\r\n" in text else "\n"
    block = nl + '    ' + json.dumps(scheme, ensure_ascii=False) + (',' if schemes.children else '') + nl
    at = schemes.start + 1
    expected.insert(0, scheme)
    return text[:at] + block + text[at:], expected


def update_text(text: str, appearance: dict[str, Any], name: str,
                guid: str | None = None, palette: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
    appearance = validate_appearance(appearance)
    root = Jsonc(text).parse()
    index, target = choose_profile(root, name, guid)
    edits: list[tuple[int, int, str]] = []
    missing: dict[str, Any] = {}
    for key, value in appearance.items():
        if key not in target.children:
            missing[key] = value
        elif type(target.value[key]) is not type(value) or target.value[key] != value:
            node = target.children[key]
            edits.append((node.start, node.end, json.dumps(value, ensure_ascii=False)))
    if missing:
        newline = "\r\n" if "\r\n" in text else "\n"
        anchor = next(iter(target.key_starts.values()), target.start)
        line_start = text.rfind("\n", 0, anchor) + 1
        prefix = text[line_start:anchor]
        indent = prefix if not prefix.strip() else "    "
        lines = [indent + json.dumps(key) + ": " + json.dumps(value, ensure_ascii=False)
                 for key, value in missing.items()]
        block = newline + ("," + newline).join(lines)
        if target.children:
            block += ","
        block += newline
        edits.append((target.start + 1, target.start + 1, block))
    edited = text
    for start, end, replacement in sorted(edits, reverse=True):
        edited = edited[:start] + replacement + edited[end:]
    # Reparse before writing and verify that ALL unrelated values survived.
    expected = copy.deepcopy(root.value)
    expected_profiles = expected["profiles"]
    if isinstance(expected_profiles, dict):
        expected_profiles = expected_profiles["list"]
    expected_profiles[index].update(appearance)
    if palette is not None:
        scheme = windows_scheme(palette, appearance.get('background', '#000000'))
        if appearance.get('colorScheme') != scheme['name']:
            raise SettingsError('colorScheme in the appearance config must match the shared palette name')
        edited, expected['schemes'] = upsert_scheme(edited, scheme)
    if Jsonc(edited).parse().value != expected:
        raise SettingsError("Post-edit validation failed; original file was not modified")
    return edited, target.value

def apply_file(path: Path, appearance: dict[str, Any], name: str,
               guid: str | None = None, dry_run: bool = False,
               palette: dict[str, str] | None = None) -> Path | None:
    if path.is_symlink() or not path.is_file():
        raise SettingsError(f"Not a regular non-symlink settings file: {path}")
    original = path.read_bytes()
    has_bom = original.startswith(b"\xef\xbb\xbf")
    text = original.decode("utf-8-sig")
    edited, target = update_text(text, appearance, name, guid, palette)
    label = target.get("name", target.get("guid", name))
    print(f"Windows Terminal: settings={path}")
    print(f"Windows Terminal: profile={label}")
    if edited == text:
        print("Windows Terminal: unchanged (already configured)")
        return None
    if dry_run:
        print("Windows Terminal: DRY RUN - no files written")
        print("".join(difflib.unified_diff(text.splitlines(keepends=True),
              edited.splitlines(keepends=True), fromfile=str(path), tofile=str(path) + " (proposed)")), end="")
        return None
    payload = (b"\xef\xbb\xbf" if has_bom else b"") + edited.encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = path.with_name(path.name + f".shell-setup-backup-{stamp}-{uuid.uuid4().hex[:8]}.bak")
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(prefix=".shell-setup-terminal-", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        if path.is_symlink() or path.read_bytes() != original:
            raise SettingsError("Settings changed during editing; close the settings editor and retry")
        with backup.open("xb") as handle:
            handle.write(original)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(backup, mode)
        # Optimistic concurrency check. Do not edit settings in another app while running.
        if path.is_symlink() or path.read_bytes() != original:
            raise SettingsError("Concurrent settings edit detected; no changes were applied")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    print(f"Windows Terminal: backup={backup}")
    print("Windows Terminal: UPDATED - reopen the target tab; restart Terminal if needed")
    return backup

def find_settings(local_app_data: Path) -> list[Path]:
    candidates = [
        local_app_data / "Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json",
        local_app_data / "Packages/Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe/LocalState/settings.json",
        local_app_data / "Microsoft/Windows Terminal/settings.json",
    ]
    return [path for path in candidates if path.is_file()]

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--settings", type=Path)
    source.add_argument("--local-app-data", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--palette-config", type=Path)
    parser.add_argument("--guid")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        appearance = validate_appearance(Jsonc(args.config.read_text(encoding="utf-8-sig")).parse().value)
        if args.settings is not None:
            path = args.settings
        else:
            paths = find_settings(args.local_app_data)
            if len(paths) != 1:
                print(f"Windows Terminal: SKIP - found {len(paths)} candidate settings files.")
                for candidate in paths:
                    print(f"  {candidate}")
                print("Open Windows Terminal once if none exist. If multiple exist, set "
                      "SHELL_SETUP_WT_SETTINGS to the intended file's WSL path and rerun.")
                return 0
            path = paths[0]
        palette = load_palette(args.palette_config) if args.palette_config else None
        apply_file(path, appearance, args.profile, args.guid, args.dry_run, palette)
        return 0
    except SelectionError as exc:
        print(f"Windows Terminal: SKIP - {exc}")
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print(f"Windows Terminal: ERROR - {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
