"""Typed wrappers for the EFRIS interface codes (T101–T139).

Each function is a thin wrapper over ``EFRISClient.call`` for one interface
code. Simple interfaces (server time, TIN lookup, dictionary sync) build their
own payloads here. Document-driven interfaces (T109/T110/T130/T131) accept a
prebuilt payload dict, since assembling it from an ERPNext document belongs in
the ``overrides`` layer.

EFRIS Settings are company-specific: pass ``company`` to target a particular
company, or an existing ``client`` to reuse one. When neither is given the
caller's default company is used.

T104 (symmetric key exchange) is no longer exposed here — the AES key is
fetched fresh inside ``EFRISClient.call`` per request.
"""

from __future__ import annotations

import frappe

from efris.efris.api.client import EFRISClient


def _client(client: EFRISClient | None = None, company: str | None = None) -> EFRISClient:
	return client or EFRISClient(company=company)


# -- Session / setup ----------------------------------------------------


def get_server_time(company: str | None = None, client: EFRISClient | None = None) -> dict:
	"""T101 — get EFRIS server time. Useful as a connectivity health check."""
	return _client(client, company).call("T101")


def login(company: str | None = None, client: EFRISClient | None = None) -> dict:
	"""T103 — log in / initialise a taxpayer session."""
	return _client(client, company).call("T103")


def fetch_taxpayer_details(
	company: str | None = None, client: EFRISClient | None = None, save: bool = True
) -> dict:
	"""T103 — log in and retrieve the taxpayer / device / branch profile.

	The T103 response carries the taxpayer profile, device info, branch and a
	large block of configuration flags. When ``save`` is set, the full response
	is dumped to EFRIS Settings (``taxpayer_details_json``) and the registered
	tax types are written to the ``tax_types`` child table.
	"""
	import json as _json

	c = _client(client, company)
	result = c.call("T103")

	if save:
		settings = c.settings
		settings.taxpayer_details_json = _json.dumps(result, indent=2)

		taxpayer = result.get("taxpayer") or {}
		branch = result.get("taxpayerBranch") or {}
		for field, value in (
			("tin", taxpayer.get("tin")),
			("brn", taxpayer.get("ninBrn")),
			("company_legal_name", taxpayer.get("legalName") or taxpayer.get("businessName")),
			("place_of_business", (taxpayer.get("placeOfBusiness") or "").strip()),
			("mobile_phone", taxpayer.get("contactNumber")),
			("email_address", taxpayer.get("contactEmail")),
			("branch_id", branch.get("id")),
			("branch_code", branch.get("branchCode")),
			("branch_name", branch.get("branchName")),
		):
			if value:
				settings.set(field, value)

		# Branch placeOfBusiness is more specific than the taxpayer-level one;
		# prefer it when present.
		branch_place = (branch.get("placeOfBusiness") or "").strip()
		if branch_place:
			settings.set("place_of_business", branch_place)

		# Preserve any user-set Account mapping across refreshes — only the
		# EFRIS-supplied fields are overwritten.
		existing_accounts = {
			row.tax_type_code: row.account for row in (settings.tax_types or []) if row.tax_type_code
		}
		settings.set("tax_types", [])
		for tax_type in result.get("taxType") or []:
			code = tax_type.get("taxTypeCode")
			settings.append(
				"tax_types",
				{
					"tax_type_name": tax_type.get("taxTypeName"),
					"tax_type_code": code,
					"registration_date": tax_type.get("registrationDate"),
					"cancellation_date": tax_type.get("cancellationDate"),
					"account": existing_accounts.get(code),
				},
			)
		settings.save(ignore_permissions=True)

	return result


def get_branches(company: str | None = None, client: EFRISClient | None = None) -> dict:
	"""T138 — list all branches registered for the taxpayer."""
	return _client(client, company).call("T138")


def upload_certificate(
	file_name: str,
	verify_string: str,
	file_content_b64: str,
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T136 — upload a certificate public key (.crt / .cer)."""
	payload = {
		"fileName": file_name,
		"verifyString": verify_string,
		"fileContent": file_content_b64,
	}
	return _client(client, company).call("T136", payload)


# -- Dictionary / reference data ---------------------------------------


def sync_dictionary(company: str | None = None, client: EFRISClient | None = None) -> dict:
	"""T115 — system dictionary update (UoM, currencies, tax categories, …)."""
	return _client(client, company).call("T115")


def get_excise_duty(company: str | None = None, client: EFRISClient | None = None) -> dict:
	"""T125 — query the full Excise Duty catalogue (URA reference data)."""
	return _client(client, company).call("T125")


def get_commodity_categories(
	company: str | None = None, client: EFRISClient | None = None
) -> list:
	"""T123 — full Commodity Category catalogue, unpaginated."""
	return _client(client, company).call("T123")


def get_commodity_categories_page(
	page_no: int = 1,
	page_size: int = 100,
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T124 — paginated Commodity Category catalogue.

	URA caps ``pageSize`` at 100. Returns ``{"page": {...}, "records": [...]}``.
	"""
	if page_size > 100:
		page_size = 100
	payload = {"pageNo": str(page_no), "pageSize": str(page_size)}
	return _client(client, company).call("T124", payload)


def get_exchange_rates(
	currency: str = "",
	issue_date: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T121 — EFRIS exchange rates, optionally scoped to a currency / date.

	``issue_date`` must be ``YYYY-MM-DD``; URA rejects other formats.
	"""
	payload: dict = {}
	if currency:
		payload["currency"] = currency
	if issue_date:
		payload["issueDate"] = issue_date
	return _client(client, company).call("T121", payload)


# -- Validation ---------------------------------------------------------


def validate_tin(
	tin: str, nin_brn: str = "", company: str | None = None, client: EFRISClient | None = None
) -> dict:
	"""T119 — validate a taxpayer TIN against URA records."""
	return _client(client, company).call("T119", {"tin": tin, "ninBrn": nin_brn})


def query_goods_stock(
	goods_id: str,
	branch_id: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T128 — query the on-hand stock for a goods by EFRIS goods id."""
	payload = {"id": goods_id, "branchId": branch_id or ""}
	return _client(client, company).call("T128", payload)


def inquire_goods(
	goods_code: str = "", company: str | None = None, client: EFRISClient | None = None
) -> dict:
	"""T127 — query goods/services already registered on EFRIS."""
	payload = {"goodsCode": goods_code} if goods_code else {}
	return _client(client, company).call("T127", payload)


# -- Document-driven interfaces ----------------------------------------
# These accept a prebuilt payload; the overrides layer assembles it from the
# ERPNext document (Sales Invoice, Item, Stock Entry, …).


def upload_invoice(
	payload: dict,
	reference_no: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T109 — upload a fiscal invoice."""
	return _client(client, company).call("T109", payload, reference_no=reference_no)


def upload_invoice_batch(
	entries: list[dict],
	company: str | None = None,
	client: EFRISClient | None = None,
) -> list | dict:
	"""T129 — Batch Invoice Upload.

	``entries`` is a list of ``{"invoiceContent": <b64 T109 JSON>,
	"invoiceSignature": <b64 RSA sig over invoiceContent>}`` dicts. URA returns
	a parallel list of ``{"invoiceContent", "invoiceReturnCode",
	"invoiceReturnMessage"}`` — a per-entry ``invoiceReturnCode`` of ``99``
	means that single entry failed (detail in ``invoiceContent``); other
	entries in the same batch may still succeed.
	"""
	return _client(client, company).call("T129", entries)


def upload_credit_note(
	payload: dict,
	reference_no: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T110 — upload a credit note against an existing invoice."""
	return _client(client, company).call("T110", payload, reference_no=reference_no)


def approve_credit_note(
	payload: dict,
	reference_no: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T113 — approve a previously submitted credit note."""
	return _client(client, company).call("T113", payload, reference_no=reference_no)


def upload_goods(
	payload: dict,
	reference_no: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T130 — register or update a good/service in the EFRIS goods registry."""
	return _client(client, company).call("T130", payload, reference_no=reference_no)


def maintain_stock(
	payload: dict,
	reference_no: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T131 — stock-in / stock maintenance against the EFRIS inventory."""
	return _client(client, company).call("T131", payload, reference_no=reference_no)


def inquire_goods_by_codes(
	goods_codes: list[str] | str,
	tin: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> list | dict:
	"""T144 — batch goods inquiry by goodsCode (comma-separated)."""
	if isinstance(goods_codes, (list, tuple, set)):
		codes_csv = ",".join(c for c in (str(x).strip() for x in goods_codes) if c)
	else:
		codes_csv = (goods_codes or "").strip()
	payload = {"goodsCode": codes_csv, "tin": tin or ""}
	return _client(client, company).call("T144", payload)


def query_stock_records(
	production_batch_no: str = "",
	invoice_no: str = "",
	reference_no: str = "",
	page_no: int = 1,
	page_size: int = 10,
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T145 — query the EFRIS goods stock records page.

	URA requires at least one of ``productionBatchNo`` / ``invoiceNo`` /
	``referenceNo`` to be set. ``pageSize`` is capped at 100.
	"""
	if page_size > 100:
		page_size = 100
	payload = {
		"productionBatchNo": production_batch_no or "",
		"invoiceNo": invoice_no or "",
		"referenceNo": reference_no or "",
		"pageNo": str(page_no or 1),
		"pageSize": str(page_size or 10),
	}
	return _client(client, company).call("T145", payload)


def query_branch_stock_records(
	combine_keywords: str = "",
	stock_in_type: str = "",
	start_date: str = "",
	end_date: str = "",
	supplier_tin: str = "",
	supplier_name: str = "",
	page_no: int = 1,
	page_size: int = 10,
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T147 — query stock records for the current branch (date / keyword filters)."""
	if page_size > 100:
		page_size = 100
	payload = {
		"combineKeywords": combine_keywords or "",
		"stockInType": stock_in_type or "",
		"startDate": start_date or "",
		"endDate": end_date or "",
		"supplierTin": supplier_tin or "",
		"supplierName": supplier_name or "",
		"pageNo": str(page_no or 1),
		"pageSize": str(page_size or 10),
	}
	return _client(client, company).call("T147", payload)


def query_credit_note_applications(
	reference_no: str = "",
	ori_invoice_no: str = "",
	invoice_no: str = "",
	combine_keywords: str = "",
	approve_status: str = "",
	query_type: str = "1",
	invoice_apply_category_code: str = "",
	start_date: str = "",
	end_date: str = "",
	page_no: int = 1,
	page_size: int = 10,
	credit_note_type: str = "1",
	branch_name: str = "",
	seller_tin_or_nin: str = "",
	seller_legal_or_business_name: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T111 — Credit/Cancel Debit Note Application List Query.

	``queryType``: 1 own applications, 2 to-do (approver), 3 approved by me.
	``approveStatus``: 101 Approved, 102 Submitted, 103 Rejected, 104 Voided
	(CSV allowed, e.g. ``"101,102"``).
	``invoiceApplyCategoryCode``: 101 credit note, 103 cancel debit note (CSV allowed).
	``creditNoteType``: 1 Credit Note (default), 2 Credit Note Without FDN.
	"""
	if page_size > 100:
		page_size = 100
	payload = {
		"referenceNo": reference_no or "",
		"oriInvoiceNo": ori_invoice_no or "",
		"invoiceNo": invoice_no or "",
		"combineKeywords": combine_keywords or "",
		"approveStatus": approve_status or "",
		"queryType": str(query_type or "1"),
		"invoiceApplyCategoryCode": invoice_apply_category_code or "",
		"startDate": start_date or "",
		"endDate": end_date or "",
		"pageNo": str(page_no or 1),
		"pageSize": str(page_size or 10),
		"creditNoteType": str(credit_note_type or "1"),
		"branchName": branch_name or "",
		"sellerTinOrNin": seller_tin_or_nin or "",
		"sellerLegalOrBusinessName": seller_legal_or_business_name or "",
	}
	import json as _json

	response = _client(client, company).call("T111", payload)
	try:
		frappe.logger("efris", allow_site=True).info(
			"T111 query %s → response: %s",
			_json.dumps(payload, separators=(",", ":")),
			_json.dumps(response, indent=2)[:16000],
		)
	except Exception:
		pass
	return response


def get_credit_note_details(
	application_id: str,
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T112 — Credit Note Application details by application ``id``.

	The ``id`` is the URA application id returned by T111 records — not the
	EFRIS Invoice FDN. Use :func:`query_credit_note_applications` first to
	resolve it from a referenceNo / oriInvoiceNo when not stored locally.

	Logs the decrypted response under the ``efris`` logger (bench log
	``logs/efris.log``) so the raw URA payload can be inspected without
	cluttering Error Log.
	"""
	import json as _json

	response = _client(client, company).call("T112", {"id": str(application_id)})
	try:
		frappe.logger("efris", allow_site=True).info(
			"T112 response (app %s): %s",
			application_id,
			_json.dumps(response, indent=2)[:16000],
		)
	except Exception:
		pass
	return response


def void_credit_note_application(
	business_key: str,
	reference_no: str,
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T120 — Void a Credit / Debit Note application.

	``business_key`` is the T111 record ``id`` (application id) and
	``reference_no`` is the T111 record ``referenceNo`` (the seller-side
	reference we originally sent on T110).
	"""
	payload = {
		"businessKey": str(business_key),
		"referenceNo": str(reference_no),
	}
	return _client(client, company).call("T120", payload, reference_no=str(reference_no))


def cancel_credit_note_application(
	payload: dict,
	reference_no: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T114 — Cancel a Credit Note / initiate Cancel-of-Debit-Note application.

	``invoiceApplyCategoryCode``:
	  * ``103`` cancel-of-debit-note (initiates a workflow / debit note)
	  * ``104`` cancel-of-credit-note (no workflow; flips invoice status)
	  * ``105`` cancel-of-credit-memo
	"""
	return _client(client, company).call("T114", payload, reference_no=reference_no)


def get_credit_note_application_details(
	application_id: str,
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T118 — Query Credit/Cancel-Debit Note Application line details by ``id``.

	Where T112 returns the application header / status, T118 returns the
	full ``goodsDetails`` / ``taxDetails`` / ``summary`` / ``payWay`` /
	``basicInformation`` blocks for the application.
	"""
	return _client(client, company).call("T118", {"id": str(application_id)})


def transfer_stock(
	payload: dict,
	reference_no: str = "",
	company: str | None = None,
	client: EFRISClient | None = None,
) -> dict:
	"""T139 — inter-branch stock transfer."""
	return _client(client, company).call("T139", payload, reference_no=reference_no)
