"""T109 Invoice Upload — push ERPNext Sales / POS Invoices to EFRIS.

Pipeline:
  Sales Invoice / POS Invoice submit
    → ``create_e_invoice`` (build the staging E-Invoice doc)
    → ``upload_e_invoice`` (assemble T109 payload, post, persist response)

Two operating modes, toggled in EFRIS Settings:
  * ``auto_upload_invoices = 1`` — fires on submit via ``auto_upload_on_submit``.
  * ``auto_upload_invoices = 0`` — user clicks the EFRIS button on the source
    Sales/POS Invoice (or on the E-Invoice itself).

When ``combined_invoice_item`` is set in EFRIS Settings, every source line
``amount`` is summed onto a single T109 goods line using that Item's
``efris_goods_code`` + commodity category. URA recomputes tax from the
configured category.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_datetime, now_datetime

from efris.efris.api.client import EFRISError, efris_errors
from efris.efris.api.goods import _code_from_uom, _format_number
from efris.efris.api.interfaces import upload_credit_note as call_t110
from efris.efris.api.interfaces import upload_invoice as call_t109


# -- public ------------------------------------------------------------


@frappe.whitelist()
def upload_source(
	source_doctype: str,
	source_name: str,
	confirm_combined: bool | int | str = False,
	force_new: bool | int | str = False,
) -> dict[str, Any]:
	"""Create the E-Invoice if missing and upload to EFRIS. Manual-button entry.

	When none of the source items have been registered on EFRIS (Item
	``efris_uploaded == 0`` across the board), the upload can only succeed via
	the ``combined_invoice_item`` fallback configured in EFRIS Settings. If
	that's not set we refuse the upload; if it is, we surface a
	``needs_confirm`` response so the UI can re-prompt the user, then re-call
	with ``confirm_combined=True``.

	``force_new`` mints a brand-new E-Invoice even when the source already has
	one uploaded — used to issue an *additional* EFRIS invoice for a single
	Sales Invoice (the UI gates this behind ``precheck_additional_invoice``).
	"""
	if not _truthy(confirm_combined):
		precheck = _check_combined_item_required(source_doctype, source_name)
		if precheck is not None:
			return precheck
	_reset_stale_return_state(source_doctype, source_name)
	if _truthy(force_new):
		e_invoice_name = create_e_invoice(source_doctype, source_name)
	else:
		e_invoice_name = _resolve_or_create_e_invoice(source_doctype, source_name)
	return upload_e_invoice(e_invoice_name)


def _truthy(value) -> bool:
	"""Whitelisted args come over the wire as strings — normalise to bool."""
	if isinstance(value, bool):
		return value
	return str(value).strip().lower() in ("1", "true", "yes")


def _check_combined_item_required(source_doctype: str, source_name: str) -> dict[str, Any] | None:
	"""If no line items are EFRIS-registered, gate on the combined-item fallback.

	Returns:
	  * ``None`` — at least one item is EFRIS-uploaded; carry on normally.
	  * ``{"needs_confirm": True, ...}`` — fallback is configured; UI should
	    re-prompt and re-call with ``confirm_combined=True``.

	Throws when no item is EFRIS-uploaded *and* ``combined_invoice_item`` is
	unset, since the upload would just fail at URA in that case.
	"""
	item_codes = [
		row.item_code
		for row in (frappe.get_all(
			f"{source_doctype} Item",
			filters={"parent": source_name, "parenttype": source_doctype},
			fields=["item_code"],
		) or [])
		if row.item_code
	]
	if not item_codes:
		return None  # empty invoice will fail downstream anyway

	any_uploaded = bool(frappe.db.exists("Item", {
		"name": ("in", list(set(item_codes))),
		"efris_uploaded": 1,
	}))
	if any_uploaded:
		return None

	from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

	company = frappe.db.get_value(source_doctype, source_name, "company")
	try:
		settings = get_efris_settings(company)
	except Exception:
		settings = None
	combined_item = settings.get("combined_invoice_item") if settings else None
	if not combined_item:
		frappe.throw(_(
			"None of the items on this invoice have been uploaded to EFRIS, "
			"and no fallback <b>Combined Invoice Item</b> is configured in "
			"EFRIS Settings. Either upload the items via the EFRIS goods "
			"registry (T130) or set a combined invoice item before retrying."
		))
	return {
		"needs_confirm": True,
		"reason": "no_uploaded_items",
		"combined_invoice_item": combined_item,
		"message": _(
			"None of the items on this invoice have been uploaded to EFRIS. "
			"Proceed using the fallback Combined Invoice Item "
			"<b>{0}</b> from EFRIS Settings?"
		).format(combined_item),
	}


def _reset_stale_return_state(source_doctype: str, source_name: str) -> None:
	"""Clear EFRIS status fields ERPNext copied from the original onto a return.

	Pre-no_copy data: a Return SI inherits ``efris_uploaded``, ``efris_e_invoice``,
	etc. from the original — which makes us refuse the upload because we
	think it's already done. If the linked E-Invoice doesn't actually point
	back at this document, wipe the stale fields.
	"""
	doc = frappe.db.get_value(
		source_doctype,
		source_name,
		["is_return", "efris_e_invoice", "efris_uploaded"],
		as_dict=True,
	) or {}
	if not doc.get("is_return"):
		return
	linked = doc.get("efris_e_invoice")
	if linked:
		einv_source = frappe.db.get_value("E-Invoice", linked, "source_name")
		if einv_source == source_name:
			return  # legitimate link
	frappe.db.set_value(source_doctype, source_name, {
		"efris_uploaded": 0,
		"efris_e_invoice": None,
		"efris_invoice_id": "",
		"efris_antifake_code": "",
		"efris_last_uploaded_on": None,
		"efris_upload_error": "",
		"efris_qr_code": "",
	}, update_modified=False)


@frappe.whitelist()
def upload_e_invoice(name: str) -> dict[str, Any]:
	"""Upload one E-Invoice via T109 (Invoice) or T110 (Credit Note)."""
	e_inv = frappe.get_doc("E-Invoice", name)
	if e_inv.upload_status == "Uploaded":
		frappe.throw(
			_("E-Invoice {0} is already uploaded — clear the EFRIS Invoice ID to retry.").format(
				e_inv.name
			)
		)

	is_credit_note = (e_inv.get("e_invoice_type") or "Invoice") == "Credit Note"
	try:
		if is_credit_note:
			payload = _build_credit_note_payload(e_inv)
			with efris_errors(_("EFRIS Credit Note Upload Failed")):
				response = call_t110(payload, reference_no=e_inv.name, company=e_inv.company)
		else:
			payload = _build_payload(e_inv)
			with efris_errors(_("EFRIS Invoice Upload Failed")):
				response = call_t109(payload, reference_no=e_inv.name, company=e_inv.company)
	except Exception as exc:
		_persist_failure(e_inv, cstr(exc))
		raise

	state = _interpret_credit_note_response(response) if is_credit_note else _interpret_response(response)
	_persist_result(e_inv, state, response)
	if state["ok"]:
		label = _("credit note") if is_credit_note else _("invoice")
		frappe.msgprint(
			_("EFRIS confirmed {0} {1}.").format(label, e_inv.efris_invoice_id or e_inv.name),
			alert=True,
			indicator="green",
		)
	else:
		frappe.throw(
			_("EFRIS rejected the upload: {0}").format(state["message"] or "(no message)")
		)
	return {"ok": state["ok"], "e_invoice": e_inv.name, "efris_invoice_id": e_inv.efris_invoice_id}


@frappe.whitelist()
def derive_print_data(name: str) -> dict[str, Any]:
	"""Goods + tax rows ready for the EFRIS e-Invoice print format.

	Resolution priority:
	  1. Linked E-Invoice — use its already-built ``items`` / ``tax_details``.
	  2. Sales Invoice ``taxes`` table — actual SI-engine tax per row.
	  3. Item EFRIS Commodity Category — derive tax category + rate.

	Returned dict carries ``goods``, ``taxes``, and the ``net``/``tax``/
	``gross`` totals so the print format doesn't have to recompute.
	"""
	doc = frappe.get_doc("Sales Invoice", name)

	e_inv_name = doc.get("efris_e_invoice")
	if e_inv_name and frappe.db.exists("E-Invoice", e_inv_name):
		e_inv = frappe.get_doc("E-Invoice", e_inv_name)
		return {
			"source": "einvoice",
			"goods": [r.as_dict() for r in (e_inv.items or [])],
			"taxes": [r.as_dict() for r in (e_inv.tax_details or [])],
			"net": flt(e_inv.net_amount),
			"tax": flt(e_inv.tax_amount),
			"gross": flt(e_inv.gross_amount),
		}

	si_tax_by_row = _si_item_wise_tax(doc)
	taxes_bucket: dict[str, dict[str, Any]] = {}
	goods: list[dict[str, Any]] = []

	for row in (doc.items or []):
		item_doc = frappe.get_cached_doc("Item", row.item_code)
		cat_code, fallback_rate_str = _resolve_tax_for_item(item_doc)
		net = flt(row.net_amount or row.amount)
		row_tax = si_tax_by_row.get(row.name) or si_tax_by_row.get(row.item_code) or {}
		si_tax_amount = flt(row_tax.get("tax_amount"))

		if si_tax_amount:
			tax = si_tax_amount
			rate_str = _ratio_as_rate_string(tax, net) or fallback_rate_str
		else:
			rate = _decimal_rate(fallback_rate_str)
			tax = net * rate
			rate_str = fallback_rate_str
		# Exempt items (cat 03) must carry tax_rate "-" per URA (error 2833).
		if cat_code == "03":
			rate_str = "-"
			tax = 0.0

		gross = net + tax
		qty = flt(row.qty) or 1
		goods.append({
			"item_name": row.item_name,
			"item_code": row.item_code,
			"qty": flt(row.qty),
			"uom": row.uom,
			"unit_of_measure_code": _code_from_uom(row.uom or item_doc.stock_uom),
			"unit_price": gross / qty,
			"total": gross,
			"tax_category_code": cat_code,
			"tax_rate": rate_str,
		})
		bucket = taxes_bucket.setdefault(
			cat_code,
			{"net": 0.0, "tax": 0.0, "gross": 0.0, "rate": rate_str},
		)
		bucket["net"] += net
		bucket["tax"] += tax
		bucket["gross"] += gross

	taxes = [
		{
			"tax_category_code": code,
			"tax_rate": data["rate"],
			"net_amount": data["net"],
			"tax_amount": data["tax"],
			"gross_amount": data["gross"],
		}
		for code, data in taxes_bucket.items()
	]
	total_net = sum(t["net_amount"] for t in taxes)
	total_tax = sum(t["tax_amount"] for t in taxes)
	total_gross = sum(t["gross_amount"] for t in taxes)
	return {
		"source": "derived",
		"goods": goods,
		"taxes": taxes,
		"net": total_net,
		"tax": total_tax,
		"gross": total_gross,
	}


UPLOAD_TRIGGERS = ("Manual", "On Submit", "On Payment")


def resolve_upload_trigger(doc) -> str:
	"""Return the effective EFRIS upload trigger for a Sales / POS Invoice.

	Priority: Customer override → EFRIS Settings default → legacy
	``auto_upload_invoices`` (1 → ``On Submit``, 0 → ``Manual``). POS Invoice
	has no Customer-level override hook and falls straight to settings.
	"""
	customer = doc.get("customer") if doc else None
	if customer:
		override = frappe.db.get_value("Customer", customer, "efris_upload_trigger")
		if override in UPLOAD_TRIGGERS:
			return override

	settings = _settings_for(doc)
	if settings:
		default = settings.get("efris_default_upload_trigger")
		if default in UPLOAD_TRIGGERS:
			return default
		return "On Submit" if settings.get("auto_upload_invoices") else "Manual"

	return "Manual"


def stamp_upload_trigger(doc, _method=None) -> None:
	"""``validate`` hook — stash the resolved trigger on the SI for the JS UI."""
	if not doc.get("customer"):
		return
	try:
		doc.efris_upload_trigger_resolved = resolve_upload_trigger(doc)
	except Exception:
		# Field is informational; never block save on resolver failure.
		pass


def auto_upload_on_submit(doc, _method=None) -> None:
	"""``on_submit`` hook for Sales Invoice / POS Invoice. Non-blocking.

	Handles both invoices and credit-note returns (Sales Invoice with
	``is_return = 1``) — the dispatch happens inside ``create_e_invoice``.
	"""
	if doc.get("docstatus") != 1:
		return
	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return

	if resolve_upload_trigger(doc) != "On Submit":
		return

	# Clear any state ERPNext copied from the original onto this return.
	_reset_stale_return_state(doc.doctype, doc.name)
	doc.reload()
	if doc.get("efris_uploaded"):
		return

	try:
		e_invoice_name = _resolve_or_create_e_invoice(doc.doctype, doc.name)
		upload_e_invoice(e_invoice_name)
	except Exception as exc:
		doc.db_set("efris_upload_error", cstr(exc), update_modified=False)
		frappe.msgprint(
			_("EFRIS invoice upload failed: {0}").format(cstr(exc)),
			alert=True,
			indicator="orange",
		)


# -- staging builder ---------------------------------------------------


def _resolve_or_create_e_invoice(source_doctype: str, source_name: str) -> str:
	"""Return an E-Invoice for the source doc, creating one when none exists.

	For credit notes that haven't been accepted by URA yet (Draft / Failed),
	we regenerate the E-Invoice from scratch on retry. The goods structure
	must mirror the original invoice, and an E-Invoice built before that
	rule was enforced would otherwise be retried with the wrong rows.
	"""
	rows = frappe.get_all(
		"E-Invoice",
		filters={"source_doctype": source_doctype, "source_name": source_name},
		fields=["name", "e_invoice_type", "upload_status"],
		order_by="creation desc",
		limit=1,
	)
	existing = rows[0] if rows else None
	if existing:
		if (
			(existing.get("e_invoice_type") or "Invoice") == "Credit Note"
			and (existing.get("upload_status") or "Draft") != "Uploaded"
		):
			frappe.delete_doc("E-Invoice", existing.name, ignore_permissions=True, force=True)
			frappe.db.set_value(
				source_doctype, source_name, "efris_e_invoice", None, update_modified=False
			)
		else:
			return existing.name
	return create_e_invoice(source_doctype, source_name)


@frappe.whitelist()
def create_e_invoice(source_doctype: str, source_name: str) -> str:
	"""Build a draft E-Invoice from a Sales Invoice or POS Invoice."""
	if source_doctype not in ("Sales Invoice", "POS Invoice"):
		frappe.throw(_("E-Invoice source must be Sales Invoice or POS Invoice."))

	src = frappe.get_doc(source_doctype, source_name)
	settings = _settings_for(src)
	if not settings:
		frappe.throw(_("EFRIS Settings not found for company {0}.").format(src.get("company") or ""))

	e_inv = frappe.new_doc("E-Invoice")
	is_credit_note = bool(src.get("is_return"))
	e_inv.e_invoice_type = "Credit Note" if is_credit_note else "Invoice"
	e_inv.source_doctype = source_doctype
	e_inv.source_name = source_name
	e_inv.company = src.company
	e_inv.currency = src.currency
	e_inv.posting_datetime = get_datetime(f"{src.posting_date} {src.get('posting_time') or '00:00:00'}")
	e_inv.reference_no = src.name
	e_inv.remarks = src.get("remarks") or ""

	original_einv_doc = None
	if is_credit_note:
		original_einv_doc = _apply_credit_note_fields(e_inv, src)

	_apply_buyer_fields(e_inv, src)
	if is_credit_note and original_einv_doc:
		_apply_credit_note_lines(e_inv, src, original_einv_doc)
	else:
		_apply_lines(e_inv, src, settings)
	_apply_tax_aggregates(e_inv)
	_apply_totals(e_inv, src)
	_apply_pay_way(e_inv, src)

	e_inv.upload_status = "Draft"
	e_inv.insert(ignore_permissions=True)
	frappe.db.set_value(source_doctype, source_name, "efris_e_invoice", e_inv.name)
	return e_inv.name


# -- additional-invoice precheck --------------------------------------


def _existing_uploaded_einvoices(source_name: str) -> list:
	"""Uploaded, non-credit-note E-Invoices already issued for this source SI."""
	return frappe.get_all(
		"E-Invoice",
		filters={
			"source_name": source_name,
			"upload_status": "Uploaded",
			"e_invoice_type": ("!=", "Credit Note"),
		},
		fields=[
			"name",
			"efris_invoice_id",
			"invoice_kind",
			"net_amount",
			"tax_amount",
			"gross_amount",
			"last_uploaded_on",
		],
		order_by="creation asc",
	)


def _einvoice_has_credit(e_invoice_name: str) -> bool:
	"""True when the E-Invoice carries a Credit (101) pay-way row."""
	modes = frappe.get_all(
		"E-Invoice Pay Way",
		filters={"parent": e_invoice_name, "parenttype": "E-Invoice"},
		pluck="payment_mode",
	)
	return any(_split_select_code(m) == "101" for m in modes)


@frappe.whitelist()
def precheck_additional_invoice(source_doctype: str, source_name: str) -> dict[str, Any]:
	"""Inspect prior EFRIS invoices for an SI before issuing another.

	Returns ``{"exists": False}`` when nothing has been uploaded yet. Otherwise
	reports whether any prior invoice was issued on Credit (``has_credit``), a
	per-invoice breakdown with pay-way rows, and roll-up totals — so the UI can
	*warn* (credit, risk of double-reporting) or show the *summary + payments
	total* (other pay-ways) and prompt before a second upload proceeds.
	"""
	existing = _existing_uploaded_einvoices(source_name)
	if not existing:
		return {"exists": False}

	has_credit = False
	payment_total = 0.0
	efris_gross_total = 0.0
	rows: list[dict[str, Any]] = []
	for einv in existing:
		pay_ways = frappe.get_all(
			"E-Invoice Pay Way",
			filters={"parent": einv.name, "parenttype": "E-Invoice"},
			fields=["payment_mode", "payment_amount"],
			order_by="idx asc",
		)
		if any(_split_select_code(p.payment_mode) == "101" for p in pay_ways):
			has_credit = True
		payment_total += sum(flt(p.payment_amount) for p in pay_ways)
		efris_gross_total += flt(einv.gross_amount)
		rows.append({
			"name": einv.name,
			"efris_invoice_id": einv.efris_invoice_id or "",
			"invoice_kind": _split_select_code(einv.invoice_kind) or "1",
			"net_amount": flt(einv.net_amount),
			"tax_amount": flt(einv.tax_amount),
			"gross_amount": flt(einv.gross_amount),
			"last_uploaded_on": str(einv.last_uploaded_on or ""),
			"pay_ways": [
				{"mode": p.payment_mode or "", "amount": flt(p.payment_amount)}
				for p in pay_ways
			],
		})

	si = frappe.db.get_value(
		source_doctype, source_name, ["grand_total", "outstanding_amount"], as_dict=True
	) or {}

	return {
		"exists": True,
		"has_credit": has_credit,
		"existing": rows,
		"totals": {
			"invoice_count": len(rows),
			"efris_gross_total": efris_gross_total,
			"payment_total": payment_total,
			"si_grand_total": flt(si.get("grand_total")),
			"si_outstanding": flt(si.get("outstanding_amount")),
		},
	}


def _apply_credit_note_fields(e_inv, src):
	"""Resolve the original E-Invoice + FDN; stamp reason and application time.

	Returns the loaded original E-Invoice doc so the caller can mirror its
	goods structure on the credit note (URA requires goods to match the
	original invoice exactly — including the discountFlag=1/0 line pairs).
	"""
	original_si = src.get("return_against")
	if not original_si:
		frappe.throw(_("Credit Note must reference an original Sales Invoice (return_against)."))

	original_einv_name = frappe.db.get_value("Sales Invoice", original_si, "efris_e_invoice")
	if not original_einv_name:
		frappe.throw(
			_("Cannot credit Sales Invoice {0} — it hasn't been uploaded to EFRIS yet.").format(
				original_si
			)
		)
	original_einv = frappe.db.get_value(
		"E-Invoice", original_einv_name, ["name", "efris_invoice_id"], as_dict=True
	)
	if not original_einv or not original_einv.efris_invoice_id:
		frappe.throw(
			_("Original E-Invoice {0} has no EFRIS Invoice ID — upload it before crediting.").format(
				original_einv_name
			)
		)

	# Pull the URA-side internal invoiceId from the original response if we
	# captured it (lives in efris_response_json basicInformation.invoiceId);
	# otherwise fall back to the FDN, which T110 accepts as oriInvoiceId.
	original_internal_id = ""
	raw = frappe.db.get_value("E-Invoice", original_einv_name, "efris_response_json") or ""
	if raw:
		try:
			parsed = json.loads(raw)
			original_internal_id = (parsed.get("basicInformation") or {}).get("invoiceId") or ""
		except Exception:
			original_internal_id = ""

	e_inv.original_e_invoice = original_einv_name
	e_inv.original_invoice_id = original_internal_id or original_einv.efris_invoice_id
	e_inv.original_invoice_no = original_einv.efris_invoice_id
	e_inv.reason_code = src.get("efris_reason_code") or "102 - Cancellation of the purchase"
	e_inv.reason = src.get("efris_reason") or ""
	e_inv.application_time = now_datetime()

	return frappe.get_doc("E-Invoice", original_einv_name)


# Maps Customer.customer_type → E-Invoice.buyer_type select code.
# Defaults to B2C for blanks or any value not in the map.
CUSTOMER_TYPE_TO_BUYER_TYPE = {
	"company": "0 - B2B",
	"partnership": "0 - B2B",
	"individual": "1 - B2C",
	"foreigner": "2 - Foreigner",
	"government": "3 - B2G",
}


def _map_customer_type_to_buyer_type(customer_type: str | None) -> str:
	return CUSTOMER_TYPE_TO_BUYER_TYPE.get((customer_type or "").strip().lower(), "1 - B2C")


def _apply_buyer_fields(e_inv, src) -> None:
	customer = src.get("customer")
	e_inv.customer = customer
	if not customer:
		e_inv.buyer_type = "1 - B2C"
		return

	cust = frappe.get_cached_doc("Customer", customer)
	e_inv.buyer_tin = cust.get("tax_id") or ""
	e_inv.buyer_legal_name = cust.get("efris_legal_name") or cust.customer_name
	e_inv.buyer_business_name = cust.get("efris_business_name") or cust.customer_name
	e_inv.buyer_type = _map_customer_type_to_buyer_type(cust.customer_type)
	e_inv.buyer_email = cust.get("email_id") or ""
	e_inv.buyer_mobile = cust.get("mobile_no") or ""
	e_inv.buyer_address = src.get("customer_address_display") or ""
	e_inv.buyer_place_of_business = src.get("customer_address") or ""


def _apply_lines(e_inv, src, settings) -> None:
	"""Populate the goods child table.

	Combined-item mode (when EFRIS Settings has ``combined_invoice_item`` set)
	collapses every source row's ``amount`` onto one E-Invoice Item line keyed
	to the configured Item's EFRIS goods code; URA recomputes tax via the
	commodity category. Per-line mode emits one row per source line.
	"""
	combined_item = settings.get("combined_invoice_item")
	source_rows = src.get("items") or []
	if not source_rows:
		return

	si_tax_by_row = _si_item_wise_tax(src)

	if combined_item:
		# net_amount is tax-exclusive even when SI uses inclusive pricing
		# (included_in_print_rate=1); falling back to amount keeps it sane
		# when no taxes are applied at all.
		final_net = sum(flt(r.net_amount or r.amount) for r in source_rows)
		# Strip the invoice-level additional discount (apply_discount_on =
		# Grand Total) that ERPNext keeps off the row nets.
		final_net = max(0.0, final_net - _residual_invoice_discount(src, source_rows))
		# Pre-discount net = list price × qty across all rows. Mirrors the
		# per-line branch: for inclusive-tax rows, scale the list rate by
		# ``net_rate/rate`` so we compare exclusive-to-exclusive.
		pre_net = 0.0
		for r in source_rows:
			qty = flt(r.qty) or 1
			pre_rate = flt(r.price_list_rate or r.rate)
			gross_rate = flt(r.rate)
			net_rate = flt(r.net_rate)
			# ERPNext already removed this row's share of any invoice-level
			# additional discount (distributed_discount_amount) from net_rate;
			# add it back so the inclusive-tax scaling ratio reflects tax only
			# and the discount stays visible in pre_net (see per-line branch).
			dist_discount = flt(r.get("distributed_discount_amount"))
			if dist_discount and qty:
				net_rate += dist_discount / qty
			if gross_rate and net_rate and net_rate < gross_rate:
				pre_rate = pre_rate * net_rate / gross_rate
			pre_net += pre_rate * qty
		if pre_net <= 0:
			pre_net = final_net  # nothing to discount against
		item_doc = frappe.get_cached_doc("Item", combined_item)
		cat_code, fallback_rate = _resolve_tax_for_item(item_doc)
		# Prefer the actual SI tax total when present; fall back to the
		# commodity-category rate when the invoice carries no tax rows.
		si_tax_total = sum(flt(t["tax_amount"]) for t in si_tax_by_row.values())
		if si_tax_total and final_net > 0:
			tax_rate = _ratio_as_rate_string(si_tax_total, final_net) or fallback_rate
		else:
			tax_rate = fallback_rate
		# Exempt items (cat 03) must carry tax_rate "-" per URA (error 2833),
		# regardless of what the SI tax inference produced.
		if cat_code == "03":
			tax_rate = "-"

		decimal_rate = _decimal_rate(tax_rate)
		pre_net = round(pre_net, 4)
		final_net = round(final_net, 4)
		pre_tax = round(pre_net * decimal_rate, 4)
		final_tax = round(final_net * decimal_rate, 4)
		disc_tax = round(pre_tax - final_tax, 4)
		pre_gross = round(pre_net + pre_tax, 4)
		final_gross = round(final_net + final_tax, 4)
		disc_gross = round(pre_gross - final_gross, 4)

		goods_code = item_doc.get("efris_goods_code") or combined_item
		stock_uom = item_doc.stock_uom
		uom_code = _code_from_uom(stock_uom)
		category_id = item_doc.get("efris_commodity_category") or ""

		# Aggregated combined discount = (line-level discounts already baked
		# into row.net_amount) + (residual additional discount). Emit URA's
		# discountFlag=1/0 pair when any positive discount exists.
		if pre_net - final_net > 0.01:
			e_inv.append("items", {
				"item_code": combined_item,
				"item_name": item_doc.item_name,
				"goods_code": goods_code,
				"qty": 1,
				"uom": stock_uom,
				"unit_of_measure_code": uom_code,
				"unit_price": pre_gross,
				"total": pre_gross,
				"tax_category_code": cat_code,
				"tax_rate": tax_rate,
				"tax_amount": pre_tax,
				"discount_flag": "1",
				"deemed_flag": "2",
				"excise_flag": "2",
				"vat_applicable_flag": "1",
				"order_number": 0,
				"goods_category_id": category_id,
			})
			e_inv.append("items", {
				"item_code": combined_item,
				"item_name": f"{item_doc.item_name} (Discount)",
				"goods_code": goods_code,
				"qty": 0,
				"uom": stock_uom,
				"unit_of_measure_code": uom_code,
				"unit_price": 0,
				"total": -disc_gross,
				"tax_category_code": cat_code,
				"tax_rate": tax_rate,
				"tax_amount": -disc_tax,
				"discount_flag": "0",
				"deemed_flag": "2",
				"excise_flag": "2",
				"vat_applicable_flag": "1",
				"order_number": 1,
				"goods_category_id": category_id,
			})
		else:
			e_inv.append("items", {
				"item_code": combined_item,
				"item_name": item_doc.item_name,
				"goods_code": goods_code,
				"qty": 1,
				"uom": stock_uom,
				"unit_of_measure_code": uom_code,
				"unit_price": final_gross,
				"total": final_gross,
				"tax_category_code": cat_code,
				"tax_rate": tax_rate,
				"tax_amount": final_tax,
				"discount_flag": "2",
				"deemed_flag": "2",
				"excise_flag": "2",
				"vat_applicable_flag": "1",
				"order_number": 0,
				"goods_category_id": category_id,
			})
		return

	# Residual invoice-level discount that ERPNext didn't push into per-row
	# ``net_amount`` (happens when ``apply_discount_on = Grand Total``).
	# Distribute it onto the first line as an additional discount.
	residual_discount = _residual_invoice_discount(src, source_rows)

	order = 0
	for row in source_rows:
		item_doc = frappe.get_cached_doc("Item", row.item_code)
		cat_code, fallback_rate = _resolve_tax_for_item(item_doc)
		qty = flt(row.qty) or 1

		# Pre-discount net (list price × qty) vs. final net (post line +
		# invoice-level discount that ERPNext baked in). The gap is the
		# row's effective discount for URA's discountFlag=1/0 pair.
		# When a tax row has ``included_in_print_rate=1``, ``price_list_rate``
		# / ``rate`` are tax-inclusive while ``net_amount`` is exclusive —
		# scale the list rate down by ``net_rate/rate`` so we compare
		# exclusive-to-exclusive (otherwise the tax portion looks like a
		# discount and we emit a spurious discountFlag=1/0 pair).
		# ERPNext has already subtracted this row's share of any invoice-level
		# additional discount (``distributed_discount_amount``) from
		# ``net_amount`` / ``net_rate``. Add it back when deriving the
		# inclusive-tax scaling ratio so the ratio reflects tax only — otherwise
		# the discount is folded into the ratio, shrinks ``pre_net`` to match
		# ``final_net``, and never surfaces as a discountFlag=1/0 pair. Folding it
		# into ``pre_net`` this way makes the distributed discount show up as a
		# line discount, exactly like an explicit per-line discount.
		dist_discount = flt(row.get("distributed_discount_amount"))
		pre_rate = flt(row.price_list_rate or row.rate)
		gross_rate = flt(row.rate)
		net_rate = flt(row.net_rate)
		if dist_discount and qty:
			net_rate += dist_discount / qty
		if gross_rate and net_rate and net_rate < gross_rate:
			pre_rate = pre_rate * net_rate / gross_rate
		pre_net = pre_rate * qty
		final_net = flt(row.net_amount or row.amount)
		if row is source_rows[0] and residual_discount:
			final_net = max(0.0, final_net - residual_discount)
		line_discount_net = max(0.0, pre_net - final_net)
		if pre_net <= 0:
			pre_net = final_net  # nothing to discount against; fall back to flat line

		# Resolution priority for line tax rate:
		#   1. Tax amount the SI engine actually computed for this row.
		#   2. Item-level ``item_tax_rate`` JSON on the row.
		#   3. EFRIS Commodity Category rate from the Item.
		row_tax = si_tax_by_row.get(row.name) or si_tax_by_row.get(row.item_code) or {}
		si_tax_amount = flt(row_tax.get("tax_amount"))
		row_rate = _line_item_tax_rate_decimal(row)
		if si_tax_amount and final_net > 0:
			tax_rate = _ratio_as_rate_string(si_tax_amount, final_net) or fallback_rate
		elif row_rate is not None:
			tax_rate = _format_rate_string(row_rate)
		else:
			tax_rate = fallback_rate
		# Exempt items (cat 03) must carry tax_rate "-" per URA (error 2833),
		# even if the SI row has a 0-rate tax entry that would otherwise
		# format as "0".
		if cat_code == "03":
			tax_rate = "-"

		decimal_rate = _decimal_rate(tax_rate)
		# Round to 4dp — URA error 1195 fires if any goodsDetails number
		# carries more than 4 decimals, which happens when the inclusive-tax
		# scaling ratio above leaks floating-point noise into pre_net.
		pre_net = round(pre_net, 4)
		final_net = round(final_net, 4)
		pre_tax = round(pre_net * decimal_rate, 4)
		final_tax = round(final_net * decimal_rate, 4)
		disc_tax = round(pre_tax - final_tax, 4)
		pre_gross = round(pre_net + pre_tax, 4)
		disc_gross = round(pre_gross - (final_net + final_tax), 4)
		display_uom = row.uom or item_doc.stock_uom
		goods_code = item_doc.get("efris_goods_code") or row.item_code

		if line_discount_net > 0:
			# Discounted-item line (discountFlag=1) carries the pre-discount values.
			e_inv.append("items", {
				"item_code": row.item_code,
				"item_name": row.item_name,
				"goods_code": goods_code,
				"qty": qty,
				"uom": display_uom,
				"unit_of_measure_code": _code_from_uom(display_uom),
				"unit_price": pre_gross / qty,
				"total": pre_gross,
				"tax_category_code": cat_code,
				"tax_rate": tax_rate,
				"tax_amount": pre_tax,
				"discount_flag": "1",
				"deemed_flag": "2",
				"excise_flag": "2",
				"vat_applicable_flag": "1",
				"order_number": order,
				"goods_category_id": item_doc.get("efris_commodity_category") or "",
			})
			order += 1
			# Discount line (discountFlag=0) — negative totals, no qty/unitPrice.
			e_inv.append("items", {
				"item_code": row.item_code,
				"item_name": f"{row.item_name or row.item_code} (Discount)",
				"goods_code": goods_code,
				"qty": 0,
				"uom": display_uom,
				"unit_of_measure_code": _code_from_uom(display_uom),
				"unit_price": 0,
				"total": -disc_gross,
				"tax_category_code": cat_code,
				"tax_rate": tax_rate,
				"tax_amount": -disc_tax,
				"discount_flag": "0",
				"deemed_flag": "2",
				"excise_flag": "2",
				"vat_applicable_flag": "1",
				"order_number": order,
				"goods_category_id": item_doc.get("efris_commodity_category") or "",
			})
			order += 1
		else:
			# Non-discount line.
			gross = final_net + final_tax
			e_inv.append("items", {
				"item_code": row.item_code,
				"item_name": row.item_name,
				"goods_code": goods_code,
				"qty": qty,
				"uom": display_uom,
				"unit_of_measure_code": _code_from_uom(display_uom),
				"unit_price": gross / qty,
				"total": gross,
				"tax_category_code": cat_code,
				"tax_rate": tax_rate,
				"tax_amount": final_tax,
				"discount_flag": "2",
				"deemed_flag": "2",
				"excise_flag": "2",
				"vat_applicable_flag": "1",
				"order_number": order,
				"goods_category_id": item_doc.get("efris_commodity_category") or "",
			})
			order += 1


def _apply_credit_note_lines(e_inv, src, original_einv) -> None:
	"""Build credit-note goods rows from the original E-Invoice.

	URA's T110 ``remaining amount`` check (error 1460) compares each credit
	row's ``|total|`` against the *net* (post-discount) remaining of the
	corresponding original line. Replaying the T109 ``discountFlag = 1/0``
	pair on T110 trips that check because the flag=1 line carries the
	pre-discount gross (e.g. 1180) which exceeds the line's net (1000).

	So for each discounted-pair on the original, we **collapse** it into a
	single credit row carrying the net values (flag=1 + flag=0 → flag=2 at
	net = 1000). Non-discount lines mirror 1:1 with negated totals.

	Two scaling modes, both keeping the ``qty × unit_price ≈ total`` invariant:
	  * **Combined-item mode** (single row with ``qty == 1`` — the EFRIS
	    Settings ``combined_invoice_item`` shape): qty stays at -1 and the
	    scale is applied to ``unit_price`` (and total / tax). URA sees one
	    "unit" of the combined invoice line priced at the credited amount.
	  * **Per-line mode**: qty is scaled (fractional for partial returns);
	    ``unit_price`` is preserved.

	Scale factor: ``abs(return.net_total) / original.net_total`` — 1.0 on a
	full return, < 1.0 on a partial return.
	"""
	ratio = _credit_note_scale_ratio(src, original_einv)
	combined_mode = _is_combined_mode_invoice(original_einv)
	rows = list(original_einv.items or [])

	i = 0
	order = 0
	while i < len(rows):
		orig = rows[i]
		flag = orig.discount_flag or "2"
		nxt = rows[i + 1] if i + 1 < len(rows) else None

		if flag == "1" and nxt and (nxt.discount_flag or "") == "0":
			# Collapse the discount pair into a single net-amount row.
			net_total = flt(orig.total) + flt(nxt.total)         # 1180 + (-180) = 1000
			net_tax = flt(orig.tax_amount) + flt(nxt.tax_amount)
			line_qty = flt(orig.qty) or 1
			net_unit_price = (net_total / line_qty) if line_qty else flt(orig.unit_price)
			_append_credit_row(
				e_inv,
				orig,
				order=order,
				ratio=ratio,
				combined_mode=combined_mode,
				orig_qty=line_qty,
				orig_unit_price=net_unit_price,
				orig_total=net_total,
				orig_tax=net_tax,
				discount_flag="2",
			)
			order += 1
			i += 2
			continue

		if flag == "0":
			# Stray discount line with no flag=1 partner — skip; nothing to credit.
			i += 1
			continue

		_append_credit_row(
			e_inv,
			orig,
			order=order,
			ratio=ratio,
			combined_mode=combined_mode,
			orig_qty=flt(orig.qty),
			orig_unit_price=flt(orig.unit_price),
			orig_total=flt(orig.total),
			orig_tax=flt(orig.tax_amount),
			discount_flag=flag,
		)
		order += 1
		i += 1


def _append_credit_row(
	e_inv,
	orig,
	*,
	order: int,
	ratio: float,
	combined_mode: bool,
	orig_qty: float,
	orig_unit_price: float,
	orig_total: float,
	orig_tax: float,
	discount_flag: str,
) -> None:
	"""Append a single credit-note item row with negated, ratio-scaled values."""
	scaled_total = -abs(orig_total) * ratio
	scaled_tax = -abs(orig_tax) * ratio

	if combined_mode:
		# Keep qty at -1 (mirrors original qty=1); scale value via unit_price.
		scaled_qty = -abs(orig_qty) if orig_qty else -1
		scaled_unit_price = abs(orig_unit_price) * ratio
	else:
		scaled_qty = -abs(orig_qty) * ratio
		scaled_unit_price = abs(orig_unit_price)

	e_inv.append("items", {
		"item_code": orig.item_code,
		"item_name": orig.item_name,
		"goods_code": orig.goods_code,
		"qty": scaled_qty,
		"uom": orig.uom,
		"unit_of_measure_code": orig.unit_of_measure_code,
		"unit_price": scaled_unit_price,
		"total": scaled_total,
		"tax_category_code": orig.tax_category_code,
		"tax_rate": orig.tax_rate,
		"tax_amount": scaled_tax,
		"discount_flag": discount_flag,
		"deemed_flag": orig.deemed_flag or "2",
		"excise_flag": orig.excise_flag or "2",
		"vat_applicable_flag": orig.vat_applicable_flag or "1",
		"order_number": order,
		"goods_category_id": orig.goods_category_id or "",
	})


def _is_combined_mode_invoice(original_einv) -> bool:
	"""Detect a T109 emitted via EFRIS Settings ``combined_invoice_item``.

	Combined mode produces a single goods row with ``qty == 1`` and no
	discount-pair structure — that signature uniquely identifies it without
	having to re-read EFRIS Settings (which may have changed since the
	original was uploaded).
	"""
	rows = original_einv.items or []
	if len(rows) != 1:
		return False
	only = rows[0]
	if (only.discount_flag or "") not in ("", "2"):
		return False
	return flt(only.qty) == 1.0


def _credit_note_scale_ratio(src, original_einv) -> float:
	"""Scale factor for partial returns. Defaults to 1.0 (full return)."""
	original_si = src.get("return_against")
	if not original_si:
		return 1.0
	original_net = flt(frappe.db.get_value("Sales Invoice", original_si, "net_total"))
	return_net = abs(flt(src.get("net_total") or 0))
	if original_net <= 0 or return_net <= 0:
		return 1.0
	ratio = return_net / original_net
	# Clamp tiny float drift; a full return often comes in at 1.0000000002.
	if ratio > 1.0:
		ratio = 1.0
	return ratio


def apply_payment_amount_scaling(e_inv, paid_gross: float) -> bool:
	"""Shrink a payment-driven E-Invoice's goods + totals to the amount paid.

	An E-Invoice issued from a Payment Entry should report only what that
	payment settled, not the full Sales Invoice. We proportionally scale every
	goods row and recompute taxDetails + summary so ``gross_amount`` equals
	``paid_gross``. A full or over-payment (ratio >= 1) leaves the invoice
	untouched — we never report more than the sale.

	Mirrors the credit-note scaling (see ``_append_credit_row``): the
	``qty x unit_price ~= total`` invariant is preserved by scaling ``qty`` in
	per-line mode and ``unit_price`` in combined-item mode, and ``tax_rate`` is
	left fixed so ``tax = net x rate`` still holds. Returns True when scaling was
	applied.
	"""
	current_gross = flt(e_inv.gross_amount) or sum(flt(r.total) for r in (e_inv.items or []))
	if current_gross <= 0 or paid_gross <= 0 or paid_gross >= current_gross:
		return False

	ratio = paid_gross / current_gross
	combined_mode = _is_combined_mode_invoice(e_inv)
	for row in e_inv.items or []:
		row.total = round(flt(row.total) * ratio, 4)
		row.tax_amount = round(flt(row.tax_amount) * ratio, 4)
		if combined_mode:
			# Single qty=1 row: keep qty, move the scale onto unit_price.
			row.unit_price = round(flt(row.unit_price) * ratio, 4)
		else:
			# Per-line (incl. discount pairs): scale qty, keep unit_price.
			row.qty = round(flt(row.qty) * ratio, 6)

	_apply_tax_aggregates(e_inv)
	_apply_totals(e_inv, None)
	return True


def _apply_tax_aggregates(e_inv) -> None:
	"""Group goods rows by tax_category_code into the taxDetails block.

	Each E-Invoice Item carries ``total = gross`` and ``tax_amount = tax``,
	so ``net = total - tax`` per row.
	"""
	bucket: dict[tuple[str, str], dict] = {}
	for row in e_inv.items or []:
		key = (row.tax_category_code or "", row.tax_rate or "0")
		b = bucket.setdefault(key, {"net": 0.0, "tax": 0.0, "gross": 0.0})
		gross = flt(row.total)
		tax = flt(row.tax_amount)
		b["gross"] += gross
		b["tax"] += tax
		b["net"] += gross - tax

	e_inv.set("tax_details", [])
	for (cat_code, rate), agg in bucket.items():
		e_inv.append("tax_details", {
			"tax_category_code": cat_code,
			"tax_rate": rate,
			"net_amount": agg["net"],
			"tax_amount": agg["tax"],
			"gross_amount": agg["gross"],
		})


def _apply_totals(e_inv, src) -> None:
	gross = sum(flt(r.total) for r in (e_inv.items or []))
	tax = sum(flt(r.tax_amount) for r in (e_inv.items or []))
	e_inv.net_amount = gross - tax
	e_inv.tax_amount = tax
	e_inv.gross_amount = gross
	# URA: itemCount = total goods rows minus discount (flag=0) rows.
	discount_rows = sum(1 for r in (e_inv.items or []) if (r.discount_flag or "") == "0")
	e_inv.item_count = max(0, len(e_inv.items or []) - discount_rows)


def _apply_pay_way(e_inv, src) -> None:
	"""Single payment line. Cash for POS Invoice, Credit for Sales Invoice.

	Credit rows mirror the E-Invoice ``gross_amount`` (the sum URA expects on
	the goodsDetails side) instead of the SI ``grand_total`` so the two
	always reconcile when ERPNext's grand_total carries rounding or
	non-EFRIS charges that gross_amount doesn't.
	"""
	is_credit = src.doctype != "POS Invoice"
	mode = "101 - Credit" if is_credit else "102 - Cash"
	amount = flt(e_inv.gross_amount) if is_credit else flt(src.get("grand_total") or 0)
	e_inv.append("pay_way", {
		"payment_mode": mode,
		"payment_amount": amount,
		"order_number": "a",
	})


# -- T109 payload ------------------------------------------------------


def _resolve_invoice_kind(e_inv, settings) -> str:
	"""Decide basicInformation.invoiceKind for a T109 upload.

	Receipt (2) when driven by a Payment Entry (stored on the E-Invoice) or for
	POS Invoices; otherwise a plain Invoice (1). A VAT-registered taxpayer (tax
	type 301) must always issue a tax invoice — URA rejects invoiceKind 2 from
	them with return code 2240 — so the receipt kind only survives for non-VAT
	taxpayers.
	"""
	invoice_kind = _split_select_code(e_inv.get("invoice_kind")) or (
		"1" if e_inv.source_doctype == "Sales Invoice" else "2"
	)
	if invoice_kind == "2" and settings and settings.is_vat_registered():
		invoice_kind = "1"
	return invoice_kind


def _build_payload(e_inv) -> dict[str, Any]:
	settings = _settings_for(e_inv)
	invoice_kind = _resolve_invoice_kind(e_inv, settings)

	return {
		"sellerDetails": _seller_block(settings, e_inv),
		"basicInformation": _basic_info_block(settings, e_inv, invoice_kind),
		"buyerDetails": _buyer_block(e_inv),
		"goodsDetails": _build_goods_details(e_inv.items or []),
		"taxDetails": [_tax_row(r) for r in (e_inv.tax_details or [])],
		"summary": _summary_block(e_inv),
		"payWay": [_pay_way_row(r) for r in (e_inv.pay_way or [])],
		"extend": {"reason": "", "reasonCode": ""},
	}


def _build_credit_note_payload(e_inv) -> dict[str, Any]:
	"""T110 envelope. Goods + tax + summary amounts must all be negative.

	ERPNext's ``is_return`` Sales Invoices already carry negative qty/amount
	on every line, so the E-Invoice rows we built come out negative too —
	we just have to take ``-abs(...)`` defensively to enforce URA's sign
	rule even if a row was hand-edited.
	"""
	settings = _settings_for(e_inv)
	app_time = e_inv.application_time or now_datetime()
	app_time_str = app_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(app_time, "strftime") else str(app_time)
	reason_code = _split_select_code(e_inv.reason_code) or "102"

	return {
		"oriInvoiceId": e_inv.original_invoice_id or "",
		"oriInvoiceNo": (e_inv.original_invoice_no or "")[:20],
		"reasonCode": reason_code,
		"reason": (e_inv.reason or "")[:1024],
		"applicationTime": app_time_str,
		"invoiceApplyCategoryCode": "101",
		"currency": e_inv.currency or "UGX",
		"source": "103",
		"remarks": (e_inv.remarks or "")[:500],
		"sellersReferenceNo": (e_inv.reference_no or e_inv.name)[:50],
		"basicInformation": {
			"operator": frappe.utils.get_fullname(frappe.session.user) or frappe.session.user,
			"invoiceKind": "1",
			"invoiceIndustryCode": "101",
			"branchId": settings.branch_id or "" if settings else "",
		},
		"buyerDetails": _buyer_block(e_inv),
		"goodsDetails": _build_credit_note_goods_details(e_inv.items or []),
		"taxDetails": [_credit_note_tax_row(r) for r in (e_inv.tax_details or [])],
		"summary": _credit_note_summary_block(e_inv),
		"payWay": [_pay_way_row(r) for r in (e_inv.pay_way or [])],
	}


def _build_credit_note_goods_details(rows) -> list[dict[str, Any]]:
	"""Emit T110 goodsDetails.

	``_apply_credit_note_lines`` has already collapsed any discount-pair from
	the original into a single net row, so there's no pairing to do here —
	each row is emitted as one flag=2 entry carrying the net credit amount.
	"""
	return [_credit_note_goods_row(row) for row in rows]


def _credit_note_goods_row(row) -> dict[str, Any]:
	"""T110 goodsDetails row — single net-amount line per original commodity.

	Signs are already correct on the row courtesy of ``_apply_credit_note_lines``
	(qty / total / tax are negative). Discount pairs from the original were
	collapsed there, so we never emit ``discountFlag = 0`` rows on T110 —
	URA's per-line remaining-amount check (error 1460) is satisfied by
	sending each line's net credit value directly.
	"""
	return {
		"item": (row.item_name or row.item_code or "")[:200],
		"itemCode": (row.goods_code or row.item_code or "")[:50],
		"qty": _format_number(flt(row.qty or 0)),
		"unitOfMeasure": row.unit_of_measure_code or "",
		"unitPrice": _format_number(abs(flt(row.unit_price or 0))),
		"total": _format_number(flt(row.total or 0)),
		"taxRate": cstr(row.tax_rate or "0"),
		"tax": _format_number(flt(row.tax_amount or 0)),
		"orderNumber": str(row.order_number if row.order_number is not None else 0),
		"discountFlag": row.discount_flag or "2",
		"deemedFlag": row.deemed_flag or "2",
		"exciseFlag": row.excise_flag or "2",
		"goodsCategoryId": row.goods_category_id or "",
		"vatApplicableFlag": row.vat_applicable_flag or "1",
	}


def _credit_note_tax_row(row) -> dict[str, Any]:
	return {
		"taxCategoryCode": row.tax_category_code or "01",
		"netAmount": _format_number(-abs(flt(row.net_amount or 0))),
		"taxRate": cstr(row.tax_rate or "0"),
		"taxAmount": _format_number(-abs(flt(row.tax_amount or 0))),
		"grossAmount": _format_number(-abs(flt(row.gross_amount or 0))),
	}


def _credit_note_summary_block(e_inv) -> dict[str, Any]:
	# itemCount is a positive count, not a signed amount.
	discount_rows = sum(1 for r in (e_inv.items or []) if (r.discount_flag or "") == "0")
	count = max(0, len(e_inv.items or []) - discount_rows) or (e_inv.item_count or 0)
	return {
		"netAmount": _format_number(-abs(flt(e_inv.net_amount or 0))),
		"taxAmount": _format_number(-abs(flt(e_inv.tax_amount or 0))),
		"grossAmount": _format_number(-abs(flt(e_inv.gross_amount or 0))),
		"itemCount": str(count),
		"modeCode": "1",
		"qrCode": "",
	}


def _interpret_credit_note_response(response: Any) -> dict[str, Any]:
	"""T110 returns ``{"referenceNo": "..."}``; map it into the standard state shape."""
	if isinstance(response, dict):
		ref = response.get("referenceNo") or response.get("reference_no") or ""
		if ref:
			return {
				"ok": True,
				"message": "",
				"invoice_id": ref,
				"basic": {"invoiceNo": ref, "antifakeCode": "", "qrCode": ""},
				"summary": {},
			}
	return {"ok": False, "message": "EFRIS did not return a credit-note referenceNo."}


def _build_goods_details(rows) -> list[dict[str, Any]]:
	"""Emit goodsDetails with discountTotal/discountTaxRate on flag=1 lines.

	URA requires the discounted-item line (discountFlag=1) to carry
	``discountTotal`` (negative, equal to the absolute value of the
	immediately-following discountFlag=0 line's total) and
	``discountTaxRate``. We pair each flag=1 row with the next flag=0 row.
	"""
	rows = list(rows)
	out: list[dict[str, Any]] = []
	for i, row in enumerate(rows):
		payload = _goods_row(row)
		if (row.discount_flag or "") == "1":
			nxt = rows[i + 1] if i + 1 < len(rows) else None
			if nxt and (nxt.discount_flag or "") == "0":
				payload["discountTotal"] = _format_number(-abs(flt(nxt.total or 0)))
				payload["discountTaxRate"] = cstr(nxt.tax_rate or row.tax_rate or "0")
		out.append(payload)
	return out


def _seller_block(settings, e_inv) -> dict[str, Any]:
	return {
		"tin": settings.tin or "",
		"ninBrn": settings.brn or "",
		"legalName": (settings.company_legal_name or settings.company or "")[:256],
		"businessName": (settings.company_legal_name or settings.company or "")[:256],
		"address": (settings.company_address or "")[:500],
		"mobilePhone": settings.mobile_phone or "",
		"linePhone": settings.line_phone or "",
		"emailAddress": settings.email_address or "",
		"placeOfBusiness": (settings.place_of_business or "")[:500],
		"referenceNo": (e_inv.reference_no or e_inv.name)[:50],
		"branchId": settings.branch_id or "",
		"isCheckReferenceNo": "0",
	}


def _basic_info_block(settings, e_inv, invoice_kind: str) -> dict[str, Any]:
	issued = e_inv.posting_datetime or now_datetime()
	return {
		"invoiceNo": "",
		"antifakeCode": "",
		"deviceNo": settings.device_no or "",
		"issuedDate": issued.strftime("%Y-%m-%d %H:%M:%S") if hasattr(issued, "strftime") else str(issued),
		"operator": frappe.utils.get_fullname(frappe.session.user) or frappe.session.user,
		"currency": e_inv.currency or "UGX",
		# Empty when raising a plain invoice/receipt; for a debit note it carries
		# the URA invoiceId returned against the original invoice/receipt.
		"oriInvoiceId": cstr(e_inv.get("original_invoice_id") or "")[:20],
		"invoiceType": "1",
		"invoiceKind": invoice_kind,
		"dataSource": "103",
		"invoiceIndustryCode": "101",
		"isBatch": "0",
	}


def _buyer_block(e_inv) -> dict[str, Any]:
	buyer_type = _split_select_code(e_inv.buyer_type) or "1"
	return {
		"buyerTin": e_inv.buyer_tin or "",
		"buyerNinBrn": "",
		"buyerPassportNum": "",
		"buyerLegalName": (e_inv.buyer_legal_name or "")[:256],
		"buyerBusinessName": (e_inv.buyer_business_name or "")[:256],
		"buyerAddress": (e_inv.buyer_address or "")[:500],
		"buyerEmail": e_inv.buyer_email or "",
		"buyerMobilePhone": e_inv.buyer_mobile or "",
		"buyerLinePhone": "",
		"buyerPlaceOfBusi": (e_inv.buyer_place_of_business or "")[:500],
		"buyerType": buyer_type,
		"buyerCitizenship": "",
		"buyerSector": "",
		"buyerReferenceNo": "",
		"nonResidentFlag": "0",
	}


def _goods_row(row) -> dict[str, Any]:
	# URA: when discountFlag=0 (the discount line itself), qty / unitPrice /
	# unitOfMeasure must all be empty — only total and tax (negative) carry.
	is_discount_line = (row.discount_flag or "") == "0"
	return {
		"item": (row.item_name or row.item_code or "")[:200],
		"itemCode": (row.goods_code or row.item_code or "")[:50],
		"qty": "" if is_discount_line else _format_number(row.qty or 0),
		"unitOfMeasure": "" if is_discount_line else (row.unit_of_measure_code or ""),
		"unitPrice": "" if is_discount_line else _format_number(row.unit_price or 0),
		"total": _format_number(row.total or 0),
		"taxRate": cstr(row.tax_rate or "0"),
		"tax": _format_number(row.tax_amount or 0),
		"orderNumber": str(row.order_number if row.order_number is not None else 0),
		"discountFlag": row.discount_flag or "2",
		"deemedFlag": row.deemed_flag or "2",
		"exciseFlag": row.excise_flag or "2",
		"goodsCategoryId": row.goods_category_id or "",
		"vatApplicableFlag": row.vat_applicable_flag or "1",
	}


def _tax_row(row) -> dict[str, Any]:
	return {
		"taxCategoryCode": row.tax_category_code or "01",
		"netAmount": _format_number(row.net_amount or 0),
		"taxRate": cstr(row.tax_rate or "0"),
		"taxAmount": _format_number(row.tax_amount or 0),
		"grossAmount": _format_number(row.gross_amount or 0),
	}


def _summary_block(e_inv) -> dict[str, Any]:
	return {
		"netAmount": _format_number(e_inv.net_amount or 0),
		"taxAmount": _format_number(e_inv.tax_amount or 0),
		"grossAmount": _format_number(e_inv.gross_amount or 0),
		"itemCount": str(e_inv.item_count or len(e_inv.items or [])),
		"modeCode": "1",
		"remarks": (e_inv.remarks or "")[:500],
		"qrCode": "",
	}


def _pay_way_row(row) -> dict[str, Any]:
	# URA caps payWay.paymentAmount at 2 decimal places (error 2266).
	return {
		"paymentMode": _split_select_code(row.payment_mode) or "102",
		"paymentAmount": _format_number(round(flt(row.payment_amount or 0), 2)),
		"orderNumber": row.order_number or "a",
	}


# -- response interpretation ------------------------------------------


def _interpret_response(response: Any) -> dict[str, Any]:
	if not isinstance(response, dict):
		return {"ok": False, "message": "Unexpected EFRIS response shape."}
	basic = response.get("basicInformation") or {}
	invoice_id = basic.get("invoiceId") or basic.get("invoiceID") or ""
	if invoice_id:
		return {"ok": True, "message": "", "invoice_id": invoice_id, "basic": basic, "summary": response.get("summary") or {}}
	# 1040 / 306: already-uploaded mirror inside `existInvoiceList`
	existing = response.get("existInvoiceList") or []
	if isinstance(existing, list) and existing and isinstance(existing[0], dict):
		first = existing[0]
		return {
			"ok": True,
			"message": "Already uploaded.",
			"invoice_id": first.get("invoiceNo") or "",
			"basic": first,
			"summary": response.get("summary") or {},
		}
	return {"ok": False, "message": "EFRIS did not return an invoiceId."}


def _persist_result(e_inv, state: dict[str, Any], response: Any) -> None:
	now = now_datetime()
	if state["ok"]:
		basic = state.get("basic") or {}
		e_inv.db_set("efris_invoice_id", basic.get("invoiceNo") or state.get("invoice_id") or "", update_modified=False)
		e_inv.db_set("efris_antifake_code", basic.get("antifakeCode") or "", update_modified=False)
		e_inv.db_set("efris_currency", basic.get("currency") or "", update_modified=False)
		try:
			currency_rate = flt(basic.get("currencyRate")) if basic.get("currencyRate") not in (None, "") else 0
		except (TypeError, ValueError):
			currency_rate = 0
		e_inv.db_set("efris_currency_rate", currency_rate, update_modified=False)
		e_inv.db_set("efris_qr_code", (response.get("summary") or {}).get("qrCode") or (state.get("basic") or {}).get("qrCode") or "", update_modified=False)
		e_inv.db_set("upload_status", "Uploaded", update_modified=False)
		e_inv.db_set("last_uploaded_on", now, update_modified=False)
		e_inv.db_set("upload_error", "", update_modified=False)
		e_inv.db_set("efris_response_json", json.dumps(response, indent=2)[:65535], update_modified=False)
		_stamp_source(e_inv, basic, response)
	else:
		e_inv.db_set("upload_status", "Failed", update_modified=False)
		e_inv.db_set("upload_error", state.get("message") or "", update_modified=False)


def _persist_failure(e_inv, message: str) -> None:
	e_inv.db_set("upload_status", "Failed", update_modified=False)
	e_inv.db_set("upload_error", message, update_modified=False)


def _stamp_source(e_inv, basic: dict, response: dict) -> None:
	"""Mirror the EFRIS identifiers onto the source Sales / POS Invoice."""
	if not (e_inv.source_doctype and e_inv.source_name):
		return
	frappe.db.set_value(e_inv.source_doctype, e_inv.source_name, {
		"efris_uploaded": 1,
		"efris_invoice_id": basic.get("invoiceNo") or "",
		"efris_antifake_code": basic.get("antifakeCode") or "",
		"efris_qr_code": (response.get("summary") or {}).get("qrCode") or "",
		"efris_last_uploaded_on": now_datetime(),
		"efris_upload_error": "",
		"efris_e_invoice": e_inv.name,
	})


# -- helpers -----------------------------------------------------------


def _settings_for(doc):
	from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

	try:
		return get_efris_settings(doc.get("company"))
	except Exception:
		return None


def _split_select_code(value) -> str:
	if not value:
		return ""
	return str(value).strip().split(" ", 1)[0]


def _resolve_tax_for_item(item_doc) -> tuple[str, str]:
	"""Map Item → (tax_category_code, tax_rate) via its EFRIS Commodity Category.

	Falls back to ``("01", "0.18")`` (Standard VAT 18%) when the Item has no
	commodity mapping or the category is unflagged.
	"""
	cat_link = item_doc.get("efris_commodity_category") if item_doc else ""
	if not cat_link:
		return ("01", "0.18")
	cat = frappe.db.get_value(
		"EFRIS Commodity Category",
		cat_link,
		["rate", "is_zero_rate", "is_exempt"],
		as_dict=True,
	) or {}

	if cat.get("is_exempt"):
		return ("03", "-")
	if cat.get("is_zero_rate"):
		return ("02", "0")
	rate = cat.get("rate")
	if rate in (None, ""):
		return ("01", "0.18")
	try:
		rate_f = float(rate)
	except Exception:
		return ("01", "0.18")
	# URA wants the decimal form (0.18, not 18). If we got 18, divide.
	if rate_f > 1:
		rate_f = rate_f / 100.0
	return ("01", f"{rate_f:.4f}".rstrip("0").rstrip("."))


def _si_item_wise_tax(src) -> dict[str, dict]:
	"""Sum each Sales Invoice line's tax from ``Sales Invoice.taxes``.

	ERPNext stores per-row tax breakdown in ``Sales Invoice Taxes and
	Charges.item_wise_tax_detail`` as a JSON dict keyed by item_code or row
	name → ``[rate, tax_amount]``. We collapse it across all tax rows so a
	single item with multiple tax components (VAT + Excise etc.) gets one
	total per row.

	Returns ``{row_name_or_item_code: {"tax_amount": float, "rate_sum": float}}``.
	"""
	out: dict[str, dict] = {}
	for tax in (src.get("taxes") or []):
		detail = tax.get("item_wise_tax_detail")
		if not detail:
			continue
		try:
			parsed = json.loads(detail) if isinstance(detail, str) else detail
		except Exception:
			continue
		if not isinstance(parsed, dict):
			continue
		for key, value in parsed.items():
			if not isinstance(value, (list, tuple)) or len(value) < 2:
				continue
			rate = flt(value[0])
			amount = flt(value[1])
			bucket = out.setdefault(key, {"tax_amount": 0.0, "rate_sum": 0.0})
			bucket["tax_amount"] += amount
			bucket["rate_sum"] += rate
	return out


def _residual_invoice_discount(src, source_rows) -> float:
	"""Invoice-level discount that ERPNext did not propagate into row ``net_amount``.

	When ``apply_discount_on = Grand Total`` (or a flat ``discount_amount``
	is set), ERPNext keeps row-level nets at their pre-additional-discount
	value and only reduces the totals. Catch any gap so URA still sees the
	right net per line. Returns 0 when ERPNext already distributed.
	"""
	rows_net = sum(flt(r.net_amount or r.amount) for r in (source_rows or []))
	si_net = flt(src.get("net_total") or src.get("base_net_total") or 0)
	if not rows_net or not si_net:
		return 0.0
	gap = rows_net - si_net
	if gap > 0.01:
		return gap
	return 0.0


def _decimal_rate(tax_rate_str) -> float:
	"""``"0.18"`` → ``0.18``; ``"-"`` / blank / non-numeric → ``0``."""
	if not tax_rate_str or tax_rate_str in ("-", " "):
		return 0.0
	try:
		r = float(tax_rate_str)
	except Exception:
		return 0.0
	if r > 1:
		r = r / 100.0
	return r


def _line_item_tax_rate_decimal(row) -> float | None:
	"""Read an ERPNext Sales Invoice Item's ``item_tax_rate`` JSON.

	The field is a JSON map ``{tax_account: rate_percent}`` — sum the rates
	and convert to URA's decimal form (18 → 0.18). Returns ``None`` when no
	row-level override exists, so the caller can fall through.
	"""
	raw = row.get("item_tax_rate")
	if not raw:
		return None
	try:
		parsed = json.loads(raw) if isinstance(raw, str) else raw
	except Exception:
		return None
	if not isinstance(parsed, dict) or not parsed:
		return None
	total_pct = sum(flt(v) for v in parsed.values())
	if total_pct <= 0:
		return 0.0
	return total_pct / 100.0


def _format_rate_string(decimal_rate: float) -> str:
	"""Format ``0.18`` style decimal rate for URA — trim trailing zeros."""
	if decimal_rate <= 0:
		return "0"
	return f"{decimal_rate:.4f}".rstrip("0").rstrip(".")


def _ratio_as_rate_string(tax: float, net: float) -> str:
	"""Express ``tax / net`` as URA's decimal rate string (e.g. ``0.18``)."""
	if not net:
		return ""
	r = flt(tax) / flt(net)
	if r <= 0:
		return ""
	return f"{r:.4f}".rstrip("0").rstrip(".")


def _line_tax(amount: float, tax_rate: str) -> float:
	"""Compute the tax amount for a line using a stringified rate."""
	if not tax_rate or tax_rate in ("-", " "):
		return 0.0
	try:
		r = float(tax_rate)
	except Exception:
		return 0.0
	if r > 1:
		r = r / 100.0
	return flt(amount) * r
