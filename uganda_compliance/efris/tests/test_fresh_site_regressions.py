"""Bugs found on the first real Offline Enabler run (4 Nov 2026, new site from the setup wizard).

- T130 "Partial failure!": the reason per item was hidden in ``data.content``.
- "Warehouse Stores - … must be an EFRIS Warehouse" for a service (non-stock) item.
- URA rejects an invoice without the seller's email; a new Company has none.
- Currency (and UOM) EFRIS codes empty on a new site: fixtures were imported before the custom fields.
"""

import json
from unittest.mock import patch

import frappe

from uganda_compliance.efris.api_classes import efris_api
from uganda_compliance.efris.api_classes.e_goods_services import upload_item_to_efris
from uganda_compliance.efris.api_classes.e_invoice import Sales_invoice_is_efris_validation
from uganda_compliance.efris.api_classes.encryption_utils import encrypt_aes_ecb
from uganda_compliance.efris.tests.efris_test_utils import (
	TEST_ITEM,
	TEST_SELLER_EMAIL,
	fake_ura,
	make_pos_invoice,
	run_queued,
)
from uganda_compliance.efris.tests.test_connection_modes import (
	AES_KEY,
	fake_http,
	no_private_key,
	online_crypto,
	plain_reply,
	set_mode,
)
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase

ITEM_REJECTED = [
	{"goodsCode": "TEST-SERVICE-01", "returnCode": "2122", "returnMessage": "currency:cannot be empty!"}
]


class TestPartialFailureShowsTheReason(EfrisTestCase):
	def test_t130_partial_failure_shows_item_reason_offline(self):
		set_mode(self.company, "Offline Enabler")
		with fake_http() as http, no_private_key():
			http.replies["T130"] = [plain_reply(ITEM_REJECTED, code="45", message="Partial failure!")]
			with self.assertRaisesRegex(
				frappe.ValidationError, r"Partial failure! TEST-SERVICE-01: currency:cannot be empty!"
			):
				upload_item_to_efris(frappe.get_doc("Item", TEST_ITEM), self.company, [{}])

	def test_t130_partial_failure_shows_item_reason_online(self):
		set_mode(self.company, "Online (URA)")
		reply = {
			"data": {
				"content": encrypt_aes_ecb(json.dumps(ITEM_REJECTED), AES_KEY),
				"dataDescription": {"codeType": "1", "encryptCode": "2", "zipCode": "0"},
			},
			"returnStateInfo": {"returnCode": "45", "returnMessage": "Partial failure!"},
		}
		with (
			fake_http() as http,
			online_crypto(),
			patch.object(efris_api, "log_request_to_efris") as log,
		):
			http.replies["T130"] = [reply]
			ok, response = efris_api.make_post("T130", [{}], self.company)
		self.assertFalse(ok)
		self.assertEqual(response, "Partial failure! TEST-SERVICE-01: currency:cannot be empty!")
		self.assertEqual(response.return_code, "45")
		# the E Invoice Request Log row shows the reason too
		self.assertEqual(log.call_args.kwargs["error_message"], response)

	def test_unreadable_content_keeps_uras_message(self):
		set_mode(self.company, "Offline Enabler")
		reply = plain_reply(code="45", message="Partial failure!")
		reply["data"]["content"] = "not base64 json"
		with fake_http() as http, no_private_key():
			http.replies["T130"] = [reply]
			ok, response = efris_api.make_post("T130", [{}], self.company)
		self.assertFalse(ok)
		self.assertEqual(response, "Partial failure!")


class TestServiceRowNeedsNoEfrisWarehouse(EfrisTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.plain_warehouse = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "EFRIS Test Plain Stores",
					"company": cls.company,
					"efris_warehouse": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def tearDown(self):
		frappe.db.set_value("Item", TEST_ITEM, "is_stock_item", 0, update_modified=False)

	def save_from(self, warehouse):
		inv = make_pos_invoice(self.ctx, submit=False)
		inv.set_warehouse = warehouse
		inv.items[0].warehouse = warehouse
		inv.save(ignore_permissions=True)
		return inv

	def test_service_row_with_default_warehouse_needs_no_efris_warehouse(self):
		self.assertFalse(frappe.db.get_value("Item", TEST_ITEM, "is_stock_item"))
		inv = self.save_from(self.plain_warehouse)
		self.assertEqual(inv.efris_invoice, 1)

	def test_sales_invoice_service_row_with_default_warehouse_saves(self):
		# James's invoice: Sales Invoice, no header warehouse, ERPNext's default "Stores" on the row
		doc = frappe._dict(
			doctype="Sales Invoice",
			company=self.company,
			customer=frappe.db.get_value("Customer", {}, "name"),
			efris_invoice=1,
			set_warehouse=None,
			items=[frappe._dict(item_code=TEST_ITEM, warehouse=self.plain_warehouse)],
			flags=frappe._dict(),
		)
		Sales_invoice_is_efris_validation(doc, "before_save")
		self.assertEqual(doc.efris_seller_email, TEST_SELLER_EMAIL)

	def test_stock_row_from_plain_warehouse_is_still_refused(self):
		frappe.db.set_value("Item", TEST_ITEM, "is_stock_item", 1, update_modified=False)
		with self.assertRaisesRegex(frappe.ValidationError, "must be an EFRIS Warehouse"):
			self.save_from(self.plain_warehouse)


class TestSellerEmail(EfrisTestCase):
	def tearDown(self):
		frappe.db.set_value("Company", self.company, "email", TEST_SELLER_EMAIL)

	def test_invoice_without_company_email_is_stopped_before_ura(self):
		frappe.db.set_value("Company", self.company, "email", None)
		with fake_ura() as ura:
			with self.assertRaisesRegex(frappe.ValidationError, "Set an Email on Company"):
				make_pos_invoice(self.ctx)
		self.assertEqual(ura.calls, [])

	def test_seller_email_comes_from_company_and_reaches_ura(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			self.assertEqual(inv.efris_seller_email, TEST_SELLER_EMAIL)
			run_queued(ura, only=inv)
		seller = ura.calls_for("T109")[0]["content"]["sellerDetails"]
		self.assertEqual(seller["emailAddress"], TEST_SELLER_EMAIL)

	def test_retry_of_invoice_saved_without_email_sends_company_email(self):
		# submitted before this fix (or before Company ▸ Email was set): the field is empty
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			inv.db_set("efris_seller_email", None, update_modified=False)
			run_queued(ura, only=inv)
		seller = ura.calls_for("T109")[0]["content"]["sellerDetails"]
		self.assertEqual(seller["emailAddress"], TEST_SELLER_EMAIL)


class TestEfrisCodesOnNewSite(EfrisTestCase):
	def test_customizations_sync_before_fixtures_on_install(self):
		# Frappe calls after_install before sync_fixtures, so the code fields exist in time
		self.assertIn("uganda_compliance.install.after_install", frappe.get_hooks("after_install"))

	def test_currency_codes_missing_on_new_site_are_backfilled(self):
		from uganda_compliance.install import backfill_efris_codes

		frappe.db.set_value("Currency", "UGX", "efris_currency_code", None, update_modified=False)
		frappe.db.set_value("Currency", "USD", "efris_currency_code", "999", update_modified=False)
		backfill_efris_codes()
		self.assertEqual(frappe.db.get_value("Currency", "UGX", "efris_currency_code"), "101")
		# a code the site already has is never overwritten
		self.assertEqual(frappe.db.get_value("Currency", "USD", "efris_currency_code"), "999")


class TestSellerPhone(EfrisTestCase):
	def tearDown(self):
		frappe.db.set_value("Company", self.company, "phone_no", None)

	def test_seller_phone_comes_from_company_when_it_has_no_address(self):
		frappe.db.set_value("Company", self.company, "phone_no", "+256700000001")
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx, company_address=None)
			run_queued(ura, only=inv)
		seller = ura.calls_for("T109")[0]["content"]["sellerDetails"]
		self.assertEqual(seller["mobilePhone"], "+256700000001")
