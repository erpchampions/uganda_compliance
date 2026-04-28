"""Unit tests for partial-failure extraction."""
import unittest

from uganda_compliance.efris.client.partial import (
    extract,
    format_summary,
    is_partial,
)


class IsPartialTests(unittest.TestCase):
    def test_recognises_partial(self):
        self.assertTrue(is_partial("Partial failure!"))
        self.assertTrue(is_partial("Partial Success"))

    def test_rejects_others(self):
        self.assertFalse(is_partial("SUCCESS"))
        self.assertFalse(is_partial(""))
        self.assertFalse(is_partial(None))


class ExtractTests(unittest.TestCase):
    def test_t130_failure_rows(self):
        decoded = {
            "goodsUploadingList": [
                {"goodsCode": "OK1", "remarks": ""},
                {"goodsCode": "BAD1", "remarks": "commodityCategoryId 30101 not found"},
                {"goodsCode": "BAD2", "remarks": "measureUnit invalid", "returnCode": "01"},
            ]
        }
        failures = extract("T130", decoded)
        self.assertEqual(len(failures), 2)
        ids = sorted(f["id"] for f in failures)
        self.assertEqual(ids, ["BAD1", "BAD2"])
        self.assertIn("commodityCategoryId", failures[0]["message"])

    def test_t109_failure_rows(self):
        decoded = {
            "einvoiceUploadingList": [
                {"invoiceNo": "INV1", "remarks": "buyer GSTIN missing"}
            ]
        }
        failures = extract("T109", decoded)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["id"], "INV1")

    def test_no_failures_returns_empty(self):
        decoded = {"goodsUploadingList": [{"goodsCode": "OK1"}]}
        self.assertEqual(extract("T130", decoded), [])

    def test_unknown_interface_falls_back(self):
        decoded = {
            "rows": [
                {"id": 1, "remarks": "bad"},
                {"id": 2, "remarks": ""},
            ]
        }
        failures = extract("T999", decoded)
        # Generic fallback finds the row with remarks.
        self.assertTrue(failures)

    def test_handles_none(self):
        self.assertEqual(extract("T130", None), [])


class FormatSummaryTests(unittest.TestCase):
    def test_single_row(self):
        out = format_summary([{"id": "X", "message": "boom"}])
        self.assertIn("X: boom", out)

    def test_truncates_to_five(self):
        rows = [{"id": f"R{i}", "message": "e"} for i in range(8)]
        out = format_summary(rows)
        self.assertIn("... and 3 more", out)

    def test_empty(self):
        self.assertEqual(format_summary([]), "")
