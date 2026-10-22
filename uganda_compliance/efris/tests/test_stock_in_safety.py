"""Regressions in the EFRIS stock-in (T131), review of 22 Oct 2026:

- the stock-in senders were whitelisted, so any logged-in user could send a document (or, for
  Stock Entry, a document dict they built) to URA;
- a Stock Reconciliation grouped its lines on a field that does not exist, so a count with
  several adjustment reasons went to URA as one request under the last line's reason;
- a stock-in URA accepted inside a submit that ERPNext then rolled back left no trace, and the
  next submit sent it again.
"""

from contextlib import ExitStack
from unittest.mock import patch

import frappe
from frappe.utils import flt, nowdate

from uganda_compliance.efris.api_classes import (
	e_company,
	e_customer,
	e_goods_services,
	efris_invoice_sync,
	stock_in,
)
from uganda_compliance.efris.page.efris_synchronizatio import efris_synchronization_center
from uganda_compliance.efris.tests.efris_test_utils import FakeURA, ensure_item_group
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase
from uganda_compliance.efris.tests.test_endpoint_permissions import AsUser, make_user

ITEMS = ("EFRIS-TEST-STOCKIN-MAIZE", "EFRIS-TEST-STOCKIN-BEANS")
SUPPLIER = "Kato Wholesalers (EFRIS Test)"


class StockInTestCase(EfrisTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for code in ITEMS:
			if not frappe.db.exists("Item", code):
				item = frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": code.title(),
						"item_group": ensure_item_group(),
						"stock_uom": "Nos",
						"is_stock_item": 1,
						"include_item_in_manufacturing": 0,
						"standard_rate": 3000,
					}
				)
				item.flags.ignore_mandatory = True
				item.insert(ignore_permissions=True)
			frappe.db.set_value(
				"Item",
				code,
				{
					"efris_item": 1,
					"efris_e_company": cls.company,
					"efris_product_code": code,
					"efris_registered": 1,
				},
				update_modified=False,
			)
		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": SUPPLIER,
					"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}),
				}
			).insert(ignore_permissions=True)

	def setUp(self):
		super().setUp()
		self.ura = FakeURA()
		self.ura.responses["T131"] = [(True, [])] * 10
		self.stack = ExitStack()
		self.stack.enter_context(patch.object(stock_in, "make_post", self.ura))

	def tearDown(self):
		self.stack.close()
		# the fake URA accepted stock-ins whose submit is never committed: drop their
		# "record if rolled back" callbacks so the class rollback does not log them
		frappe.db.after_rollback.reset()
		frappe.set_user("Administrator")

	def set_auto_send(self, on):
		frappe.db.set_value(
			"E Invoicing Settings", {"company": self.company}, "auto_send_submitted_invoice", on
		)
		frappe.local.efris_company_settings_cache = {}

	def purchase_receipt(self, qty=10, submit=True):
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"company": self.company,
				"supplier": SUPPLIER,
				"posting_date": nowdate(),
				"set_warehouse": self.ctx.warehouse,
				"efris_stockin_type": "102:Local Purchase",
				"items": [
					{
						"item_code": code,
						"qty": qty,
						"rate": 3000,
						"warehouse": self.ctx.warehouse,
						"efris_receipt": 1,
						"efris_unit_price": 3000,
					}
					for code in ITEMS
				],
			}
		)
		pr.insert(ignore_permissions=True)
		if submit:
			pr.submit()
		return pr

	def t131(self):
		return [c["content"] for c in self.ura.calls_for("T131")]


class TestStockInIsNotAPublicApi(StockInTestCase):
	def test_stock_in_senders_and_doc_events_are_not_whitelisted(self):
		for fn in (
			stock_in.stock_in_T131,
			stock_in.send_purchase_receipt,
			stock_in.send_stock_entry,
			stock_in.send_stock_reconciliation,
			stock_in.process_pending_efris_stock_entries,
			stock_in.before_submit_on_stock_entry,
			stock_in.before_save_on_purchase_receipt,
			stock_in.purchase_uom_validation,
			stock_in.get_stock_entry_item_type,
			e_goods_services.after_save_item,
			e_goods_services.item_validations,
			e_customer.before_save_query_customer,
			e_company.before_save_query_company,
			efris_invoice_sync.format_date,
			efris_invoice_sync.get_customer_type,
		):
			with self.subTest(fn=fn.__name__), self.assertRaises(frappe.PermissionError):
				frappe.is_whitelisted(fn)

	def test_submit_stock_in_needs_submit_permission_and_sends_once(self):
		self.set_auto_send(0)
		pr = self.purchase_receipt()
		self.assertEqual(self.t131(), [], "auto send is off: the submit sends nothing")

		nobody = make_user("efris-nobody@example.ug", "Mukasa")
		with AsUser(nobody), self.assertRaises(frappe.PermissionError):
			stock_in.submit_stock_in("Purchase Receipt", pr.name)
		self.assertEqual(self.t131(), [])

		with self.assertRaises(frappe.ValidationError):
			stock_in.submit_stock_in("Sales Invoice", pr.name)

		keeper = make_user("efris-storekeeper@example.ug", "Achieng", "Stock Manager")
		with AsUser(keeper):
			self.assertTrue(stock_in.submit_stock_in("Purchase Receipt", pr.name))
			# already at URA: a second click sends nothing
			stock_in.submit_stock_in("Purchase Receipt", pr.name)
		(content,) = self.t131()
		self.assertEqual([g["goodsCode"] for g in content["goodsStockInItem"]], list(ITEMS))
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "efris_submitted"), 1)

	def test_submit_stock_in_refuses_a_draft(self):
		pr = self.purchase_receipt(submit=False)
		with self.assertRaises(frappe.ValidationError):
			stock_in.submit_stock_in("Purchase Receipt", pr.name)
		self.assertEqual(self.t131(), [])

	def test_helpers_check_permissions(self):
		pr = self.purchase_receipt()
		nobody = make_user("efris-nobody@example.ug", "Mukasa")
		with AsUser(nobody):
			for call in (
				lambda: stock_in.get_efris_unit_price(pr.name, ITEMS[0]),
				lambda: stock_in.is_efris_warehouse(self.ctx.warehouse),
				lambda: stock_in.query_currency_exchange_rate(
					frappe.as_json({"company": self.company, "currency": "EUR"})
				),
				lambda: e_goods_services.send_item_to_efris(ITEMS[0]),
				lambda: e_goods_services.create_item_prices(ITEMS[0]),
				lambda: e_company.check_efris_company("1000000001", self.company),
				efris_invoice_sync.efris_invoice_sync,
				efris_synchronization_center.process_pending_efris_entries,
				efris_synchronization_center.process_pending_efris_stock_entries,
				efris_synchronization_center.get_recent_efris_statuses,
				efris_synchronization_center.check_invoice_statuses,
			):
				with self.assertRaises(frappe.PermissionError):
					call()
		self.assertEqual(flt(stock_in.get_efris_unit_price(pr.name, ITEMS[0])["efris_unit_price"]), 3000)
		self.assertTrue(stock_in.is_efris_warehouse(self.ctx.warehouse))


class TestStockReconciliationReasons(StockInTestCase):
	def count(self, rows):
		sr = frappe.get_doc(
			{
				"doctype": "Stock Reconciliation",
				"company": self.company,
				"purpose": "Stock Reconciliation",
				"posting_date": nowdate(),
				"set_posting_time": 1,
				"posting_time": "23:59:00",
				"items": [
					{
						"item_code": code,
						"warehouse": self.ctx.warehouse,
						"qty": qty,
						"valuation_rate": 3000,
						"efris_reconcilliation": 1,
						"efris_adjustment_type": reason,
						"efris_remarks": remark,
					}
					for code, qty, reason, remark in rows
				],
			}
		)
		sr.insert(ignore_permissions=True)
		sr.submit()
		return sr

	def on_hand(self, code):
		return flt(
			frappe.db.get_value("Bin", {"item_code": code, "warehouse": self.ctx.warehouse}, "actual_qty")
		)

	def test_a_count_with_two_reasons_sends_each_line_under_its_own_reason(self):
		self.purchase_receipt(qty=10)
		maize, beans = (self.on_hand(code) for code in ITEMS)
		self.ura.calls.clear()
		sr = self.count(
			[
				(ITEMS[0], maize - 2, "101:Expired Goods", "past best-before"),
				(ITEMS[1], beans - 3, "102:Damaged Goods", "rain damage"),
			]
		)
		sent = {
			c["goodsStockIn"]["adjustType"]: (
				c["goodsStockIn"]["operationType"],
				[(g["goodsCode"], flt(g["quantity"])) for g in c["goodsStockInItem"]],
				c["goodsStockIn"]["remarks"],
			)
			for c in self.t131()
		}
		self.assertEqual(
			sent,
			{
				"101": ("102", [(ITEMS[0], 2)], "past best-before"),
				"102": ("102", [(ITEMS[1], 3)], "rain damage"),
			},
		)
		self.assertEqual({r.efris_registered for r in frappe.get_doc(sr.doctype, sr.name).items}, {1})

	def test_an_increase_is_not_sent_and_not_marked_sent(self):
		self.purchase_receipt(qty=10)
		maize, beans = (self.on_hand(code) for code in ITEMS)
		self.ura.calls.clear()
		sr = self.count(
			[
				(ITEMS[0], maize + 1, "104:Others. (Please specify)", "found a bag"),
				(ITEMS[1], beans - 1, "102:Damaged Goods", "torn"),
			]
		)
		(content,) = self.t131()
		self.assertEqual(content["goodsStockIn"]["adjustType"], "102")
		self.assertEqual([g["goodsCode"] for g in content["goodsStockInItem"]], [ITEMS[1]])
		registered = {r.item_code: r.efris_registered for r in frappe.get_doc(sr.doctype, sr.name).items}
		self.assertEqual(registered, {ITEMS[0]: 0, ITEMS[1]: 1})


class TestStockInRolledBackAfterUraAccepted(StockInTestCase):
	"""URA accepted the stock-in, then something after it in the same submit failed."""

	def fail_after_stock_in(self, pr):
		real = stock_in.stock_in_T131

		def stock_in_then_fail(doc, method):
			real(doc, method)
			raise frappe.ValidationError("a later on_submit step failed")

		frappe.db.savepoint("before_submit")
		with patch.object(stock_in, "stock_in_T131", stock_in_then_fail):
			self.assertRaises(frappe.ValidationError, pr.submit)
		# what the request does on an error: roll back, then run the after-rollback callbacks.
		# The submit is undone to the savepoint (the test's data stays); the callback's own
		# COMMIT / START TRANSACTION are skipped so nothing is committed for real.
		frappe.db.rollback(save_point="before_submit")
		real_sql = frappe.db.sql

		def sql(query, *args, **kwargs):
			return None if query == "commit" else real_sql(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", sql), patch.object(frappe.db, "begin", lambda **kw: None):
			frappe.db.after_rollback.run()
		# Error Log is MyISAM (outside the transaction): remove this test's flag afterwards
		self.addCleanup(
			frappe.db.delete,
			"Error Log",
			{"reference_name": pr.name, "method": ("like", "EFRIS stock-in accepted%")},
		)

	def test_rolled_back_stock_in_is_recorded_flagged_and_not_sent_again(self):
		pr = self.purchase_receipt(submit=False)
		errors_before = frappe.db.count("Error Log")
		self.fail_after_stock_in(pr)
		self.assertEqual(len(self.t131()), 1)
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 0)
		self.assertTrue(
			frappe.db.exists(
				"E Invoice Request Log",
				{"reference_document": pr.name, "interface_code": "T131", "status": "Success"},
			)
		)
		self.assertEqual(frappe.db.count("Error Log"), errors_before + 1)
		self.assertTrue(frappe.db.exists("Error Log", {"reference_name": pr.name}))

		pr = frappe.get_doc("Purchase Receipt", pr.name)
		pr.submit()
		self.assertEqual(len(self.t131()), 1, "URA already has it: not sent a second time")
		pr.reload()
		self.assertEqual((pr.docstatus, pr.efris_submitted), (1, 1))
		self.assertEqual({r.efris_registered for r in pr.items}, {1})

	def test_resubmitting_other_lines_than_ura_accepted_is_refused(self):
		pr = self.purchase_receipt(submit=False)
		self.fail_after_stock_in(pr)
		pr = frappe.get_doc("Purchase Receipt", pr.name)
		pr.items[0].qty = pr.items[0].received_qty = 7
		pr.save(ignore_permissions=True)
		self.assertRaisesRegex(frappe.ValidationError, "other lines", pr.submit)
		self.assertEqual(len(self.t131()), 1)

	def test_a_record_older_than_the_document_does_not_stop_its_stock_in(self):
		# a document rolled back away can leave its name to a later one (naming series): that
		# one's stock-in is new and must be sent
		pr = self.purchase_receipt(submit=False)
		frappe.get_doc(
			{
				"doctype": "E Invoice Request Log",
				"reference_doc_type": "Purchase Receipt",
				"reference_document": pr.name,
				"interface_code": "T131",
				"status": "Success",
				"timestamp": frappe.utils.add_days(pr.creation, -1),
				"request_data": frappe.as_json({"goodsStockIn": {"operationType": "101", "adjustType": ""}}),
			}
		).insert(ignore_permissions=True)
		pr.submit()
		self.assertEqual(len(self.t131()), 1)
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "efris_submitted"), 1)
