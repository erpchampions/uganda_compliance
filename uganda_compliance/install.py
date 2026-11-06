import json

import frappe
from frappe.modules.utils import sync_customizations

# fixtures whose EFRIS codes live in this app's custom fields: (doctype, field, fixture file)
EFRIS_CODE_FIXTURES = (
	("Currency", "efris_currency_code", "currency.json"),
	("UOM", "efris_uom_code", "uom.json"),
)


def after_install():
	"""Frappe syncs an app's fixtures before its customizations (installer.install_app), so on a
	new site the Currency/UOM fixtures were imported before efris_currency_code / efris_uom_code
	existed and their EFRIS codes were dropped. Create the custom fields first."""
	sync_customizations("uganda_compliance")


def backfill_efris_codes():
	"""Fill EFRIS currency/UOM codes the fixtures ship, only where a site has none."""
	for doctype, field, filename in EFRIS_CODE_FIXTURES:
		path = frappe.get_app_path("uganda_compliance", "fixtures", filename)
		with open(path) as f:
			rows = json.load(f)
		for row in rows:
			code = row.get(field)
			if (
				code
				and frappe.db.exists(doctype, row["name"])
				and not frappe.db.get_value(doctype, row["name"], field)
			):
				frappe.db.set_value(doctype, row["name"], field, code, update_modified=False)
