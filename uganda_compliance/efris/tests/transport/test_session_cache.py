"""Unit tests for the AES session-key cache."""
import unittest
from unittest.mock import MagicMock, patch

from uganda_compliance.efris.client import session as session_cache


class _FakeCache:
    def __init__(self):
        self.store = {}

    def get_value(self, key):
        return self.store.get(key)

    def set_value(self, key, value, expires_in_sec=None):
        self.store[key] = value

    def delete_value(self, key):
        self.store.pop(key, None)


class SessionCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = _FakeCache()
        self.cache_patch = patch(
            "uganda_compliance.efris.client.session.frappe.cache",
            return_value=self.cache,
        )
        self.cache_patch.start()
        self.logger_patch = patch(
            "uganda_compliance.efris.client.session.get_logger",
            return_value=MagicMock(),
        )
        self.logger_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.logger_patch.stop()

    def test_round_trip(self):
        session_cache.set_cached("TIN", "DEV", "https://x", b"\x00\x01\x02key")
        cached = session_cache.get_cached("TIN", "DEV", "https://x")
        self.assertEqual(cached, b"\x00\x01\x02key")

    def test_miss_returns_none(self):
        self.assertIsNone(session_cache.get_cached("TIN", "DEV", "https://x"))

    def test_invalidate(self):
        session_cache.set_cached("TIN", "DEV", "https://x", b"key")
        session_cache.invalidate("TIN", "DEV", "https://x")
        self.assertIsNone(session_cache.get_cached("TIN", "DEV", "https://x"))

    def test_namespaced_per_tuple(self):
        session_cache.set_cached("TIN1", "DEV", "https://x", b"key1")
        session_cache.set_cached("TIN2", "DEV", "https://x", b"key2")
        self.assertEqual(session_cache.get_cached("TIN1", "DEV", "https://x"), b"key1")
        self.assertEqual(session_cache.get_cached("TIN2", "DEV", "https://x"), b"key2")
