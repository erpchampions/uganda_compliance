"""EFRIS service items (non-stock, e.g. the Till King subscription plans the vendor
site invoices): they move no stock, so the invoice needs no EFRIS warehouse."""

import frappe

from uganda_compliance.efris.api_classes.e_invoice import set_efris_based_on_items
from uganda_compliance.efris.tests.efris_test_utils import TEST_CUSTOMER, TEST_ITEM
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase


class TestEfrisServiceItems(EfrisTestCase):
	def invoice(self, warehouse=None):
		return frappe._dict(
			customer=TEST_CUSTOMER,
			items=[frappe._dict(item_code=TEST_ITEM, warehouse=warehouse)],
			flags=frappe._dict(),
		)

	def test_service_item_without_warehouse_is_an_efris_invoice(self):
		# TEST_ITEM is a non-stock EFRIS item
		self.assertFalse(frappe.db.get_value("Item", TEST_ITEM, "is_stock_item"))
		doc = self.invoice()
		set_efris_based_on_items(doc, doc["items"])
		self.assertEqual(doc.efris_invoice, 1)
		self.assertEqual(doc.efris_customer_type, "B2C")

	def test_stock_item_still_needs_an_efris_warehouse(self):
		frappe.db.set_value("Item", TEST_ITEM, "is_stock_item", 1, update_modified=False)
		doc = self.invoice()
		with self.assertRaisesRegex(frappe.ValidationError, "must be an EFRIS Warehouse"):
			set_efris_based_on_items(doc, doc["items"])
		doc = self.invoice(warehouse=self.ctx.warehouse)
		set_efris_based_on_items(doc, doc["items"])
		self.assertEqual(doc.efris_invoice, 1)
