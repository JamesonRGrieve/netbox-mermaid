# SPDX-License-Identifier: AGPL-3.0-or-later
"""Encode the introspected SoT dict (from :func:`netbox_mermaid.report.introspect.build_report`) into
the three requested output formats: **markdown**, **json**, and **toon**.

Each format is content-negotiable: :func:`render_report` returns ``(content, content_type, filename)``
so the API can serve the raw artifact with the right MIME type + a download name, and the UI can embed
it. All three consume the same dict, so a new plugin never touches this module.
"""

from __future__ import annotations

import json

from . import toon

# format alias -> canonical name
FORMATS: dict[str, str] = {
    "markdown": "markdown",
    "md": "markdown",
    "json": "json",
    "toon": "toon",
}
DEFAULT_FORMAT = "markdown"

_CONTENT_TYPE: dict[str, str] = {
    "markdown": "text/markdown; charset=utf-8",
    "json": "application/json",
    "toon": "text/plain; charset=utf-8",
}
_EXTENSION: dict[str, str] = {"markdown": "md", "json": "json", "toon": "toon"}


def normalize_format(value: str | None) -> str:
    """Map a requested format (any alias, any case) to a canonical name, defaulting safely."""
    return FORMATS.get((value or "").strip().lower(), DEFAULT_FORMAT)


def render_report(data: dict, fmt: str) -> tuple[str, str, str]:
    """Render ``data`` in ``fmt`` (canonical). Returns ``(content, content_type, filename)``."""
    canonical = normalize_format(fmt)
    if canonical == "json":
        content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    elif canonical == "toon":
        content = toon.encode(data)
    else:
        content = _to_markdown(data)
    return content, _CONTENT_TYPE[canonical], f"netbox-sot-report.{_EXTENSION[canonical]}"


def _cell(value: object) -> str:
    """Render one field value as a single Markdown table cell (pipes/newlines neutralised)."""
    if value is None:
        text = ""
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _to_markdown(data: dict) -> str:
    summary = data.get("summary", {}) or {}
    lines: list[str] = ["# NetBox Source-of-Truth Report", ""]
    generated = data.get("generated")
    version = data.get("netbox_version")
    meta_bits = []
    if generated:
        meta_bits.append(f"**Generated:** {generated}")
    if version:
        meta_bits.append(f"**NetBox:** {version}")
    meta_bits.append(
        f"**Apps:** {summary.get('apps', 0)} · "
        f"**Models:** {summary.get('models', 0)} · "
        f"**Objects:** {summary.get('objects', 0)}"
    )
    lines.append("  \n".join(meta_bits))
    lines.append("")

    sections = data.get("sections", []) or []

    # Contents index — one bullet per app with its object total.
    if sections:
        lines.append("## Contents")
        lines.append("")
        current_group = None
        for section in sections:
            group = section.get("group")
            if group != current_group:
                current_group = group
                lines.append(f"- **{_group_title(group)}**")
            total = sum(m.get("count", 0) for m in section.get("models", []))
            anchor = _anchor(section.get("app_label", ""))
            lines.append(
                f"  - [{section.get('app_name')} "
                f"(`{section.get('app_label')}`)](#{anchor}) — {total} objects"
            )
        lines.append("")

    current_group = None
    for section in sections:
        group = section.get("group")
        if group != current_group:
            current_group = group
            lines.append(f"## {_group_title(group)}")
            lines.append("")
        lines.append(
            f"### {section.get('app_name')} (`{section.get('app_label')}`)"
            f' <a id="{_anchor(section.get("app_label", ""))}"></a>'
        )
        lines.append("")
        for model in section.get("models", []):
            lines.append(f"#### {model.get('model')} — `{model.get('label')}` ({model.get('count')})")
            lines.append("")
            if model.get("error"):
                lines.append(f"> ⚠️ could not introspect: {model['error']}")
                lines.append("")
                continue
            objects = model.get("objects", [])
            fields = model.get("fields", [])
            if not objects or not fields:
                lines.append("_none_")
                lines.append("")
                continue
            lines.append("| " + " | ".join(_cell(f) for f in fields) + " |")
            lines.append("| " + " | ".join("---" for _ in fields) + " |")
            for obj in objects:
                lines.append("| " + " | ".join(_cell(obj.get(f)) for f in fields) + " |")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _group_title(group: object) -> str:
    return {"core": "Core NetBox", "plugin": "In-house plugins"}.get(str(group), str(group).title())


def _anchor(app_label: str) -> str:
    return "app-" + app_label.replace("_", "-")
