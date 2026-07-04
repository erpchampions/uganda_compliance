"""T131 Goods Stock Maintain — push ERPNext stock movements to EFRIS.

Hooks into ``Stock Entry``, ``Purchase Receipt`` and ``Purchase Invoice``
(when ``update_stock = 1``) on submit:

  * ``upload_stock_entry`` / ``upload_purchase_receipt`` /
    ``upload_purchase_invoice`` — whitelisted, raise on hard errors.
  * ``auto_upload_on_submit`` — non-blocking ``on_submit`` hook used for all
    three doctypes; dispatches on ``doc.doctype``.

Mapping rules:
  * Purchase Invoice / Purchase Receipt → one T131 stock-in (op 101).
    ``stockInType`` is 101 (Import) when the Supplier's country isn't
    Uganda, else 102 (Local Purchase).
  * Stock Entry Material Receipt → 101 stock-in (stockInType from
    ``efris_stock_in_type``).
  * Stock Entry Material Issue → 102 stock-out (adjustType from
    ``efris_adjust_type``).
  * Stock Entry Manufacture / Repack → two T131 calls: 102 for consumed
    raws and 101 (stockInType=103 Manufacture) for produced items, with
    ``productionBatchNo`` / ``productionDate`` populated.
  * Stock Entry Material Transfer → skipped (cross-branch transfers belong
    on T139, same-branch transfers don't touch EFRIS).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, now_datetime

from efris.efris.api.client import efris_errors
from efris.efris.api.goods import (
	_buying_unit_price,
	_code_from_uom,
	_format_number,
)
from efris.efris.api.interfaces import (
	maintain_stock as call_t131,
	transfer_stock as call_t139,
)


# -- public ------------------------------------------------------------


@frappe.whitelist()
def upload_stock_entry(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Stock Entry", name)
	return _upload(doc, raise_on_error=True)


@frappe.whitelist()
def upload_purchase_receipt(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Purchase Receipt", name)
	return _upload(doc, raise_on_error=True)


@frappe.whitelist()
def upload_purchase_invoice(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Purchase Invoice", name)
	if not doc.get("update_stock"):
		frappe.throw(_("Purchase Invoice does not update stock — nothing to send to EFRIS."))
	return _upload(doc, raise_on_error=True)


def auto_upload_on_submit(doc, _method=None) -> None:
	"""Submit-time hook for Stock Entry / Purchase Receipt / Purchase Invoice."""
	if doc.doctype == "Purchase Invoice" and not doc.get("update_stock"):
		return
	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return
	if doc.get("efris_uploaded"):
		return

	try:
		_upload(doc, raise_on_error=False)
	except Exception as exc:  # defensive — _upload swallows when raise_on_error=False
		_set_state_db(doc, error=cstr(exc))
		frappe.msgprint(
			_("EFRIS upload failed: {0}").format(cstr(exc)),
			alert=True,
			indicator="orange",
		)


# -- core --------------------------------------------------------------


def _upload(doc, raise_on_error: bool) -> dict[str, Any]:
	"""Run all T131 calls required for this document and persist the result."""
	if doc.get("efris_uploaded"):
		msg = _(
			"{0} has already been uploaded to EFRIS on {1}. Clear the EFRIS "
			"Uploaded flag if you need to re-send."
		).format(doc.name, doc.get("efris_last_uploaded_on") or "?")
		if raise_on_error:
			frappe.throw(msg)
		return {"ok": False, "skipped": True, "message": msg}

	payloads = _dispatch_payloads(doc)
	if not payloads:
		_set_state_db(doc, error=_("Nothing to send to EFRIS — no eligible lines."))
		if raise_on_error:
			frappe.throw(_("No eligible items on this document for EFRIS T131."))
		return {"ok": False, "skipped": True, "message": "No eligible lines."}

	combined_states: list[dict[str, Any]] = []
	last_op_type = ""
	for op_type, payload in payloads:
		try:
			response = _send_payload(op_type, payload, doc.name)
			state = _interpret_response(response)
		except Exception as exc:
			_set_state_db(doc, error=cstr(exc))
			if raise_on_error:
				raise
			frappe.msgprint(
				_("EFRIS upload failed: {0}").format(cstr(exc)),
				alert=True,
				indicator="orange",
			)
			return {"ok": False, "message": cstr(exc)}

		combined_states.append(state)
		last_op_type = op_type

		if not state["ok"]:
			_set_state_db(doc, error=state["message"] or "(no message)")
			if raise_on_error:
				frappe.throw(
					_("EFRIS rejected the upload: {0}").format(state["message"] or "(no message)")
				)
			frappe.msgprint(
				_("EFRIS rejected the upload: {0}").format(state["message"]),
				alert=True,
				indicator="orange",
			)
			return state

	_set_state_db(doc, uploaded=1, operation_type=last_op_type, error="")
	if raise_on_error:
		frappe.msgprint(
			_("EFRIS confirmed {0}.").format(doc.name),
			alert=True,
			indicator="green",
		)
	return {"ok": True, "states": combined_states}


def _send_payload(op_type: str, payload: dict[str, Any], reference_no: str) -> Any:
	if op_type == "T139":
		with efris_errors(_("EFRIS Stock Transfer Failed")):
			return call_t139(payload, reference_no=reference_no)
	with efris_errors(_("EFRIS Stock Maintain Failed")):
		return call_t131(payload, reference_no=reference_no)


def _dispatch_payloads(doc) -> list[tuple[str, dict[str, Any]]]:
	"""Build the list of ``(operationType, payload)`` pairs to send for this doc."""
	if doc.doctype in ("Purchase Receipt", "Purchase Invoice"):
		lines = _build_lines(doc.get("items") or [], stock_in=True)
		if not lines:
			return []
		stock_in_type = _resolve_stock_in_type_from_supplier(doc)
		header = _build_stock_in_header(
			doc,
			supplier_tin=frappe.db.get_value("Supplier", doc.supplier, "tax_id") or "",
			supplier_name=doc.supplier_name or doc.supplier or "",
			stock_in_type=stock_in_type,
			invoice_no="",
		)
		return [("101", {"goodsStockIn": header, "goodsStockInItem": lines})]

	if doc.doctype == "Stock Entry":
		return _dispatch_stock_entry(doc)

	return []


def _dispatch_stock_entry(doc) -> list[tuple[str, dict[str, Any]]]:
	"""Stock Entry → one or two T131 payloads depending on the entry type."""
	purpose = (doc.get("stock_entry_type") or doc.get("purpose") or "").strip()

	if purpose == "Material Transfer":
		return _dispatch_material_transfer(doc)

	if purpose == "Material Receipt":
		lines = _build_lines(doc.get("items") or [], stock_in=True)
		if not lines:
			return []
		header = _build_stock_in_header(
			doc,
			supplier_tin="",
			supplier_name="",
			stock_in_type=_split_select_code(doc.get("efris_stock_in_type")) or "104",
			invoice_no="",
		)
		return [("101", {"goodsStockIn": header, "goodsStockInItem": lines})]

	if purpose == "Material Issue":
		lines = _build_lines(doc.get("items") or [], stock_in=False)
		if not lines:
			return []
		header = _build_stock_out_header(doc)
		return [("102", {"goodsStockIn": header, "goodsStockInItem": lines})]

	if purpose in ("Manufacture", "Repack"):
		# Split lines: rows with only s_warehouse are consumed (102),
		# rows with t_warehouse are produced (101 / stockInType=103).
		consumed_rows = [r for r in (doc.get("items") or []) if r.s_warehouse and not r.t_warehouse]
		produced_rows = [r for r in (doc.get("items") or []) if r.t_warehouse]
		out: list[tuple[str, dict[str, Any]]] = []

		consumed_lines = _build_lines(consumed_rows, stock_in=False)
		if consumed_lines:
			header = _build_stock_out_header(doc, default_adjust_type="105")
			out.append(("102", {"goodsStockIn": header, "goodsStockInItem": consumed_lines}))

		produced_lines = _build_lines(produced_rows, stock_in=True)
		if produced_lines:
			production_date = getdate(doc.posting_date).strftime("%Y-%m-%d")
			header = _build_stock_in_header(
				doc,
				supplier_tin="",
				supplier_name="",
				stock_in_type="103",
				invoice_no="",
				production_batch_no=(doc.get("name") or "")[:50],
				production_date=production_date,
			)
			out.append(("101", {"goodsStockIn": header, "goodsStockInItem": produced_lines}))

		return out

	return []


def _dispatch_material_transfer(doc) -> list[tuple[str, dict[str, Any]]]:
	"""Stock Entry Material Transfer → one T139 payload per (src, dst) branch pair.

	Same-branch rows (or rows whose warehouses aren't mapped to an EFRIS
	branch) are skipped — EFRIS only cares about inter-branch transfers.
	"""
	rows = doc.get("items") or []
	if not rows:
		return []

	transfer_type = _split_select_code(doc.get("efris_transfer_type")) or "101"
	remarks = (
		doc.get("efris_transfer_remarks")
		or doc.get("remarks")
		or doc.name
	)
	vehicle_no = (doc.get("efris_vehicle_no") or "")[:200]

	groups: dict[tuple[str, str], list] = {}
	for row in rows:
		src = _warehouse_efris_branch_id(row.get("s_warehouse"))
		dst = _warehouse_efris_branch_id(row.get("t_warehouse"))
		if not src or not dst or src == dst:
			continue
		groups.setdefault((src, dst), []).append(row)

	out: list[tuple[str, dict[str, Any]]] = []
	for (src, dst), grp_rows in groups.items():
		lines = _build_transfer_lines(grp_rows)
		if not lines:
			continue
		payload = {
			"goodsStockTransfer": {
				"sourceBranchId": src,
				"destinationBranchId": dst,
				"transferTypeCode": transfer_type,
				"remarks": remarks[:1024],
				"rollBackIfError": "1",
				"goodsTypeCode": "101",
				"vehicleNo": vehicle_no,
			},
			"goodsStockTransferItem": lines,
		}
		out.append(("T139", payload))
	return out


def _warehouse_efris_branch_id(warehouse: str | None) -> str:
	"""Resolve a Warehouse → EFRIS branch ID via the ``efris_branch`` link."""
	if not warehouse:
		return ""
	branch = frappe.db.get_value("Warehouse", warehouse, "efris_branch")
	if not branch:
		return ""
	return frappe.db.get_value("Branch", branch, "efris_branch_id") or ""


def _build_transfer_lines(rows: list) -> list[dict[str, Any]]:
	"""``goodsStockTransferItem`` rows. Skips lines whose Item isn't on EFRIS yet."""
	lines: list[dict[str, Any]] = []
	for row in rows:
		item_code = row.get("item_code")
		if not item_code:
			continue
		uploaded, goods_code, stock_uom = frappe.db.get_value(
			"Item",
			item_code,
			["efris_uploaded", "efris_goods_code", "stock_uom"],
		) or (None, None, None)
		if not uploaded:
			continue

		goods_code = (goods_code or item_code)[:50]
		measure_unit = _code_from_uom(row.get("uom") or stock_uom)
		qty = flt(row.get("stock_qty") or row.get("qty") or 0)
		if qty <= 0:
			continue

		lines.append({
			"goodsCode": goods_code,
			"measureUnit": measure_unit,
			"quantity": _format_number(qty),
			"remarks": (row.get("description") or "")[:1024],
		})
	return lines


# -- header builders ---------------------------------------------------


def _build_stock_in_header(
	doc,
	supplier_tin: str,
	supplier_name: str,
	stock_in_type: str,
	invoice_no: str,
	production_batch_no: str = "",
	production_date: str = "",
) -> dict[str, Any]:
	settings = _settings_for(doc)
	# URA: op=101 requires supplierName, except when stockInType=103
	# (Manufacture) where it must be empty. For stock-in entries with no
	# Supplier (Opening Stock, Import without a counterparty, etc.) fall
	# back to the taxpayer's own legal name.
	if stock_in_type == "103":
		supplier_name = ""
		supplier_tin = ""
	elif not supplier_name:
		supplier_name = settings.company_legal_name or settings.company or ""
	header: dict[str, Any] = {
		"operationType": "101",
		"supplierTin": supplier_tin,
		"supplierName": supplier_name[:100],
		"adjustType": "",
		"remarks": (doc.get("remarks") or doc.name)[:1024],
		"stockInDate": getdate(doc.posting_date).strftime("%Y-%m-%d"),
		"stockInType": stock_in_type,
		"productionBatchNo": production_batch_no,
		"productionDate": production_date,
		"branchId": settings.branch_id or "",
		"invoiceNo": (invoice_no or "")[:20],
		"isCheckBatchNo": "0",
		"rollBackIfError": "1",
		"goodsTypeCode": "101",
	}
	return header


def _build_stock_out_header(doc, default_adjust_type: str = "104") -> dict[str, Any]:
	settings = _settings_for(doc)
	adjust_type = (
		_split_select_code(doc.get("efris_adjust_type")) if doc.get("efris_adjust_type") else ""
	) or default_adjust_type
	remarks = (
		doc.get("efris_adjust_remarks")
		or doc.get("remarks")
		or doc.name
	)
	return {
		"operationType": "102",
		"supplierTin": "",
		"supplierName": "",
		"adjustType": adjust_type,
		"remarks": remarks[:1024],
		"stockInDate": getdate(doc.posting_date).strftime("%Y-%m-%d"),
		"stockInType": "",
		"productionBatchNo": "",
		"productionDate": "",
		"branchId": settings.branch_id or "",
		"invoiceNo": "",
		"isCheckBatchNo": "0",
		"rollBackIfError": "1",
		"goodsTypeCode": "101",
	}


# -- line builder ------------------------------------------------------


def _build_lines(rows: list, stock_in: bool) -> list[dict[str, Any]]:
	"""Build ``goodsStockInItem`` entries for the eligible rows.

	Skips rows whose Item has not been uploaded to EFRIS — we cannot stock
	on a goodsCode URA doesn't know about yet.
	"""
	lines: list[dict[str, Any]] = []
	for row in rows:
		item_code = row.get("item_code")
		if not item_code:
			continue
		uploaded, goods_code, stock_uom = frappe.db.get_value(
			"Item",
			item_code,
			["efris_uploaded", "efris_goods_code", "stock_uom"],
		) or (None, None, None)
		if not uploaded:
			continue

		goods_code = (goods_code or item_code)[:50]
		measure_unit = _code_from_uom(row.get("uom") or stock_uom)

		# Quantity in stock-UOM; ERPNext keeps that on `stock_qty`.
		qty = flt(row.get("stock_qty") or row.get("qty") or 0)
		if qty <= 0:
			continue

		unit_price = (
			flt(row.get("rate"))
			or flt(row.get("basic_rate"))
			or flt(row.get("valuation_rate"))
		)
		if unit_price <= 0:
			unit_price = _buying_unit_price_for_item(item_code)

		lines.append({
			"goodsCode": goods_code,
			"measureUnit": measure_unit,
			"quantity": _format_number(qty),
			"unitPrice": _format_number(unit_price),
			"remarks": (row.get("description") or "")[:1024],
		})
	return lines


def _buying_unit_price_for_item(item_code: str) -> float:
	"""Reuse goods.py's buying-price lookup with a minimal stand-in doc."""
	item = frappe.get_cached_doc("Item", item_code)
	return _buying_unit_price(item)


# -- response interpretation ------------------------------------------


def _interpret_response(response: Any) -> dict[str, Any]:
	"""Mirror of the T130 interpreter — URA reuses the per-entry shape."""
	if isinstance(response, list) and not response:
		return {"ok": True, "code": "", "message": ""}

	entry = _first_entry(response)
	if entry is None:
		try:
			raw = frappe.as_json(response, indent=2)
		except Exception:
			raw = repr(response)
		return {
			"ok": False,
			"code": "",
			"message": f"EFRIS returned an unexpected payload:\n{raw[:4000]}",
		}

	code = (entry.get("returnCode") or "").strip()
	if code in ("", "00"):
		return {"ok": True, "code": code, "message": ""}
	return {"ok": False, "code": code, "message": entry.get("returnMessage") or ""}


def _first_entry(response: Any) -> dict | None:
	if isinstance(response, list):
		return response[0] if response and isinstance(response[0], dict) else None
	if isinstance(response, dict):
		if "returnCode" in response or "returnMessage" in response:
			return response
		for value in response.values():
			if isinstance(value, list) and value and isinstance(value[0], dict):
				return value[0]
	return None


# -- persistence -------------------------------------------------------


def _set_state_db(
	doc,
	uploaded: int | None = None,
	operation_type: str | None = None,
	error: str | None = None,
) -> None:
	if uploaded is not None:
		doc.db_set("efris_uploaded", uploaded, update_modified=False)
	if operation_type is not None:
		doc.db_set("efris_operation_type", operation_type, update_modified=False)
	if error is not None:
		doc.db_set("efris_upload_error", error, update_modified=False)
	if uploaded:
		doc.db_set("efris_last_uploaded_on", now_datetime(), update_modified=False)


# -- helpers -----------------------------------------------------------


def _settings_for(doc):
	from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

	return get_efris_settings(doc.get("company"))


def _resolve_stock_in_type_from_supplier(doc) -> str:
	"""101 (Import) when the supplier's country isn't Uganda, else 102 (Local Purchase)."""
	supplier = doc.get("supplier")
	if not supplier:
		return "102"
	country = frappe.db.get_value("Supplier", supplier, "country") or ""
	if country and country.strip().lower() != "uganda":
		return "101"
	return "102"


def _split_select_code(value: str | None) -> str:
	"""Pull the leading ``101`` out of select options like ``101 - Import``.

	For multi-select (comma-separated) values, splits each part and rejoins
	the codes — URA expects ``adjustType='101,102'``.
	"""
	if not value:
		return ""
	parts = [p.strip().split(" ", 1)[0].strip() for p in cstr(value).split(",")]
	return ",".join(p for p in parts if p)
