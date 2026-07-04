"""EFRIS Goods Stock Records — Script Report wrapping T145.

Only ``pageNo`` and ``pageSize`` are required by URA. The three identifier
filters (``productionBatchNo``, ``invoiceNo``, ``referenceNo``) are optional.
"""

from __future__ import annotations

import frappe
from frappe import _

from efris.efris.api.client import efris_errors
from efris.efris.api.interfaces import query_stock_records


COLUMNS = [
	{"label": _("Stock-In Date"), "fieldname": "stockInDate", "fieldtype": "Data", "width": 110},
	{"label": _("Branch"), "fieldname": "branchName", "fieldtype": "Data", "width": 200},
	{"label": _("Branch ID"), "fieldname": "branchId", "fieldtype": "Data", "width": 150},
	{"label": _("Supplier TIN"), "fieldname": "supplierTin", "fieldtype": "Data", "width": 110},
	{"label": _("Supplier Name"), "fieldname": "supplierName", "fieldtype": "Data", "width": 200},
	{"label": _("Stock-In Type"), "fieldname": "stockInType", "fieldtype": "Data", "width": 90},
	{"label": _("Adjust Type"), "fieldname": "adjustType", "fieldtype": "Data", "width": 90},
	{"label": _("Invoice No"), "fieldname": "invoiceNo", "fieldtype": "Data", "width": 130},
	{"label": _("Reference No"), "fieldname": "referenceNo", "fieldtype": "Data", "width": 150},
	{"label": _("Batch No"), "fieldname": "productionBatchNo", "fieldtype": "Data", "width": 110},
	{"label": _("Production Date"), "fieldname": "productionDate", "fieldtype": "Data", "width": 110},
	{"label": _("Total Amount"), "fieldname": "totalAmount", "fieldtype": "Float", "width": 110},
	{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Small Text", "width": 200},
]


def execute(filters=None):
	filters = frappe._dict(filters or {})

	with efris_errors(_("EFRIS Stock Records Query Failed")):
		response = query_stock_records(
			production_batch_no=filters.get("production_batch_no") or "",
			invoice_no=filters.get("invoice_no") or "",
			reference_no=filters.get("reference_no") or "",
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
