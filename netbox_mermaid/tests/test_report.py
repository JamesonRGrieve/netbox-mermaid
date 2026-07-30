# SPDX-License-Identifier: AGPL-3.0-or-later
"""SoT report tests against a real NetBox DB (no mocks).

Builds a small real graph, introspects it into the report document, and asserts the structure, the
per-model exhaustive field capture (richer than the diagram's label-only view), and that all three
encoders (markdown / json / toon) render the seeded data. Redaction + coercion helpers are covered
as pure units.
"""

import datetime
import decimal
import json

from django.test import SimpleTestCase, TestCase
from utilities.testing import create_test_device, create_test_virtualmachine

from netbox_mermaid.report import build_report, normalize_format, render_report
from netbox_mermaid.report.introspect import _is_secret, _to_jsonsafe


class ReportBuildTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.device = create_test_device("rpt-host")
        cls.vm = create_test_virtualmachine("rpt-vm")

    def _dcim_device_section(self, data):
        section = next(s for s in data["sections"] if s["app_label"] == "dcim")
        return next(m for m in section["models"] if m["label"] == "dcim.device")

    def test_top_level_shape(self):
        data = build_report()
        self.assertEqual(data["report"], "netbox-sot")
        for key in ("generated", "netbox_version", "summary", "sections"):
            self.assertIn(key, data)
        for key in ("apps", "models", "objects"):
            self.assertIn(key, data["summary"])
        self.assertGreater(data["summary"]["objects"], 0)

    def test_core_apps_present(self):
        labels = {s["app_label"] for s in build_report()["sections"]}
        self.assertIn("dcim", labels)

    def test_device_captured_with_exhaustive_fields(self):
        model = self._dcim_device_section(build_report())
        self.assertGreaterEqual(model["count"], 1)
        names = [o.get("name") for o in model["objects"]]
        self.assertIn("rpt-host", names)
        # The report captures full per-object detail the diagram omits — e.g. the status column.
        self.assertIn("status", model["fields"])
        self.assertIn("id", model["fields"])

    def test_empty_models_hidden_by_default(self):
        default = build_report()
        with_empty = build_report(include_empty=True)
        self.assertGreater(with_empty["summary"]["models"], default["summary"]["models"])

    def test_render_json_parses(self):
        content, content_type, filename = render_report(build_report(), "json")
        self.assertEqual(content_type, "application/json")
        self.assertTrue(filename.endswith(".json"))
        parsed = json.loads(content)
        self.assertEqual(parsed["report"], "netbox-sot")

    def test_render_markdown(self):
        content, content_type, filename = render_report(build_report(), "markdown")
        self.assertIn("text/markdown", content_type)
        self.assertTrue(content.startswith("# NetBox Source-of-Truth Report"))
        self.assertIn("rpt-host", content)
        self.assertIn("#### Device", content)

    def test_render_toon(self):
        content, content_type, filename = render_report(build_report(), "toon")
        self.assertTrue(filename.endswith(".toon"))
        self.assertTrue(content.startswith("report: netbox-sot"))
        self.assertIn("dcim", content)
        self.assertIn("rpt-host", content)


class ReportHelperTest(SimpleTestCase):
    def test_is_secret(self):
        for name in ("password", "api_key", "wg_private_key", "auth_token", "db_secret"):
            self.assertTrue(_is_secret(name), name)
        for name in ("name", "hostname", "openbao_path", "bao_kv_path", "public_key_ref"):
            self.assertFalse(_is_secret(name), name)

    def test_to_jsonsafe(self):
        self.assertEqual(_to_jsonsafe("s"), "s")
        self.assertEqual(_to_jsonsafe(3), 3)
        self.assertEqual(_to_jsonsafe(None), None)
        self.assertEqual(_to_jsonsafe(decimal.Decimal("1.5")), "1.5")
        self.assertEqual(_to_jsonsafe(datetime.date(2026, 7, 17)), "2026-07-17")
        self.assertEqual(_to_jsonsafe({"a": decimal.Decimal("2")}), {"a": "2"})
        self.assertEqual(_to_jsonsafe([1, decimal.Decimal("2")]), [1, "2"])

    def test_normalize_format(self):
        self.assertEqual(normalize_format("json"), "json")
        self.assertEqual(normalize_format("MD"), "markdown")
        self.assertEqual(normalize_format("toon"), "toon")
        self.assertEqual(normalize_format(None), "markdown")
        self.assertEqual(normalize_format("bogus"), "markdown")
