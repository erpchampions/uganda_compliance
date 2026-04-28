"""Unit tests for the typed `EfrisResponse` and `EfrisError`."""
import unittest

from uganda_compliance.efris.client.result import EfrisError, EfrisResponse


class ResultTests(unittest.TestCase):
    def test_legacy_tuple_success(self):
        r = EfrisResponse(ok=True, interface_code="T119", request_id="abc", data={"x": 1})
        self.assertEqual(r.as_legacy_tuple(), (True, {"x": 1}))

    def test_legacy_tuple_failure(self):
        r = EfrisResponse(
            ok=False,
            interface_code="T130",
            request_id="abc",
            error_message="boom",
        )
        self.assertEqual(r.as_legacy_tuple(), (False, "boom"))

    def test_legacy_tuple_failure_default_message(self):
        r = EfrisResponse(ok=False, interface_code="T130", request_id="abc")
        ok, msg = r.as_legacy_tuple()
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_raise_for_error_on_success(self):
        r = EfrisResponse(ok=True, interface_code="T119", request_id="abc")
        # Should not raise.
        r.raise_for_error()

    def test_raise_for_error_on_failure_includes_metadata(self):
        r = EfrisResponse(
            ok=False,
            interface_code="T130",
            request_id="abc",
            error_code="01",
            error_message="commodity invalid",
            partial_failures=[{"id": "X", "message": "y"}],
        )
        with self.assertRaises(EfrisError) as cm:
            r.raise_for_error()
        e = cm.exception
        self.assertEqual(e.interface_code, "T130")
        self.assertEqual(e.return_code, "01")
        self.assertEqual(e.partial_failures, [{"id": "X", "message": "y"}])
