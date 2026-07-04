"""EFRIS Credit Note Applications — Script Report wrapping T111.

Lists credit-note / cancel-debit-note applications submitted to URA with their
approval status. ``pageNo``/``pageSize``/``queryType`` are required; all other
URA filters are optional.
"""

from __future__ import annotations

import frappe
from frappe import _

from efris.efris.api.client import efris_errors
from efris.efris.api.interfaces import query_credit_note_applications


APPROVE_STATUS = {
	"101": _("Approved"),
	"102": _("Submitted"),
	"103": _("Rejected"),
	"104": _("Voided"),
}

APPLY_CATEGORY = {
	"101": _("Credit Note"),
	"102": _("Debit Note"),
	"103": _("Cancel of Debit Note"),
	"104": _("Cancel of Credit Note"),
}

DATA_SOURCE = {
	"101": "EFD",
	"102": "Windows Client",
	"103": "WebService API",
	"104": "MIS",
	"105": "Webportal",
	"106": "Offline Mode",
	"107": "USSD",
	"108": "ASK URA",
}


COLUMNS = [
	{"label": _("Application Time"), "fieldname": "applicationTime", "fieldtype": "Data", "width": 140},
	{"label": _("Reference No"), "fieldname": "referenceNo", "fieldtype": "Data", "width": 150},
	{"label": _("Invoice No"), "fieldname": "invoiceNo", "fieldtype": "Data", "width": 140},
	{"label": _("Original Invoice"), "fieldname": "oriInvoiceNo", "fieldtype": "Data", "width": 140},
	{"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 150},
	{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	{"label": _("Gross Amount"), "fieldname": "grossAmount", "fieldtype": "Float", "width": 110},
	{"label": _("Original Gross"), "fieldname": "oriGrossAmount", "fieldtype": "Float", "width": 110},
	{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
	{"label": _("Buyer TIN"), "fieldname": "buyerTin", "fieldtype": "Data", "width": 110},
	{"label": _("Buyer Name"), "fieldname": "buyerBusinessName", "fieldtype": "Data", "width": 200},
	{"label": _("Waiting (days)"), "fieldname": "waitingDate", "fieldtype": "Data", "width": 100},
	{"label": _("Source"), "fieldname": "source", "fieldtype": "Data", "width": 120},
	{"label": _("Application ID"), "fieldname": "id", "fieldtype": "Data", "width": 150},
]


def execute(filters=None):
	filters = frappe._dict(filters or {})

	with efris_errors(_("EFRIS Credit Note Applications Query Failed")):
		response = query_credit_note_applications(
			reference_no=filters.get("reference_no") or "",
			ori_invoice_no=filters.get("ori_invoice_no") or "",
			invoice_no=filters.get("invoice_no") or "",
			combine_keywords=filters.get("combine_keywords") or "",
			approve_status=_leading_code(filters.get("approve_status")),
			query_type=_leading_code(filters.get("query_type")) or "1",
			invoice_apply_category_code=_leading_code(filters.get("invoice_apply_category_code")),
			start_date=_date_str(filters.get("start_date")),
			end_date=_date_str(filters.get("end_date")),
			page_no=int(filters.get("page_no") or 1),
			page_size=int(filters.get("page_size") or 10),
			credit_note_type=_leading_code(filters.get("credit_note_type")) or "1",
			company=filters.get("company") or None,
		)

	records = _extract_records(response)
	rows = [_decode(rec) for rec in records]
	page_info = (response or {}).get("page") if isinstance(response, dict) else None

	message = None
	if page_info:
		message = _(
			"Page {0} of {1} — {2} records on this page, {3} in total."
		).format(
			page_info.get("pageNo") or filters.get("page_no") or 1,
			page_info.get("pageCount") or "?",
			len(rows),
			page_info.get("totalSize") or "?",
		)

	return COLUMNS, rows, message


def _decode(rec: dict) -> dict:
	out = dict(rec)
	out["status"] = APPROVE_STATUS.get(str(rec.get("approveStatus") or ""), rec.get("approveStatus") or "")
	out["category"] = APPLY_CATEGORY.get(
		str(rec.get("invoiceApplyCategoryCode") or ""),
		rec.get("invoiceApplyCategoryCode") or "",
	)
	out["source"] = DATA_SOURCE.get(str(rec.get("dataSource") or ""), rec.get("dataSource") or "")
	return out


def _extract_records(response) -> list[dict]:
	if isinstance(response, list):
		return [r for r in response if isinstance(r, dict)]
	if isinstance(response, dict):
		records = response.get("records")
		if isinstance(records, list):
			return [r for r in records if isinstance(r, dict)]
	return []


def _leading_code(value) -> str:
	"""``101 - Approved`` → ``101``; pass through plain codes / CSVs."""
	if not value:
		return ""
	return str(value).strip().split(" ", 1)[0]


def _date_str(value) -> str:
	if not value:
		return ""
	try:
		from frappe.utils import getdate

		return getdate(value).strftime("%Y-%m-%d")
	except Exception:
		return str(value)
