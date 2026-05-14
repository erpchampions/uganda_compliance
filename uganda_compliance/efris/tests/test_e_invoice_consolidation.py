"""Unit tests for EFRIS single-line consolidation in E Invoice generation.

These tests exercise ``EInvoice.fetch_consolidated_item_from_invoice`` —
the helper that replaces the per-line ``goodsDetails`` payload with a
single configured "summary item" whose amount/tax/discount are the sum
of the source Sales Invoice items.
"""
from __future__ import unicode_literals

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from uganda_compliance.efris.doctype.e_invoice.e_invoice import EInvoice


def _d(**kwargs):
    """Attribute-access record. We avoid ``frappe._dict`` here because it
    inherits from ``dict`` and shadows attribute names like ``items``."""
    return SimpleNamespace(**kwargs)


def _make_si_item(idx, item_code, amount, dsct_total=0.0, dsct_tax=0.0,
                  dsct_item_tax=0.0, dsct_taxable_amount=0.0,
                  dsct_item_discount=0.0, dsct_tax_rate=""):
    return _d(
        idx=idx,
        item_code=item_code,
        item_name=item_code,
        qty=1,
        uom="Nos",
        rate=amount,
        amount=amount,
        efris_commodity_code="010101",
        efris_dsct_discount_total=dsct_total,
        efris_dsct_discount_tax=dsct_tax,
        efris_dsct_discount_tax_rate=dsct_tax_rate,
        efris_dsct_item_tax=dsct_item_tax,
        efris_dsct_taxable_amount=dsct_taxable_amount,
        efris_dsct_item_discount=dsct_item_discount,
    )


def _make_sales_invoice(items, item_wise_tax_details, conversion_rate=1):
    return _d(
        items=items,
        item_wise_tax_details=item_wise_tax_details,
        conversion_rate=conversion_rate,
        taxes=[_d(account_head="VAT")],
    )


SUMMARY_ITEM_CODE = "EFRIS-SUMMARY"
SUMMARY_COMMODITY = "010101"
SUMMARY_COMMODITY_NAME = "Consolidated Sales"
DEFAULT_TAX_CATEGORY = "01: Standard"


def _fake_get_doc_factory(item_category_map, summary_item_category=None,
                          summary_has_uom_code=True, summary_has_commodity=True,
                          summary_has_taxes=True):
    """Build a ``frappe.get_doc`` stand-in.

    ``item_category_map`` maps Sales-Invoice item_code → e_tax_category.
    """

    summary_category = summary_item_category or DEFAULT_TAX_CATEGORY

    def _fake(doctype, name=None):
        if doctype == "Item":
            if name == SUMMARY_ITEM_CODE:
                return _d(
                    item_code=SUMMARY_ITEM_CODE,
                    item_name="EFRIS Summary",
                    stock_uom="Nos",
                    efris_commodity_code=(SUMMARY_COMMODITY if summary_has_commodity else None),
                    taxes=([_d(item_tax_template=f"ITT::{summary_category}")] if summary_has_taxes else []),
                )
            # SI line item -> normal Item doc
            return _d(
                item_code=name,
                taxes=[_d(item_tax_template=f"ITT::{item_category_map[name]}")],
            )

        if doctype == "Item Tax Template":
            # Name is "ITT::<category>" - pull category off the end.
            category = name.split("::", 1)[1]
            return _d(taxes=[_d(efris_e_tax_category=category)])

        if doctype == "UOM":
            return _d(efris_uom_code=("NO" if summary_has_uom_code else None))

        if doctype == "EFRIS Commodity Code":
            return _d(commodity_name=SUMMARY_COMMODITY_NAME)

        raise AssertionError(f"Unexpected get_doc call: {doctype} / {name}")

    return _fake


class _EInvoiceForTest(EInvoice):
    """EInvoice constructed without DB I/O so we can call the helper directly."""

    def __init__(self, sales_invoice, company="Test Co"):
        self.sales_invoice = sales_invoice
        self.company = company
        self._appended_items = []

    def append(self, fieldname, value):  # type: ignore[override]
        assert fieldname == "items"
        row = frappe._dict(value)
        self._appended_items.append(row)
        return row

    @property
    def items(self):
        return self._appended_items


class ConsolidationTests(unittest.TestCase):
    def test_single_tax_category_three_items_collapses_to_one_line(self):
        si = _make_sales_invoice(
            items=[
                _make_si_item(1, "ITEM-A", 100.0),
                _make_si_item(2, "ITEM-B", 250.0),
                _make_si_item(3, "ITEM-C", 50.0),
            ],
            item_wise_tax_details=[
                _d(amount=18.0, rate=18),
                _d(amount=45.0, rate=18),
                _d(amount=9.0, rate=18),
            ],
        )
        einvoice = _EInvoiceForTest(si)

        category_map = {"ITEM-A": DEFAULT_TAX_CATEGORY,
                        "ITEM-B": DEFAULT_TAX_CATEGORY,
                        "ITEM-C": DEFAULT_TAX_CATEGORY}

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_fake_get_doc_factory(category_map),
        ):
            einvoice.fetch_consolidated_item_from_invoice(SUMMARY_ITEM_CODE)

        self.assertEqual(len(einvoice.items), 1)
        row = einvoice.items[0]
        self.assertEqual(row.item_code, SUMMARY_ITEM_CODE)
        self.assertEqual(row.efris_commodity_code, SUMMARY_COMMODITY)
        self.assertEqual(row.commodity_code_description, SUMMARY_COMMODITY_NAME)
        self.assertEqual(row.quantity, 1)
        self.assertEqual(row.unit, "Nos")
        self.assertEqual(row.amount, 400.0)  # 100 + 250 + 50
        self.assertEqual(row.rate, 400.0)
        self.assertEqual(row.tax, 72.0)  # 18 + 45 + 9
        self.assertEqual(row.e_tax_category, DEFAULT_TAX_CATEGORY)
        self.assertEqual(row.order_number, 0)

    def test_aggregates_efris_discount_fields(self):
        si = _make_sales_invoice(
            items=[
                _make_si_item(1, "ITEM-A", 100.0, dsct_total=10.0,
                              dsct_tax=1.8, dsct_item_tax=18.0,
                              dsct_taxable_amount=90.0, dsct_item_discount=10.0,
                              dsct_tax_rate="0.18"),
                _make_si_item(2, "ITEM-B", 200.0, dsct_total=20.0,
                              dsct_tax=3.6, dsct_item_tax=36.0,
                              dsct_taxable_amount=180.0, dsct_item_discount=20.0,
                              dsct_tax_rate="0.18"),
            ],
            item_wise_tax_details=[
                _d(amount=18.0, rate=18),
                _d(amount=36.0, rate=18),
            ],
        )
        einvoice = _EInvoiceForTest(si)

        category_map = {"ITEM-A": DEFAULT_TAX_CATEGORY,
                        "ITEM-B": DEFAULT_TAX_CATEGORY}

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_fake_get_doc_factory(category_map),
        ):
            einvoice.fetch_consolidated_item_from_invoice(SUMMARY_ITEM_CODE)

        row = einvoice.items[0]
        self.assertEqual(row.efris_dsct_discount_total, 30.0)
        self.assertAlmostEqual(row.efris_dsct_discount_tax, 5.4, places=4)
        self.assertEqual(row.efris_dsct_item_tax, 54.0)
        self.assertEqual(row.efris_dsct_taxable_amount, 270.0)
        self.assertEqual(row.efris_dsct_item_discount, 30.0)
        self.assertEqual(row.efris_dsct_discount_tax_rate, "0.18")

    def test_conversion_rate_scales_tax(self):
        si = _make_sales_invoice(
            items=[_make_si_item(1, "ITEM-A", 100.0),
                   _make_si_item(2, "ITEM-B", 100.0)],
            item_wise_tax_details=[_d(amount=36.0, rate=18),
                                   _d(amount=36.0, rate=18)],
            conversion_rate=2,
        )
        einvoice = _EInvoiceForTest(si)
        category_map = {"ITEM-A": DEFAULT_TAX_CATEGORY,
                        "ITEM-B": DEFAULT_TAX_CATEGORY}

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_fake_get_doc_factory(category_map),
        ):
            einvoice.fetch_consolidated_item_from_invoice(SUMMARY_ITEM_CODE)

        # Each row's tax divided by conversion_rate=2: (36/2) + (36/2) = 36
        self.assertEqual(einvoice.items[0].tax, 36.0)

    def test_mixed_tax_categories_raise(self):
        si = _make_sales_invoice(
            items=[_make_si_item(1, "ITEM-A", 100.0),
                   _make_si_item(2, "ITEM-B", 100.0)],
            item_wise_tax_details=[_d(amount=18.0, rate=18),
                                   _d(amount=0.0, rate=0)],
        )
        einvoice = _EInvoiceForTest(si)
        category_map = {"ITEM-A": "01: Standard", "ITEM-B": "02: Zero Rated"}

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_fake_get_doc_factory(category_map),
        ):
            with self.assertRaises(frappe.ValidationError) as ctx:
                einvoice.fetch_consolidated_item_from_invoice(SUMMARY_ITEM_CODE)

        msg = str(ctx.exception)
        self.assertIn("01: Standard", msg)
        self.assertIn("02: Zero Rated", msg)
        self.assertEqual(len(einvoice.items), 0)

    def test_summary_item_missing_commodity_code_raises(self):
        si = _make_sales_invoice(
            items=[_make_si_item(1, "ITEM-A", 100.0)],
            item_wise_tax_details=[_d(amount=18.0, rate=18)],
        )
        einvoice = _EInvoiceForTest(si)
        category_map = {"ITEM-A": DEFAULT_TAX_CATEGORY}

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_fake_get_doc_factory(category_map, summary_has_commodity=False),
        ):
            with self.assertRaises(frappe.ValidationError):
                einvoice.fetch_consolidated_item_from_invoice(SUMMARY_ITEM_CODE)

    def test_summary_item_missing_uom_code_raises(self):
        si = _make_sales_invoice(
            items=[_make_si_item(1, "ITEM-A", 100.0)],
            item_wise_tax_details=[_d(amount=18.0, rate=18)],
        )
        einvoice = _EInvoiceForTest(si)
        category_map = {"ITEM-A": DEFAULT_TAX_CATEGORY}

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_fake_get_doc_factory(category_map, summary_has_uom_code=False),
        ):
            with self.assertRaises(frappe.ValidationError):
                einvoice.fetch_consolidated_item_from_invoice(SUMMARY_ITEM_CODE)

    def test_summary_item_missing_taxes_raises(self):
        si = _make_sales_invoice(
            items=[_make_si_item(1, "ITEM-A", 100.0)],
            item_wise_tax_details=[_d(amount=18.0, rate=18)],
        )
        einvoice = _EInvoiceForTest(si)
        category_map = {"ITEM-A": DEFAULT_TAX_CATEGORY}

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_fake_get_doc_factory(category_map, summary_has_taxes=False),
        ):
            with self.assertRaises(frappe.ValidationError):
                einvoice.fetch_consolidated_item_from_invoice(SUMMARY_ITEM_CODE)


class FetchItemsDispatchTests(unittest.TestCase):
    """``fetch_items_from_invoice`` should call the consolidation helper
    only when both the checkbox is on AND a summary item is configured."""

    def _run(self, settings_dict):
        si = _make_sales_invoice(
            items=[_make_si_item(1, "ITEM-A", 100.0)],
            item_wise_tax_details=[_d(amount=18.0, rate=18)],
        )
        einvoice = _EInvoiceForTest(si)
        # Replace the helper with a tracker; stop the fallback path before
        # it touches the DB by making it raise immediately.
        calls = []
        einvoice.fetch_consolidated_item_from_invoice = lambda code: calls.append(code)

        def _explode(*a, **kw):
            raise RuntimeError("fallback path entered")

        with patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.get_e_company_settings",
            return_value=frappe._dict(settings_dict),
        ), patch(
            "uganda_compliance.efris.doctype.e_invoice.e_invoice.frappe.get_doc",
            side_effect=_explode,
        ):
            try:
                einvoice.fetch_items_from_invoice()
            except RuntimeError:
                pass  # fallback path — consolidation was not taken
        return calls

    def test_dispatch_takes_consolidation_when_both_flags_set(self):
        calls = self._run({
            "consolidate_efris_invoice": 1,
            "efris_summary_item": SUMMARY_ITEM_CODE,
        })
        self.assertEqual(calls, [SUMMARY_ITEM_CODE])

    def test_dispatch_skips_consolidation_when_checkbox_off(self):
        calls = self._run({
            "consolidate_efris_invoice": 0,
            "efris_summary_item": SUMMARY_ITEM_CODE,
        })
        self.assertEqual(calls, [])

    def test_dispatch_skips_consolidation_when_no_summary_item(self):
        calls = self._run({
            "consolidate_efris_invoice": 1,
            "efris_summary_item": None,
        })
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
