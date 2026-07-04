# Copyright (c) 2026, Ignite Digital and Contributors
# See license.txt

"""Tests for the T129 batch upload path.

The EFRIS HTTP layer is mocked end-to-end — these tests cover classification,
per-entry result mapping, and the orchestration in ``upload_batch`` without
touching URA.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
import unittest

from efris.efris.api import batch_invoice


def _b64_json(payload: dict) -> str:
	return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def _mock_t109_response(invoice_no: str, antifake: str = "AF123") -> dict:
	"""Shape that ``_interpret_response`` recognises as success."""
	return {
		"basicInformation": {"invoiceId": invoice_no, "invoiceNo": invoice_no, "antifakeCode": antifake},
		"summary": {"qrCode": "QR-DATA"},
	}


class TestParseNames(unittest.TestCase):
	def test_json_list(self):
		self.assertEqual(batch_invoice._parse_names('["A", "B"]'), ["A", "B"])

	def test_comma_string(self):
		self.assertEqual(batch_invoice._parse_names("A, B,C"), ["A", "B", "C"])

	def test_list_passthrough(self):
		self.assertEqual(batch_invoice._parse_names(["A", "B"]), ["A", "B"])

	def test_empty(self):
		self.assertEqual(batch_invoice._parse_names(None), [])
		self.assertEqual(batch_invoice._parse_names([]), [])

	def test_strips_falsy(self):
		self.assertEqual(batch_invoice._parse_names(["A", "", None, "B"]), ["A", "B"])


class TestValidateSourceDoctype(unittest.TestCase):
	def test_accepts_supported(self):
		batch_invoice._validate_source_doctype("Sales Invoice")
		batch_invoice._validate_source_doctype("POS Invoice")

	def test_rejects_other(self):
		with self.assertRaises(frappe.ValidationError):
			batch_invoice._validate_source_doctype("Purchase Invoice")


class TestClassify(unittest.TestCase):
	"""Eligibility filter: submitted, not uploaded, not a return, configured company."""

	def _rows(self):
		return [
			SimpleNamespace(name="SI-OK", company="Acme", docstatus=1, is_return=0, efris_uploaded=0),
			SimpleNamespace(name="SI-UPLOADED", company="Acme", docstatus=1, is_return=0, efris_uploaded=1),
			SimpleNamespace(name="SI-DRAFT", company="Acme", docstatus=0, is_return=0, efris_uploaded=0),
			SimpleNamespace(name="SI-RETURN", company="Acme", docstatus=1, is_return=1, efris_uploaded=0),
			SimpleNamespace(name="SI-NOCO", company="Other", docstatus=1, is_return=0, efris_uploaded=0),
		]

	def test_buckets_each_reason(self):
		# Make SimpleNamespace behave like Frappe's _dict.get(...).
		rows = self._rows()
		for r in rows:
			r.get = r.__dict__.get  # type: ignore[attr-defined]

		with (
			patch.object(frappe, "get_all", side_effect=[rows, ["Acme"]]),
		):
			eligible, skipped = batch_invoice._classify(
				"Sales Invoice",
				["SI-OK", "SI-UPLOADED", "SI-DRAFT", "SI-RETURN", "SI-NOCO", "SI-MISSING"],
			)

		self.assertEqual([e["name"] for e in eligible], ["SI-OK"])
		reasons = {s["name"]: s["reason"] for s in skipped}
		self.assertEqual(reasons["SI-UPLOADED"], "Already uploaded")
		self.assertEqual(reasons["SI-DRAFT"], "Not submitted")
		self.assertEqual(reasons["SI-RETURN"], "Credit note — use T110")
		self.assertEqual(reasons["SI-NOCO"], "No EFRIS Settings for company")
		self.assertEqual(reasons["SI-MISSING"], "Document not found")

	def test_empty_names(self):
		self.assertEqual(batch_invoice._classify("Sales Invoice", []), ([], []))


class TestApplyEntryResult(unittest.TestCase):
	def _entry(self) -> SimpleNamespace:
		return SimpleNamespace(
			source_doctype="Sales Invoice",
			source_name="SI-1",
			e_invoice=None,
			status="Pending",
			return_code=None,
			return_message=None,
			efris_invoice_id=None,
			efris_antifake_code=None,
			qr_code=None,
		)

	def test_success_populates_efris_ids(self):
		entry = self._entry()
		batch_invoice._apply_entry_result(entry, {
			"invoiceReturnCode": "00",
			"invoiceReturnMessage": "SUCCESS",
			"invoiceContent": _b64_json(_mock_t109_response("FDN-1")),
		})
		self.assertEqual(entry.status, "Success")
		self.assertEqual(entry.efris_invoice_id, "FDN-1")
		self.assertEqual(entry.efris_antifake_code, "AF123")
		self.assertEqual(entry.qr_code, "QR-DATA")
		self.assertEqual(entry.return_code, "00")

	def test_per_entry_99_marks_failed(self):
		entry = self._entry()
		batch_invoice._apply_entry_result(entry, {
			"invoiceReturnCode": "99",
			"invoiceReturnMessage": "Invalid TIN",
			"invoiceContent": _b64_json({"detail": "TIN check failed"}),
		})
		self.assertEqual(entry.status, "Failed")
		self.assertEqual(entry.return_code, "99")
		self.assertIn("TIN check failed", entry.return_message or "")

	def test_malformed_result(self):
		entry = self._entry()
		batch_invoice._apply_entry_result(entry, "not a dict")
		self.assertEqual(entry.status, "Failed")

	def test_success_without_invoice_id(self):
		"""URA returned 00 but the inner T109 response has no invoiceId."""
		entry = self._entry()
		batch_invoice._apply_entry_result(entry, {
			"invoiceReturnCode": "00",
			"invoiceReturnMessage": "SUCCESS",
			"invoiceContent": _b64_json({"basicInformation": {}}),
		})
		self.assertEqual(entry.status, "Failed")


class TestUploadBatchEndToEnd(unittest.TestCase):
	"""Full ``upload_batch`` flow with EFRIS, E-Invoice resolution, and signing mocked."""

	def setUp(self):
		# Stub EFRISClient so it doesn't try to read EFRIS Settings.
		self.client_patcher = patch.object(batch_invoice, "EFRISClient")
		self.MockClient = self.client_patcher.start()
		instance = MagicMock()
		instance.private_key = "fake-key"
		self.MockClient.return_value = instance

		# Stub the crypto signing — return deterministic bytes.
		self.sign_patcher = patch.object(batch_invoice, "sign_data", return_value=b"sig-bytes")
		self.sign_patcher.start()

		# Stub the E-Invoice resolution + T109 payload build so we don't need
		# real Items / Customer / Sales Invoice records.
		self.resolve_patcher = patch.object(
			batch_invoice,
			"_resolve_or_create_e_invoice",
			side_effect=lambda dt, name: f"EINV-{name}",
		)
		self.resolve_patcher.start()

		self.build_patcher = patch.object(
			batch_invoice, "_build_payload", return_value={"sellerDetails": {}, "basicInformation": {}}
		)
		self.build_patcher.start()

		# Don't actually load / save an E-Invoice in _apply_entry_result.
		self.persist_patcher = patch.object(batch_invoice, "_persist_result")
		self.persist_patcher.start()

		# Only intercept frappe.get_doc("E-Invoice", ...) — everything else
		# (e.g. Frappe's internal System Settings lookup inside now_datetime)
		# must pass through to avoid leaking MagicMocks into Redis caches.
		real_get_doc = frappe.get_doc

		def _scoped_get_doc(*args, **kwargs):
			if args and args[0] == "E-Invoice":
				return MagicMock()
			return real_get_doc(*args, **kwargs)

		self.get_doc_patcher = patch.object(frappe, "get_doc", side_effect=_scoped_get_doc)
		self.get_doc_patcher.start()

	def tearDown(self):
		self.client_patcher.stop()
		self.sign_patcher.stop()
		self.resolve_patcher.stop()
		self.build_patcher.stop()
		self.persist_patcher.stop()
		self.get_doc_patcher.stop()

	def _classify_returns(self, eligible_names, company="Acme"):
		"""Bypass _classify so we don't need real SIs in the test DB."""
		eligible = [{"name": n, "company": company} for n in eligible_names]
		return patch.object(batch_invoice, "_classify", return_value=(eligible, []))

	def _mock_efris_doc(self):
		"""frappe.new_doc('EFRIS Batch Invoice Upload', ...) substitute."""
		doc = SimpleNamespace(
			name="BATCH-TEST-0001",
			entries=[],
			skipped_entries=[],
			company=None,
			source_doctype=None,
			submitted_on=None,
			submitted_by=None,
			status="Draft",
			entry_count=0,
			success_count=0,
			failed_count=0,
			skipped_count=0,
			efris_response_json=None,
		)

		def append(table, row):
			defaults = {
				"return_code": None, "return_message": None,
				"efris_invoice_id": None, "efris_antifake_code": None, "qr_code": None,
			}
			merged = {**defaults, **row}
			getattr(doc, table).append(SimpleNamespace(**merged))

		doc.append = append
		doc.insert = MagicMock()
		doc.save = MagicMock()
		return doc

	def test_all_success(self):
		batch_doc = self._mock_efris_doc()
		response = [
			{"invoiceReturnCode": "00", "invoiceReturnMessage": "OK",
				"invoiceContent": _b64_json(_mock_t109_response("FDN-A"))},
			{"invoiceReturnCode": "00", "invoiceReturnMessage": "OK",
				"invoiceContent": _b64_json(_mock_t109_response("FDN-B"))},
		]
		with (
			self._classify_returns(["SI-A", "SI-B"]),
			patch.object(frappe, "new_doc", return_value=batch_doc),
			patch.object(frappe.db, "commit"),
			patch.object(batch_invoice, "call_t129", return_value=response) as mocked_t129,
		):
			summary = batch_invoice.upload_batch("Sales Invoice", ["SI-A", "SI-B"])

		mocked_t129.assert_called_once()
		sent_entries = mocked_t129.call_args.args[0]
		self.assertEqual(len(sent_entries), 2)
		# Each entry must carry both keys (URA spec).
		for entry in sent_entries:
			self.assertIn("invoiceContent", entry)
			self.assertIn("invoiceSignature", entry)
			# invoiceContent is b64-encoded JSON of the T109 payload.
			json.loads(base64.b64decode(entry["invoiceContent"]).decode("utf-8"))

		self.assertEqual(summary["status"], "Success")
		self.assertEqual(summary["success"], 2)
		self.assertEqual(summary["failed"], 0)
		self.assertEqual(batch_doc.entries[0].efris_invoice_id, "FDN-A")
		self.assertEqual(batch_doc.entries[1].efris_invoice_id, "FDN-B")

	def test_partial_success(self):
		batch_doc = self._mock_efris_doc()
		response = [
			{"invoiceReturnCode": "00", "invoiceReturnMessage": "OK",
				"invoiceContent": _b64_json(_mock_t109_response("FDN-A"))},
			{"invoiceReturnCode": "99", "invoiceReturnMessage": "Invalid TIN",
				"invoiceContent": _b64_json({"err": "TIN"})},
		]
		with (
			self._classify_returns(["SI-A", "SI-B"]),
			patch.object(frappe, "new_doc", return_value=batch_doc),
			patch.object(frappe.db, "commit"),
			patch.object(batch_invoice, "call_t129", return_value=response),
		):
			summary = batch_invoice.upload_batch("Sales Invoice", ["SI-A", "SI-B"])

		self.assertEqual(summary["status"], "Partial")
		self.assertEqual(summary["success"], 1)
		self.assertEqual(summary["failed"], 1)

	def test_all_failed(self):
		batch_doc = self._mock_efris_doc()
		response = [
			{"invoiceReturnCode": "99", "invoiceReturnMessage": "Bad", "invoiceContent": ""},
		]
		with (
			self._classify_returns(["SI-A"]),
			patch.object(frappe, "new_doc", return_value=batch_doc),
			patch.object(frappe.db, "commit"),
			patch.object(batch_invoice, "call_t129", return_value=response),
		):
			summary = batch_invoice.upload_batch("Sales Invoice", ["SI-A"])

		self.assertEqual(summary["status"], "Failed")
		self.assertEqual(summary["success"], 0)
		self.assertEqual(summary["failed"], 1)

	def test_rejects_multi_company(self):
		batch_doc = self._mock_efris_doc()
		eligible = [
			{"name": "SI-A", "company": "Acme"},
			{"name": "SI-B", "company": "BetaCo"},
		]
		with (
			patch.object(batch_invoice, "_classify", return_value=(eligible, [])),
			patch.object(frappe, "new_doc", return_value=batch_doc),
		):
			with self.assertRaises(frappe.ValidationError):
				batch_invoice.upload_batch("Sales Invoice", ["SI-A", "SI-B"])

	def test_throws_when_no_eligible(self):
		with patch.object(batch_invoice, "_classify", return_value=([], [{"name": "SI-X", "reason": "Already uploaded"}])):
			with self.assertRaises(frappe.ValidationError):
				batch_invoice.upload_batch("Sales Invoice", ["SI-X"])

	def test_build_failure_recorded_but_not_sent(self):
		"""When the T109 payload build raises, the entry is recorded as Failed
		and only the successful builds go into the T129 request."""
		batch_doc = self._mock_efris_doc()
		response = [
			{"invoiceReturnCode": "00", "invoiceReturnMessage": "OK",
				"invoiceContent": _b64_json(_mock_t109_response("FDN-B"))},
		]
		# Swap _build_payload's behaviour for the duration of this test only —
		# first call raises, second succeeds. Using patch.object as a context
		# manager auto-restores the setUp-installed patch on exit.
		with (
			patch.object(
				batch_invoice,
				"_build_payload",
				side_effect=[Exception("missing customer"), {"ok": 1}],
			),
			self._classify_returns(["SI-BAD", "SI-OK"]),
			patch.object(frappe, "new_doc", return_value=batch_doc),
			patch.object(frappe.db, "commit"),
			patch.object(batch_invoice, "call_t129", return_value=response) as mocked_t129,
		):
			summary = batch_invoice.upload_batch("Sales Invoice", ["SI-BAD", "SI-OK"])

		# Only one entry sent to EFRIS; the build failure is local.
		self.assertEqual(len(mocked_t129.call_args.args[0]), 1)
		self.assertEqual(summary["status"], "Partial")
		# Build failure shows up as a Failed entry with BUILD code.
		build_failures = [e for e in batch_doc.entries if getattr(e, "return_code", None) == "BUILD"]
		self.assertEqual(len(build_failures), 1)
		self.assertIn("missing customer", build_failures[0].return_message)
