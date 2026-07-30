# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generic SoT introspection — the report's data source.

Where the diagram *collectors* are hand-written and deliberately selective (they draw only the
topologically meaningful nodes/edges, omitting per-row detail "for brevity"), the **report** is the
exhaustive counterpart: it walks every model of every relevant NetBox app and serialises **all**
concrete fields of **all** objects. It is fully generic — a new in-house plugin (any installed app
whose label starts with ``netbox_``) and every one of its models are picked up automatically, so the
report never needs editing when a plugin is added.

Output is one plain, JSON-safe ``dict`` (see :func:`build_report`) that the three encoders
(markdown / json / toon) render without any further model knowledge.

Secret hygiene: OpenBao / password / token *values* are never emitted — a field whose name matches
:data:`_SECRET_HINTS` is redacted to :data:`REDACTED` (its key stays, so the schema is still legible).
OpenBao *path references* are not secrets and are kept — they are pointers, not credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Core NetBox apps that constitute the modelled source-of-truth. Ordered as they appear in the
# report. NetBox bookkeeping apps (extras/changelog/users/core) are intentionally excluded — they
# are platform meta, not the SoT this workspace curates.
CORE_APPS: tuple[str, ...] = (
    "tenancy",
    "dcim",
    "ipam",
    "vpn",
    "virtualization",
    "circuits",
    "wireless",
)

# Installed apps whose label starts with this prefix are treated as in-house SoT plugins and fully
# introspected — this is what makes the report auto-cover every current and future plugin.
PLUGIN_PREFIX = "netbox_"

# This plugin owns no data; never introspect itself.
EXCLUDE_APPS: frozenset[str] = frozenset({"netbox_mermaid"})

# A field whose (lower-cased) name contains any of these is a credential value — redact it.
_SECRET_HINTS: tuple[str, ...] = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "private_key",
    "privatekey",
    "preshared",
    "presharedkey",
    "psk",
    "api_key",
    "apikey",
    "token",
    "credential",
)

REDACTED = "«redacted»"


@dataclass(frozen=True)
class ModelSection:
    """One model's slice of the report."""

    model: str  # class name, e.g. "Device"
    label: str  # app-qualified, e.g. "dcim.device"
    verbose_name_plural: str
    count: int
    fields: list[str]
    objects: list[dict[str, object]]
    error: str | None = None


@dataclass(frozen=True)
class AppSection:
    """One app's slice of the report (a group of model sections)."""

    group: str  # "core" | "plugin"
    app_label: str
    app_name: str  # verbose
    models: list[ModelSection]


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def _to_jsonsafe(value: object) -> object:
    """Coerce a field value into something the json/markdown/toon encoders can emit. Scalars pass
    through; dates/decimals/addresses/UUIDs stringify; JSON (dict/list) fields recurse."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonsafe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonsafe(v) for v in value]
    # Decimal, datetime/date, UUID, netaddr IP/Network, and anything else with a sane __str__.
    return str(value)


def _fk_value(obj: object, field: object) -> object:
    """A foreign-key / one-to-one field rendered as the related object's display string (or ``None``).
    Falls back to ``<app.model>:<pk>`` if the related row can't be stringified."""
    related_id = getattr(obj, field.attname, None)  # <name>_id
    if related_id is None:
        return None
    try:
        return str(getattr(obj, field.name))
    except Exception:
        related_model = getattr(field, "related_model", None)
        label = getattr(getattr(related_model, "_meta", None), "label_lower", "object")
        return f"{label}:{related_id}"


def _field_names(model: object) -> tuple[list[str], list[str], list[str]]:
    """Return (concrete field names to emit, FK field names for select_related, m2m field names)."""
    concrete: list[str] = []
    fk_names: list[str] = []
    m2m_names: list[str] = []
    for field in model._meta.concrete_fields:
        if field.name.startswith("_"):
            continue  # internal cache columns (e.g. Device._name naturalisation key)
        concrete.append(field.name)
        if field.is_relation:
            fk_names.append(field.name)
    for field in model._meta.many_to_many:
        m2m_names.append(field.name)
    return concrete, fk_names, m2m_names


def _serialize(obj: object, concrete_fields: list[str], m2m_fields: list[str]) -> dict[str, object]:
    """Serialise one object to a flat, JSON-safe dict of every concrete field (+ m2m lists, +
    resolved generic-FK targets), redacting credential-valued fields."""
    meta = obj._meta
    field_map = {f.name: f for f in meta.concrete_fields}
    data: dict[str, object] = {}
    for name in concrete_fields:
        field = field_map[name]
        if field.is_relation:
            value: object = _fk_value(obj, field)
        else:
            value = _to_jsonsafe(field.value_from_object(obj))
        if _is_secret(name) and value not in (None, "", [], {}):
            value = REDACTED
        data[name] = value

    # Generic foreign keys are virtual (not concrete) — resolve their target's display string.
    for gfk in getattr(meta, "private_fields", []):
        gname = getattr(gfk, "name", None)
        if gname is None or gname in data:
            continue
        if gfk.__class__.__name__ != "GenericForeignKey":
            continue
        try:
            target = getattr(obj, gname)
            data[gname] = str(target) if target is not None else None
        except Exception:
            continue

    for name in m2m_fields:
        try:
            data[name] = [str(rel) for rel in getattr(obj, name).all()]
        except Exception:
            data[name] = []

    try:  # NetBox tags (taggit) — a GenericRelation, not a declared m2m field.
        tags = getattr(obj, "tags", None)
        if tags is not None and hasattr(tags, "all"):
            names = [str(t) for t in tags.all()]
            if names:
                data["tags"] = names
    except Exception:
        pass

    return data


def _collect_model(model: object) -> ModelSection:
    """Serialise every object of one model, guarded so a single broken model degrades to an error
    marker rather than sinking the whole report."""
    meta = model._meta
    label = meta.label_lower
    verbose_plural = str(getattr(meta, "verbose_name_plural", meta.model_name))
    try:
        concrete, fk_names, m2m_names = _field_names(model)
        qs = model.objects.all().order_by("pk")
        if fk_names:
            qs = qs.select_related(*fk_names)
        if m2m_names:
            qs = qs.prefetch_related(*m2m_names)
        objects = [_serialize(obj, concrete, m2m_names) for obj in qs]
        fields = list(objects[0].keys()) if objects else concrete
        return ModelSection(
            model=meta.object_name,
            label=label,
            verbose_name_plural=verbose_plural,
            count=len(objects),
            fields=fields,
            objects=objects,
        )
    except Exception as exc:  # noqa: BLE001 — a report is best-effort; never let one model 500 it.
        return ModelSection(
            model=meta.object_name,
            label=label,
            verbose_name_plural=verbose_plural,
            count=0,
            fields=[],
            objects=[],
            error=f"{type(exc).__name__}: {exc}",
        )


def _app_models(app_label: str) -> Iterable[object]:
    from django.apps import apps

    config = apps.get_app_config(app_label)
    return sorted(config.get_models(), key=lambda m: m._meta.object_name)


def discover_apps() -> tuple[list[str], list[str]]:
    """Return (installed core app labels, installed in-house plugin app labels) in report order."""
    from django.apps import apps

    core = [label for label in CORE_APPS if apps.is_installed(label)]
    plugins = sorted(
        config.label
        for config in apps.get_app_configs()
        if config.label.startswith(PLUGIN_PREFIX) and config.label not in EXCLUDE_APPS
    )
    return core, plugins


def _build_app_section(group: str, app_label: str, *, include_empty: bool) -> AppSection | None:
    from django.apps import apps

    config = apps.get_app_config(app_label)
    sections = [_collect_model(model) for model in _app_models(app_label)]
    if not include_empty:
        sections = [s for s in sections if s.count or s.error]
    if not sections:
        return None
    return AppSection(
        group=group,
        app_label=app_label,
        app_name=str(config.verbose_name),
        models=sections,
    )


def build_report(*, include_empty: bool = False) -> dict[str, object]:
    """Introspect the whole SoT (core apps + every in-house plugin) into one JSON-safe dict.

    ``include_empty`` keeps models with zero rows (off by default so the report stays tight). The
    returned structure is the single contract the encoders consume::

        {report, generated, netbox_version, summary{apps,models,objects}, sections:[{group,
         app_label, app_name, models:[{model,label,verbose_name_plural,count,fields,objects,error}]}]}
    """
    core, plugins = discover_apps()

    sections: list[AppSection] = []
    for label in core:
        section = _build_app_section("core", label, include_empty=include_empty)
        if section is not None:
            sections.append(section)
    for label in plugins:
        section = _build_app_section("plugin", label, include_empty=include_empty)
        if section is not None:
            sections.append(section)

    model_count = sum(len(s.models) for s in sections)
    object_count = sum(m.count for s in sections for m in s.models)

    return {
        "report": "netbox-sot",
        "generated": _now_iso(),
        "netbox_version": _netbox_version(),
        "summary": {
            "apps": len(sections),
            "models": model_count,
            "objects": object_count,
        },
        "sections": [
            {
                "group": s.group,
                "app_label": s.app_label,
                "app_name": s.app_name,
                "models": [
                    {
                        "model": m.model,
                        "label": m.label,
                        "verbose_name_plural": m.verbose_name_plural,
                        "count": m.count,
                        "fields": m.fields,
                        "objects": m.objects,
                        **({"error": m.error} if m.error else {}),
                    }
                    for m in s.models
                ],
            }
            for s in sections
        ],
    }


def _now_iso() -> str:
    try:
        from django.utils import timezone

        return timezone.now().isoformat(timespec="seconds")
    except Exception:
        return ""


def _netbox_version() -> str:
    try:
        from django.conf import settings

        return str(getattr(settings, "VERSION", ""))
    except Exception:
        return ""
