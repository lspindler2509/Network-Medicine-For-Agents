"""Specification downloads retry transient failures only."""

import unittest
from unittest.mock import Mock, patch

import requests

from netmed.importers.openapi import fetch_spec

URL = "https://example.org/openapi.json"


class FetchSpecTests(unittest.TestCase):
    def test_timeout_and_server_error_are_retried(self):
        ok = Mock(status_code=200)
        with (
            patch(
                "netmed.importers.openapi.requests.get",
                side_effect=[requests.ReadTimeout(), Mock(status_code=503), ok],
            ) as get,
            patch("netmed.importers.openapi.time.sleep") as sleep,
        ):
            self.assertIs(fetch_spec(URL), ok)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_client_errors_are_not_retried(self):
        missing = Mock(status_code=404)
        with patch(
            "netmed.importers.openapi.requests.get", return_value=missing
        ) as get:
            self.assertIs(fetch_spec(URL), missing)
        get.assert_called_once()

    def test_persistent_timeout_is_raised(self):
        with (
            patch(
                "netmed.importers.openapi.requests.get",
                side_effect=requests.ReadTimeout(),
            ) as get,
            patch("netmed.importers.openapi.time.sleep"),
        ):
            with self.assertRaises(requests.ReadTimeout):
                fetch_spec(URL)
        self.assertEqual(get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
