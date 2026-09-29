import frappe
from frappe import _

from uganda_compliance.efris.api_classes.e_stock import query_efris_goods


def execute(filters=None):
	filters = frappe._dict(filters or {})
	company = filters.get("company")
	if not company:
		row = frappe.get_all("E Invoicing Settings", filters={"enabled": 1}, fields=["company"], limit=1)
		company = row[0].company if row else None
	if not company:
		frappe.throw(_("Select a company with E Invoicing Settings."))

	columns = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 260},
		{"label": _("EFRIS Goods Code"), "fieldname": "goods_code", "fieldtype": "Data", "width": 220},
		{"label": _("ERPNext Qty (EFRIS warehouses)"), "fieldname": "erpnext_qty", "fieldtype": "Float", "width": 180},
		{"label": _("EFRIS Stock"), "fieldname": "efris_stock", "fieldtype": "Float", "width": 120},
		{"label": _("Difference"), "fieldname": "difference", "fieldtype": "Float", "width": 110},
		{"label": _("UOM (EFRIS)"), "fieldname": "measure_unit", "fieldtype": "Data", "width": 90},
		{"label": _("URA Tax Rate"), "fieldname": "tax_rate", "fieldtype": "Data", "width": 90},
		{"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 110},
		{"label": _("EFRIS Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
	]

	warehouses = frappe.get_all("Warehouse", filters={"company": company, "efris_warehouse": 1}, pluck="name")
	items = frappe.get_all(
		"Item", filters={"efris_item": 1, "efris_e_company": company},
		fields=["name", "efris_product_code"],
	)
	efris = {}
	for rec in query_efris_goods(company):
		efris[rec.get("goodsCode")] = rec

	data = []
	for it in items:
		goods_code = it.efris_product_code or it.name
		qty = 0.0
		if warehouses:
			qty = sum(frappe.get_all(
				"Bin", filters={"item_code": it.name, "warehouse": ["in", warehouses]}, pluck="actual_qty",
			) or [])
		rec = efris.get(goods_code, {})
		efris_stock = float(rec.get("stock") or 0) if rec else None
		data.append({
			"item_code": it.name,
			"goods_code": goods_code,
			"erpnext_qty": qty,
			"efris_stock": efris_stock,
			"difference": (qty - efris_stock) if efris_stock is not None else None,
			"measure_unit": rec.get("measureUnit"),
			"tax_rate": rec.get("taxRate"),
			"category": rec.get("commodityCategoryCode"),
			"status": {"101": "enabled", "102": "disabled"}.get(rec.get("statusCode"), rec.get("statusCode") or "not in EFRIS"),
		})
	return columns, data
