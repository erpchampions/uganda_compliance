"""Regression: a Purchase Receipt or Stock Reconciliation of a company without (enabled)
E Invoicing Settings failed to submit with "No E Invoicing Settings found for company"
(stock_in_T131 asked for the settings before checking the company uses EFRIS)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from uganda_compliance.efris.api_classes import stock_in


class TestStockInWithoutEfrisSettings(FrappeTestCase):
	def company_without_settings(self):
		with_settings = frappe.get_all("E Invoicing Settings", filters={"enabled": 1}, pluck="company")
		company = frappe.db.get_value("Company", {"name": ("not in", with_settings or [""])})
		if not company:
			self.skipTest("every company on this site uses EFRIS")
		return company

	def test_stock_in_t131_sends_nothing_for_a_company_without_efris(self):
		company = self.company_without_settings()
		for doctype in ("Purchase Receipt", "Stock Reconciliation"):
			doc = frappe._dict(doctype=doctype, company=company, name="TEST", items=[])
			with patch.object(stock_in, "make_post") as post:
				stock_in.stock_in_T131(doc, "on_submit")  # used to throw
			post.assert_not_called()
