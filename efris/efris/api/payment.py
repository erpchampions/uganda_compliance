"""Payment-Entry-driven EFRIS upload.

When a Sales Invoice is configured (via Customer or EFRIS Settings) with the
``On Payment`` upload trigger, the EFRIS push is deferred until a Payment
Entry referencing that invoice is submitted.

Two entry points:
  * ``auto_upload_on_payment_submit`` — ``on_submit`` doc_event hook. Respects
    the Payment Entry's ``efris_auto_upload_invoices`` flag and only fires
    for SIs whose resolved trigger is ``On Payment``.
  * ``upload_invoices_for_payment`` — whitelisted manual entry point used by
    the button on Payment Entry. Uploads any referenced SI that is not yet
    uploaded, regardless of trigger.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

# Mirror the option strings on E-Invoice Pay Way.payment_mode so the
# Select field accepts the value we write back.
_PAYMENT_MODE_LABELS = {
	"101": "101 - Credit",
	"102": "102 - Cash",
	"103": "103 - Cheque",
	"104": "104 - Demand Draft",
	"105": "105 - Mobile Money",
	"106": "106 - Visa/Master Card",
	"107": "107 - EFT",
	"108": "108 - POS",
	"109": "109 - RTGS",
	"110": "110 - Swift Transfer",
}



def _payment_mode_label(mode_of_payment: str | None) -> str:
	"""Map Mode of Payment → E-Invoice payment_mode select label.

	Uses ``Mode of Payment.efris_dictionary`` (``payWay-<code>``) when set.
	Falls back to ``101 - Credit`` so URA still accepts the payload.
	"""
	if mode_of_payment:
		link = frappe.db.get_value("Mode of Payment", mode_of_payment, "efris_dictionary")
		if link and "-" in link:
			code = link.split("-", 1)[1].strip()
			if code in _PAYMENT_MODE_LABELS:
				return _PAYMENT_MODE_LABELS[code]
	return "101 - Credit"


def auto_upload_on_payment_submit(doc, _method=None) -> None:
	"""``on_submit`` hook for Payment Entry. Non-blocking."""
	if doc.get("docstatus") != 1:
		return
	if (doc.get("payment_type") or "") != "Receive":
		return
	if not doc.get("efris_auto_upload_invoices"):
		return
	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return

	_upload_referenced_invoices(doc, gate_on_trigger=True)


@frappe.whitelist()
def upload_invoices_for_payment(payment_entry: str) -> dict[str, Any]:
	"""Manual: upload every referenced SI that isn't yet uploaded.

	Trigger gate is skipped — the user explicitly asked.
	"""
	doc = frappe.get_doc("Payment Entry", payment_entry)
	if doc.docstatus != 1:
		frappe.throw(_("Payment Entry must be submitted before uploading to EFRIS."))
	return _upload_referenced_invoices(doc, gate_on_trigger=False)


def _upload_referenced_invoices(pe_doc, gate_on_trigger: bool) -> dict[str, Any]:
	from efris.efris.api.invoice import (
		_resolve_or_create_e_invoice,
		create_e_invoice,
		resolve_upload_trigger,
		upload_e_invoice,
	)

	uploaded: list[str] = []
	skipped: list[str] = []
	errors: list[str] = []

	for row in (pe_doc.references or []):
		if (row.reference_doctype or "") != "Sales Invoice":
			continue
		si_name = row.reference_name
		if not si_name:
			continue

		si = frappe.db.get_value(
			"Sales Invoice",
			si_name,
			["name", "docstatus", "customer", "company", "efris_uploaded"],
			as_dict=True,
		)
		if not si or si.docstatus != 1:
			skipped.append(si_name)
			continue

		# Already-uploaded SI: each Payment Entry that settles it can produce one
		# additional EFRIS document, so installment payments each get their own.
		force_new = False
		if si.efris_uploaded:
			# Non-VAT taxpayers issue a Receipt (invoiceKind 2); VAT-registered
			# taxpayers keep a tax invoice (invoiceKind 1) since URA rejects
			# invoiceKind 2 from them (code 2240). The kind is resolved downstream
			# in _apply_payment_entry_pay_way. We only refuse when this exact
			# Payment Entry was already documented against the SI.
			if not _should_issue_receipt_for_payment(si_name, pe_doc.name):
				skipped.append(si_name)
				continue
			# Auto path is gated by the company setting; the manual button
			# (gate_on_trigger=False) always allows the additional receipt.
			if gate_on_trigger and not _auto_receipts_enabled(si.company):
				skipped.append(si_name)
				continue
			force_new = True

		# The trigger gate defers the *first* upload until payment; a receipt on
		# an already-uploaded credit invoice is governed by the PE's auto-upload
		# flag instead, so skip the gate there.
		if gate_on_trigger and not force_new:
			si_doc = frappe.get_doc("Sales Invoice", si_name)
			if resolve_upload_trigger(si_doc) != "On Payment":
				skipped.append(si_name)
				continue

		try:
			if force_new:
				e_invoice_name = create_e_invoice("Sales Invoice", si_name)
			else:
				e_invoice_name = _resolve_or_create_e_invoice("Sales Invoice", si_name)
			_apply_payment_entry_pay_way(e_invoice_name, pe_doc, row)
			upload_e_invoice(e_invoice_name)
			uploaded.append(si_name)
		except Exception as exc:
			errors.append(f"{si_name}: {cstr(exc)}")

	_persist_payment_status(pe_doc, uploaded, errors)

	if errors and not gate_on_trigger:
		# Manual flow: surface a single combined error so the UI shows it.
		frappe.msgprint(
			_("EFRIS upload finished with errors:\n{0}").format("\n".join(errors)),
			alert=True,
			indicator="orange",
		)

	return {"uploaded": uploaded, "skipped": skipped, "errors": errors}


def _is_vat_registered(company: str | None) -> bool:
	"""True when the company's EFRIS taxpayer holds an active VAT registration."""
	from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

	try:
		settings = get_efris_settings(company)
	except Exception:
		return False
	return bool(settings and settings.is_vat_registered())


def _auto_receipts_enabled(company: str | None) -> bool:
	"""Company-level switch for auto-issuing receipts on payment."""
	from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

	try:
		settings = get_efris_settings(company)
	except Exception:
		return False
	return bool(settings and settings.get("auto_issue_payment_receipts"))


def _should_issue_receipt_for_payment(si_name: str, pe_name: str) -> bool:
	"""Gate for issuing one additional EFRIS document per Payment Entry.

	Issue another document for an already-uploaded SI only when (a) the SI is
	genuinely already reported to URA (a prior uploaded, non-credit-note
	E-Invoice exists) and (b) we have not already issued one keyed to this exact
	Payment Entry. Every distinct Payment Entry against the SI can produce its
	own document; the same PE never produces two.
	"""
	from efris.efris.api.invoice import _existing_uploaded_einvoices

	existing = _existing_uploaded_einvoices(si_name)
	if not existing:
		return False
	already = frappe.db.exists(
		"E-Invoice",
		{"source_name": si_name, "reference_no": pe_name, "upload_status": "Uploaded"},
	)
	return not already


def _apply_payment_entry_pay_way(e_invoice_name: str, pe_doc, ref_row) -> None:
	"""Replace the E-Invoice's pay_way table with this Payment Entry's mode/amount.

	Uses ``mode_of_payment`` from the PE and the row's ``allocated_amount``
	(the share of the PE applied to this specific Sales Invoice). Falls back
	to ``paid_amount`` if the reference row has no allocation.
	"""
	e_inv = frappe.get_doc("E-Invoice", e_invoice_name)
	if e_inv.upload_status == "Uploaded":
		return

	amount = flt(ref_row.allocated_amount) or flt(pe_doc.get("paid_amount") or 0)
	mode_label = _payment_mode_label(pe_doc.get("mode_of_payment"))

	# Uploaded via a Payment Entry. Non-VAT taxpayers issue a Receipt
	# (invoiceKind 2); VAT-registered taxpayers must keep a tax invoice
	# (invoiceKind 1) or URA rejects it with return code 2240. Key the
	# E-Invoice to the PE so a re-submit can't issue a duplicate.
	if not _is_vat_registered(pe_doc.get("company")):
		e_inv.invoice_kind = "2 - Receipt"
	e_inv.reference_no = pe_doc.name

	# Report only what this payment settled, not the full Sales Invoice. Scaling
	# is a no-op on a full/over-payment, so a single full settlement still
	# reports the whole invoice.
	from efris.efris.api.invoice import apply_payment_amount_scaling

	apply_payment_amount_scaling(e_inv, amount)

	e_inv.set("pay_way", [])
	e_inv.append(
		"pay_way",
		{
			"payment_mode": mode_label,
			"payment_amount": round(amount, 2),
			"order_number": "a",
		},
	)
	e_inv.save(ignore_permissions=True)


def _persist_payment_status(pe_doc, uploaded: list[str], errors: list[str]) -> None:
	if not uploaded and not errors:
		return
	pe_doc.db_set(
		{
			"efris_last_uploaded_on": now_datetime(),
			"efris_upload_error": "\n".join(errors) if errors else "",
		},
		update_modified=False,
	)
