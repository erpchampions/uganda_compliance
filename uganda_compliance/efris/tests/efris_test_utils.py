"""Shared fixtures for EFRIS tests: fictional Ugandan retailer data + a fake URA."""

import json
from contextlib import contextmanager, nullcontext
from unittest.mock import patch

import frappe
from frappe.utils import flt, now_datetime

TEST_TIN = "1000000001"
TEST_DEVICE = "1000000001_01"
TEST_CUSTOMER = "Nakato Walk-in (EFRIS Test)"
TEST_ITEM = "EFRIS-TEST-SUGAR-1KG"
TEST_UOM = "Nos"
TEST_COMMODITY = None  # picked from the EFRIS Commodity Code fixture


def get_company():
	return (
		frappe.db.get_single_value("Global Defaults", "default_company")
		or frappe.get_all("Company", pluck="name")[0]
	)


def _abbr(company):
	return frappe.get_cached_value("Company", company, "abbr")


def ensure_vat_account(company):
	name = frappe.db.get_value("Account", {"company": company, "account_name": "EFRIS Output VAT"})
	if name:
		return name
	parent = frappe.db.get_value(
		"Account", {"company": company, "account_name": "Duties and Taxes", "is_group": 1}
	) or frappe.db.get_value("Account", {"company": company, "root_type": "Liability", "is_group": 1}, "name")
	acc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": "EFRIS Output VAT",
			"company": company,
			"parent_account": parent,
			"account_type": "Tax",
			"root_type": "Liability",
		}
	).insert(ignore_permissions=True)
	return acc.name


def ensure_item_group():
	name = "EFRIS Test Goods"
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": name, "parent_item_group": "All Item Groups"}
		).insert(ignore_permissions=True)
	return name


def ensure_settings(company, max_attempts=3):
	vat = ensure_vat_account(company)
	name = frappe.db.get_value("E Invoicing Settings", {"company": company})
	s = frappe.get_doc("E Invoicing Settings", name) if name else frappe.new_doc("E Invoicing Settings")
	s.update(
		{
			"company": company,
			"enabled": 1,
			"sandbox_mode": 1,
			"tin": TEST_TIN,
			"device_no": TEST_DEVICE,
			"auto_send_submitted_invoice": 1,
			"sales_invoice_submission": "Background",
			"efris_max_attempts": max_attempts,
			"output_vat_account": vat,
		}
	)
	s.flags.ignore_mandatory = True
	s.save(ignore_permissions=True)
	return s


def ensure_masters(company):
	global TEST_COMMODITY
	abbr = _abbr(company)
	frappe.db.set_value("Company", company, "tax_id", TEST_TIN)
	frappe.db.set_value("UOM", TEST_UOM, "efris_uom_code", "101")

	TEST_COMMODITY = frappe.get_all("EFRIS Commodity Code", pluck="name", limit=1, order_by="name")[0]

	warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
	frappe.db.set_value("Warehouse", warehouse, "efris_warehouse", 1)

	if not frappe.db.exists("Customer", TEST_CUSTOMER):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": TEST_CUSTOMER,
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				"efris_customer_type": "B2C",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("Customer", TEST_CUSTOMER, "efris_customer_type", "B2C")

	# created by E Invoicing Settings.create_item_tax_templates for this company
	item_tax_template = frappe.db.sql(
		"""select itt.name from `tabItem Tax Template` itt
		join `tabItem Tax Template Detail` d on d.parent = itt.name and d.idx = 1
		where itt.company = %s and d.efris_e_tax_category like '01:%%'
		order by itt.creation limit 1""",
		company,
	)[0][0]
	if not frappe.db.exists("Item", TEST_ITEM):
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": TEST_ITEM,
				"item_name": "Kakira Sugar 1kg",
				"item_group": ensure_item_group(),
				"stock_uom": TEST_UOM,
				"is_stock_item": 0,
				"include_item_in_manufacturing": 0,
			}
		)
		item.flags.ignore_mandatory = True
		item.insert(ignore_permissions=True)
	item = frappe.get_doc("Item", TEST_ITEM)
	# EFRIS master data, set directly (item registration with URA is out of scope here)
	frappe.db.set_value(
		"Item",
		TEST_ITEM,
		{
			"efris_item": 1,
			"efris_commodity_code": TEST_COMMODITY,
			"efris_product_code": TEST_ITEM,
		},
		update_modified=False,
	)
	frappe.db.delete("Item Tax", {"parent": TEST_ITEM, "parenttype": "Item"})
	frappe.get_doc(
		{
			"doctype": "Item Tax",
			"parent": TEST_ITEM,
			"parenttype": "Item",
			"parentfield": "taxes",
			"item_tax_template": item_tax_template,
			"idx": 1,
		}
	).db_insert()

	cash_account = frappe.get_cached_value("Company", company, "default_cash_account") or frappe.db.get_value(
		"Account", {"company": company, "account_type": "Cash", "is_group": 0}
	)
	frappe.db.set_value("Mode of Payment", "Cash", "efris_payment_mode", "102:Cash")
	mop = frappe.get_doc("Mode of Payment", "Cash")
	if not any(a.company == company for a in mop.accounts):
		mop.append("accounts", {"company": company, "default_account": cash_account})
		mop.save(ignore_permissions=True)

	profile_name = "EFRIS Test Till 1"
	if not frappe.db.exists("POS Profile", profile_name):
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": profile_name,
				"__newname": profile_name,
				"company": company,
				"warehouse": warehouse,
				"currency": frappe.get_cached_value("Company", company, "default_currency"),
				"write_off_account": frappe.get_cached_value("Company", company, "write_off_account")
				or frappe.db.get_value(
					"Account", {"company": company, "root_type": "Expense", "is_group": 0}
				),
				"write_off_cost_center": frappe.get_cached_value("Company", company, "cost_center"),
				"payments": [{"mode_of_payment": "Cash", "default": 1}],
				"selling_price_list": "Standard Selling",
				"customer": TEST_CUSTOMER,
				"update_stock": 0,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists(
		"POS Opening Entry", {"pos_profile": profile_name, "status": "Open", "docstatus": 1}
	):
		opening = frappe.get_doc(
			{
				"doctype": "POS Opening Entry",
				"company": company,
				"pos_profile": profile_name,
				"user": "Administrator",
				"period_start_date": now_datetime(),
				"posting_date": frappe.utils.nowdate(),
				"balance_details": [{"mode_of_payment": "Cash", "opening_amount": 0}],
			}
		)
		opening.insert(ignore_permissions=True)
		opening.submit()

	return frappe._dict(
		company=company,
		abbr=abbr,
		warehouse=warehouse,
		pos_profile=profile_name,
		cash_account=cash_account,
		sales_taxes_template=frappe.db.get_value(
			"E Invoicing Settings", {"company": company}, "sales_taxes_and_charges_template"
		),
	)


def make_pos_invoice(ctx, qty=2, rate=5900, submit=True, **kwargs):
	inv = frappe.new_doc("POS Invoice")
	inv.update(
		{
			"company": ctx.company,
			"pos_profile": ctx.pos_profile,
			"customer": TEST_CUSTOMER,
			"is_pos": 1,
			"update_stock": 0,
			"posting_date": frappe.utils.nowdate(),
			"currency": frappe.get_cached_value("Company", ctx.company, "default_currency"),
			"taxes_and_charges": ctx.sales_taxes_template,
		}
	)
	inv.update(kwargs)
	inv.append(
		"items",
		{
			"item_code": TEST_ITEM,
			"qty": qty,
			"rate": rate,
			"uom": TEST_UOM,
			"warehouse": ctx.warehouse,
		},
	)
	inv.set_missing_values()
	# EFRIS VAT template created by E Invoicing Settings (18% included in price)
	inv.taxes_and_charges = ctx.sales_taxes_template
	inv.set("taxes", [])
	inv.set_taxes()
	inv.calculate_taxes_and_totals()
	inv.set("payments", [])
	inv.append(
		"payments", {"mode_of_payment": "Cash", "amount": inv.rounded_total or inv.grand_total, "default": 1}
	)
	inv.efris_invoice = 1
	inv.insert(ignore_permissions=True)
	if submit:
		inv.submit()
	return inv


# ---------------------------------------------------------------------------
# Fake URA
# ---------------------------------------------------------------------------


class FakeURA:
	"""Replacement for efris_api.make_post (the single HTTP entry point).

	Behaviour per interface code can be scripted with ``responses[code] = [...]``;
	each item is either a (status, response) tuple or an Exception to raise.
	"""

	def __init__(self):
		self.calls = []
		self.responses = {}
		self.fdn_counter = 3240000000000
		self.on_call = None  # optional hook run at the start of every call ("during the HTTP call")

	def next_fdn(self):
		self.fdn_counter += 1
		return str(self.fdn_counter)

	def invoice_response(self, fdn=None):
		fdn = fdn or self.next_fdn()
		return {
			"basicInformation": {
				"invoiceNo": fdn,
				"invoiceId": f"ID{fdn}",
				"antifakeCode": f"AF{fdn[-8:]}",
				"issuedDate": now_datetime().strftime("%d/%m/%Y %H:%M:%S"),
				"dataSource": "103",
			},
			"summary": {"qrCode": f"https://efristest.ura.go.ug/efrisws/invoiceValidation?invoiceNo={fdn}"},
			"extend": {"reason": "102:Cancellation of the purchase"},
		}

	def calls_for(self, code):
		return [c for c in self.calls if c["interfaceCode"] == code]

	def __call__(
		self, interfaceCode, content, company_name, reference_doc_type=None, reference_document=None
	):
		self.calls.append(
			{
				"interfaceCode": interfaceCode,
				"content": json.loads(json.dumps(content, default=str)),
				"company": company_name,
				"reference_doc_type": reference_doc_type,
				"reference_document": reference_document,
			}
		)
		if self.on_call:
			self.on_call(interfaceCode)
		scripted = self.responses.get(interfaceCode)
		if scripted:
			result = scripted.pop(0)
			if isinstance(result, Exception):
				raise result
			status, response = result
		else:
			status, response = self.default(interfaceCode, content)

		if status and interfaceCode in ("T109", "T110"):
			# the real make_post logs every successful request (needed by credit notes)
			frappe.get_doc(
				{
					"doctype": "E Invoice Request Log",
					"request_data": frappe.as_json(content),
					"response_data": frappe.as_json(response),
					"request_full": "{}",
					"response_full": "{}",
					"reference_doc_type": reference_doc_type,
					"reference_document": reference_document,
					"status": "Success",
					"interface_code": interfaceCode,
				}
			).insert(ignore_permissions=True)
		return status, response

	def default(self, code, content):
		if code == "T109":
			return True, self.invoice_response()
		if code == "T110":
			return True, {"referenceNo": f"CN{self.next_fdn()}"}
		if code == "T106":
			return True, {"page": {"pageCount": 0}, "records": []}
		if code == "T119":
			return True, {"taxpayer": {"tin": content.get("tin")}}
		return False, f"FakeURA: no default for {code}"


@contextmanager
def fake_ura(real_commit=False):
	"""Fake URA + captured enqueues.

	The worker commits (claim, E Invoice, result). Unless ``real_commit``, commits are no-ops so
	each test class keeps rolling back its data; tests of the commit/lock behaviour pass True.
	"""
	ura = FakeURA()
	enqueued = []

	def fake_enqueue(method, **kwargs):
		enqueued.append(frappe._dict(method=method, **kwargs))

	with (
		patch("uganda_compliance.efris.api_classes.e_invoice.make_post", ura),
		patch("uganda_compliance.efris.api_classes.efris_api.make_post", ura),
		patch("uganda_compliance.efris.efris_queue.frappe.enqueue", fake_enqueue),
		nullcontext() if real_commit else patch.object(frappe.db, "commit", lambda *a, **kw: None),
	):
		ura.enqueued = enqueued
		yield ura


def run_queued(ura, only=None):
	"""Simulate the worker: run every queued EFRIS job once.

	``only`` (a document): run just its job. Sweep tests use it because the sweep also picks up
	invoices committed by other tests (the lock test commits for real).
	"""
	from uganda_compliance.efris.efris_queue import process_efris_submission

	jobs, ura.enqueued[:] = list(ura.enqueued), []
	if only:
		jobs = [j for j in jobs if (j.doctype, j.name) == (only.doctype, only.name)]
	return [process_efris_submission(j.doctype, j.name, manual=j.get("manual", False)) for j in jobs]


def reload(doc):
	return frappe.get_doc(doc.doctype, doc.name)


def approx(a, b):
	return abs(flt(a) - flt(b)) < 0.01
