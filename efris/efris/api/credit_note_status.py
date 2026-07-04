"""T112 — Credit Note Application status sync.

Exposes ``check_credit_note_status`` (whitelisted), called from the Sales
Invoice form on credit notes to refresh the URA-side approval status.

T112 takes the application ``id`` (URA-internal), not the FDN we stored on
``E-Invoice.efris_invoice_id``. When the id isn't cached yet we resolve it
via T111 using the referenceNo we originally sent (the E-Invoice name).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, now_datetime

from efris.efris.api.client import efris_errors
from efris.efris.api.interfaces import (
	approve_credit_note as call_t113,
)
from efris.efris.api.interfaces import (
	cancel_credit_note_application as call_t114,
)
from efris.efris.api.interfaces import (
	get_credit_note_application_details,
	get_credit_note_details,
	query_credit_note_applications,
)
from efris.efris.api.interfaces import (
	void_credit_note_application as call_t120,
)


APPROVE_STATUS_LABELS = {
	"101": "101 - Approved",
	"102": "102 - Pending",
	"103": "103 - Rejected",
	"104": "104 - Voided",
}


@frappe.whitelist()
def check_credit_note_status(sales_invoice: str) -> dict[str, Any]:
	"""Resolve + refresh the EFRIS credit-note status for a Sales Invoice.

	Returns the T112 response plus ``status_changed`` / ``status_code`` /
	``status_label`` so the JS layer can render details and signal updates.
	"""
	si = frappe.get_doc("Sales Invoice", sales_invoice)
	if not si.get("is_return"):
		frappe.throw(_("This action is only available on credit notes (is_return = 1)."))

	e_invoice_name = si.get("efris_e_invoice")
	if not e_invoice_name:
		frappe.throw(_("Sales Invoice {0} has no linked E-Invoice.").format(sales_invoice))

	e_inv = frappe.get_doc("E-Invoice", e_invoice_name)
	if (e_inv.get("e_invoice_type") or "Invoice") != "Credit Note":
		frappe.throw(_("Linked E-Invoice {0} is not a credit note.").format(e_invoice_name))

	application_id = e_inv.get("application_id") or _resolve_application_id(e_inv)
	if not application_id:
		frappe.throw(
			_("No EFRIS application id found for {0} (referenceNo {1}).").format(
				e_invoice_name, e_inv.reference_no or e_inv.name
			)
		)

	with efris_errors(_("EFRIS Credit Note Status Query Failed")):
		details = get_credit_note_details(application_id, company=e_inv.company)

	if not isinstance(details, dict):
		frappe.throw(_("EFRIS returned an unexpected response shape for T112."))

	_persist_t112_fields(e_inv, details)

	new_code = cstr(details.get("approveStatusCode") or "")
	new_label = APPROVE_STATUS_LABELS.get(new_code, new_code)
	old_label = e_inv.get("credit_note_status") or ""
	changed = bool(new_label) and new_label != old_label

	now = now_datetime()
	e_inv.db_set("application_id", application_id, update_modified=False)
	e_inv.db_set("credit_note_status_checked_on", now, update_modified=False)
	if changed:
		e_inv.db_set("credit_note_status", new_label, update_modified=False)
		frappe.db.set_value(
			"Sales Invoice",
			sales_invoice,
			{
				"efris_credit_note_status": new_label,
				"efris_credit_note_application_id": application_id,
			},
			update_modified=False,
		)
	else:
		# keep application id mirrored even when status unchanged
		frappe.db.set_value(
			"Sales Invoice",
			sales_invoice,
			"efris_credit_note_application_id",
			application_id,
			update_modified=False,
		)

	return {
		"application_id": application_id,
		"status_code": new_code,
		"status_label": new_label,
		"previous_status": old_label,
		"status_changed": changed,
		"details": details,
	}


@frappe.whitelist()
def get_credit_note_application(sales_invoice: str) -> dict[str, Any]:
	"""T118 — fetch line-level details (goods / tax / summary / payway) for a credit note.

	Resolves the EFRIS application id via the linked E-Invoice (or T111 lookup
	if not yet cached), caches it onto the E-Invoice for next time, and
	returns the raw T118 response under ``details`` for the JS layer to render.
	"""
	si = frappe.get_doc("Sales Invoice", sales_invoice)
	if not si.get("is_return"):
		frappe.throw(_("This action is only available on credit notes (is_return = 1)."))

	e_invoice_name = si.get("efris_e_invoice")
	if not e_invoice_name:
		frappe.throw(_("Sales Invoice {0} has no linked E-Invoice.").format(sales_invoice))

	e_inv = frappe.get_doc("E-Invoice", e_invoice_name)
	if (e_inv.get("e_invoice_type") or "Invoice") != "Credit Note":
		frappe.throw(_("Linked E-Invoice {0} is not a credit note.").format(e_invoice_name))

	application_id = e_inv.get("application_id") or _resolve_application_id(e_inv)
	if not application_id:
		frappe.throw(
			_("No EFRIS application id found for {0} (referenceNo {1}).").format(
				e_invoice_name, e_inv.reference_no or e_inv.name
			)
		)

	with efris_errors(_("EFRIS Credit Note Details Query Failed")):
		details = get_credit_note_application_details(application_id, company=e_inv.company)

	if not isinstance(details, dict):
		frappe.throw(_("EFRIS returned an unexpected response shape for T118."))

	if not e_inv.get("application_id"):
		e_inv.db_set("application_id", application_id, update_modified=False)
		frappe.db.set_value(
			"Sales Invoice",
			sales_invoice,
			"efris_credit_note_application_id",
			application_id,
			update_modified=False,
		)

	return {"application_id": application_id, "details": details}


@frappe.whitelist()
def approve_credit_note_application(
	sales_invoice: str, approve_status: str = "101", remark: str = ""
) -> dict[str, Any]:
	"""T113 — approve (101) or reject (103) a credit note application (Sandbox only).

	Sandbox testing helper that lets the seller self-approve their own
	credit-note application. URA blocks this on Production — the approval
	there comes from the buyer-side workflow.

	Resolves the application id + taskId from T112 when not already cached,
	then posts the T113 envelope and refreshes the local status.
	"""
	approve_status = str(approve_status or "").strip() or "101"
	if approve_status not in {"101", "103"}:
		frappe.throw(_("approve_status must be 101 (Approved) or 103 (Rejected)."))
	if not (remark or "").strip():
		frappe.throw(_("A remark is required for T113."))

	si = frappe.get_doc("Sales Invoice", sales_invoice)
	if not si.get("is_return"):
		frappe.throw(_("This action is only available on credit notes (is_return = 1)."))

	e_invoice_name = si.get("efris_e_invoice")
	if not e_invoice_name:
		frappe.throw(_("Sales Invoice {0} has no linked E-Invoice.").format(sales_invoice))

	e_inv = frappe.get_doc("E-Invoice", e_invoice_name)
	if (e_inv.get("e_invoice_type") or "Invoice") != "Credit Note":
		frappe.throw(_("Linked E-Invoice {0} is not a credit note.").format(e_invoice_name))

	settings = _settings_for_company(e_inv.company)
	if (settings.environment or "").lower() != "sandbox":
		frappe.throw(_("T113 self-approval is only allowed in the Sandbox environment."))

	application_id = e_inv.get("application_id") or _resolve_application_id(e_inv)
	if not application_id:
		frappe.throw(
			_("No EFRIS application id found for {0} (referenceNo {1}).").format(
				e_invoice_name, e_inv.reference_no or e_inv.name
			)
		)

	# T113 needs the URA-side taskId. Prefer the cached value (populated by
	# any prior T112 call); otherwise fetch T112 fresh, then fall back to
	# T111 query_type=2 (to-do queue) which lists pending tasks with ids.
	task_id = cstr(e_inv.get("task_id") or "")
	header: dict | None = None
	if not task_id:
		with efris_errors(_("EFRIS Credit Note Header Query Failed")):
			header = get_credit_note_details(application_id, company=e_inv.company)
		_persist_t112_fields(e_inv, header)
		task_id = _pick_task_id(header)
	if not task_id:
		task_id = _resolve_task_id_via_todo(e_inv, application_id)
	if not task_id:
		_log_t112_for_debug(application_id, header, reason="missing taskId")
		current_status = cstr((header or {}).get("approveStatusCode") or "")
		status_label = APPROVE_STATUS_LABELS.get(current_status, current_status)
		hint = ""
		if current_status and current_status != "102":
			hint = _(" Current status is {0} — only Pending (102) applications can be approved.").format(
				status_label or current_status
			)
		frappe.throw(
			_(
				"EFRIS did not return a taskId for this credit note application — there is no pending approval task assigned. Open the EFRIS portal to check the application's workflow state.{0}"
			).format(hint)
		)

	# T113's ``referenceNo`` is the **seller-side referenceNo** we originally
	# sent on T110 (= ``e_inv.reference_no`` / ``e_inv.name``) — *not* the
	# URA-side response referenceNo (which can be > 20 chars and trips error
	# 99) and *not* the application id (which T113 does not index by — sending
	# it returns error 304 "result is null").
	seller_reference_no = cstr(e_inv.reference_no or e_inv.name)
	payload = {
		"referenceNo": seller_reference_no,
		"approveStatus": approve_status,
		"taskId": task_id,
		"remark": (remark or "")[:1024],
	}
	with efris_errors(_("EFRIS Credit Note Approval Failed")):
		call_t113(payload, reference_no=seller_reference_no, company=e_inv.company)

	# Refresh local status from URA after approval.
	new_label = APPROVE_STATUS_LABELS.get(approve_status, approve_status)
	now = now_datetime()
	e_inv.db_set("credit_note_status", new_label, update_modified=False)
	e_inv.db_set("credit_note_status_checked_on", now, update_modified=False)
	frappe.db.set_value(
		"Sales Invoice",
		sales_invoice,
		"efris_credit_note_status",
		new_label,
		update_modified=False,
	)

	return {
		"application_id": application_id,
		"task_id": task_id,
		"reference_no": reference_no,
		"approve_status": approve_status,
		"status_label": new_label,
	}


CANCEL_REASON_CODES = {"101", "102", "103"}


@frappe.whitelist()
def void_credit_note(sales_invoice: str) -> dict[str, Any]:
	"""T120 — void a Credit / Debit Note application.

	Resolves ``businessKey`` (= application id, T111 ``id``) and ``referenceNo``
	(= what we sent on T110, T111 ``referenceNo``) for the credit note linked
	to ``sales_invoice``, then posts T120. Use T120 to void an application
	that's still in workflow (e.g. submitted/pending); use T114 for an
	already-approved credit note.
	"""
	si = frappe.get_doc("Sales Invoice", sales_invoice)
	if not si.get("is_return"):
		frappe.throw(_("This action is only available on credit notes (is_return = 1)."))

	e_invoice_name = si.get("efris_e_invoice")
	if not e_invoice_name:
		frappe.throw(_("Sales Invoice {0} has no linked E-Invoice.").format(sales_invoice))

	e_inv = frappe.get_doc("E-Invoice", e_invoice_name)
	if (e_inv.get("e_invoice_type") or "Invoice") != "Credit Note":
		frappe.throw(_("Linked E-Invoice {0} is not a credit note.").format(e_invoice_name))

	business_key = cstr(e_inv.get("application_id") or _resolve_application_id(e_inv))
	if not business_key:
		frappe.throw(
			_("No EFRIS application id found for {0} — nothing to void.").format(e_invoice_name)
		)

	reference_no = cstr(e_inv.get("reference_no") or e_inv.name)

	with efris_errors(_("EFRIS Credit Note Void Failed")):
		call_t120(
			business_key=business_key,
			reference_no=reference_no,
			company=e_inv.get("company"),
		)

	voided_label = APPROVE_STATUS_LABELS["104"]
	now = now_datetime()
	e_inv.db_set("credit_note_status", voided_label, update_modified=False)
	e_inv.db_set("credit_note_status_checked_on", now, update_modified=False)
	frappe.db.set_value(
		"Sales Invoice",
		sales_invoice,
		"efris_credit_note_status",
		voided_label,
		update_modified=False,
	)

	return {
		"business_key": business_key,
		"reference_no": reference_no,
		"status_label": voided_label,
	}


@frappe.whitelist()
def cancel_credit_note(
	sales_invoice: str,
	reason_code: str = "103",
	reason: str = "",
	invoice_apply_category_code: str = "104",
) -> dict[str, Any]:
	"""T114 — cancel a previously submitted credit-note application.

	``reason_code``: 101 buyer refused / 102 not delivered / 103 other (reason required).
	``invoice_apply_category_code``: 104 cancel-of-credit-note (default), 103 cancel-of-debit-note,
	105 cancel-of-credit-memo.

	Resolves ``oriInvoiceId`` (URA's internal id of the credited invoice — already
	stored on the E-Invoice from T110 prep) and ``invoiceNo`` (the credit-note FDN,
	pulled from T112's ``refundInvoiceNo`` since it's only assigned after URA
	processes the application).
	"""
	reason_code = cstr(reason_code or "").strip() or "103"
	if reason_code not in CANCEL_REASON_CODES:
		frappe.throw(_("reason_code must be 101, 102, or 103."))
	if reason_code == "103" and not (reason or "").strip():
		frappe.throw(_("A reason is required when reason_code = 103."))

	invoice_apply_category_code = cstr(invoice_apply_category_code or "104").strip() or "104"

	si = frappe.get_doc("Sales Invoice", sales_invoice)
	if not si.get("is_return"):
		frappe.throw(_("This action is only available on credit notes (is_return = 1)."))

	e_invoice_name = si.get("efris_e_invoice")
	if not e_invoice_name:
		frappe.throw(_("Sales Invoice {0} has no linked E-Invoice.").format(sales_invoice))

	e_inv = frappe.get_doc("E-Invoice", e_invoice_name)
	if (e_inv.get("e_invoice_type") or "Invoice") != "Credit Note":
		frappe.throw(_("Linked E-Invoice {0} is not a credit note.").format(e_invoice_name))

	ori_invoice_id = cstr(e_inv.original_invoice_id or "")
	if not ori_invoice_id:
		frappe.throw(_("E-Invoice {0} is missing original_invoice_id.").format(e_invoice_name))

	# T114 needs the credit-note FDN — URA's *issued invoice number* for the
	# credit note, not the application referenceNo. Resolution order:
	#   1. ``refund_invoice_no`` cached on the E-Invoice (from a prior T112
	#      with ``refundInvoiceNo``, or from a T111 backfill below).
	#   2. T112 fetch + cache (only if it returns ``refundInvoiceNo``).
	#   3. T111 fetch — each record's ``invoiceNo`` is the issued credit-note
	#      FDN. This is the most reliable source: T112 doesn't always return
	#      refundInvoiceNo in every URA env, and ``efris_invoice_id`` is the
	#      T110 application referenceNo (URA rejects it with error 1561).
	refund_invoice_no = cstr(e_inv.get("refund_invoice_no") or "")
	if not refund_invoice_no:
		application_id = e_inv.get("application_id") or _resolve_application_id(e_inv)
		if not application_id:
			frappe.throw(_("No EFRIS application id found — cannot resolve credit-note FDN."))
		with efris_errors(_("EFRIS Credit Note Header Query Failed")):
			header = get_credit_note_details(application_id, company=e_inv.company)
		_persist_t112_fields(e_inv, header)
		refund_invoice_no = _pick_refund_invoice_no(header)
		if not refund_invoice_no:
			refund_invoice_no = _resolve_fdn_via_t111(e_inv)
			if refund_invoice_no:
				e_inv.db_set("refund_invoice_no", refund_invoice_no, update_modified=False)
		if not refund_invoice_no:
			_log_t112_for_debug(application_id, header, reason="missing refundInvoiceNo")
			frappe.throw(
				_(
					"EFRIS did not return a credit-note FDN via T112 or T111. The credit note may not have been issued an FDN yet (still in workflow). T112 response logged to Error Log ('EFRIS T112 missing refundInvoiceNo (app {0})')."
				).format(application_id)
			)

	payload: dict[str, Any] = {
		"oriInvoiceId": ori_invoice_id[:20],
		"invoiceNo": refund_invoice_no[:20],
		"reasonCode": reason_code,
		"invoiceApplyCategoryCode": invoice_apply_category_code,
	}
	if reason:
		payload["reason"] = reason[:1024]

	reference_no = cstr(e_inv.reference_no or e_inv.name)
	with efris_errors(_("EFRIS Credit Note Cancellation Failed")):
		call_t114(payload, reference_no=reference_no, company=e_inv.company)

	# 104 (cancel-of-credit-note) flips status immediately; 103 starts a
	# workflow and the final state lands later. Stamp Voided locally either
	# way and let the next T112 poll reconcile if needed.
	voided_label = APPROVE_STATUS_LABELS["104"]
	now = now_datetime()
	e_inv.db_set("credit_note_status", voided_label, update_modified=False)
	e_inv.db_set("credit_note_status_checked_on", now, update_modified=False)
	frappe.db.set_value(
		"Sales Invoice",
		sales_invoice,
		"efris_credit_note_status",
		voided_label,
		update_modified=False,
	)

	return {
		"ori_invoice_id": ori_invoice_id,
		"invoice_no": refund_invoice_no,
		"reason_code": reason_code,
		"invoice_apply_category_code": invoice_apply_category_code,
		"status_label": voided_label,
	}


@frappe.whitelist()
def get_sandbox_environment(company: str | None = None) -> dict[str, Any]:
	"""Return ``{"is_sandbox": bool, "environment": str}`` for a Sales Invoice form.

	Used by the JS layer to guard the T113 button — Production must not show
	it because URA rejects seller self-approval there.
	"""
	settings = _settings_for_company(company)
	env = (settings.environment or "") if settings else ""
	return {"environment": env, "is_sandbox": env.lower() == "sandbox"}


def _settings_for_company(company: str | None):
	from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

	return get_efris_settings(company)


def _persist_t112_fields(e_inv, header) -> None:
	"""Cache useful fields from a T112 response onto the E-Invoice.

	T112 returns the application ``id``, the credit-note ``refundInvoiceNo``
	(FDN), and a workflow ``taskId``. Persist all three so T113 / T114 / T120
	can use the cached values without re-querying T112 on every action.
	Called from every T112 call site.
	"""
	if not isinstance(header, dict):
		return
	app_id = cstr(header.get("id") or "")
	if app_id and app_id != cstr(e_inv.get("application_id") or ""):
		e_inv.db_set("application_id", app_id, update_modified=False)
	fdn = _pick_refund_invoice_no(header)
	if fdn and fdn != cstr(e_inv.get("refund_invoice_no") or ""):
		e_inv.db_set("refund_invoice_no", fdn, update_modified=False)
	task_id = _pick_task_id(header)
	if task_id and task_id != cstr(e_inv.get("task_id") or ""):
		e_inv.db_set("task_id", task_id, update_modified=False)


def _pick_refund_invoice_no(header) -> str:
	"""Pull the credit-note FDN from a T112 response — tolerates field-name drift."""
	if not isinstance(header, dict):
		return ""
	candidates = [
		header.get("refundInvoiceNo"),
		header.get("refundInvoiceNumber"),
		header.get("refundInvoiceId"),
		header.get("creditNoteNo"),
		header.get("cnInvoiceNo"),
	]
	basic = header.get("basicInformation") or {}
	if isinstance(basic, dict):
		candidates += [basic.get("refundInvoiceNo"), basic.get("invoiceNo")]
	for val in candidates:
		s = cstr(val or "").strip()
		if s:
			return s
	return ""


def _resolve_fdn_via_t111(e_inv) -> str:
	"""Look up the credit-note FDN from T111 records.

	T112 sometimes omits ``refundInvoiceNo``; T111 records carry the issued
	FDN. We try several candidate referenceNo values URA might index by
	(seller-side reference, URA response reference, sellersReferenceNo) and
	an oriInvoiceNo fallback, then match the right record by application id.
	"""
	application_id = cstr(e_inv.get("application_id") or "")
	candidate_refs = [
		cstr(e_inv.get("reference_no") or e_inv.name),
		cstr(e_inv.get("efris_invoice_id") or ""),  # URA's response referenceNo
	]
	# De-dupe while preserving order; drop empties.
	candidate_refs = list({r: None for r in candidate_refs if r}.keys())

	for ref in candidate_refs:
		records = _safe_t111(e_inv, reference_no=ref)
		fdn = _match_fdn_in_records(records, application_id, ref)
		if fdn:
			return fdn

	if e_inv.get("original_invoice_no"):
		records = _safe_t111(e_inv, ori_invoice_no=cstr(e_inv.get("original_invoice_no")))
		fdn = _match_fdn_in_records(records, application_id, "")
		if fdn:
			return fdn

	return ""


def _safe_t111(e_inv, **kwargs) -> list[dict]:
	"""Run a T111 query, returning records (or ``[]`` on error)."""
	try:
		response = query_credit_note_applications(
			page_size=20,
			company=e_inv.get("company"),
			**kwargs,
		)
	except Exception:
		return []
	return _extract_records(response)


def _match_fdn_in_records(records: list[dict], application_id: str, ref: str) -> str:
	"""Find the first record's FDN, preferring the one whose ``id`` matches."""
	if not records:
		return ""
	# Prefer the exact-app-id match.
	if application_id:
		for rec in records:
			if cstr(rec.get("id")) == application_id:
				fdn = _pick_record_fdn(rec)
				if fdn:
					return fdn
	# Then prefer the exact referenceNo match.
	if ref:
		for rec in records:
			if cstr(rec.get("referenceNo")) == ref:
				fdn = _pick_record_fdn(rec)
				if fdn:
					return fdn
	# Last resort — first record with any FDN-like field.
	for rec in records:
		fdn = _pick_record_fdn(rec)
		if fdn:
			return fdn
	return ""


def _pick_record_fdn(record: dict) -> str:
	"""Pull the credit-note FDN from a T111 record. Tolerates field-name drift."""
	if not isinstance(record, dict):
		return ""
	for key in ("invoiceNo", "invoiceNumber", "refundInvoiceNo", "creditNoteNo", "fdn"):
		val = cstr(record.get(key) or "").strip()
		if val:
			return val
	return ""


def _pick_task_id(header) -> str:
	"""Pull a taskId from a T112 response. Tolerates URA field-name variants."""
	if not isinstance(header, dict):
		return ""
	for key in ("taskId", "taskID", "task_id", "taskid"):
		val = cstr(header.get(key) or "")
		if val and val != "0":
			return val
	return ""


def _resolve_task_id_via_todo(e_inv, application_id: str) -> str:
	"""Fallback: scan T111 ``queryType=2`` (to-do for approver) for our app's task.

	Returns the taskId off the record whose ``id`` matches ``application_id``,
	or empty when nothing matches (typical when the app isn't on a pending
	approval queue).
	"""
	try:
		response = query_credit_note_applications(
			reference_no=cstr(e_inv.reference_no or e_inv.name),
			query_type="2",
			page_size=50,
			company=e_inv.get("company"),
		)
	except Exception:
		return ""
	for rec in _extract_records(response):
		if cstr(rec.get("id")) == cstr(application_id):
			return _pick_task_id(rec)
	return ""


def _log_t112_for_debug(application_id: str, header, reason: str = "field missing") -> None:
	"""Drop the T112 response into the error log so a missing field can be diagnosed.

	``reason`` is included in the title so different call sites (missing
	taskId vs. missing refundInvoiceNo) end up in distinct log entries.
	"""
	try:
		import json as _json

		frappe.log_error(
			message=_json.dumps(header or {}, indent=2)[:32000],
			title=f"EFRIS T112 {reason} (app {application_id})",
		)
	except Exception:
		pass


def _resolve_application_id(e_inv) -> str:
	"""Find the URA application id for this credit note via T111.

	We look it up by ``referenceNo`` (what we sent on T110, == E-Invoice name)
	and fall back to ``oriInvoiceNo`` (the credited FDN) if nothing matches.
	"""
	reference_no = e_inv.reference_no or e_inv.name
	candidates: list[dict] = []

	with efris_errors(_("EFRIS Credit Note Application Lookup Failed")):
		response = query_credit_note_applications(
			reference_no=reference_no,
			page_size=10,
			company=e_inv.company,
		)
	candidates = _extract_records(response)

	if not candidates and e_inv.get("original_invoice_no"):
		with efris_errors(_("EFRIS Credit Note Application Lookup Failed")):
			response = query_credit_note_applications(
				ori_invoice_no=e_inv.original_invoice_no,
				page_size=10,
				company=e_inv.company,
			)
		candidates = _extract_records(response)

	for rec in candidates:
		if cstr(rec.get("referenceNo")) == cstr(reference_no) and rec.get("id"):
			return cstr(rec.get("id"))

	if candidates and candidates[0].get("id"):
		return cstr(candidates[0].get("id"))
	return ""


def _extract_records(response) -> list[dict]:
	if isinstance(response, list):
		return [r for r in response if isinstance(r, dict)]
	if isinstance(response, dict):
		records = response.get("records")
		if isinstance(records, list):
			return [r for r in records if isinstance(r, dict)]
	return []
