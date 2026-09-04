# Copyright (c) 2023, Frappe Technologied Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from uganda_compliance.efris.api_classes.efris_api import make_post

# T124 flags -> E Tax Category (names as shipped in the E Tax Category fixture)
TAX_CATEGORY_STANDARD = "01:A: Standard (18%)"
TAX_CATEGORY_ZERO = "02:B: Zero (0%)"
TAX_CATEGORY_EXEMPT = "03:C: Exempt (-)"


class EFRISCommodityCode(Document):
	def before_save(self):
		if self.has_value_changed("e_tax_category") and not frappe.flags.efris_commodity_sync:
			self.mapping_source = "Manual"


def map_e_tax_category(rec):
	"""URA's category record -> our E Tax Category, or None if URA is silent."""
	if rec.get("isZeroRate") == "101" or rec.get("exclusion") in ("0", "3"):
		return TAX_CATEGORY_ZERO
	if rec.get("isExempt") == "101" or rec.get("exclusion") == "1":
		return TAX_CATEGORY_EXEMPT
	if str(rec.get("rate") or "") in ("0.18", "18", "0.180"):
		return TAX_CATEGORY_STANDARD
	return None


def _enabled_company(company=None):
	if company:
		return company
	row = frappe.get_all("E Invoicing Settings", filters={"enabled": 1}, fields=["company"], limit=1)
	if not row:
		frappe.throw(_("No enabled E Invoicing Settings found."))
	return row[0].company


def fetch_commodity_page(company, page_no, page_size=99):
	"""One T124 page. The interface is unencrypted (codeType 0); URA rejects an
	encrypted envelope with "Illegal json format". pageSize must stay below 100."""
	content = {"pageNo": str(page_no), "pageSize": str(page_size)}
	settings = frappe.db.get_value("E Invoicing Settings", {"company": company}, "name")
	status, response = make_post(
		interfaceCode="T124", content=content, company_name=company,
		reference_doc_type="E Invoicing Settings", reference_document=settings, encrypt=False,
	)
	if not status:
		frappe.throw(_("EFRIS T124 failed: {0}").format(response))
	return response


def upsert_from_ura(rec, now):
	"""Create or refresh one EFRIS Commodity Code row from a T124 record.
	A manually chosen tax category (mapping_source "Manual") is kept; every
	other row - synced before, seeded from the spreadsheet, or empty -
	follows URA. Returns (created, updated)."""
	code = str(rec.get("commodityCategoryCode") or "").strip()
	if not code:
		return 0, 0
	values = {
		"commodity_name": rec.get("commodityCategoryName"),
		"efris_rate": rec.get("rate"),
		"is_zero_rate": 1 if rec.get("isZeroRate") == "101" else 0,
		"is_exempt": 1 if rec.get("isExempt") == "101" else 0,
		"exclusion": rec.get("exclusion"),
		"parent_code": rec.get("parentCode"),
		"commodity_category_level": rec.get("commodityCategoryLevel"),
		"enabled_in_efris": 1 if str(rec.get("enableStatusCode")) == "1" else 0,
		"last_synced_from_ura": now,
	}
	category = map_e_tax_category(rec)
	name = frappe.db.exists("EFRIS Commodity Code", code)
	frappe.flags.efris_commodity_sync = True
	try:
		if name:
			doc = frappe.get_doc("EFRIS Commodity Code", name)
			doc.update(values)
			if category and doc.mapping_source != "Manual":
				doc.e_tax_category = category
				doc.mapping_source = "URA"
			doc.save(ignore_permissions=True)
			return 0, 1
		doc = frappe.get_doc({"doctype": "EFRIS Commodity Code", "commodity_code": code, **values})
		if category:
			doc.e_tax_category = category
			doc.mapping_source = "URA"
		doc.insert(ignore_permissions=True)
		return 1, 0
	finally:
		frappe.flags.efris_commodity_sync = False


def sync_commodity_categories(company=None, leaf_only=True, max_pages=None, page_size=99):
	"""Pull URA's commodity categories (T124, paged) into EFRIS Commodity Code."""
	company = _enabled_company(company)
	now = frappe.utils.now()
	page, created, updated, seen = 1, 0, 0, 0
	while True:
		resp = fetch_commodity_page(company, page, page_size)
		records = resp.get("records", []) or []
		for rec in records:
			seen += 1
			if leaf_only and rec.get("isLeafNode") not in ("101", None):
				continue
			c, u = upsert_from_ura(rec, now)
			created += c
			updated += u
		frappe.db.commit()
		page_count = int(resp.get("page", {}).get("pageCount") or 0)
		if not records or page >= page_count or (max_pages and page >= int(max_pages)):
			break
		page += 1
	result = {"pages": page, "records_seen": seen, "created": created, "updated": updated}
	frappe.log_error(message=frappe.as_json(result), title="EFRIS commodity category sync finished")
	return result


@frappe.whitelist()
def fetch_from_ura(company=None, max_pages=None, background=1):
	"""Button on the EFRIS Commodity Code list. URA's full list runs to well over
	a hundred thousand rows, so the pull is queued; a small max_pages runs inline
	(used for testing and for a quick refresh of the first pages)."""
	company = _enabled_company(company)
	if int(background) and not max_pages:
		frappe.enqueue(
			"uganda_compliance.efris.doctype.efris_commodity_code.efris_commodity_code.sync_commodity_categories",
			queue="long", timeout=6 * 60 * 60, company=company,
		)
		return {"queued": True, "company": company}
	return sync_commodity_categories(company=company, max_pages=max_pages)
