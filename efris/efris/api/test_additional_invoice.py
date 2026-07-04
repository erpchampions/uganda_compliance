# Copyright (c) 2026, Ignite Digital and Contributors
# See license.txt

"""Tests for issuing additional EFRIS invoices against a single Sales Invoice.

Covers the read-only ``precheck_additional_invoice`` (warn-on-credit vs
summary) and the auto payment-flow gate ``_should_issue_receipt_for_payment``.
Frappe DB access is mocked end-to-end — no records are touched.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from efris.efris.api import invoice, payment
from efris.efris.doctype.efris_settings.efris_settings import EFRISSettings


def _einv(**kw) -> frappe._dict:
	base = {
		"name": "EINV-1",
		"efris_invoice_id": "FDN-1",
		"invoice_kind": "1 - Invoice",
		"net_amount": 100.0,
		"tax_amount": 18.0,
		"gross_amount": 118.0,
		"last_uploaded_on": "2026-06-01 10:00:00",
	}
	base.update(kw)
	return frappe._dict(base)


def _payway(mode: str, amount: float) -> frappe._dict:
	return frappe._dict({"payment_mode": mode, "payment_amount": amount})


class TestPrecheckAdditionalInvoice(unittest.TestCase):
	def test_no_existing_returns_not_exists(self):
		with patch.object(frappe, "get_all", return_value=[]):
			res = invoice.precheck_additional_invoice("Sales Invoice", "SI-1")
		self.assertEqual(res, {"exists": False})

	def test_credit_existing_flags_has_credit(self):
		get_all = patch.object(
			frappe,
			"get_all",
			side_effect=[
				[_einv()],  # _existing_uploaded_einvoices
				[_payway("101 - Credit", 118.0)],  # pay_ways for EINV-1
			],
		)
		get_value = patch.object(
			frappe.db,
			"get_value",
			return_value=frappe._dict({"grand_total": 118.0, "outstanding_amount": 118.0}),
		)
		with get_all, get_value:
			res = invoice.precheck_additional_invoice("Sales Invoice", "SI-1")

		self.assertTrue(res["exists"])
		self.assertTrue(res["has_credit"])
		self.assertEqual(res["totals"]["invoice_count"], 1)
		self.assertEqual(res["totals"]["efris_gross_total"], 118.0)
		self.assertEqual(res["totals"]["payment_total"], 118.0)
		self.assertEqual(res["existing"][0]["pay_ways"][0]["mode"], "101 - Credit")

	def test_cash_existing_shows_summary_without_credit(self):
		get_all = patch.object(
			frappe,
			"get_all",
			side_effect=[
				[_einv(invoice_kind="2 - Receipt")],
				[_payway("102 - Cash", 118.0)],
			],
		)
		get_value = patch.object(
			frappe.db,
			"get_value",
			return_value=frappe._dict({"grand_total": 118.0, "outstanding_amount": 0.0}),
		)
		with get_all, get_value:
			res = invoice.precheck_additional_invoice("Sales Invoice", "SI-1")

		self.assertTrue(res["exists"])
		self.assertFalse(res["has_credit"])
		self.assertEqual(res["existing"][0]["invoice_kind"], "2")
		self.assertEqual(res["totals"]["payment_total"], 118.0)
		self.assertEqual(res["totals"]["si_outstanding"], 0.0)

	def test_multiple_invoices_roll_up(self):
		get_all = patch.object(
			frappe,
			"get_all",
			side_effect=[
				[_einv(name="EINV-1", gross_amount=100.0), _einv(name="EINV-2", gross_amount=50.0)],
				[_payway("102 - Cash", 100.0)],
				[_payway("105 - Mobile Money", 50.0)],
			],
		)
		get_value = patch.object(
			frappe.db,
			"get_value",
			return_value=frappe._dict({"grand_total": 150.0, "outstanding_amount": 0.0}),
		)
		with get_all, get_value:
			res = invoice.precheck_additional_invoice("Sales Invoice", "SI-1")

		self.assertEqual(res["totals"]["invoice_count"], 2)
		self.assertEqual(res["totals"]["efris_gross_total"], 150.0)
		self.assertEqual(res["totals"]["payment_total"], 150.0)
		self.assertFalse(res["has_credit"])


class TestShouldIssueReceiptForPayment(unittest.TestCase):
	def test_no_existing_invoice(self):
		with patch.object(invoice, "_existing_uploaded_einvoices", return_value=[]):
			self.assertFalse(payment._should_issue_receipt_for_payment("SI-1", "PE-1"))

	def test_uploaded_invoice_not_yet_documented_for_pe(self):
		# Any already-uploaded SI (credit or not) can get one document per PE.
		with (
			patch.object(
				invoice, "_existing_uploaded_einvoices", return_value=[frappe._dict(name="EINV-1")]
			),
			patch.object(frappe.db, "exists", return_value=None),
		):
			self.assertTrue(payment._should_issue_receipt_for_payment("SI-1", "PE-1"))

	def test_duplicate_payment_entry_skipped(self):
		with (
			patch.object(
				invoice, "_existing_uploaded_einvoices", return_value=[frappe._dict(name="EINV-1")]
			),
			patch.object(frappe.db, "exists", return_value="EINV-RECEIPT-1"),
		):
			self.assertFalse(payment._should_issue_receipt_for_payment("SI-1", "PE-1"))


class TestAutoReceiptsEnabled(unittest.TestCase):
	def test_enabled_when_flag_set(self):
		with patch(
			"efris.efris.doctype.efris_settings.efris_settings.get_efris_settings",
			return_value=frappe._dict(auto_issue_payment_receipts=1),
		):
			self.assertTrue(payment._auto_receipts_enabled("Acme"))

	def test_disabled_when_flag_unset(self):
		with patch(
			"efris.efris.doctype.efris_settings.efris_settings.get_efris_settings",
			return_value=frappe._dict(auto_issue_payment_receipts=0),
		):
			self.assertFalse(payment._auto_receipts_enabled("Acme"))

	def test_disabled_when_no_settings(self):
		with patch(
			"efris.efris.doctype.efris_settings.efris_settings.get_efris_settings",
			side_effect=Exception("no settings"),
		):
			self.assertFalse(payment._auto_receipts_enabled("Acme"))


def _tax_type(code: str, cancellation_date: str = "") -> frappe._dict:
	return frappe._dict({"tax_type_code": code, "cancellation_date": cancellation_date})


class _FakeSettings:
	"""Minimal stand-in exposing is_vat_registered for kind resolution."""

	def __init__(self, vat: bool):
		self._vat = vat

	def is_vat_registered(self) -> bool:
		return self._vat


class TestIsVatRegistered(unittest.TestCase):
	"""EFRISSettings.is_vat_registered keys off an active tax type 301."""

	def _check(self, tax_types) -> bool:
		# Call the unbound method against a frappe._dict acting as self; the
		# method only relies on .get(), which _dict provides.
		return EFRISSettings.is_vat_registered(frappe._dict(tax_types=tax_types))

	def test_active_vat_row(self):
		self.assertTrue(self._check([_tax_type("301")]))

	def test_cancelled_vat_row_does_not_count(self):
		self.assertFalse(self._check([_tax_type("301", cancellation_date="2026-01-01")]))

	def test_other_tax_types_only(self):
		self.assertFalse(self._check([_tax_type("302"), _tax_type("303")]))

	def test_no_tax_types(self):
		self.assertFalse(self._check([]))


class TestResolveInvoiceKind(unittest.TestCase):
	def test_vat_taxpayer_forced_to_invoice(self):
		# Even a Payment-Entry-stamped receipt must go out as a tax invoice.
		kind = invoice._resolve_invoice_kind(_einv(invoice_kind="2 - Receipt"), _FakeSettings(vat=True))
		self.assertEqual(kind, "1")

	def test_non_vat_taxpayer_keeps_receipt(self):
		kind = invoice._resolve_invoice_kind(_einv(invoice_kind="2 - Receipt"), _FakeSettings(vat=False))
		self.assertEqual(kind, "2")

	def test_pos_invoice_defaults_to_receipt_when_unset_and_non_vat(self):
		e_inv = _einv(invoice_kind="", source_doctype="POS Invoice")
		self.assertEqual(invoice._resolve_invoice_kind(e_inv, _FakeSettings(vat=False)), "2")

	def test_pos_invoice_forced_to_invoice_for_vat(self):
		e_inv = _einv(invoice_kind="", source_doctype="POS Invoice")
		self.assertEqual(invoice._resolve_invoice_kind(e_inv, _FakeSettings(vat=True)), "1")

	def test_no_settings_keeps_resolved_kind(self):
		e_inv = _einv(invoice_kind="2 - Receipt")
		self.assertEqual(invoice._resolve_invoice_kind(e_inv, None), "2")


class TestVatReceiptGate(unittest.TestCase):
	"""VAT taxpayers never issue an additional receipt on an already-uploaded SI."""

	def test_vat_registered_true(self):
		with patch(
			"efris.efris.doctype.efris_settings.efris_settings.get_efris_settings",
			return_value=_FakeSettings(vat=True),
		):
			self.assertTrue(payment._is_vat_registered("Acme"))

	def test_vat_registered_false(self):
		with patch(
			"efris.efris.doctype.efris_settings.efris_settings.get_efris_settings",
			return_value=_FakeSettings(vat=False),
		):
			self.assertFalse(payment._is_vat_registered("Acme"))

	def test_vat_registered_no_settings(self):
		with patch(
			"efris.efris.doctype.efris_settings.efris_settings.get_efris_settings",
			side_effect=Exception("no settings"),
		):
			self.assertFalse(payment._is_vat_registered("Acme"))


class _FakeEInv:
	"""Minimal E-Invoice stand-in for the goods/total helpers (no DB)."""

	def __init__(self, items: list[frappe._dict], gross: float):
		self.items = items
		self.gross_amount = gross
		self.net_amount = 0.0
		self.tax_amount = 0.0
		self.tax_details: list[frappe._dict] = []

	def set(self, field: str, value):
		setattr(self, field, value)

	def append(self, field: str, row: dict):
		getattr(self, field).append(frappe._dict(row))


def _item(**kw) -> frappe._dict:
	base = {
		"item_code": "ITEM-1",
		"item_name": "Item 1",
		"goods_code": "G1",
		"qty": 2.0,
		"uom": "Nos",
		"unit_of_measure_code": "PCS",
		"unit_price": 59.0,
		"total": 118.0,
		"tax_category_code": "01",
		"tax_rate": "0.18",
		"tax_amount": 18.0,
		"discount_flag": "2",
		"deemed_flag": "2",
		"excise_flag": "2",
		"vat_applicable_flag": "1",
		"goods_category_id": "",
	}
	base.update(kw)
	return frappe._dict(base)


class TestApplyPaymentAmountScaling(unittest.TestCase):
	def test_half_payment_per_line_scales_qty(self):
		e_inv = _FakeEInv([_item(qty=2.0, unit_price=59.0, total=118.0, tax_amount=18.0)], 118.0)
		applied = invoice.apply_payment_amount_scaling(e_inv, 59.0)
		self.assertTrue(applied)
		row = e_inv.items[0]
		# qty scaled, unit_price preserved (qty x unit_price == total).
		self.assertEqual(row.qty, 1.0)
		self.assertEqual(row.unit_price, 59.0)
		self.assertEqual(row.total, 59.0)
		self.assertEqual(row.tax_amount, 9.0)
		self.assertAlmostEqual(e_inv.gross_amount, 59.0, places=2)
		self.assertAlmostEqual(e_inv.tax_amount, 9.0, places=2)
		self.assertAlmostEqual(e_inv.net_amount, 50.0, places=2)

	def test_combined_mode_scales_unit_price(self):
		# Single qty=1 row is the combined-item signature: keep qty, scale price.
		e_inv = _FakeEInv([_item(qty=1.0, unit_price=118.0, total=118.0, tax_amount=18.0)], 118.0)
		applied = invoice.apply_payment_amount_scaling(e_inv, 59.0)
		self.assertTrue(applied)
		row = e_inv.items[0]
		self.assertEqual(row.qty, 1.0)
		self.assertEqual(row.unit_price, 59.0)
		self.assertEqual(row.total, 59.0)
		self.assertAlmostEqual(e_inv.gross_amount, 59.0, places=2)

	def test_full_payment_is_noop(self):
		e_inv = _FakeEInv([_item()], 118.0)
		self.assertFalse(invoice.apply_payment_amount_scaling(e_inv, 118.0))
		self.assertEqual(e_inv.items[0].qty, 2.0)
		self.assertEqual(e_inv.items[0].total, 118.0)

	def test_overpayment_is_noop(self):
		e_inv = _FakeEInv([_item()], 118.0)
		self.assertFalse(invoice.apply_payment_amount_scaling(e_inv, 200.0))

	def test_zero_or_missing_amount_is_noop(self):
		e_inv = _FakeEInv([_item()], 118.0)
		self.assertFalse(invoice.apply_payment_amount_scaling(e_inv, 0.0))


if __name__ == "__main__":
	unittest.main()
