"""EFRIS slide of the ERPNext setup wizard: a new site starts with its EFRIS basics in place."""

import re

import frappe
from frappe import _
from frappe.utils import cint, validate_email_address

from uganda_compliance.efris.api_classes.efris_api import get_server_time
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import (
	OFFLINE_ENABLER,
	ONLINE_URA,
)
from uganda_compliance.tillking import get_missing_credentials

# ERPNext's preset Modes of Payment -> EFRIS Payment Mode (fixture)
PAYMENT_MODES = {
	"Cash": "102:Cash",
	"Credit Card": "106:Visa/Master card",
	"Wire Transfer": "107:EFT",
	"Bank Draft": "104:Demand draft",
}


def get_setup_stages(args=None):
	"""Frappe collects the stages before it runs any of them, so bad input stops here, with
	nothing created yet."""
	args = args or {}
	if not (cint(args.get("efris_setup")) and args.get("company_name")):
		return []
	validate_efris_input(args)
	return [
		{
			"status": _("Setting up EFRIS"),
			"fail_msg": _("Failed to set up EFRIS"),
			"tasks": [{"fn": setup_efris, "args": args, "fail_msg": _("Failed to set up EFRIS")}],
		}
	]


def validate_efris_input(args):
	if not re.fullmatch(r"\d{10}", args.get("efris_tin") or ""):
		frappe.throw(_("EFRIS TIN must be 10 digits"))
	if not seller_email(args):
		frappe.throw(_("EFRIS needs the seller's email"))
	validate_email_address(seller_email(args), throw=True)
	if args.get("efris_connection_mode") == OFFLINE_ENABLER and not (
		args.get("efris_device_no") and args.get("efris_enabler_url")
	):
		frappe.throw(_("Offline Enabler mode needs the Device No and the Enabler URL"))


def seller_email(args):
	return args.get("efris_seller_email") or args.get("email")


def setup_efris(args):
	company = args.get("company_name")
	set_company_details(company, args)
	mark_default_warehouse(company)
	set_payment_modes()
	settings = save_settings(company, args)
	notify_connection_result(settings, args)


def set_company_details(company, args):
	doc = frappe.get_doc("Company", company)
	doc.tax_id = args.get("efris_tin")
	doc.email = seller_email(args)
	doc.phone_no = args.get("efris_seller_phone") or doc.phone_no
	doc.save(ignore_permissions=True)


def mark_default_warehouse(company):
	warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
	if warehouse and frappe.db.get_value("Warehouse", warehouse, "company") == company:
		doc = frappe.get_doc("Warehouse", warehouse)
		doc.efris_warehouse = 1
		doc.save(ignore_permissions=True)


def set_payment_modes():
	"""Only where a mode has no EFRIS code yet."""
	for mode, code in PAYMENT_MODES.items():
		if frappe.db.exists("Mode of Payment", mode) and not frappe.db.get_value(
			"Mode of Payment", mode, "efris_payment_mode"
		):
			frappe.db.set_value("Mode of Payment", mode, "efris_payment_mode", code)


def save_settings(company, args):
	"""The VAT account comes from ERPNext's Uganda tax preset (erpnext country_wise_tax.json)."""
	name = frappe.db.get_value("E Invoicing Settings", {"company": company})
	doc = frappe.get_doc("E Invoicing Settings", name) if name else frappe.new_doc("E Invoicing Settings")
	vat_account = frappe.db.get_value("Account", {"company": company, "account_name": "VAT", "is_group": 0})
	doc.update(
		{
			"company": company,
			"tin": args.get("efris_tin"),
			"device_no": args.get("efris_device_no"),
			"connection_mode": args.get("efris_connection_mode") or ONLINE_URA,
			"enabler_url": args.get("efris_enabler_url"),
			"sandbox_mode": cint(args.get("efris_sandbox")),
			"output_vat_account": vat_account,
			"input_vat_account": vat_account,
		}
	)
	# Online mode still waits for its private key, which is uploaded in the settings form
	doc.enabled = 0 if get_missing_credentials(doc) else 1
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.save()
	return doc


def notify_connection_result(settings, args):
	"""A failed test must not fail the wizard: the enabler or URA may simply be unreachable today."""
	if settings.enabled:
		ok, _response = get_server_time(settings.company)  # the failure itself is in the Error Log
		if ok:
			subject = _("EFRIS connection works ({0}).").format(settings.connection_mode)
		else:
			subject = _("EFRIS could not connect ({0}). Check E Invoicing Settings.").format(
				settings.connection_mode
			)
	else:
		# the connection test refuses to run on disabled settings
		subject = _("EFRIS is not on yet: finish E Invoicing Settings (for Online, upload the private key).")
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"subject": subject,
			"for_user": args.get("email") or frappe.session.user,
			"type": "Alert",
			"document_type": "E Invoicing Settings",
			"document_name": settings.name,
		}
	).insert(ignore_permissions=True)
