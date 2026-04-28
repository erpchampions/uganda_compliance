"""Unit tests for the circuit breaker state machine."""
import time
import unittest
from unittest.mock import MagicMock, patch

from uganda_compliance.efris.client import breaker


class _FakeCache:
    def __init__(self):
        self.store = {}

    def get_value(self, key):
        return self.store.get(key)

    def set_value(self, key, value, expires_in_sec=None):
        self.store[key] = value

    def delete_value(self, key):
        self.store.pop(key, None)


class BreakerTests(unittest.TestCase):
    def setUp(self):
        self.cache = _FakeCache()
        self.cache_patch = patch(
            "uganda_compliance.efris.client.breaker.frappe.cache",
            return_value=self.cache,
        )
        self.cache_patch.start()
        self.logger_patch = patch(
            "uganda_compliance.efris.client.breaker.get_logger",
            return_value=MagicMock(),
        )
        self.logger_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.logger_patch.stop()

    def test_starts_closed_and_allows(self):
        allowed, reason = breaker.allow("Co", "T130")
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_opens_after_threshold(self):
        for _ in range(breaker.FAILURE_THRESHOLD):
            breaker.record_failure("Co", "T130")
        allowed, reason = breaker.allow("Co", "T130")
        self.assertFalse(allowed)
        self.assertIn("OPEN", reason)

    def test_success_resets_counter(self):
        for _ in range(breaker.FAILURE_THRESHOLD - 1):
            breaker.record_failure("Co", "T130")
        breaker.record_success("Co", "T130")
        # Now we'd need FAILURE_THRESHOLD failures again before opening.
        for _ in range(breaker.FAILURE_THRESHOLD - 1):
            breaker.record_failure("Co", "T130")
        allowed, _ = breaker.allow("Co", "T130")
        self.assertTrue(allowed)

    def test_half_open_after_cooloff(self):
        for _ in range(breaker.FAILURE_THRESHOLD):
            breaker.record_failure("Co", "T130")
        # Force opened_at into the past.
        key = "efris:breaker:Co:T130"
        import json
        state = json.loads(self.cache.store[key])
        state["opened_at"] = time.time() - breaker.COOLOFF_SECONDS - 1
        self.cache.store[key] = json.dumps(state)
        allowed, _ = breaker.allow("Co", "T130")
        self.assertTrue(allowed)
        # State should now be HALF_OPEN.
        state = json.loads(self.cache.store[key])
        self.assertEqual(state["state"], "HALF_OPEN")

    def test_half_open_failure_returns_to_open(self):
        # Drive into HALF_OPEN.
        for _ in range(breaker.FAILURE_THRESHOLD):
            breaker.record_failure("Co", "T130")
        key = "efris:breaker:Co:T130"
        import json
        state = json.loads(self.cache.store[key])
        state["state"] = "HALF_OPEN"
        self.cache.store[key] = json.dumps(state)
        breaker.record_failure("Co", "T130")
        new_state = json.loads(self.cache.store[key])
        self.assertEqual(new_state["state"], "OPEN")

    def test_keys_are_namespaced_per_company_and_interface(self):
        for _ in range(breaker.FAILURE_THRESHOLD):
            breaker.record_failure("CompanyA", "T130")
        # Other (company, interface) combos remain unaffected.
        self.assertTrue(breaker.allow("CompanyA", "T109")[0])
        self.assertTrue(breaker.allow("CompanyB", "T130")[0])
