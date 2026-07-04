"""T130 Goods Upload — push ERPNext Items to EFRIS.

Public surface:
  * ``upload_item(name)`` — whitelisted; loads the Item, builds the T130
    payload, calls URA, and persists the result (success state or error
    message).
  * ``auto_upload_on_save(doc, _method)`` — Item ``on_update`` hook. Calls
    ``upload_item`` only when an EFRIS-mapped field has actually changed,
    swallows failures into a non-blocking alert.

Field mapping notes:
  * ``measureUnit`` comes from ``stock_uom.efris_dictionary`` (a Link to
    EFRIS Dictionary in category ``rateUnit``).
  * ``currency`` comes from the Company default currency's
    ``efris_dictionary``.
  * The EFRIS Dictionary autoname is ``{category}-{code}``; we strip the
    category prefix to recover the raw EFRIS code URA expects.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

from efris.efris.api.client import EFRISError, efris_errors
from efris.efris.api.interfaces import inquire_goods as call_t127
from efris.efris.api.interfaces import query_goods_stock as call_t128
from efris.efris.api.interfaces import upload_goods as call_t130


# Item fields whose change should trigger a re-upload.
_TRACKED_FIELDS = (
	"item_name",
	"item_code",
	"description",
	"stock_uom",
	"standard_rate",
	"valuation_rate",
	"disabled",
	"efris_goods_code",
	"efris_commodity_category",
	"efris_goods_type",
	"efris_stock_prewarning",
	"efris_have_excise_tax",
	"efris_excise_duty_code",
	"efris_have_piece_unit",
	"efris_piece_measure_unit",
	"efris_piece_unit_price",
	"efris_package_scaled_value",
	"efris_piece_scaled_value",
	"efris_have_customs_unit",
	"uoms",
)


# -- public ------------------------------------------------------------


@frappe.whitelist()
def upload_item(name: str) -> dict[str, Any]:
	"""Upload one Item to EFRIS via T130 and persist the response state.

	Raises on hard configuration errors (missing UOM mapping, missing
	currency mapping, no EFRIS Settings) so the user can fix the inputs.
	On EFRIS-level failures (per-entry ``returnMessage`` or transport
	exceptions), the error is stored on the item and a Frappe error is
	raised — appropriate for the button flow where the user is waiting.
	"""
	item = frappe.get_doc("Item", name)
	missing = _missing_required(item)
	if missing:
		frappe.throw(_("Cannot upload to EFRIS — missing: {0}").format(", ".join(missing)))

	payload = _build_payload(item)
	operation_type = payload["operationType"]

	try:
		response = call_t130([payload])
	except EFRISError as exc:
		# URA already has this goodsCode (code 602 / "already exists"). Locally
		# we hadn't marked it uploaded, so we sent operationType=101. Retry as
		# an update (102) once — that's what the user effectively means.
		if operation_type == "101" and _already_exists_upstream(exc):
			payload["operationType"] = "102"
			operation_type = "102"
			with efris_errors(_("EFRIS Goods Upload Failed")):
				response = call_t130([payload])
		# Inverse: T127 probe or local flag said the item exists upstream, but
		# T130 came back 684 / "does not exist". Happens after the EFRIS
		# Settings account is repointed at a TIN the goodsCode was never sent
		# to. Retry as a fresh upload (101) and clear the now-bogus local
		# uploaded flag.
		elif operation_type == "102" and _product_does_not_exist(exc):
			payload["operationType"] = "101"
			operation_type = "101"
			_set_state_db(item, uploaded=0)
			with efris_errors(_("EFRIS Goods Upload Failed")):
				response = call_t130([payload])
		else:
			with efris_errors(_("EFRIS Goods Upload Failed")):
				raise

	state = _interpret_response(response)
	_persist_result(item, operation_type, state)

	if state["ok"]:
		frappe.msgprint(
			_("EFRIS confirmed {0} ({1}).").format(item.name, payload["goodsCode"]),
			alert=True,
			indicator="green",
		)
	else:
		frappe.throw(
			_("EFRIS rejected the upload: {0}").format(state["message"] or "(no message)")
		)
	return state


@frappe.whitelist()
def query_item_stock(name: str) -> dict[str, Any]:
	"""T128 — return on-hand stock for an Item.

	URA's T128 takes an EFRIS goods id, not the local goodsCode, so we first
	resolve the id via T127, then call T128. ``branchId`` is taken from the
	Item's Company EFRIS Settings.
	"""
	from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

	item = frappe.get_doc("Item", name)
	goods_code = (item.get("efris_goods_code") or item.item_code or "")[:50]
	if not goods_code:
		frappe.throw(_("Item has no EFRIS goods code to query."))

	with efris_errors(_("EFRIS Goods Stock Query Failed")):
		t127_response = call_t127(goods_code=goods_code)

	record = _first_goods_record(t127_response)
	if not record:
		return {
			"found": False,
			"goods_code": goods_code,
			"message": _("Item not found on EFRIS — upload it first."),
		}

	goods_id = (
		record.get("id")
		or record.get("commodityGoodsId")
		or record.get("goodsId")
		or ""
	)
	if not goods_id:
		return {
			"found": False,
			"goods_code": goods_code,
			"message": _("EFRIS did not return a goods id for this item."),
		}

	settings = get_efris_settings()
	branch_id = settings.branch_id or ""

	with efris_errors(_("EFRIS Goods Stock Query Failed")):
		t128_response = call_t128(goods_id=goods_id, branch_id=branch_id)

	stock_payload = t128_response if isinstance(t128_response, dict) else {}
	return {
		"found": True,
		"goods_code": goods_code,
		"goods_id": goods_id,
		"branch_id": branch_id,
		"stock": stock_payload.get("stock"),
		"stock_prewarning": stock_payload.get("stockPrewarning"),
		"raw": stock_payload,
	}


@frappe.whitelist()
def query_item(name: str) -> dict[str, Any]:
	"""T127 — look up an Item on EFRIS by its goodsCode.

	Returns ``{"found": bool, "record": dict | None, "goods_code": str}``.
	A missing entry is not an error — URA returns an empty list and we report
	``found: False`` so the JS caller can show a clean status.
	"""
	item = frappe.get_doc("Item", name)
	goods_code = (item.get("efris_goods_code") or item.item_code or "")[:50]
	if not goods_code:
		frappe.throw(_("Item has no EFRIS goods code to query."))

	with efris_errors(_("EFRIS Goods Query Failed")):
		response = call_t127(goods_code=goods_code)

	record = _first_goods_record(response)
	return {"found": record is not None, "record": record, "goods_code": goods_code}


def _first_goods_record(response: Any) -> dict | None:
	"""Pluck the first goods record out of a T127 response, whatever its shape."""
	if isinstance(response, list):
		return response[0] if response and isinstance(response[0], dict) else None
	if isinstance(response, dict):
		if "goodsCode" in response or "goodsName" in response:
			return response
		for value in response.values():
			if isinstance(value, list) and value and isinstance(value[0], dict):
				return value[0]
			if isinstance(value, dict) and ("goodsCode" in value or "goodsName" in value):
				return value
	return None


def _already_exists_upstream(exc: EFRISError) -> bool:
	"""Detect URA's 'goodsCode already exists' rejection from a T130 EFRISError.

	URA returns it as a per-entry 602 inside an overall code-45 response. The
	per-entry JSON is embedded in ``exc.message`` by ``EFRISClient.call``.
	"""
	msg = (exc.message or "").lower()
	return "already exists" in msg or '"returncode": "602"' in msg.lower()


def _product_does_not_exist(exc: EFRISError) -> bool:
	"""Detect URA's 'product does not exist' rejection from a T130 EFRISError.

	Symmetric counterpart to ``_already_exists_upstream``. URA returns this as
	a per-entry 684 inside an overall code-45 response when we send
	``operationType=102`` for a goodsCode the current TIN has never seen —
	typically after an EFRIS Settings account switch.
	"""
	msg = (exc.message or "").lower()
	return "does not exist" in msg or '"returncode": "684"' in msg


def _probe_operation_type(doc) -> str:
	"""Ask URA via T127 whether this goodsCode is already registered.

	Returns ``"102"`` (update) when T127 finds the record, ``"101"`` (new)
	otherwise. URA's view is authoritative — it survives EFRIS Settings being
	repointed at a different TIN, which the local ``efris_uploaded`` flag does
	not. On any T127 failure we fall back to the local-flag heuristic so an
	upstream blip never blocks an upload.
	"""
	goods_code = (doc.get("efris_goods_code") or doc.get("item_code") or "")[:50]
	if not goods_code:
		return "101"
	try:
		response = call_t127(goods_code=goods_code)
	except Exception as exc:
		frappe.log_error(
			message=cstr(exc),
			title=f"EFRIS T127 probe failed for {doc.get('name') or goods_code}",
		)
		return "102" if doc.get("efris_uploaded") else "101"
	return "102" if _first_goods_record(response) is not None else "101"


def sync_piece_unit_from_uoms(doc, _method=None) -> None:
	"""Mirror the stock-UOM row's EFRIS values onto the Item's piece-unit fields.

	When a row in ``Item.uoms`` matches the Item's ``stock_uom``, treat it as
	the EFRIS "piece" unit: copy its EFRIS price/scaled values up to the Item
	and turn ``efris_have_piece_unit`` on. Runs on Item ``validate`` so it
	persists with the save.
	"""
	stock_uom = doc.get("stock_uom")
	if not stock_uom:
		return

	row = next((r for r in (doc.get("uoms") or []) if r.uom == stock_uom), None)
	if not row:
		return

	measure_unit = frappe.db.get_value("UOM", stock_uom, "efris_dictionary") or ""
	if not measure_unit:
		# UOM not mapped — leave the fields alone; goods.py validation will
		# surface this when the user uploads.
		return

	doc.efris_have_piece_unit = 1
	doc.efris_piece_measure_unit = measure_unit
	doc.efris_piece_unit_price = row.get("efris_unit_price") or 0
	doc.efris_piece_scaled_value = row.get("efris_package_scaled") or 1


def auto_upload_on_save(doc, _method=None) -> None:
	"""Doc-event hook: re-upload to EFRIS when an EFRIS-mapped field changes.

	Never blocks the Item save:
	  * Skips silently when EFRIS Settings isn't enabled, the item is
	    disabled, or nothing relevant has changed.
	  * Records missing-required-field reasons on ``efris_upload_error``
	    without erroring.
	  * Network / URA errors land in ``efris_upload_error`` and surface as
	    an orange alert.
	"""
	if doc.get("disabled"):
		return
	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return

	already_uploaded = bool(doc.get("efris_uploaded"))
	if already_uploaded and not _any_tracked_field_changed(doc):
		return

	missing = _missing_required(doc)
	if missing:
		_set_state_db(
			doc,
			error=_("Missing required EFRIS fields: {0}").format(", ".join(missing)),
		)
		return

	try:
		payload = _build_payload(doc)
		operation_type = payload["operationType"]
		try:
			response = call_t130([payload])
		except EFRISError as exc:
			# Same two-direction retry as upload_item — see comments there.
			if operation_type == "101" and _already_exists_upstream(exc):
				payload["operationType"] = "102"
				operation_type = "102"
				response = call_t130([payload])
			elif operation_type == "102" and _product_does_not_exist(exc):
				payload["operationType"] = "101"
				operation_type = "101"
				_set_state_db(doc, uploaded=0)
				response = call_t130([payload])
			else:
				raise
		state = _interpret_response(response)
	except (EFRISError, Exception) as exc:
		_set_state_db(doc, error=cstr(exc))
		frappe.msgprint(
			_("EFRIS upload failed: {0}").format(cstr(exc)),
			alert=True,
			indicator="orange",
		)
		return

	if state["ok"]:
		_set_state_db(
			doc,
			uploaded=1,
			operation_type=operation_type,
			error="",
		)
	else:
		_set_state_db(doc, error=state["message"] or "(no message)")
		frappe.msgprint(
			_("EFRIS rejected the upload: {0}").format(state["message"]),
			alert=True,
			indicator="orange",
		)


# -- internals ---------------------------------------------------------


def _any_tracked_field_changed(doc) -> bool:
	for fld in _TRACKED_FIELDS:
		if doc.has_value_changed(fld):
			return True
	return False


def _missing_required(doc) -> list[str]:
	"""Return a list of human-readable reasons preventing upload.

	An empty list means the item is uploadable.
	"""
	reasons: list[str] = []

	if not doc.get("item_name"):
		reasons.append(_("Item Name"))
	if not _code_from_uom(doc.get("stock_uom")):
		reasons.append(
			_("Stock UOM {0} is not mapped to EFRIS Dictionary (rateUnit)").format(
				doc.get("stock_uom") or ""
			)
		)
	if not _company_currency_code(doc):
		reasons.append(_("Company currency is not mapped to EFRIS Dictionary (currencyType)"))
	if not doc.get("efris_commodity_category"):
		reasons.append(_("EFRIS Commodity Category ID"))

	if doc.get("efris_have_excise_tax") and not doc.get("efris_excise_duty_code"):
		reasons.append(_("Excise Duty Code (required when Has Excise Tax is set)"))

	if doc.get("efris_have_piece_unit"):
		if not _strip_category(doc.get("efris_piece_measure_unit")):
			reasons.append(_("Piece Measure Unit"))

	if doc.get("efris_have_customs_unit") and not (doc.get("efris_customs_units") or []):
		reasons.append(_("At least one row in Customs Units"))

	for row in _other_uom_rows(doc):
		if not _code_from_uom(row.uom):
			reasons.append(
				_("UOM {0} is not mapped to EFRIS Dictionary (rateUnit)").format(row.uom)
			)

	return reasons


def _build_payload(doc) -> dict[str, Any]:
	"""Construct the T130 entry for one Item."""
	goods_code = doc.get("efris_goods_code") or doc.item_code

	payload: dict[str, Any] = {
		"operationType": _probe_operation_type(doc),
		"goodsName": (doc.item_name or "")[:200],
		"goodsCode": goods_code[:50],
		"measureUnit": _code_from_uom(doc.stock_uom),
		"unitPrice": _format_number(_buying_unit_price(doc)),
		"currency": _company_currency_code(doc),
		"commodityCategoryId": _commodity_category_code(doc.efris_commodity_category),
		"haveExciseTax": "101" if doc.get("efris_have_excise_tax") else "102",
		"description": _plain_text(doc.get("description") or "")[:1024],
		"stockPrewarning": _format_number(doc.get("efris_stock_prewarning") or 0),
		"havePieceUnit": "101" if doc.get("efris_have_piece_unit") else "102",
		"haveOtherUnit": "101" if _other_uom_rows(doc) else "102",
		"haveCustomsUnit": "101" if doc.get("efris_have_customs_unit") else "102",
		"goodsTypeCode": _split_select_code(doc.get("efris_goods_type")) or "101",
	}

	if doc.get("efris_have_excise_tax"):
		payload["exciseDutyCode"] = _excise_duty_code(doc.efris_excise_duty_code)

	if doc.get("efris_have_piece_unit"):
		piece_price = (
			flt(doc.get("efris_piece_unit_price"))
			or _buying_unit_price(doc)
			or flt(doc.get("valuation_rate"))
		)
		payload["pieceMeasureUnit"] = _strip_category(doc.efris_piece_measure_unit)
		payload["pieceUnitPrice"] = _format_number(piece_price)
		payload["packageScaledValue"] = _format_number(doc.get("efris_package_scaled_value") or 1)
		payload["pieceScaledValue"] = _format_number(doc.get("efris_piece_scaled_value") or 1)

	if doc.get("efris_have_customs_unit") and doc.get("efris_customs_units"):
		payload["customsUnitList"] = [
			{
				"customsMeasureUnit": _strip_category(row.customs_measure_unit),
				"customsUnitPrice": _format_number(row.customs_unit_price),
				"packageScaledValueCustoms": _format_number(row.package_scaled_value_customs),
				"customsScaledValue": _format_number(row.customs_scaled_value),
			}
			for row in doc.get("efris_customs_units") or []
		]

	other_rows = _other_uom_rows(doc)
	if other_rows:
		payload["goodsOtherUnits"] = [
			{
				"otherUnit": _code_from_uom(row.uom),
				"otherPrice": _format_number(row.get("efris_unit_price") or 0),
				"otherScaled": _format_number(row.conversion_factor or 1),
				"packageScaled": _format_number(row.get("efris_package_scaled") or 1),
			}
			for row in other_rows
		]

	return payload


def _other_uom_rows(doc) -> list:
	"""Item.uoms rows excluding the stock_uom — these are the EFRIS 'other units'."""
	stock_uom = doc.get("stock_uom")
	return [row for row in (doc.get("uoms") or []) if row.uom and row.uom != stock_uom]


def _interpret_response(response: Any) -> dict[str, Any]:
	"""Decide whether T130 accepted our entry.

	URA returns the per-entry result in one of two shapes:
	  * a list of mirror entries, each with ``returnCode`` / ``returnMessage``
	  * a dict like ``{"goodsUploadingItems": [...]}`` (observed on partial
	    failure with ``returnStateInfo.returnCode = 45``).

	An empty / ``"00"`` per-entry code is success; anything else is a URA-side
	rejection — surface its ``returnMessage`` to the caller.
	"""
	# URA accepts T130 updates with an empty mirror list — the overall
	# returnCode was already validated as success by EFRISClient, so an empty
	# payload here means "accepted, nothing to echo".
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
	"""Pluck the first mirror-entry from a T130 response, regardless of shape."""
	if isinstance(response, list):
		return response[0] if response and isinstance(response[0], dict) else None
	if isinstance(response, dict):
		# Direct entry shape.
		if "returnCode" in response or "returnMessage" in response:
			return response
		# Wrapped: look for the first list of entries inside the dict.
		for value in response.values():
			if isinstance(value, list) and value and isinstance(value[0], dict):
				return value[0]
	return None


def _persist_result(item, operation_type: str, state: dict[str, Any]) -> None:
	"""Persist T130 state on the Item without retriggering on_update."""
	if state["ok"]:
		_set_state_db(item, uploaded=1, operation_type=operation_type, error="")
	else:
		_set_state_db(item, error=state["message"])


def _set_state_db(
	doc,
	uploaded: int | None = None,
	operation_type: str | None = None,
	error: str | None = None,
) -> None:
	"""Write EFRIS status fields straight to the DB.

	``db_set`` avoids ``on_update`` re-firing — without it we'd loop on
	every successful upload.
	"""
	if uploaded is not None:
		doc.db_set("efris_uploaded", uploaded, update_modified=False)
	if operation_type is not None:
		doc.db_set("efris_operation_type", operation_type, update_modified=False)
	if error is not None:
		doc.db_set("efris_upload_error", error, update_modified=False)
	if uploaded:
		doc.db_set("efris_last_uploaded_on", now_datetime(), update_modified=False)


# -- code resolution ---------------------------------------------------


def _strip_category(link_name: str | None) -> str:
	"""Return the trailing ``<code>`` from an EFRIS Dictionary name (``cat-code``)."""
	if not link_name:
		return ""
	if "-" not in link_name:
		return link_name
	return link_name.split("-", 1)[1]


def _commodity_category_code(link_value: str | None) -> str:
	"""Resolve the URA commodity category code from the Item's Link → EFRIS Commodity Category.

	The Link is autonamed by ``commodity_category_code``, so the link value
	already is the code, but we re-fetch the field explicitly to stay correct
	if the autoname strategy ever changes.
	"""
	if not link_value:
		return ""
	return (
		frappe.db.get_value("EFRIS Commodity Category", link_value, "commodity_category_code")
		or link_value
	)


def _excise_duty_code(link_value: str | None) -> str:
	"""Resolve the URA excise duty code from the Item's Link → EFRIS Excise Duty.

	The Link is autonamed by ``excise_duty_code``, so the link value already is
	the code, but we re-fetch the field explicitly to stay correct if the
	autoname strategy ever changes.
	"""
	if not link_value:
		return ""
	return frappe.db.get_value("EFRIS Excise Duty", link_value, "excise_duty_code") or link_value


def on_item_price_change(doc, _method=None) -> None:
	"""Re-upload the linked Item to EFRIS when its buying stock-UOM price changes.

	Fires on Item Price ``on_update``. Only re-uploads when the price is a
	buying price at the Item's stock UOM and the Item has already been
	uploaded to EFRIS — otherwise the normal Item save flow handles it.
	"""
	if not doc.get("selling"):
		return
	item_code = doc.get("item_code")
	if not item_code:
		return

	stock_uom, uploaded = frappe.db.get_value(
		"Item", item_code, ["stock_uom", "efris_uploaded"]
	) or (None, None)
	if not uploaded or doc.get("uom") != stock_uom:
		return

	try:
		upload_item(item_code)
	except Exception as exc:
		frappe.msgprint(
			_("EFRIS unit price sync failed for {0}: {1}").format(item_code, cstr(exc)),
			alert=True,
			indicator="orange",
		)


def _buying_unit_price(doc) -> float:
	"""Resolve the EFRIS unitPrice from the latest buying Item Price.

	Looks up the most recent ``Item Price`` for this item where ``buying`` is
	set and ``uom`` matches the Item's ``stock_uom``. Falls back to
	``standard_rate`` when no such price exists.
	"""
	item_code = doc.get("item_code") or doc.get("name")
	stock_uom = doc.get("stock_uom")
	if item_code and stock_uom:
		price = frappe.db.get_value(
			"Item Price",
			{"item_code": item_code, "uom": stock_uom, "selling": 1},
			"price_list_rate",
			order_by="modified desc",
		)
		if price:
			return flt(price)
	return flt(doc.get("standard_rate") or 0)


def _code_from_uom(uom_name: str | None) -> str:
	if not uom_name:
		return ""
	mapping = frappe.db.get_value("UOM", uom_name, "efris_dictionary")
	return _strip_category(mapping)


def _company_currency_code(doc) -> str:
	"""Resolve the EFRIS code for the Item's pricing currency.

	Items don't carry a currency directly — we use the default Company
	currency from the global default Company, then look up its EFRIS
	mapping. A site without a default company can still upload as long as
	exactly one Currency record has an ``efris_dictionary`` set.
	"""
	currency = None
	default_company = frappe.defaults.get_global_default("company")
	if default_company:
		currency = frappe.db.get_value("Company", default_company, "default_currency")
	if not currency:
		return ""
	mapping = frappe.db.get_value("Currency", currency, "efris_dictionary")
	return _strip_category(mapping)


def _split_select_code(value: str | None) -> str:
	"""Pull the leading ``101`` out of select options like ``101 - Goods``."""
	if not value:
		return ""
	return value.split(" ", 1)[0].strip()


def _plain_text(text: str) -> str:
	"""Strip HTML tags from rich text inputs — URA's description is plain."""
	from frappe.utils import strip_html

	return strip_html(text or "").strip()


def _format_number(value: Any) -> str:
	"""Format a number the way URA expects: plain decimal string."""
	if value in (None, ""):
		return "0"
	# `flt` handles strings, ints, Decimals.
	n = flt(value)
	if n == int(n):
		return str(int(n))
	return f"{n:.8f}".rstrip("0").rstrip(".")
