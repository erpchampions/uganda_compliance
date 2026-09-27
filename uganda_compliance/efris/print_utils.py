"""Jinja helpers for EFRIS receipts (registered in hooks.jinja)."""

import frappe
from frappe.utils import cint

from uganda_compliance.efris.utils.utils import get_qr_code


def _clean_data_uri(uri):
	# get_qr_code() historically emits "data:image/png;base64, <data>" (note the space)
	return (uri or "").replace("base64, ", "base64,").strip()


def efris_receipt_data(doc):
	"""Everything the receipt needs about the invoice's EFRIS state.

	``state`` is one of:
	  * ``not_efris``        - not an EFRIS invoice (or company not on EFRIS)
	  * ``fiscalised``       - has an FDN (invoice or approved credit note)
	  * ``credit_note_pending`` - return: credit note application sent, awaiting URA approval
	  * ``pending``          - EFRIS invoice not fiscalised yet (queued / failed / offline)
	"""
	data = frappe._dict(state="not_efris", fdn=None, verification_code=None, qr=None)
	if not doc or not cint(doc.get("efris_invoice")):
		return data

	einvoice_name = doc.get("efris_e_invoice") or frappe.db.get_value(
		"E Invoice", {"invoice": doc.name}, "name"
	)
	einvoice = frappe.get_doc("E Invoice", einvoice_name) if einvoice_name else None

	settings = (
		frappe.db.get_value(
			"E Invoicing Settings",
			{"company": doc.company},
			["tin", "device_no", "sandbox_mode"],
			as_dict=True,
		)
		or frappe._dict()
	)

	data.update(
		{
			"tin": (einvoice and einvoice.seller_gstin) or settings.tin or doc.get("efris_company_tax_id"),
			"device_no": (einvoice and einvoice.get("device_no")) or settings.device_no,
			"sandbox": cint(settings.sandbox_mode),
			"efris_status": doc.get("efris_status"),
			"is_return": cint(doc.get("is_return")),
			"original_fdn": (einvoice and einvoice.get("original_fdn"))
			or (
				doc.get("return_against")
				and frappe.db.get_value(doc.doctype, doc.return_against, "efris_irn")
			),
		}
	)

	fdn = doc.get("efris_irn") or (einvoice and einvoice.irn)
	if fdn and einvoice and (einvoice.antifake_code or not data.is_return):
		qr = _clean_data_uri(einvoice.qr_code_data)
		if not qr and einvoice.efris_qr_code:
			qr = _clean_data_uri(get_qr_code(einvoice.efris_qr_code))
		data.update(
			{
				"state": "fiscalised",
				"fdn": fdn,
				"verification_code": einvoice.antifake_code,
				"qr": qr or None,
				"issued": " ".join(str(x) for x in (einvoice.invoice_date, einvoice.issued_time) if x),
			}
		)
	elif data.is_return and einvoice and einvoice.get("credit_note_application_ref_no"):
		data.update(
			{
				"state": "credit_note_pending",
				"application_ref": einvoice.credit_note_application_ref_no,
			}
		)
	else:
		data.state = "pending"
	return data
