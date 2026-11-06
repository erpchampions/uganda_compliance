"""EFRIS slide of the setup wizard: stages run through the real functions, HTTP faked."""

import frappe

from uganda_compliance.efris.setup_wizard import get_setup_stages, setup_efris
from uganda_compliance.efris.tests.efris_test_utils import TEST_TIN, ensure_item_group
from uganda_compliance.efris.tests.test_connection_modes import ENABLER_DEVICE, ENABLER_URL, fake_http
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase

COMPANY = "EFRIS Wizard Test Ltd"
EMAIL = "seller@example.com"
OWNER = "owner@example.com"


def wizard_args(**overrides):
	args = {
		"company_name": COMPANY,
		"email": "owner@example.com",
		"efris_setup": 1,
		"efris_tin": TEST_TIN,
		"efris_connection_mode": "Offline Enabler",
		"efris_device_no": ENABLER_DEVICE,
		"efris_enabler_url": ENABLER_URL,
		"efris_seller_email": EMAIL,
		"efris_seller_phone": "+256700000000",
		"efris_sandbox": 1,
	}
	args.update(overrides)
	return frappe._dict(args)


class TestEfrisWizardInput(EfrisTestCase):
	def test_unticked_slide_adds_no_stage(self):
		self.assertEqual(get_setup_stages(wizard_args(efris_setup=0)), [])

	def test_bad_input_is_refused_before_any_stage_runs(self):
		for bad in (
			{"efris_tin": "12345"},
			{"efris_seller_email": "", "email": ""},
			{"efris_seller_email": "not-an-email"},
			{"efris_device_no": ""},
			{"efris_enabler_url": ""},
		):
			with self.subTest(bad), self.assertRaises(frappe.ValidationError):
				get_setup_stages(wizard_args(**bad))

	def test_seller_email_defaults_to_the_owners_email(self):
		(stage,) = get_setup_stages(wizard_args(efris_seller_email=""))
		self.assertEqual(stage["tasks"][0]["fn"], setup_efris)


class TestEfrisWizardSetup(EfrisTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_item_group()
		# Frappe's own wizard stage creates this user before our stage runs
		if not frappe.db.exists("User", OWNER):
			frappe.get_doc(
				{"doctype": "User", "email": OWNER, "first_name": "Owner", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.flags.country_change = True
		if not frappe.db.exists("Company", COMPANY):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": COMPANY,
					"abbr": "EWT",
					"default_currency": "UGX",
					"country": "Uganda",
					"create_chart_of_accounts_based_on": "Standard Template",
					"chart_of_accounts": "Standard",
				}
			).insert(ignore_permissions=True)
		cls.abbr = "EWT"
		parent = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_name": "Duties and Taxes", "is_group": 1}
		)
		if not frappe.db.exists("Account", {"company": COMPANY, "account_name": "VAT"}):
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": "VAT",
					"company": COMPANY,
					"parent_account": parent,
					"account_type": "Tax",
				}
			).insert(ignore_permissions=True)
		cls.stores = frappe.db.get_value("Warehouse", {"company": COMPANY, "warehouse_name": "Stores"})
		cls.old_default_warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
		frappe.db.set_single_value("Stock Settings", "default_warehouse", cls.stores)

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_single_value("Stock Settings", "default_warehouse", cls.old_default_warehouse)
		super().tearDownClass()

	def run_wizard(self, **overrides):
		with fake_http() as http:
			setup_efris(wizard_args(**overrides))
		return http

	def settings(self):
		return frappe.get_doc("E Invoicing Settings", {"company": COMPANY})

	def test_offline_setup_leaves_efris_ready_to_invoice(self):
		http = self.run_wizard()

		company = frappe.get_doc("Company", COMPANY)
		self.assertEqual(
			(company.tax_id, company.email, company.phone_no), (TEST_TIN, EMAIL, "+256700000000")
		)
		self.assertEqual(frappe.db.get_value("Warehouse", self.stores, "efris_warehouse"), 1)

		s = self.settings()
		self.assertEqual(s.enabled, 1, "the enabler holds the key: nothing else is missing")
		self.assertEqual((s.connection_mode, s.device_no), ("Offline Enabler", ENABLER_DEVICE))
		self.assertTrue(s.sales_taxes_and_charges_template, "VAT account set: templates exist")
		self.assertEqual([c.code for c in http.calls], ["T101"])
		self.assertEqual(http.calls[0].url, ENABLER_URL)

		note = frappe.get_last_doc("Notification Log", {"for_user": "owner@example.com"})
		self.assertIn("EFRIS connection works", note.subject)

	def test_online_setup_stays_disabled_until_the_key_is_uploaded(self):
		http = self.run_wizard(efris_connection_mode="Online (URA)", efris_enabler_url="", efris_device_no="")
		self.assertEqual(self.settings().enabled, 0)
		self.assertEqual(http.calls, [], "nothing to test yet, and the wizard must not fail on it")
		note = frappe.get_last_doc("Notification Log", {"for_user": OWNER})
		self.assertIn("upload the private key", note.subject)

	def test_failed_connection_does_not_fail_the_wizard(self):
		with fake_http() as http:
			http.replies["T101"] = [ConnectionError("no route to host")]
			setup_efris(wizard_args())
		note = frappe.get_last_doc("Notification Log", {"for_user": "owner@example.com"})
		self.assertIn("EFRIS could not connect", note.subject)
		self.assertEqual(self.settings().enabled, 1)

	def test_rerun_keeps_one_settings_record(self):
		self.run_wizard()
		self.run_wizard(efris_tin="1000000002")
		self.assertEqual(frappe.db.count("E Invoicing Settings", {"company": COMPANY}), 1)
		self.assertEqual(self.settings().tin, "1000000002")

	def test_payment_modes_get_codes_only_where_empty(self):
		frappe.db.set_value("Mode of Payment", "Cash", "efris_payment_mode", "105:Mobile money")
		frappe.db.set_value("Mode of Payment", "Wire Transfer", "efris_payment_mode", None)
		self.run_wizard()
		self.assertEqual(
			frappe.db.get_value("Mode of Payment", "Cash", "efris_payment_mode"), "105:Mobile money"
		)
		self.assertEqual(
			frappe.db.get_value("Mode of Payment", "Wire Transfer", "efris_payment_mode"), "107:EFT"
		)
		frappe.db.set_value("Mode of Payment", "Cash", "efris_payment_mode", "102:Cash")
