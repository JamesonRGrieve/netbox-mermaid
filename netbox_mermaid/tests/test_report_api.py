# SPDX-License-Identifier: AGPL-3.0-or-later
"""Report API tests against a real DB + real authenticated API client (no mocks).

Exercises ``GET /api/plugins/mermaid/report/`` across all three formats: the right content-type per
format, a parseable JSON body, the seeded object surfacing in the output, and the download
disposition when requested.
"""

import json

from utilities.testing import APITestCase, create_test_device

_URL = "/api/plugins/mermaid/report/"


class ReportAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        create_test_device("rpt-api-host")

    def test_json_format(self):
        response = self.client.get(f"{_URL}?format=json", **self.header)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])
        body = json.loads(response.content)
        self.assertEqual(body["report"], "netbox-sot")
        labels = {s["app_label"] for s in body["sections"]}
        self.assertIn("dcim", labels)

    def test_markdown_format_default(self):
        response = self.client.get(_URL, **self.header)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response["Content-Type"])
        self.assertIn(b"# NetBox Source-of-Truth Report", response.content)
        self.assertIn(b"rpt-api-host", response.content)

    def test_toon_format(self):
        response = self.client.get(f"{_URL}?format=toon", **self.header)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"report: netbox-sot"))

    def test_download_disposition(self):
        response = self.client.get(f"{_URL}?format=json&download=1", **self.header)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("netbox-sot-report.json", response["Content-Disposition"])

    def test_unauthenticated_denied(self):
        response = self.client.get(_URL)
        self.assertIn(response.status_code, (401, 403))
