"""EFRIS Excise Duty (T125) sync.

T125 returns the full URA excise duty catalogue — taxpayer-independent
reference data. We mirror it into ``EFRIS Excise Duty`` so users can pick
the code as a Link on Item (``efris_excise_duty_code``) instead of typing
it free-form.

A daily scheduler refreshes the table; users can also trigger it manually.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe
from frappe.utils import getdate, now_datetime

from efris.efris.api.client import EFRISClient, efris_errors
from efris.efris.api.interfaces import get_excise_duty as call_t125


def enqueue_sync(company: str | None = None, prune: bool = True) -> str:
	"""Queue an excise-duty sync on the long worker — see ``dictionary.enqueue_sync``."""
	job = frappe.enqueue(
		"efris.efris.api.excise_duty.sync_excise_duty",
		queue="long",
		timeout=600,
		job_id="efris-excise-duty-sync",
		deduplicate=True,
		company=company,
		prune=prune,
	)
	return job.id


@frappe.whitelist()
def sync_excise_duty(
	company: str | None = None,
	client: EFRISClient | None = None,
	prune: bool = True,
) -> dict[str, Any]:
	"""Run T125 and upsert ``EFRIS Excise Duty`` rows.

	URA reference data — the call doesn't depend on which company's credentials
	are used. When ``company`` is omitted the first enabled EFRIS Settings is
	picked.
	"""
	if client is None and company is None:
		company = frappe.db.get_value("EFRIS Settings", {"enabled": 1}, "company")
		if not company:
			frappe.throw("No enabled EFRIS Settings record found to source credentials from.")

	c = client or EFRISClient(company=company)
	with efris_errors("EFRIS Excise Duty Sync Failed"):
		response = c.call("T125")

	entries = (response or {}).get("exciseDutyList") or []
	now = now_datetime()
	seen: set[str] = set()
	upserted = 0

	for entry in entries:
		code = (entry.get("exciseDutyCode") or "").strip()
		if not code:
			continue
		_upsert(entry, code, now)
		seen.add(code)
		upserted += 1

	pruned = _prune(seen) if prune else 0
	return {"rows_upserted": upserted, "rows_pruned": pruned}


# -- internals ---------------------------------------------------------


def _upsert(entry: dict, code: str, now) -> None:
	values = {
		"excise_duty_code": code,
		"good_service": (entry.get("goodService") or "")[:500],
		"parent_code": entry.get("parentCode") or "",
		"rate_text": (entry.get("rateText") or "")[:100],
		"efris_id": entry.get("id") or "",
		"is_leaf_node": 1 if str(entry.get("isLeafNode") or "0") == "1" else 0,
		"effective_date": _parse_date(entry.get("effectiveDate")),
		"last_synced_on": now,
	}

	if frappe.db.exists("EFRIS Excise Duty", code):
		doc = frappe.get_doc("EFRIS Excise Duty", code)
		doc.update(values)
		doc.set("details", [])
	else:
		doc = frappe.new_doc("EFRIS Excise Duty")
		doc.update(values)

	for detail in entry.get("exciseDutyDetailsList") or []:
		doc.append(
			"details",
			{
				"type": _detail_type(detail.get("type")),
				"rate": _parse_rate(detail.get("rate")),
				"unit": detail.get("unit") or "",
				"currency": detail.get("currency") or "",
			},
		)

	doc.save(ignore_permissions=True)


def _parse_rate(raw: Any) -> float:
	"""URA sometimes returns ``'Nil'`` (or blank) for exempt entries — treat as 0."""
	if raw in (None, "", "Nil", "nil", "NIL"):
		return 0.0
	try:
		return float(raw)
	except (TypeError, ValueError):
		return 0.0


def _detail_type(raw: Any) -> str:
	mapping = {"101": "101 - Percentage", "102": "102 - Unit of Measurement"}
	return mapping.get(str(raw or "").strip(), "")


def _parse_date(raw: Any):
	"""URA's ``effectiveDate`` is ``dd/MM/yyyy`` — Frappe wants ISO."""
	if not raw:
		return None
	raw = str(raw).strip()
	for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
		try:
			return datetime.strptime(raw, fmt).date()
		except ValueError:
			continue
	try:
		return getdate(raw)
	except Exception:
		return None


def _prune(seen: set[str]) -> int:
	existing = frappe.get_all("EFRIS Excise Duty", pluck="name")
	pruned = 0
	for name in existing:
		if name in seen:
			continue
		frappe.delete_doc("EFRIS Excise Duty", name, ignore_permissions=True, force=True)
		pruned += 1
	return pruned
