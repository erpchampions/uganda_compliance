"""Unit tests for the sync vs async dispatcher.

These tests stub `make_post`, `is_async_mode`, `enqueue_job`, and the
source-stamp helper so they exercise routing logic without touching URA,
the database, or the queue.
"""
import unittest
from unittest.mock import MagicMock, patch

from uganda_compliance.efris.client import dispatch
from uganda_compliance.efris.client.result import EfrisResponse


class _Doc:
    doctype = "Item"
    name = "TEST-ITEM-001"


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.async_patch = patch.object(dispatch, "is_async_mode", return_value=False)
        self.async_patch.start()
        self.make_post_patch = patch.object(
            dispatch,
            "make_post",
            return_value=EfrisResponse(
                ok=True, interface_code="T130", request_id="abc", data={"hi": 1}
            ),
        )
        self.make_post_mock = self.make_post_patch.start()
        self.stamp_patch = patch.object(dispatch, "_stamp_source")
        self.stamp_patch.start()
        self.enqueue_patch = patch.object(
            dispatch, "enqueue_job", return_value="ESJ-2026-00001"
        )
        self.enqueue_mock = self.enqueue_patch.start()

    def tearDown(self):
        self.async_patch.stop()
        self.make_post_patch.stop()
        self.stamp_patch.stop()
        self.enqueue_patch.stop()

    def test_sync_mode_calls_make_post_directly(self):
        result = dispatch.dispatch(
            company="Co", interface_code="T130", payload={"a": 1}, doc=_Doc()
        )
        self.assertTrue(result.ok)
        self.make_post_mock.assert_called_once()
        self.enqueue_mock.assert_not_called()

    def test_async_mode_enqueues(self):
        dispatch.is_async_mode.return_value = True
        result = dispatch.dispatch(
            company="Co", interface_code="T130", payload={"a": 1}, doc=_Doc()
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"queued": True, "job": "ESJ-2026-00001"})
        self.make_post_mock.assert_not_called()
        self.enqueue_mock.assert_called_once()

    def test_force_sync_overrides_async_toggle(self):
        dispatch.is_async_mode.return_value = True
        dispatch.dispatch(
            company="Co",
            interface_code="T109",
            payload={"a": 1},
            doc=_Doc(),
            force_sync=True,
        )
        self.make_post_mock.assert_called_once()
        self.enqueue_mock.assert_not_called()


class DispatchLegacyTests(unittest.TestCase):
    def test_success_returns_tuple(self):
        with patch.object(
            dispatch,
            "dispatch",
            return_value=EfrisResponse(
                ok=True, interface_code="T119", request_id="abc", data={"x": 1}
            ),
        ):
            ok, response = dispatch.dispatch_legacy(
                company="Co", interface_code="T119", payload={}
            )
        self.assertTrue(ok)
        self.assertEqual(response, {"x": 1})

    def test_failure_appends_partial_summary(self):
        with patch.object(
            dispatch,
            "dispatch",
            return_value=EfrisResponse(
                ok=False,
                interface_code="T130",
                request_id="abc",
                error_message="Partial failure!",
                partial_failures=[{"id": "X", "message": "bad"}],
            ),
        ):
            ok, msg = dispatch.dispatch_legacy(
                company="Co", interface_code="T130", payload={}
            )
        self.assertFalse(ok)
        self.assertIn("Partial failure!", msg)
        self.assertIn("X: bad", msg)
