"""T129 Batch Invoice Upload — bulk-push Sales / POS Invoices to EFRIS.

User multi-selects on the Sales Invoice / POS Invoice list, the server filters
out already-uploaded / returns / drafts, builds each as a T109 payload, signs
each entry, and posts the array via T129. Per-entry results are recorded on
an ``EFRIS Batch Invoice Upload`` doc.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, now_datetime

from efris.efris.api.client import EFRISClient, efris_errors
from efris.efris.api.crypto import sign_data
from efris.efris.api.interfaces import upload_invoice_batch as call_t129
from efris.efris.api.invoice import (
	_build_payload,
	_interpret_response,
	_persist_result,
	_resolve_or_create_e_invoice,
)

ELIGIBLE_DOCTYPES = ("Sales Invoice", "POS Invoice")


# -- public -----------------------------------------------------------


@frappe.whitelist()
def prepare_batch(source_doctype: str, names) -> dict[str, Any]:
	"""Sort selected invoices into eligible / skipped for T129 upload."""
	names = _parse_names(names)
	_validate_source_doctype(source_doctype)
	eligible, skipped = _classify(source_doctype, names)
	return {"eligible": eligible, "skipped": skipped}


@frappe.whitelist()
def upload_batch(source_doctype: str, names) -> dict[str, Any]:
	"""Build T129 payload, post to EFRIS, record per-entry outcomes.

	Returns ``{batch, success, failed, skipped}``. The batch doc captures the
	full per-entry status and the raw URA response for audit.
	"""
	names = _parse_names(names)
	_validate_source_doctype(source_doctype)
	eligible, skipped = _classify(source_doctype, names)

	if not eligible:
		frappe.throw(_("No eligible invoices to upload. All selected are already uploaded or otherwise skipped."))

	# Resolve a single company — T129 is per-taxpayer; mixed-company selection
	# is rejected because the EFRIS Settings (TIN / key) differ per company.
	companies = {row["company"] for row in eligible}
	if len(companies) > 1:
		frappe.throw(_("Selected invoices span multiple companies. Run one batch per company."))
	company = companies.pop()

	client = EFRISClient(company=company)

	# Build the batch doc up front so partial failures are still persisted.
	batch = frappe.new_doc("EFRIS Batch Invoice Upload")
	batch.company = company
	batch.source_doctype = source_doctype
	batch.submitted_on = now_datetime()
	batch.submitted_by = frappe.session.user
	batch.status = "Draft"

	# Build each entry: resolve-or-create E-Invoice, build T109 payload, sign.
	entries_for_efris: list[dict[str, str]] = []
	entry_rows: list[dict[str, Any]] = []
	build_failures: list[dict[str, Any]] = []

	for row in eligible:
		try:
			e_invoice_name = _resolve_or_create_e_invoice(source_doctype, row["name"])
			e_inv = frappe.get_doc("E-Invoice", e_invoice_name)
			payload = _build_payload(e_inv)
			content_b64 = base64.b64encode(
				json.dumps(payload, separators=(",", ":")).encode("utf-8")
			).decode("utf-8")
			signature_b64 = base64.b64encode(
				sign_data(client.private_key, content_b64.encode("utf-8"))
			).decode("utf-8")
			entries_for_efris.append({"invoiceContent": content_b64, "invoiceSignature": signature_b64})
			entry_rows.append({
				"source_doctype": source_doctype,
				"source_name": row["name"],
				"e_invoice": e_invoice_name,
				"status": "Pending",
			})
		except Exception as exc:
			build_failures.append({
				"source_doctype": source_doctype,
				"source_name": row["name"],
				"status": "Failed",
				"return_code": "BUILD",
				"return_message": cstr(exc)[:500],
			})

	for row in build_failures:
		batch.append("entries", row)
	for row in entry_rows:
		batch.append("entries", row)
	for skip in skipped:
		batch.append("skipped_entries", {
			"source_doctype": source_doctype,
			"source_name": skip["name"],
			"status": "Skipped",
			"skip_reason": skip["reason"],
		})

	batch.entry_count = len(entry_rows) + len(build_failures)
	batch.skipped_count = len(skipped)
	batch.status = "Submitted"
	batch.insert(ignore_permissions=True)
	frappe.db.commit()

	if not entries_for_efris:
		# All builds failed; nothing to send.
		batch.failed_count = len(build_failures)
		batch.success_count = 0
		batch.status = "Failed"
		batch.save(ignore_permissions=True)
		return _summary(batch)

	# Fire T129. Transport failures bubble out as user errors; per-entry
	# rejections come back inside the response list and are non-fatal.
	with efris_errors(_("EFRIS Batch Invoice Upload Failed")):
		response = call_t129(entries_for_efris, company=company, client=client)

	batch.efris_response_json = json.dumps(response, indent=2)[:65535]

	# Apply per-entry results back onto the entry rows we just inserted.
	# Build failures occupy positions 0..len(build_failures)-1 in batch.entries;
	# real entries start after that and align 1:1 with entries_for_efris.
	offset = len(build_failures)
	results = response if isinstance(response, list) else []
	for i, entry_row in enumerate(batch.entries[offset:], start=0):
		result = results[i] if i < len(results) else None
		if result is None:
			entry_row.status = "Failed"
			entry_row.return_message = "EFRIS did not return a result for this entry."
			continue
		_apply_entry_result(entry_row, result)

	success_count = sum(1 for r in batch.entries if r.status == "Success")
	failed_count = sum(1 for r in batch.entries if r.status == "Failed")
	batch.success_count = success_count
	batch.failed_count = failed_count
	if failed_count == 0 and success_count > 0:
		batch.status = "Success"
	elif success_count == 0:
		batch.status = "Failed"
	else:
		batch.status = "Partial"
	batch.save(ignore_permissions=True)

	return _summary(batch)


# -- helpers ----------------------------------------------------------


def _summary(batch) -> dict[str, Any]:
	return {
		"batch": batch.name,
		"status": batch.status,
		"success": batch.success_count or 0,
		"failed": batch.failed_count or 0,
		"skipped": batch.skipped_count or 0,
	}


def _parse_names(names) -> list[str]:
	if isinstance(names, str):
		try:
			parsed = json.loads(names)
		except Exception:
			parsed = [n.strip() for n in names.split(",") if n.strip()]
	else:
		parsed = names or []
	return [str(n) for n in parsed if n]


def _validate_source_doctype(source_doctype: str) -> None:
	if source_doctype not in ELIGIBLE_DOCTYPES:
		frappe.throw(_("Batch upload supports Sales Invoice or POS Invoice only."))


def _classify(source_doctype: str, names: list[str]) -> tuple[list[dict], list[dict]]:
	"""Return (eligible, skipped) row dicts for the given source names.

	Eligibility rules:
	  * docstatus == 1 (submitted)
	  * not already uploaded to EFRIS (``efris_uploaded`` is falsy)
	  * not a credit-note return — T129 is invoice-only; credit notes go via T110
	  * company has EFRIS Settings configured
	"""
	if not names:
		return [], []

	rows = frappe.get_all(
		source_doctype,
		filters={"name": ("in", names)},
		fields=["name", "company", "docstatus", "is_return", "efris_uploaded"],
	)
	# Preserve user's selection order.
	by_name = {row.name: row for row in rows}

	configured_companies = {
		c for c in frappe.get_all(
			"EFRIS Settings", filters={"enabled": 1}, pluck="company"
		) if c
	}

	eligible: list[dict] = []
	skipped: list[dict] = []
	for name in names:
		row = by_name.get(name)
		if not row:
			skipped.append({"name": name, "reason": "Document not found"})
			continue
		if row.docstatus != 1:
			skipped.append({"name": name, "reason": "Not submitted"})
			continue
		if row.get("is_return"):
			skipped.append({"name": name, "reason": "Credit note — use T110"})
			continue
		if row.get("efris_uploaded"):
			skipped.append({"name": name, "reason": "Already uploaded"})
			continue
		if row.company not in configured_companies:
			skipped.append({"name": name, "reason": "No EFRIS Settings for company"})
			continue
		eligible.append({"name": name, "company": row.company})
	return eligible, skipped


def _apply_entry_result(entry_row, result: dict) -> None:
	"""Map one T129 response entry onto its batch row + mirror to source/E-Invoice."""
	if not isinstance(result, dict):
		entry_row.status = "Failed"
		entry_row.return_message = "Malformed entry result"
		return

	code = cstr(result.get("invoiceReturnCode") or "")
	message = cstr(result.get("invoiceReturnMessage") or "")
	entry_row.return_code = code
	entry_row.return_message = message[:500]

	inner_b64 = result.get("invoiceContent") or ""
	inner_json: Any = None
	if inner_b64:
		try:
			inner_json = json.loads(base64.b64decode(inner_b64).decode("utf-8"))
		except Exception:
			inner_json = None

	is_success = code in ("", "00")
	if not is_success:
		entry_row.status = "Failed"
		# When 99, URA puts the detail inside invoiceContent.
		if inner_json:
			entry_row.return_message = (json.dumps(inner_json)[:500]) or entry_row.return_message
		return

	state = _interpret_response(inner_json or {})
	if not state.get("ok"):
		entry_row.status = "Failed"
		entry_row.return_message = (state.get("message") or entry_row.return_message)[:500]
		return

	basic = state.get("basic") or {}
	entry_row.status = "Success"
	entry_row.efris_invoice_id = basic.get("invoiceNo") or state.get("invoice_id") or ""
	entry_row.efris_antifake_code = basic.get("antifakeCode") or ""
	entry_row.qr_code = (inner_json or {}).get("summary", {}).get("qrCode") or basic.get("qrCode") or ""

	if entry_row.e_invoice:
		try:
			e_inv = frappe.get_doc("E-Invoice", entry_row.e_invoice)
			_persist_result(e_inv, state, inner_json or {})
		except Exception as exc:
			# Mirror failure shouldn't lose the URA confirmation — log and move on.
			frappe.log_error(
				message=cstr(exc),
				title=f"EFRIS T129 mirror failed for {entry_row.e_invoice}",
			)
