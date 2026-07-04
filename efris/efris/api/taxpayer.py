"""T119 — taxpayer TIN validation with side effects on party records.

Public surface is one whitelisted method, ``validate_party_tin``, called from
the EFRIS button on Customer and Supplier forms. It runs T119 against the
party's Tax ID, then writes the verified taxpayer details back onto the doc
via the custom fields installed by ``efris.efris.setup``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from efris.efris.api.client import efris_errors
from efris.efris.api.interfaces import validate_tin as call_t119


SUPPORTED_PARTY_DOCTYPES = {"Customer", "Supplier"}

_TAXPAYER_TO_FIELD = {
	"legalName": "efris_legal_name",
	"businessName": "efris_business_name",
	"taxpayerStatus": "efris_taxpayer_status",
	"taxpayerType": "efris_taxpayer_type",
}

# The display-name fieldname on each supported party doctype.
_PARTY_NAME_FIELD = {"Customer": "customer_name", "Supplier": "supplier_name"}


@frappe.whitelist()
def validate_party_tin(doctype: str, name: str) -> dict:
	"""Run T119 against the party's Tax ID and persist the result on the doc.

	Raises if the party's Tax ID is empty — T119 has nothing to query in
	that case, and silently no-opping would mislead the user.
	"""
	if doctype not in SUPPORTED_PARTY_DOCTYPES:
		frappe.throw(_("EFRIS TIN validation is not supported for {0}.").format(doctype))

	party = frappe.get_doc(doctype, name)
	tin = (party.tax_id or "").strip()
	if not tin:
		frappe.throw(_("Set Tax ID on {0} before validating with EFRIS.").format(party.name))

	with efris_errors(_("EFRIS TIN Validation Failed")):
		result = call_t119(tin=tin)

	taxpayer = (result or {}).get("taxpayer") or {}
	if not taxpayer:
		frappe.throw(_("EFRIS returned no taxpayer details for TIN {0}.").format(tin))

	for src, field in _TAXPAYER_TO_FIELD.items():
		party.set(field, taxpayer.get(src) or "")
	party.set("efris_last_validated_on", now_datetime())
	party.save(ignore_permissions=True)

	display = party.efris_legal_name or party.efris_business_name or tin
	frappe.msgprint(
		_("EFRIS confirmed TIN {0} — {1}").format(tin, display),
		alert=True,
		indicator="green",
	)
	return taxpayer


@frappe.whitelist()
def create_party_from_tin(doctype: str, tin: str) -> str:
	"""Create a Customer or Supplier from an EFRIS T119 lookup.

	Returns the new doc's name (so the JS caller can route to it). Refuses
	to create a duplicate when a party with the same Tax ID already exists.
	Required defaults (customer_group/territory or supplier_group) come from
	Selling/Buying Settings — if those aren't configured, the insert will
	surface the standard ERPNext validation error.
	"""
	if doctype not in SUPPORTED_PARTY_DOCTYPES:
		frappe.throw(_("EFRIS create-by-TIN is not supported for {0}.").format(doctype))

	tin = (tin or "").strip()
	if not tin:
		frappe.throw(_("Enter a TIN to look up."))

	with efris_errors(_("EFRIS TIN Lookup Failed")):
		result = call_t119(tin=tin)

	taxpayer = (result or {}).get("taxpayer") or {}
	if not taxpayer:
		frappe.throw(_("EFRIS returned no taxpayer details for TIN {0}.").format(tin))

	existing = frappe.db.exists(doctype, {"tax_id": tin})
	if existing:
		party = frappe.get_doc(doctype, existing)
		_apply_taxpayer(party, taxpayer)
		party.save(ignore_permissions=True)
		frappe.msgprint(
			_("EFRIS details refreshed on existing {0} {1}.").format(doctype, existing),
			alert=True,
			indicator="blue",
		)
		return party.name

	party = frappe.new_doc(doctype)
	party.tax_id = tin
	display_name = taxpayer.get("legalName") or taxpayer.get("businessName") or tin
	party.set(_PARTY_NAME_FIELD[doctype], display_name)
	_apply_taxpayer(party, taxpayer)

	if doctype == "Customer":
		party.customer_type = "Company"
		party.customer_group = frappe.db.get_single_value("Selling Settings", "customer_group")
		party.territory = frappe.db.get_single_value("Selling Settings", "territory")
	else:  # Supplier
		party.supplier_type = "Company"
		party.supplier_group = frappe.db.get_single_value("Buying Settings", "supplier_group")

	party.insert(ignore_permissions=True)
	return party.name


def _apply_taxpayer(party, taxpayer: dict) -> None:
	"""Write EFRIS T119 ``taxpayer`` fields onto a party doc."""
	for src, field in _TAXPAYER_TO_FIELD.items():
		party.set(field, taxpayer.get(src) or "")
	party.set("efris_last_validated_on", now_datetime())


def auto_validate_party_tin(doc, _method=None) -> None:
	"""Document-event hook: run T119 on Customer/Supplier save when needed.

	Triggered from ``doc_events`` ``validate`` for Customer and Supplier:

	* No Tax ID → skip.
	* No enabled EFRIS Settings on this site → skip (EFRIS isn't in use yet).
	* Existing doc with unchanged Tax ID that we've validated before → skip.

	Any failure (network, EFRIS error code, unexpected payload) is swallowed
	and surfaced as a non-blocking alert. The save must always proceed —
	failed validation is not a reason to lose the user's edit.
	"""
	tin = (doc.tax_id or "").strip()
	if not tin:
		return

	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return

	already_validated = bool(doc.get("efris_last_validated_on"))
	tin_unchanged = not doc.is_new() and not doc.has_value_changed("tax_id")
	if already_validated and tin_unchanged:
		return

	try:
		result = call_t119(tin=tin)
		taxpayer = (result or {}).get("taxpayer") or {}
		if not taxpayer:
			raise RuntimeError(_("EFRIS returned no taxpayer details."))
		_apply_taxpayer(doc, taxpayer)
	except Exception as exc:
		frappe.msgprint(
			_("EFRIS TIN validation skipped: {0}").format(frappe.utils.cstr(exc)),
			alert=True,
			indicator="orange",
		)
