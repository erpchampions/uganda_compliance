"""Regression: URA sandbox rejected every invoice with a line quantity above 1 (2026-10-21):

    "Tax Amount in the Tax Details(Section E: Tax Details) cannot be less than the sum Tax in the
    Goods Details(Section D: Goods & Services Details)!"

POS Invoice ACC-PSINV-2026-00017 (demo Masindi): 2 x 2,500 + 1 x 2,000, VAT 18 % included.
The goods lines took ERPNext's tax on the rounded nets (762.71 + 305.09 = 1,067.80); Section E and
the summary were recomputed from the gross (762.71 + 305.08 = 1,067.79), so Section E < Section D.
ERPNext itself books VAT 1,067.80 on net 5,932.21: 7,000.01 against a grand total of 7,000.00
(the cent goes to Round Off). URA is sent amounts but no HTTP call is made (FakeURA).
"""

import json
from unittest.mock import patch

import frappe
import frappe.model.meta
from frappe.utils import flt

from uganda_compliance.efris.inclusive_vat import allocate, reconcile_inclusive_vat, vat_in
from uganda_compliance.efris.tests.efris_test_utils import (
	TEST_CUSTOMER,
	TEST_ITEM,
	TEST_UOM,
	fake_ura,
	reload,
	run_queued,
)
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase

SECOND_ITEM = "EFRIS-TEST-MILK-500ML"


def ensure_second_item():
	"""A second EFRIS item like TEST_ITEM (EFRIS master data set directly, as ensure_masters does)."""
	if not frappe.db.exists("Item", SECOND_ITEM):
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": SECOND_ITEM,
				"item_name": "Fresh Milk 500ml",
				"item_group": frappe.db.get_value("Item", TEST_ITEM, "item_group"),
				"stock_uom": TEST_UOM,
				"is_stock_item": 0,
				"include_item_in_manufacturing": 0,
			}
		)
		item.flags.ignore_mandatory = True
		item.insert(ignore_permissions=True)
	fields = frappe.db.get_value("Item", TEST_ITEM, ["efris_item", "efris_commodity_code"], as_dict=True)
	frappe.db.set_value(
		"Item", SECOND_ITEM, {**fields, "efris_product_code": SECOND_ITEM}, update_modified=False
	)
	frappe.db.delete("Item Tax", {"parent": SECOND_ITEM, "parenttype": "Item"})
	template = frappe.db.get_value(
		"Item Tax", {"parent": TEST_ITEM, "parenttype": "Item"}, "item_tax_template"
	)
	frappe.get_doc(
		{
			"doctype": "Item Tax",
			"parent": SECOND_ITEM,
			"parenttype": "Item",
			"parentfield": "taxes",
			"item_tax_template": template,
			"idx": 1,
		}
	).db_insert()


class TestInclusiveVatRounding(EfrisTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_second_item()

	def make_invoice(self, doctype, lines, percentage=None, discount=None, submit=True):
		inv = frappe.new_doc(doctype)
		inv.update(
			{
				"company": self.company,
				"customer": TEST_CUSTOMER,
				"currency": frappe.get_cached_value("Company", self.company, "default_currency"),
				"update_stock": 0,
			}
		)
		if doctype == "POS Invoice":
			inv.update({"pos_profile": self.ctx.pos_profile, "is_pos": 1})
		for item_code, qty, rate in lines:
			inv.append(
				"items",
				{
					"item_code": item_code,
					"qty": qty,
					"rate": rate,
					"uom": TEST_UOM,
					"warehouse": self.ctx.warehouse,
				},
			)
		inv.set_missing_values()
		for row, (_item_code, _qty, rate) in zip(inv.items, lines, strict=True):
			row.price_list_rate = row.rate = rate
			row.discount_percentage = row.margin_rate_or_amount = 0
		inv.taxes_and_charges = self.ctx.sales_taxes_template
		inv.set("taxes", [])
		inv.set_taxes()
		if percentage or discount:
			inv.apply_discount_on = "Grand Total"
			inv.additional_discount_percentage = percentage or 0
			inv.discount_amount = discount or 0
		inv.calculate_taxes_and_totals()
		if doctype == "POS Invoice":
			inv.set("payments", [])
			inv.append("payments", {"mode_of_payment": "Cash", "amount": inv.grand_total, "default": 1})
		inv.efris_invoice = 1
		inv.insert(ignore_permissions=True)
		if submit:
			inv.submit()
		return inv

	def fiscalise(self, doctype, lines, **kwargs):
		with fake_ura() as ura:
			inv = self.make_invoice(doctype, lines, **kwargs)
			(result,) = run_queued(ura, only=inv)
		self.assertEqual(result["outcome"], "submitted", result)
		return reload(inv), ura.calls_for("T109")[0]["content"]

	def assert_consistent(self, inv, payload):
		"""What URA validates, plus: ERPNext and EFRIS agree to the cent."""
		goods = payload["goodsDetails"]
		goods_tax = round(sum(flt(g["tax"]) for g in goods), 2)
		goods_gross = round(sum(flt(g["total"]) for g in goods), 2)
		section_e = payload["taxDetails"]
		summary = payload["summary"]
		for g in goods:
			# URA: line tax = total x 18/118, within 0.02 (sandbox rejects 0.05 off)
			self.assertAlmostEqual(flt(g["tax"]), flt(g["total"]) * 18 / 118, delta=0.01, msg=g)
		self.assertEqual(round(sum(flt(t["taxAmount"]) for t in section_e), 2), goods_tax)
		self.assertEqual(round(sum(flt(t["grossAmount"]) for t in section_e), 2), goods_gross)
		self.assertEqual(flt(summary["taxAmount"]), goods_tax)
		self.assertEqual(flt(summary["grossAmount"]), goods_gross)
		self.assertEqual(round(flt(summary["netAmount"]) + goods_tax, 2), goods_gross)
		self.assertEqual(int(summary["itemCount"]), len([g for g in goods if g["discountFlag"] != "0"]))
		# ERPNext: lines add up to the VAT row and net + VAT = grand total = EFRIS gross
		vat = inv.taxes[0]
		self.assertEqual(flt(vat.tax_amount), goods_tax)
		self.assertEqual(round(flt(inv.net_total) + flt(vat.tax_amount), 2), flt(inv.grand_total))
		self.assertEqual(flt(vat.total), flt(inv.grand_total))
		self.assertEqual(round(sum(flt(i.net_amount) for i in inv.items), 2), flt(inv.net_total))
		item_wise = json.loads(vat.item_wise_tax_detail)
		self.assertEqual(round(sum(v[1] for v in item_wise.values()), 2), goods_tax)
		self.assertEqual(goods_gross, flt(inv.grand_total))

	def test_qty_above_one_tax_details_not_below_goods_tax(self):
		inv, payload = self.fiscalise("POS Invoice", [(TEST_ITEM, 2, 2500), (SECOND_ITEM, 1, 2000)])
		self.assertEqual([g["tax"] for g in payload["goodsDetails"]], ["762.71", "305.08"])
		self.assertEqual(payload["taxDetails"][0]["taxAmount"], "1067.79")
		self.assertEqual(payload["taxDetails"][0]["netAmount"], "5932.21")
		self.assertEqual(flt(payload["summary"]["grossAmount"]), 7000)
		self.assertEqual((inv.net_total, inv.taxes[0].tax_amount, inv.grand_total), (5932.21, 1067.79, 7000))
		self.assert_consistent(inv, payload)

	def test_no_round_off_gl_entry_for_inclusive_vat(self):
		inv, payload = self.fiscalise("Sales Invoice", [(TEST_ITEM, 2, 2500), (SECOND_ITEM, 1, 2000)])
		self.assert_consistent(inv, payload)
		gl = frappe.get_all(
			"GL Entry", {"voucher_no": inv.name, "is_cancelled": 0}, ["account", "debit", "credit"]
		)
		round_off = frappe.get_cached_value("Company", self.company, "round_off_account")
		self.assertFalse([g for g in gl if g.account == round_off], gl)
		self.assertEqual(round(sum(g.debit for g in gl), 2), round(sum(g.credit for g in gl), 2))

	def test_qty_seven_and_mixed_items(self):
		inv, payload = self.fiscalise(
			"POS Invoice", [(TEST_ITEM, 7, 3500), (SECOND_ITEM, 3, 1500), (TEST_ITEM, 2, 999)]
		)
		self.assertEqual(len(payload["goodsDetails"]), 3, "a repeated item is sent on its own line")
		self.assert_consistent(inv, payload)

	def test_percentage_discount(self):
		inv, payload = self.fiscalise(
			"POS Invoice", [(TEST_ITEM, 7, 3500), (SECOND_ITEM, 3, 1500), (TEST_ITEM, 2, 999)], percentage=10
		)
		discount_lines = [g for g in payload["goodsDetails"] if g["discountFlag"] == "0"]
		self.assertEqual(len(discount_lines), 3)
		self.assertEqual(round(sum(flt(g["total"]) for g in discount_lines), 2), -inv.discount_amount)
		self.assertEqual(inv.discount_amount, 3099.8)
		self.assert_consistent(inv, payload)

	def test_amount_discount(self):
		inv, payload = self.fiscalise(
			"Sales Invoice",
			[(TEST_ITEM, 3, 1100), (SECOND_ITEM, 2, 2350), (TEST_ITEM, 5, 700)],
			discount=1000,
		)
		self.assertEqual(flt(payload["summary"]["grossAmount"]), 10500)
		self.assert_consistent(inv, payload)

	def test_odd_percentage_discount_sales_invoice(self):
		inv, payload = self.fiscalise(
			"Sales Invoice",
			[(TEST_ITEM, 3, 1100), (SECOND_ITEM, 2, 2350), (TEST_ITEM, 5, 700)],
			percentage=7.5,
		)
		self.assertEqual(inv.grand_total, 10637.5)
		self.assert_consistent(inv, payload)

	def test_efris_amounts_keep_two_decimals_when_currency_has_none(self):
		"""UGX with 0 decimals: ERPNext rounds VAT to whole shillings (1,068), URA rejects line taxes
		that are not within ~0.02 of total x 18/118, so EFRIS figures stay at 2 decimals."""
		with patch.object(frappe.model.meta, "get_precision_from_currency_format", lambda currency: 0):
			inv = self.make_invoice(
				"POS Invoice", [(TEST_ITEM, 2, 2500), (SECOND_ITEM, 1, 2000)], submit=False
			)
			self.assertEqual((inv.taxes[0].tax_amount, inv.net_total), (1068, 5932))
			from uganda_compliance.efris.inclusive_vat import line_figures

			self.assertEqual([f.tax for f in line_figures(inv)], [762.71, 305.08])


class TestInclusiveVatHelpers(EfrisTestCase):
	def test_vat_in(self):
		self.assertEqual(vat_in(5000, 18), 762.71)
		self.assertEqual(vat_in(2000, 18), 305.08)
		self.assertEqual(vat_in(2000, 0), 0)

	def test_allocate_adds_up_exactly(self):
		shares = allocate(3099.8, [24500, 4500, 1998])
		self.assertEqual(round(sum(shares), 2), 3099.8)
		self.assertEqual(allocate(0, [1, 2]), [0.0, 0.0])
		self.assertEqual(allocate(10, [0, 3, 0]), [0.0, 10.0, 0.0])

	def test_exclusive_vat_untouched(self):
		doc = frappe._dict(
			taxes=[frappe._dict(included_in_print_rate=0, charge_type="On Net Total", tax_amount=1)],
			net_total=5,
		)
		reconcile_inclusive_vat(doc)
		self.assertEqual((doc.taxes[0].tax_amount, doc.net_total), (1, 5))
