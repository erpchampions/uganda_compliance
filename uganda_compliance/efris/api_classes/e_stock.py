import frappe
from frappe import _

from uganda_compliance.efris.api_classes.efris_api import make_post


def query_efris_goods(company, goods_code="", page_size=99, max_pages=50):
	"""URA's goods register for this taxpayer (T127, paged): one record per
	registered goods with its current EFRIS stock, tax rate and category.
	Read-only. Optionally filtered by goodsCode."""
	records, page = [], 1
	settings = frappe.db.get_value("E Invoicing Settings", {"company": company}, "name")
	while True:
		content = {
			"goodsCode": goods_code or "",
			"goodsName": "",
			"commodityCategoryName": "",
			"pageNo": str(page),
			"pageSize": str(page_size),
			"branchId": "",
		}
		status, response = make_post(
			interfaceCode="T127", content=content, company_name=company,
			reference_doc_type="E Invoicing Settings", reference_document=settings,
		)
		if not status:
			frappe.throw(_("EFRIS T127 failed: {0}").format(response))
		batch = response.get("records", []) or []
		records.extend(batch)
		page_count = int(response.get("page", {}).get("pageCount") or 0)
		if not batch or page >= page_count or page >= max_pages:
			break
		page += 1
	return records


@frappe.whitelist()
def query_efris_stock(company=None, item_code=None):
	"""Stock URA holds for our goods, keyed by goods code (JSON-safe)."""
	if not company:
		row = frappe.get_all("E Invoicing Settings", filters={"enabled": 1}, fields=["company"], limit=1)
		if not row:
			frappe.throw(_("No enabled E Invoicing Settings found."))
		company = row[0].company
	goods_code = ""
	if item_code:
		goods_code = frappe.db.get_value("Item", item_code, "efris_product_code") or item_code
	out = {}
	for rec in query_efris_goods(company, goods_code):
		out[rec.get("goodsCode")] = {
			"id": rec.get("id"),
			"goodsName": rec.get("goodsName"),
			"stock": rec.get("stock"),
			"stockPrewarning": rec.get("stockPrewarning"),
			"measureUnit": rec.get("measureUnit"),
			"unitPrice": rec.get("unitPrice"),
			"commodityCategoryCode": rec.get("commodityCategoryCode"),
			"taxRate": rec.get("taxRate"),
			"isZeroRate": rec.get("isZeroRate"),
			"isExempt": rec.get("isExempt"),
			"statusCode": rec.get("statusCode"),
		}
	return out
