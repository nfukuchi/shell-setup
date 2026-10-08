#!/usr/bin/env python3
"""Conservative, format-preserving edits of individual TOML scalar settings.

The standard-library TOML parser validates both versions and proves that only
requested fields changed. Unsupported structures fail closed, before a write.
This is not a general-purpose TOML serializer. Requires Python 3.11+.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
import json
import math
import tomllib
from typing import Any


class EditError(ValueError):
    pass


@dataclass(frozen=True)
class Statement:
    start: int
    end: int
    after: int


def statements(text: str) -> list[Statement]:
    """Find logical statements without mistaking string/comment text for keys."""
    result = []
    i, length = 0, len(text)
    while i < length:
        while i < length and text[i] in ' \t\r\n':
            i += 1
        if i == length:
            break
        if text[i] == '#':
            j = text.find('\n', i)
            i = length if j == -1 else j + 1
            continue
        start, depth, quote, triple = i, 0, None, False
        while i < length:
            ch = text[i]
            if quote:
                if quote == '"' and ch == '\\':
                    i += 2
                    continue
                if ch == quote:
                    if not triple:
                        quote = None
                    elif text.startswith(ch * 3, i):
                        # A valid multiline string can end in 3, 4 or 5 quotes.
                        j = i
                        while j < length and text[j] == ch:
                            j += 1
                        i, quote = j, None
                        continue
                i += 1
                continue
            if ch in ('"', "'"):
                quote = ch
                triple = text.startswith(ch * 3, i)
                i += 3 if triple else 1
                continue
            if ch == '#':
                end = start + len(text[start:i].rstrip(' \t\r'))
                j = text.find('\n', i)
                i = length if j == -1 else j + 1
                if depth == 0:
                    result.append(Statement(start, end, i))
                    break
                continue
            if ch in '[{':
                depth += 1
            elif ch in ']}':
                depth -= 1
            elif ch == '\n' and depth == 0:
                end = start + len(text[start:i].rstrip(' \t\r'))
                i += 1
                result.append(Statement(start, end, i))
                break
            i += 1
        else:
            result.append(Statement(start, length, length))
    return result


def _path(tree: Any) -> tuple[str, ...]:
    result = []
    while isinstance(tree, dict) and len(tree) == 1:
        key, tree = next(iter(tree.items()))
        result.append(key)
    if tree != 0 or type(tree) is not int:
        raise EditError('Unsupported TOML key structure')
    return tuple(result)


def _assignment(code: str) -> tuple[tuple[str, ...], int]:
    quote = None
    i = 0
    while i < len(code):
        ch = code[i]
        if quote:
            if quote == '"' and ch == '\\':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == '=':
            keys = _path(tomllib.loads(code[:i] + ' = 0'))
            i += 1
            while i < len(code) and code[i] in ' \t':
                i += 1
            return keys, i
        i += 1
    raise EditError('Could not locate the TOML assignment')


def _table(code: str) -> tuple[str, ...] | None:
    if code.startswith('[['):
        return None
    keys = _path(tomllib.loads(code + '\n__shell_setup_probe__ = 0'))
    return keys[:-1]


def _get(tree: dict, path: tuple[str, ...], missing: Any) -> Any:
    node = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return missing
        node = node[key]
    return node


def equivalent(first: Any, second: Any) -> bool:
    if type(first) is not type(second):
        return False
    if isinstance(first, dict):
        return first.keys() == second.keys() and all(equivalent(first[k], second[k]) for k in first)
    if isinstance(first, list):
        return len(first) == len(second) and all(equivalent(a, b) for a, b in zip(first, second))
    if isinstance(first, float) and math.isnan(first):
        return math.isnan(second)
    return first == second


def replace_scalar(text: str, path: tuple[str, ...], value: str | bool) -> str:
    original = tomllib.loads(text)
    missing = object()
    current = _get(original, path, missing)
    if current is not missing and equivalent(current, value):
        return text
    expected = copy.deepcopy(original)
    parent = expected
    for key in path[:-1]:
        parent = parent.setdefault(key, {})
        if not isinstance(parent, dict):
            raise EditError('Non-table ancestor of managed setting: ' + '.'.join(path))
    parent[path[-1]] = value
    encoded = ('true' if value else 'false') if isinstance(value, bool) else json.dumps(value)
    parts = statements(text)
    context: tuple[str, ...] | None = ()
    table_after = None
    found = None
    for part in parts:
        code = text[part.start:part.end]
        if code.startswith('['):
            context = _table(code)
            if context == path[:-1]:
                table_after = part.after
            continue
        lhs, rhs = _assignment(code)
        effective = None if context is None else context + lhs
        if effective == path:
            found = (part.start + rhs, part.end)
            break
        if effective and path[:len(effective)] == effective and len(effective) < len(path):
            raise EditError('Expand the inline table containing ' + '.'.join(path) +
                            ' into a regular [table] before applying; file unchanged')
    newline = '\r\n' if '\r\n' in text else '\n'
    if found:
        edited = text[:found[0]] + encoded + text[found[1]:]
    elif current is not missing:
        raise EditError('Managed setting is declared as a table: ' + '.'.join(path) +
                        '; convert it to a scalar assignment before applying')
    elif path[:-1] and table_after is not None:
        prefix = '' if table_after == 0 or text[table_after - 1] == '\n' else newline
        edited = (text[:table_after] + prefix + json.dumps(path[-1]) + ' = ' + encoded +
                  newline + text[table_after:])
    else:
        at = parts[0].start if parts else len(text)
        prefix = '' if at == 0 or text[at - 1] == '\n' else newline
        key = '.'.join(json.dumps(p) for p in path)
        edited = text[:at] + prefix + key + ' = ' + encoded + newline + text[at:]
    try:
        after = tomllib.loads(edited)
    except tomllib.TOMLDecodeError as exc:
        raise EditError('Unsupported TOML layout; no changes written: ' + str(exc)) from exc
    if not equivalent(expected, after):
        raise EditError('Post-edit validation failed; unrelated values would change')
    return edited


def merge_scalars(text: str, changes: dict[tuple[str, ...], str | bool]) -> str:
    for path, value in changes.items():
        text = replace_scalar(text, path, value)
    return text
