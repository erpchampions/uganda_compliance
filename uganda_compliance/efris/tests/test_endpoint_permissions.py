"""Regressions: whitelisted EFRIS endpoints that did not check permissions (review, 28 Sep 2026)."""

from unittest.mock import patch

import frappe

from uganda_compliance.efris.api_classes import e_invoice
from uganda_compliance.efris.doctype.e_invoicing_settings import e_invoicing_settings
from uganda_compliance.efris.tests import test_efris_queue
from uganda_compliance.efris.tests.efris_test_utils import ensure_vat_account, fake_ura, reload, run_queued
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase

SETTINGS_MODULE = "uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings"


def make_user(email, first_name, *roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first_name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	missing = set(roles) - {r.role for r in user.roles}
	if missing:
		user.add_roles(*missing)
	return email


class AsUser:
	def __init__(self, user):
		self.user = user

	def __enter__(self):
		frappe.set_user(self.user)

	def __exit__(self, *exc):
		frappe.set_user("Administrator")


class TestUnauthenticatedEndpointsClosed(EfrisTestCase):
	def test_create_item_tax_templates_is_not_an_api(self):
		# regression: whitelisted, took a client-built doc and inserted Item Tax Templates for any
		# company with ignore_permissions
		with self.assertRaises(frappe.PermissionError):
			frappe.is_whitelisted(e_invoicing_settings.create_item_tax_templates)

		# its legitimate caller (E Invoicing Settings save) still creates the templates
		efris_templates = {"company": self.company, "title": ["like", "EFRIS %"]}
		names = frappe.get_all("Item Tax Template", efris_templates, pluck="name")
		self.assertEqual(len(names), 4)
		frappe.db.delete("Item Tax Template Detail", {"parent": ["in", names]})
		frappe.db.delete("Item Tax Template", {"name": ["in", names]})
		settings = frappe.get_doc("E Invoicing Settings", {"company": self.company})
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		self.assertCountEqual(frappe.get_all("Item Tax Template", efris_templates, pluck="name"), names)

	def test_settings_before_save_wrapper_removed_and_runs_once(self):
		# regression: `e_invoicing_settings.before_save(doc, method)` was whitelisted and registered
		# as a doc_event on top of the controller's own before_save, so it also ran twice per save
		self.assertFalse(hasattr(e_invoicing_settings, "before_save"))
		self.assertNotIn(
			f"{SETTINGS_MODULE}.before_save",
			frappe.get_hooks("doc_events").get("E Invoicing Settings", {}).get("before_save", []),
		)
		settings = frappe.get_doc("E Invoicing Settings", {"company": self.company})
		settings.flags.ignore_mandatory = True
		with patch.object(
			e_invoicing_settings.EInvoicingSettings,
			"create_tax_templates",
			autospec=True,
			side_effect=e_invoicing_settings.EInvoicingSettings.create_tax_templates,
		) as create_tax_templates:
			settings.save(ignore_permissions=True)
		self.assertEqual(create_tax_templates.call_count, 1)
		# update_efris_company is still hooked
		self.assertEqual(frappe.db.get_value("Company", self.company, "efris_company"), 1)

	def test_get_e_tax_template_checks_permissions(self):
		nobody = make_user("efris-nobody@example.ug", "Mukasa")
		buyer = make_user("efris-buyer@example.ug", "Nansubuga", "Purchase User")
		accountant = make_user("efris-accountant@example.ug", "Wasswa", "Accounts Manager")

		with AsUser(nobody), self.assertRaises(frappe.PermissionError):
			e_invoicing_settings.get_e_tax_template(self.company, "Sales Tax")
		# can read the company, but not sales tax templates
		with AsUser(buyer), self.assertRaises(frappe.PermissionError):
			e_invoicing_settings.get_e_tax_template(self.company, "Sales Tax")

		with AsUser(accountant):
			out = e_invoicing_settings.get_e_tax_template(self.company, "Sales Tax")
		self.assertEqual(out["template_name"], self.ctx.sales_taxes_template)
		self.assertEqual(out["taxes"][0]["rate"], 18)

	def test_get_e_tax_template_purchase_reads_purchase_template(self):
		# regression: "Purchase Tax" loaded the purchase template name as a *Sales* template
		settings = frappe.get_doc("E Invoicing Settings", {"company": self.company})
		settings.input_vat_account = ensure_vat_account(self.company)
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		out = e_invoicing_settings.get_e_tax_template(self.company, "Purchase Tax")
		self.assertEqual(out["template_name"], settings.purchase_taxes_and_charges_template)
		self.assertEqual(
			frappe.db.get_value("Purchase Taxes and Charges Template", out["template_name"], "company"),
			self.company,
		)


class TestCheckEfrisFlagForSalesInvoice(EfrisTestCase):
	def test_check_efris_flag_requires_read_permission(self):
		with fake_ura() as ura:
			si = test_efris_queue.TestEfrisSalesInvoice._make_si(self)
			run_queued(ura)
		self.assertTrue(reload(si).efris_irn)

		self.assertTrue(e_invoice.check_efris_flag_for_sales_invoice(1, si.name))
		# regression: is_return arrives as the string "0" from the client and bool("0") is True
		self.assertFalse(e_invoice.check_efris_flag_for_sales_invoice("0", si.name))

		nobody = make_user("efris-nobody@example.ug", "Mukasa")
		with AsUser(nobody), self.assertRaises(frappe.PermissionError):
			e_invoice.check_efris_flag_for_sales_invoice(1, si.name)
