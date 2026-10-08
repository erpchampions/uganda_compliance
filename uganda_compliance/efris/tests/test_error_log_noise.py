"""Normal EFRIS paths must not write to the Error Log (r5 P3: one debug Error Log per Stock Entry)."""

from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from uganda_compliance.efris.api_classes import stock_in
from uganda_compliance.efris.tests.efris_test_utils import ensure_item_group
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase

STOCK_ITEM = "EFRIS-TEST-NOLOG-RICE"


class TestErrorLogNoise(EfrisTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("Item", STOCK_ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": STOCK_ITEM,
					"item_name": "Nile Rice 1kg",
					"item_group": ensure_item_group(),
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"include_item_in_manufacturing": 0,
				}
			).insert(ignore_permissions=True)

	def error_logs(self):
		return frappe.db.count("Error Log")

	def material_receipt(self):
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": self.company,
				"posting_date": nowdate(),
				"to_warehouse": self.ctx.warehouse,
				"items": [{"item_code": STOCK_ITEM, "qty": 5, "basic_rate": 4000, "conversion_factor": 1}],
			}
		)
		se.insert(ignore_permissions=True)
		se.submit()
		return se

	def test_stock_entry_submit_writes_no_debug_error_log(self):
		before = self.error_logs()
		self.material_receipt()
		self.assertEqual(self.error_logs(), before)

	def test_pending_stock_entry_posted_writes_no_error_log(self):
		se = self.material_receipt()
		# make it a pending EFRIS transfer, as the scheduler sees it
		frappe.db.set_value("Stock Entry", se.name, {"purpose": "Material Transfer", "efris_posted": 0})
		frappe.db.set_value("Stock Entry Detail", {"parent": se.name}, "efris_transfer", 1)
		before = self.error_logs()
		with patch.object(stock_in, "send_stock_entry") as send:
			processed = stock_in.process_pending_efris_stock_entries()
		self.assertIn(se.name, [p["name"] for p in processed])
		self.assertTrue(send.called)
		self.assertEqual(self.error_logs(), before)

	def test_failed_pending_stock_entry_is_still_logged(self):
		se = self.material_receipt()
		frappe.db.set_value("Stock Entry", se.name, {"purpose": "Material Transfer", "efris_posted": 0})
		frappe.db.set_value("Stock Entry Detail", {"parent": se.name}, "efris_transfer", 1)
		before = self.error_logs()
		with patch.object(stock_in, "send_stock_entry", side_effect=frappe.ValidationError("URA said no")):
			processed = stock_in.process_pending_efris_stock_entries()
		self.assertNotIn(se.name, [p["name"] for p in processed])
		self.assertGreater(self.error_logs(), before)
