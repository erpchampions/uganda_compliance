"""EFRIS Goods Inquiry — Script Report wrapping T144.

Items filter is restricted to EFRIS-uploaded items (``efris_uploaded = 1``).
The TIN is resolved from EFRIS Settings of the selected Company.
"""

from __future__ import annotations

import frappe
from frappe import _

from efris.efris.api.client import efris_errors
from efris.efris.api.interfaces import inquire_goods_by_codes


COLUMNS = [
	{"label": _("Goods Code"), "fieldname": "goodsCode", "fieldtype": "Data", "width": 130},
	{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 180},
	{"label": _("Measure Unit"), "fieldname": "measureUnit", "fieldtype": "Data", "width": 100},
	{"label": _("Has Piece Unit"), "fieldname": "havePieceUnit", "fieldtype": "Data", "width": 110},
	{"label": _("Piece Measure Unit"), "fieldname": "pieceMeasureUnit", "fieldtype": "Data", "width": 130},
	{"label": _("Has Other Unit"), "fieldname": "haveOtherUnit", "fieldtype": "Data", "width": 110},
	{"label": _("Package Scaled"), "fieldname": "packageScaledValue", "fieldtype": "Float", "width": 110},
	{"label": _("Piece Scaled"), "fieldname": "pieceScaledValue", "fieldtype": "Float", "width": 110},
	{"label": _("Other Units"), "fieldname": "otherUnits", "fieldtype": "Small Text", "width": 240},
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	items = _resolve_items(filters.get("items"))
	if not items:
		return COLUMNS, [], _(
			"Select one or more EFRIS-uploaded items to query."
		)

	tin = _resolve_tin(filters.get("company"))
	codes = [it["goods_code"] for it in items if it["goods_code"]]
	if not codes:
		return COLUMNS, [], _("Selected items have no EFRIS goods code.")

	with efris_errors(_("EFRIS Goods Inquiry Failed")):
		response = inquire_goods_by_codes(
			goods_codes=codes,
			tin=tin,
			company=filters.get("company") or None,
		)

	records = _extract_records(response)
	by_code = {it["goods_code"]: it["item_code"] for it in items}

	rows: list[dict] = []
	for rec in records:
		other_units = rec.get("goodsOtherUnits") or []
		other_units_text = "; ".join(
			f"{u.get('otherUnit', '')} ×{u.get('otherScaled', '')} pkg={u.get('packageScaled', '')}"
			for u in other_units if isinstance(u, dict)
		)
		rows.append({
			"goodsCode": rec.get("goodsCode") or "",
			"item_code": by_code.get(rec.get("goodsCode") or ""),
			"measureUnit": rec.get("measureUnit") or "",
			"havePieceUnit": rec.get("havePieceUnit") or "",
			"pieceMeasureUnit": rec.get("pieceMeasureUnit") or "",
			"haveOtherUnit": rec.get("haveOtherUnit") or "",
			"packageScaledValue": rec.get("packageScaledValue") or 0,
			"pieceScaledValue": rec.get("pieceScaledValue") or 0,
			"otherUnits": other_units_text,
		})

	return COLUMNS, rows


def _resolve_items(items_filter) -> list[dict]:
	"""Return ``[{item_code, goods_code}]`` for the picked Items."""
	if not items_filter:
		return []
	if isinstance(items_filter, str):
		names = [s.strip() for s in items_filter.split(",") if s.strip()]
	else:
		names = [str(n).strip() for n in items_filter if str(n).strip()]
	if not names:
		return []

	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", names], "efris_uploaded": 1},
		fields=["name", "item_code", "efris_goods_code"],
	)
	return [
		{
			"item_code": r["item_code"],
			"goods_code": r["efris_goods_code"] or r["item_code"],
		}
		for r in rows
	]


def _resolve_tin(company: str | None) -> str:
	"""TIN from EFRIS Settings for the selected company, else from any enabled settings."""
	if company and frappe.db.exists("EFRIS Settings", company):
		return frappe.db.get_value("EFRIS Settings", company, "tin") or ""
	# Fallback: pick the first enabled record.
	row = frappe.db.get_value("EFRIS Settings", {"enabled": 1}, "tin")
	return row or ""


def _extract_records(response) -> list[dict]:
	if isinstance(response, list):
		return [r for r in response if isinstance(r, dict)]
	if isinstance(response, dict):
		for key in ("records", "goods", "goodsList", "data"):
			val = response.get(key)
			if isinstance(val, list):
				return [r for r in val if isinstance(r, dict)]
		if "goodsCode" in response:
			return [response]
	return []
