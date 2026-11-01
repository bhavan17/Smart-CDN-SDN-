"""Unit tests for the content lookup helper (does not require Mininet/Ryu)."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import get_content  # noqa: E402


class GetContentTests(unittest.TestCase):
    def test_root_maps_to_index(self):
        status, content_type, body = get_content("/", "CDN-TEST")
        self.assertEqual(status, "200 OK")
        self.assertIn("text/html", content_type)
        self.assertIn(b"CDN-TEST", body)

    def test_health_returns_valid_json(self):
        status, content_type, body = get_content("/health", "CDN-TEST")
        self.assertEqual(status, "200 OK")
        self.assertIn("application/json", content_type)
        parsed = json.loads(body.decode("utf-8"))
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["server"], "CDN-TEST")

    def test_query_string_does_not_change_content_route(self):
        status, content_type, body = get_content("/about.txt?from=test", "CDN-TEST")
        self.assertEqual(status, "200 OK")
        self.assertIn(b"Smart CDN demonstration content", body)

    def test_missing_path_returns_404(self):
        status, content_type, body = get_content("/does-not-exist", "CDN-TEST")
        self.assertEqual(status, "404 Not Found")
        self.assertIn(b"Not found", body)

    def test_sample_binary_is_nonempty(self):
        status, content_type, body = get_content("/sample.bin", "CDN-TEST")
        self.assertEqual(status, "200 OK")
        self.assertEqual(content_type, "application/octet-stream")
        self.assertGreater(len(body), 100_000)


if __name__ == "__main__":
    unittest.main()
