# SPDX-License-Identifier: AGPL-3.0-or-later
"""TOON (Token-Oriented Object Notation) encoder.

TOON is a compact, indentation-based serialisation designed to be token-cheap when handed to an LLM:
YAML-style ``key: value`` nesting, but with two token-saving twists —

* an array declares its length inline: ``tags[3]: a,b,c`` (primitive arrays render on one line);
* a *uniform* array of flat objects renders as a **table** — one header row of field names, then one
  comma-separated row per object, so each field name is written once instead of once per element::

      objects[2]{id,name,role}:
        1,alice,admin
        2,bob,user

Non-uniform arrays fall back to YAML-style ``-`` list items; nested objects nest by indentation.
This module is standalone (no NetBox / Django imports) and fully covered by ``tests/test_toon.py``.
"""

from __future__ import annotations

import math

_INDENT = "  "
_RESERVED = {"true", "false", "null"}
# Characters that force a value/key to be double-quoted (they are structural in TOON).
_SPECIAL = (",", ":", '"', "\n", "[", "]", "{", "}", "#", "|")


def encode(value: object) -> str:
    """Encode a JSON-safe value (dict / list / scalar) as TOON text (no trailing newline)."""
    lines: list[str] = []
    if isinstance(value, dict):
        _encode_mapping(value, 0, lines)
    elif isinstance(value, (list, tuple)):
        _encode_array("root", list(value), 0, lines)
    else:
        lines.append(_scalar(value))
    return "\n".join(lines)


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else _quote(str(value))
    text = str(value)
    if _needs_quoting(text):
        return _quote(text)
    return text


def _needs_quoting(text: str) -> bool:
    if text == "" or text != text.strip():
        return True
    if text.lower() in _RESERVED or _looks_numeric(text):
        return True
    if text == "-" or text.startswith("- "):
        return True
    return any(ch in text for ch in _SPECIAL)


def _key(name: str) -> str:
    text = str(name)
    if not text or any(ch.isspace() for ch in text) or any(ch in text for ch in _SPECIAL):
        return _quote(text)
    return text


def _encode_mapping(mapping: dict, depth: int, lines: list[str]) -> None:
    pad = _INDENT * depth
    for raw_key, value in mapping.items():
        key = _key(raw_key)
        if isinstance(value, dict):
            if value:
                lines.append(f"{pad}{key}:")
                _encode_mapping(value, depth + 1, lines)
            else:
                lines.append(f"{pad}{key}:")
        elif isinstance(value, (list, tuple)):
            _encode_array(key, list(value), depth, lines)
        else:
            lines.append(f"{pad}{key}: {_scalar(value)}")


def _uniform_object_keys(array: list) -> list[str] | None:
    """If every element is a flat object (dict of scalars) with the *same* key order, return that
    key list — the array is table-eligible. Otherwise ``None``."""
    if not array or not all(isinstance(item, dict) for item in array):
        return None
    keys = list(array[0].keys())
    if not keys:
        return None
    for item in array:
        if list(item.keys()) != keys:
            return None
        if not all(_is_scalar(item[k]) for k in keys):
            return None
    return keys


def _encode_array(key: str, array: list, depth: int, lines: list[str]) -> None:
    pad = _INDENT * depth
    count = len(array)
    if count == 0:
        lines.append(f"{pad}{key}[0]:")
        return

    if all(_is_scalar(item) for item in array):  # primitive array → single inline line
        joined = ",".join(_scalar(item) for item in array)
        lines.append(f"{pad}{key}[{count}]: {joined}")
        return

    header = _uniform_object_keys(array)
    if header is not None:  # tabular form
        cols = ",".join(_key(name) for name in header)
        lines.append(f"{pad}{key}[{count}]{{{cols}}}:")
        row_pad = _INDENT * (depth + 1)
        for item in array:
            lines.append(row_pad + ",".join(_scalar(item[name]) for name in header))
        return

    # General fallback: YAML-style list items.
    lines.append(f"{pad}{key}[{count}]:")
    for item in array:
        _encode_list_item(item, depth + 1, lines)


def _encode_list_item(item: object, depth: int, lines: list[str]) -> None:
    pad = _INDENT * depth
    if isinstance(item, dict):
        if not item:
            lines.append(f"{pad}-")
            return
        inner: list[str] = []
        _encode_mapping(item, 0, inner)
        for index, line in enumerate(inner):
            prefix = f"{pad}- " if index == 0 else f"{pad}  "
            lines.append(prefix + line)
    elif isinstance(item, (list, tuple)):
        nested = list(item)
        if all(_is_scalar(sub) for sub in nested):
            joined = ",".join(_scalar(sub) for sub in nested)
            lines.append(f"{pad}- [{len(nested)}]: {joined}")
        else:
            lines.append(f"{pad}-")
            for sub in nested:
                _encode_list_item(sub, depth + 1, lines)
    else:
        lines.append(f"{pad}- {_scalar(item)}")
