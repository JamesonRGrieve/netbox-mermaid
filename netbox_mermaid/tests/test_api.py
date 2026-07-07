# SPDX-License-Identifier: AGPL-3.0-or-later
"""API tests against a real DB + real authenticated API client (no mocks).

Exercises ``GET /api/plugins/mermaid/diagram/`` (and its ``?sanitize=true`` variant): a 200, a
non-empty ``mermaid`` string, integer counts, and the ``sanitized`` flag echoing the request.
"""

from utilities.testing import APITestCase, create_test_device

_URL = "/api/plugins/mermaid/diagram/"


class DiagramAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        create_test_device("mm-api-host")

    def test_get_diagram(self):
        response = self.client.get(_URL, **self.header)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("mermaid", body)
        self.assertTrue(body["mermaid"].startswith("flowchart TD"))
        self.assertIsInstance(body["node_count"], int)
        self.assertIsInstance(body["edge_count"], int)
        self.assertGreater(body["node_count"], 0)
        self.assertFalse(body["sanitized"])

    def test_get_diagram_sanitized(self):
        response = self.client.get(f"{_URL}?sanitize=true", **self.header)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["mermaid"])
        self.assertTrue(body["sanitized"])
        # The seeded device's real name must not appear in the public-safe diagram.
        self.assertNotIn("mm-api-host", body["mermaid"])

    def test_get_diagram_scoped(self):
        response = self.client.get(f"{_URL}?scope=all", **self.header)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["mermaid"].startswith("flowchart TD"))

    def test_unauthenticated_denied(self):
        response = self.client.get(_URL)
        self.assertIn(response.status_code, (401, 403))
