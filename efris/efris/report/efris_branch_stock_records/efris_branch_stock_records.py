"""EFRIS Branch Stock Records — Script Report wrapping T147.

T147 is scoped to the current branch (unlike T145, which is global). Only
``pageNo`` and ``pageSize`` are required by URA; everything else is a
free-form filter.
"""

from __future__ import annotations

import frappe
from frappe import _

from efris.efris.api.client import efris_errors
from efris.efris.api.interfaces import query_branch_stock_records


COLUMNS = [
	{"label": _("Stock-In Date"), "fieldname": "stockInDate", "fieldtype": "Data", "width": 110},
	{"label": _("Branch"), "fieldname": "branchName", "fieldtype": "Data", "width": 200},
	{"label": _("Branch ID"), "fieldname": "branchId", "fieldtype": "Data", "width": 150},
	{"label": _("Supplier TIN"), "fieldname": "supplierTin", "fieldtype": "Data", "width": 110},
	{"label": _("Supplier Name"), "fieldname": "supplierName", "fieldtype": "Data", "width": 200},
	{"label": _("Stock-In Type"), "fieldname": "stockInType", "fieldtype": "Data", "width": 90},
	{"label": _("Invoice No"), "fieldname": "invoiceNo", "fieldtype": "Data", "width": 130},
	{"label": _("Reference No"), "fieldname": "referenceNo", "fieldtype": "Data", "width": 150},
	{"label": _("Record ID"), "fieldname": "id", "fieldtype": "Data", "width": 150},
	{"label": _("Batch No"), "fieldname": "productionBatchNo", "fieldtype": "Data", "width": 110},
	{"label": _("Production Date"), "fieldname": "productionDate", "fieldtype": "Data", "width": 110},
	{"label": _("Total Amount"), "fieldname": "totalAmount", "fieldtype": "Float", "width": 110},
	{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Small Text", "width": 200},
]


def execute(filters=None):
	filters = frappe._dict(filters or {})

	with efris_errors(_("EFRIS Branch Stock Records Query Failed")):
		response = query_branch_stock_records(
			combine_keywords=filters.get("combine_keywords") or "",
			stock_in_type=_leading_code(filters.get("stock_in_type")),
			start_date=_date_str(filters.get("start_date")),
			end_date=_date_str(filters.get("end_date")),
			supplier_tin=filters.get("supplier_tin") or "",
			supplier_name=filters.get("supplier_name") or "",
			page_no=int(filters.get("page_no") or 1),
			page_size=int(filters.get("page_size") or 10),
			company=filters.get("company") or None,
		)

	records = _extract_records(response)
	page_info = (response or {}).get("page") if isinstance(response, dict) else None

	message = None
	if page_info:
		message = _(
			"Page {0} of {1} — {2} records on this page, {3} in total."
		).format(
			page_info.get("pageNo") or filters.get("page_no") or 1,
			page_info.get("pageCount") or "?",
			len(records),
			page_info.get("totalSize") or "?",
		)

	return COLUMNS, records, message


def _extract_records(response) -> list[dict]:
	if isinstance(response, list):
		return [r for r in response if isinstance(r, dict)]
	if isinstance(response, dict):
		records = response.get("records")
		if isinstance(records, list):
			return [r for r in records if isinstance(r, dict)]
		if "stockInDate" in response or "invoiceNo" in response:
			return [response]
	return []


def _leading_code(value) -> str:
	"""``101 - Import`` → ``101``; pass through plain codes."""
	if not value:
		return ""
	return str(value).strip().split(" ", 1)[0]


def _date_str(value) -> str:
	"""Normalise a filter date to ``YYYY-MM-DD`` (URA's required format)."""
	if not value:
		return ""
	try:
		from frappe.utils import getdate

		return getdate(value).strftime("%Y-%m-%d")
	except Exception:
		return str(value)
