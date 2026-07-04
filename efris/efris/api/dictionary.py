"""EFRIS dictionary (T115) sync and lookup.

T115 returns a bag of category → entries (currencies, pay ways, sectors,
units, …) — reference data that is the same for every taxpayer, so the local
copy in ``EFRIS Dictionary`` is company-independent. Any company's EFRIS
credentials can be used to make the call. A daily scheduler refreshes the
cache; users can also trigger it manually from EFRIS Settings.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import now_datetime

from efris.efris.api.client import EFRISClient
from efris.efris.api.interfaces import sync_dictionary as call_t115


_CACHE_KEY = "efris_dictionary"

# Fields URA already gives us as named columns; anything else on an entry
# spills into ``extra_json`` so we don't lose it.
_KNOWN_ENTRY_FIELDS = {"value", "code", "name"}


def enqueue_sync(company: str | None = None, prune: bool = True) -> str:
	"""Enqueue a T115 sync to a background worker and return immediately.

	The full sync writes a few hundred rows and prunes anything stale — too
	slow to run inline on a button click. We queue it as a long job on the
	``long`` queue so the request returns quickly; progress and errors land
	in the standard Background Jobs / Error Log views.

	Returns the queued job's id so the UI can show a link.
	"""
	job = frappe.enqueue(
		"efris.efris.api.dictionary.sync_dictionary",
		queue="long",
		timeout=600,
		job_id="efris-dictionary-sync",
		deduplicate=True,
		company=company,
		prune=prune,
	)
	return job.id


def sync_dictionary(
	company: str | None = None,
	client: EFRISClient | None = None,
	prune: bool = True,
) -> dict[str, Any]:
	"""Run T115 (using ``company``'s credentials) and refresh EFRIS Dictionary.

	The stored rows are not company-scoped — T115 is URA reference data, the
	same for every taxpayer. ``company`` only chooses *which* settings record
	supplies the credentials for the call. When omitted, the first enabled
	EFRIS Settings record is used.
	"""
	if client is None and company is None:
		company = _first_enabled_company()
		if not company:
			frappe.throw("No enabled EFRIS Settings record found to source credentials from.")

	c = client or EFRISClient(company=company)
	response = call_t115(client=c)
	if not isinstance(response, dict):
		frappe.throw("EFRIS T115 returned an unexpected payload (not a JSON object).")

	# If the response carries a version we recognise, short-circuit when it
	# matches the last one we stored.
	version = response.get("version") or response.get("dictionaryVersion") or ""
	stored_version = _get_stored_version()
	if version and stored_version == version:
		_touch_meta(version)
		_invalidate_cache()
		return {
			"categories": 0,
			"rows_upserted": 0,
			"rows_pruned": 0,
			"version": version,
			"skipped": True,
		}

	seen: set[tuple[str, str]] = set()
	rows_upserted = 0
	categories = 0
	now = now_datetime()

	for category, payload in response.items():
		if category in ("version", "dictionaryVersion"):
			continue
		categories += 1
		for entry in _flatten_category(payload):
			code = entry.pop("__code", "")
			name = entry.pop("__name", "")
			efris_value = entry.pop("__value", "")
			extras = entry  # whatever else came along

			_upsert_row(
				category=category,
				code=code,
				name=name,
				efris_value=efris_value,
				extras=extras,
				last_synced_on=now,
			)
			seen.add((category, code))
			rows_upserted += 1

	_touch_meta(version)
	if version:
		seen.add(("_meta", "version"))

	rows_pruned = 0
	if prune:
		rows_pruned = _prune(seen)

	_invalidate_cache()

	return {
		"categories": categories,
		"rows_upserted": rows_upserted,
		"rows_pruned": rows_pruned,
		"version": version,
		"skipped": False,
	}


def _flatten_category(payload: Any) -> list[dict[str, Any]]:
	"""Normalise a T115 category's value into a list of entries.

	URA shapes categories three ways:
	  * list[dict]   — many entries (currencyType, payWay, …)
	  * dict (entry) — one entry per category (creditNoteMaximumInvoicingDays)
	  * dict (map)   — a config dict with no value/name (e.g. format)

	Every entry comes back as a dict with three reserved keys (``__code``,
	``__name``, ``__value``) plus any extras we want to keep.
	"""
	if isinstance(payload, list):
		return [_entry_from_dict(e) for e in payload if isinstance(e, dict)]

	if isinstance(payload, dict):
		if "value" in payload or "code" in payload or "name" in payload:
			return [_entry_from_dict(payload)]
		return [{"__code": "", "__name": "", "__value": "", **payload}]

	return [{"__code": "", "__name": "", "__value": str(payload)}]


def _entry_from_dict(entry: dict) -> dict[str, Any]:
	code = entry.get("value") or entry.get("code") or ""
	name = entry.get("name") or ""
	value = entry.get("value") or ""
	extras = {k: v for k, v in entry.items() if k not in _KNOWN_ENTRY_FIELDS}
	return {"__code": str(code), "__name": str(name), "__value": str(value), **extras}


def _upsert_row(
	*,
	category: str,
	code: str,
	name: str,
	efris_value: str,
	extras: dict,
	last_synced_on,
) -> None:
	row_name = f"{category}-{code}"
	values = {
		"category": category,
		"code": code,
		"entry_name": name,
		"efris_value": efris_value,
		"extra_json": json.dumps(extras, separators=(",", ":")) if extras else "",
		"last_synced_on": last_synced_on,
	}

	if frappe.db.exists("EFRIS Dictionary", row_name):
		doc = frappe.get_doc("EFRIS Dictionary", row_name)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return

	doc = frappe.new_doc("EFRIS Dictionary")
	doc.update(values)
	doc.insert(ignore_permissions=True)


def _prune(seen: set[tuple[str, str]]) -> int:
	existing = frappe.get_all("EFRIS Dictionary", fields=["name", "category", "code"])
	pruned = 0
	for row in existing:
		if (row.category, row.code or "") in seen:
			continue
		frappe.delete_doc("EFRIS Dictionary", row.name, ignore_permissions=True, force=True)
		pruned += 1
	return pruned


def _get_stored_version() -> str:
	row_name = "_meta-version"
	if not frappe.db.exists("EFRIS Dictionary", row_name):
		return ""
	return frappe.db.get_value("EFRIS Dictionary", row_name, "efris_value") or ""


def _touch_meta(version: str) -> None:
	row_name = "_meta-version"
	if not version:
		if frappe.db.exists("EFRIS Dictionary", row_name):
			frappe.delete_doc("EFRIS Dictionary", row_name, ignore_permissions=True, force=True)
		return
	_upsert_row(
		category="_meta",
		code="version",
		name="Dictionary Version",
		efris_value=version,
		extras={},
		last_synced_on=now_datetime(),
	)


def _first_enabled_company() -> str | None:
	"""Return any enabled EFRIS Settings company — credentials source only."""
	return frappe.db.get_value("EFRIS Settings", {"enabled": 1}, "company")


# -- lookup helpers ----------------------------------------------------


def lookup(category: str, code: str) -> str | None:
	"""Return the ``name`` for a (category, code) entry, or ``None``."""
	for entry in list_category(category):
		if entry["code"] == code:
			return entry["name"]
	return None


def code_for(category: str, name: str) -> str | None:
	"""Inverse of :func:`lookup` — return the ``code`` for a category/name pair.

	Case-insensitive on the name, since URA labels can vary in casing. Returns
	``None`` when no entry matches.
	"""
	if not name:
		return None
	target = name.strip().casefold()
	for entry in list_category(category):
		if entry["name"].strip().casefold() == target:
			return entry["code"]
	return None


def list_category(category: str) -> list[dict[str, Any]]:
	"""Return all entries in a category as ``[{code, name, value, extra}, ...]``."""
	cache = frappe.cache()
	cached = cache.hget(_CACHE_KEY, category)
	if cached is not None:
		return cached

	rows = frappe.get_all(
		"EFRIS Dictionary",
		filters={"category": category},
		fields=["code", "entry_name", "efris_value", "extra_json"],
	)
	result = [
		{
			"code": r.code or "",
			"name": r.entry_name or "",
			"value": r.efris_value or "",
			"extra": json.loads(r.extra_json) if r.extra_json else {},
		}
		for r in rows
	]
	cache.hset(_CACHE_KEY, category, result)
	return result


def _invalidate_cache() -> None:
	frappe.cache().delete_key(_CACHE_KEY)


# -- Link field queries ------------------------------------------------


@frappe.whitelist()
def dictionary_query(doctype, txt, searchfield, start, page_len, filters):
	"""Standard Frappe link-field query, filtered by category.

	Wire a Link field on any doctype to this via either Python (a `get_query`
	in `frm.set_query` callback) or JS (the ``efris.dictionary`` helper).
	Pass ``{"category": "<name>"}`` in ``filters``; the optional ``code``
	filter narrows further.
	"""
	filters = filters or {}
	if isinstance(filters, str):
		filters = json.loads(filters)

	category = filters.get("category")
	if not category:
		return []

	values: dict[str, Any] = {
		"category": category,
		"start": int(start or 0),
		"page_len": int(page_len or 20),
	}
	conditions = ["category = %(category)s"]
	if filters.get("code"):
		conditions.append("code = %(code)s")
		values["code"] = filters["code"]
	if txt:
		conditions.append("(name LIKE %(txt)s OR entry_name LIKE %(txt)s OR code LIKE %(txt)s)")
		values["txt"] = f"%{txt}%"

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT name, entry_name, code
		FROM `tabEFRIS Dictionary`
		WHERE {where}
		ORDER BY code
		LIMIT %(start)s, %(page_len)s
		""",
		values,
	)


def link_filters(category: str, **extra) -> dict[str, Any]:
	"""Return a filter dict for server-side Link queries.

	Useful inside controllers that call `frappe.get_all("EFRIS Dictionary",
	filters=link_filters("currencyType"))` or similar.
	"""
	return {"category": category, **extra}
