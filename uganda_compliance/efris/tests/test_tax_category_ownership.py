"""Regression: the app shipped its own copy of ERPNext's Tax Category DocType (module EFRIS)."""

import frappe
from frappe.model.base_document import get_controller
from frappe.tests.utils import FrappeTestCase

from uganda_compliance.patches import restore_erpnext_tax_category


class TestTaxCategoryBelongsToERPNext(FrappeTestCase):
	def assert_owned_by_erpnext(self):
		frappe.clear_cache(doctype="Tax Category")
		self.assertEqual(frappe.db.get_value("DocType", "Tax Category", "module"), "Accounts")
		self.assertTrue(get_controller("Tax Category").__module__.startswith("erpnext.accounts."))
		# what `bench uninstall-app uganda_compliance` would delete: DocTypes in the app's modules
		app_modules = frappe.get_all("Module Def", {"app_name": "uganda_compliance"}, pluck="name")
		self.assertNotIn(
			"Tax Category", frappe.get_all("DocType", {"module": ["in", app_modules]}, pluck="name")
		)

	def test_tax_category_is_erpnexts(self):
		self.assert_owned_by_erpnext()

	def test_patch_gives_tax_category_back_to_erpnext(self):
		frappe.db.set_value("DocType", "Tax Category", "module", "EFRIS", update_modified=False)
		restore_erpnext_tax_category.execute()
		self.assert_owned_by_erpnext()
		self.assertTrue(frappe.db.exists("Tax Category", "Foreign"), "records are untouched")
		restore_erpnext_tax_category.execute()  # idempotent
		self.assert_owned_by_erpnext()
