# SPDX-License-Identifier: AGPL-3.0-or-later
"""TOON encoder tests — pure, no DB. Verify the tabular form for uniform object arrays, inline
primitive arrays, the YAML-style fallback for non-uniform/nested arrays, scalar quoting rules, and
that a report-shaped document encodes without loss of structure.
"""

from django.test import SimpleTestCase

from netbox_mermaid.report import toon


class ToonScalarTest(SimpleTestCase):
    def test_bare_scalars(self):
        self.assertEqual(toon._scalar("plain"), "plain")
        self.assertEqual(toon._scalar("with space"), "with space")
        self.assertEqual(toon._scalar(42), "42")
        self.assertEqual(toon._scalar(True), "true")
        self.assertEqual(toon._scalar(False), "false")
        self.assertEqual(toon._scalar(None), "null")

    def test_quoted_when_ambiguous(self):
        # Reserved words, numeric-looking strings, empties, and structural chars must be quoted so a
        # decoder can't mistake them for a bool/number/delimiter.
        self.assertEqual(toon._scalar("true"), '"true"')
        self.assertEqual(toon._scalar("42"), '"42"')
        self.assertEqual(toon._scalar(""), '""')
        self.assertEqual(toon._scalar("trailing "), '"trailing "')
        self.assertEqual(toon._scalar("a,b"), '"a,b"')
        self.assertEqual(toon._scalar("a:b"), '"a:b"')

    def test_quote_escaping(self):
        self.assertEqual(toon._scalar('he said "hi"'), '"he said \\"hi\\""')
        self.assertEqual(toon._scalar("line\nbreak"), '"line\\nbreak"')


class ToonArrayTest(SimpleTestCase):
    def test_primitive_array_inline(self):
        out = toon.encode({"tags": ["a", "b", "c"]})
        self.assertEqual(out, "tags[3]: a,b,c")

    def test_empty_array(self):
        self.assertEqual(toon.encode({"items": []}), "items[0]:")

    def test_uniform_objects_tabular(self):
        out = toon.encode(
            {"rows": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]}
        )
        lines = out.splitlines()
        self.assertEqual(lines[0], "rows[2]{id,name}:")
        self.assertEqual(lines[1], "  1,a")
        self.assertEqual(lines[2], "  2,b")

    def test_nonuniform_objects_fall_back_to_list(self):
        # Differing key sets (or nested values) can't be tabular → YAML-style "- " items.
        out = toon.encode({"rows": [{"id": 1}, {"id": 2, "extra": "x"}]})
        self.assertIn("rows[2]:", out)
        self.assertIn("- id: 1", out)

    def test_nested_dict_value_breaks_tabular(self):
        out = toon.encode({"rows": [{"id": 1, "cfg": {"k": "v"}}]})
        self.assertIn("rows[1]:", out)
        self.assertIn("- id: 1", out)
        self.assertIn("cfg:", out)
        self.assertIn("k: v", out)


class ToonMappingTest(SimpleTestCase):
    def test_nested_mapping_indentation(self):
        out = toon.encode({"summary": {"apps": 2, "models": 3}})
        self.assertEqual(out.splitlines(), ["summary:", "  apps: 2", "  models: 3"])

    def test_report_shaped_document(self):
        data = {
            "report": "netbox-sot",
            "summary": {"apps": 1, "models": 1, "objects": 2},
            "sections": [
                {
                    "group": "core",
                    "app_label": "dcim",
                    "models": [
                        {
                            "model": "Device",
                            "count": 2,
                            "fields": ["id", "name"],
                            "objects": [{"id": 1, "name": "h1"}, {"id": 2, "name": "h2"}],
                        }
                    ],
                }
            ],
        }
        out = toon.encode(data)
        self.assertTrue(out.startswith("report: netbox-sot"))
        # The uniform object list is emitted tabularly (header once, then a row per object).
        self.assertIn("objects[2]{id,name}:", out)
        self.assertIn("    1,h1", out)
        self.assertIn("    2,h2", out)
