"""EFRIS Commodity Category sync (T123 / T124).

T124 is the primary driver — paginated, cap 100 rows/page. We use it for both
the foreground first-batch (50 rows for fast feedback from the button) and a
background job that drains the remaining pages with 100-row batches and a
``frappe.db.commit()`` per batch.

Performance notes:
  * Rows already seeded are skipped via a Redis SET cache; we never re-fetch
    or compare per-row. The user's spec is "ignore the ones already saved".
  * Insert path is ``frappe.db.bulk_insert`` (raw multi-row INSERT) so we
    skip the Document layer's per-row overhead — including ``NestedSet``'s
    ``update_nsm`` bookkeeping, which would otherwise dominate the cost.
  * After the final page, ``rebuild_tree`` rebuilds ``lft``/``rgt`` once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe
from frappe.utils import getdate, now_datetime
from frappe.utils.nestedset import rebuild_tree

from efris.efris.api.client import EFRISClient, efris_errors
from efris.efris.api.interfaces import get_commodity_categories_page as call_t124


_DOCTYPE = "EFRIS Commodity Category"
_CACHE_KEY = "efris:commodity_categories:seeded"
_BG_PAGE_SIZE = 100
_FG_PAGE_SIZE = 50
_BG_JOB_ID = "efris-commodity-categories-sync"


# Columns we write — must match the order in the bulk_insert call below.
_INSERT_FIELDS = (
	"name",
	"commodity_category_code",
	"commodity_category_name",
	"parent_efris_commodity_category",
	"is_group",
	"commodity_category_level",
	"rate",
	"exclusion",
	"service_mark",
	"excisable",
	"vat_out_scope_code",
	"enable_status_code",
	"is_zero_rate",
	"zero_rate_start_date",
	"zero_rate_end_date",
	"is_exempt",
	"exempt_rate_start_date",
	"exempt_rate_end_date",
	"last_synced_on",
	"creation",
	"modified",
	"modified_by",
	"owner",
	"docstatus",
)


# -- public ------------------------------------------------------------


@frappe.whitelist()
def sync_commodity_categories(company: str | None = None) -> dict:
	"""Foreground entry — page 1 inline, queue the rest.

	Returns ``{imported, total_size, total_pages, queued}``.
	"""
	_warm_cache()
	result = _ingest_page(page_no=1, page_size=_FG_PAGE_SIZE, company=company)

	queued = False
	if result["total_pages"] > 1:
		# Background driver uses 100-row batches and commits per page.
		frappe.enqueue(
			"efris.efris.api.commodity_category.sync_remaining",
			queue="long",
			timeout=1800,
			job_id=_BG_JOB_ID,
			deduplicate=True,
			company=company,
			start_page=2,
		)
		queued = True
	else:
		# Single page — rebuild the tree now since no background pass will.
		rebuild_tree(_DOCTYPE)

	return {
		"imported": result["imported"],
		"total_size": result["total_size"],
		"total_pages": result["total_pages"],
		"queued": queued,
	}


def sync_remaining(company: str | None = None, start_page: int = 2) -> dict:
	"""Background entry — drain pages from ``start_page`` to the last page.

	Commits per page so a long sync that crashes mid-way doesn't lose work.
	Rebuilds the nested-set tree once at the end.
	"""
	_warm_cache()
	imported = 0
	page_no = start_page
	while True:
		result = _ingest_page(page_no=page_no, page_size=_BG_PAGE_SIZE, company=company)
		imported += result["imported"]
		frappe.db.commit()  # batch boundary

		if page_no >= result["total_pages"]:
			break
		page_no += 1

	rebuild_tree(_DOCTYPE)
	frappe.db.commit()
	return {"imported": imported, "last_page": page_no}


# -- internals ---------------------------------------------------------


def _ingest_page(*, page_no: int, page_size: int, company: str | None) -> dict:
	"""Fetch one T124 page, bulk-insert unseen rows. Returns counts."""
	c = EFRISClient(company=company) if company else EFRISClient()
	with efris_errors(f"EFRIS Commodity Category Sync Failed (page {page_no})"):
		response = call_t124(page_no=page_no, page_size=page_size, client=c)

	records = (response or {}).get("records") or []
	page_info = (response or {}).get("page") or {}
	total_pages = int(page_info.get("pageCount") or 1)
	total_size = int(page_info.get("totalSize") or len(records))

	cache = frappe.cache()
	now = now_datetime()
	user = frappe.session.user or "Administrator"

	# URA occasionally repeats a code within a single page — dedupe before
	# we hit MySQL or we'd blow up on the PK.
	rows: list[tuple] = []
	new_codes: list[str] = []
	seen_in_page: set[str] = set()
	for record in records:
		code = (record.get("commodityCategoryCode") or "").strip()
		if not code or code in seen_in_page:
			continue
		if cache.sismember(_CACHE_KEY, code):
			continue
		seen_in_page.add(code)
		rows.append(_row_tuple(record, code=code, now=now, user=user))
		new_codes.append(code)

	if rows:
		# ``ignore_duplicates`` makes the INSERT survive cross-page repeats
		# and codes that slipped past the cache (e.g. cache wasn't warmed).
		frappe.db.bulk_insert(
			_DOCTYPE, fields=list(_INSERT_FIELDS), values=rows, ignore_duplicates=True
		)
		for code in new_codes:
			cache.sadd(_CACHE_KEY, code)

	return {
		"imported": len(rows),
		"total_pages": total_pages,
		"total_size": total_size,
	}


def _row_tuple(record: dict, *, code: str, now, user: str) -> tuple:
	parent_code = (record.get("parentCode") or "").strip()
	parent = parent_code if parent_code and parent_code != "0" else None

	# isLeafNode: 101 = Y (leaf), 102 = N (group). is_group is the inverse.
	is_group = 0 if str(record.get("isLeafNode") or "") == "101" else 1

	return (
		code,                                                         # name
		code,                                                         # commodity_category_code
		(record.get("commodityCategoryName") or "")[:200],            # commodity_category_name
		parent,                                                       # parent_efris_commodity_category
		is_group,                                                     # is_group
		record.get("commodityCategoryLevel") or "",                   # commodity_category_level
		_to_float(record.get("rate")),                                # rate
		_exclusion_label(record.get("exclusion")),                    # exclusion
		_y_flag(record.get("serviceMark")),                           # service_mark
		_y_flag(record.get("excisable")),                             # excisable
		_y_flag(record.get("vatOutScopeCode")),                       # vat_out_scope_code
		record.get("enableStatusCode") or "",                         # enable_status_code
		_y_flag(record.get("isZeroRate")),                            # is_zero_rate
		_parse_date(record.get("zeroRateStartDate")),                 # zero_rate_start_date
		_parse_date(record.get("zeroRateEndDate")),                   # zero_rate_end_date
		_y_flag(record.get("isExempt")),                              # is_exempt
		_parse_date(record.get("exemptRateStartDate")),               # exempt_rate_start_date
		_parse_date(record.get("exemptRateEndDate")),                 # exempt_rate_end_date
		now,                                                          # last_synced_on
		now,                                                          # creation
		now,                                                          # modified
		user,                                                         # modified_by
		user,                                                         # owner
		0,                                                            # docstatus
	)


def _warm_cache() -> None:
	"""Seed the Redis SET with codes already in the DB, so the cache is correct.

	Cheap: a single column scan, then ``sadd`` in bulk. Skipped if the cache
	already looks populated (any member exists).
	"""
	cache = frappe.cache()
	# Quick probe: if the set has any entry, assume it's already warm.
	if cache.scard(_CACHE_KEY) > 0:
		return
	existing = frappe.get_all(_DOCTYPE, pluck="commodity_category_code") or []
	for code in existing:
		if code:
			cache.sadd(_CACHE_KEY, code)


@frappe.whitelist()
def reset_cache() -> int:
	"""Drop the seeded-set cache. Returns the number of entries removed."""
	cache = frappe.cache()
	count = cache.scard(_CACHE_KEY) or 0
	cache.delete_key(_CACHE_KEY)
	return count


# -- value coercion ----------------------------------------------------


def _y_flag(raw: Any) -> int:
	"""URA flag: 101 = Y, 102 = N. Anything else falsy."""
	return 1 if str(raw or "").strip() == "101" else 0


def _to_float(raw: Any) -> float:
	if raw in (None, "", "Nil", "nil", "NIL"):
		return 0.0
	try:
		return float(raw)
	except (TypeError, ValueError):
		return 0.0


def _exclusion_label(raw: Any) -> str:
	mapping = {
		"0": "0 - Zero",
		"1": "1 - Exempt",
		"2": "2 - No Exclusion",
		"3": "3 - Both 0% & '-'",
	}
	return mapping.get(str(raw or "").strip(), "")


def _parse_date(raw: Any):
	"""URA dates are ``dd/MM/yyyy``."""
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
