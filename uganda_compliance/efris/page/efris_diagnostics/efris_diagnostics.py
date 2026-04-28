"""Whitelisted backends for the EFRIS Diagnostics page.

The page renders four panels:

- **Overview** — sync-job counts by status (last 24h) and per-interface success rate.
- **Circuit breakers** — current breaker state per (company, interfaceCode).
- **AES sessions** — for each enabled company, whether an AES key is cached.
- **Recent failures** — last 20 failed sync-jobs / non-success request logs.

Everything is read-only; mutations go through the underlying doctypes.
"""
import time

import frappe
from frappe.utils import add_to_date, now_datetime

from uganda_compliance.efris.client import session as session_cache


@frappe.whitelist()
def get_overview() -> dict:
    """Aggregate sync-job stats over the last 24h."""
    since = add_to_date(now_datetime(), hours=-24)
    rows = frappe.db.sql(
        """
        SELECT status, COUNT(*) AS n
        FROM `tabEFRIS Sync Job`
        WHERE creation >= %s
        GROUP BY status
        """,
        (since,),
        as_dict=True,
    )
    by_status = {r["status"]: r["n"] for r in rows}

    interface_rows = frappe.db.sql(
        """
        SELECT
            interface_code,
            SUM(CASE WHEN status = 'Synced' THEN 1 ELSE 0 END) AS synced,
            SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN status IN ('Pending', 'In Progress') THEN 1 ELSE 0 END) AS pending,
            COUNT(*) AS total
        FROM `tabEFRIS Sync Job`
        WHERE creation >= %s
        GROUP BY interface_code
        ORDER BY total DESC
        """,
        (since,),
        as_dict=True,
    )
    for row in interface_rows:
        total = row["total"] or 0
        row["success_rate"] = round((row["synced"] / total) * 100, 1) if total else None

    return {
        "window_hours": 24,
        "by_status": by_status,
        "by_interface": interface_rows,
    }


@frappe.whitelist()
def get_breaker_states() -> list:
    """Inspect the circuit breaker state held in `frappe.cache` for every enabled company."""
    companies = [
        r["company"]
        for r in frappe.get_all(
            "E Invoicing Settings",
            filters={"enabled": 1},
            fields=["company"],
        )
    ]
    interfaces = ("T107", "T108", "T109", "T110", "T111", "T119", "T121", "T130", "T131", "T144")
    rows = []
    for company in companies:
        for interface in interfaces:
            raw = frappe.cache().get_value(f"efris:breaker:{company}:{interface}")
            if not raw:
                continue
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                state = frappe.parse_json(raw) if isinstance(raw, str) else raw
            except Exception:
                continue
            opened_at = state.get("opened_at") or 0
            opened_age = int(time.time() - opened_at) if opened_at else None
            rows.append(
                {
                    "company": company,
                    "interface_code": interface,
                    "state": state.get("state"),
                    "failures": state.get("failures"),
                    "opened_age_seconds": opened_age,
                }
            )
    return rows


@frappe.whitelist()
def get_session_keys() -> list:
    """For each enabled company, report whether an AES key is currently cached."""
    settings = frappe.get_all(
        "E Invoicing Settings",
        filters={"enabled": 1},
        fields=["company", "tin", "device_no", "sandbox_mode", "sandbox_portal_url", "live_portal_url"],
    )
    rows = []
    for s in settings:
        mode_url = s.get("sandbox_portal_url") if s.get("sandbox_mode") else s.get("live_portal_url")
        cached = session_cache.get_cached(s.get("tin"), s.get("device_no"), mode_url or "")
        rows.append(
            {
                "company": s.get("company"),
                "tin": s.get("tin"),
                "device_no": s.get("device_no"),
                "sandbox_mode": s.get("sandbox_mode"),
                "key_cached": bool(cached),
            }
        )
    return rows


@frappe.whitelist()
def get_recent_failures(limit: int = 20) -> list:
    rows = frappe.get_all(
        "EFRIS Sync Job",
        filters={"status": ["in", ("Failed", "Pending")]},
        fields=[
            "name",
            "company",
            "interface_code",
            "status",
            "attempts",
            "max_attempts",
            "last_attempt",
            "next_attempt_at",
            "reference_doctype",
            "reference_name",
            "left(last_error, 300) as last_error",
        ],
        order_by="modified desc",
        limit=limit,
    )
    return rows


@frappe.whitelist()
def reset_breaker(company: str, interface_code: str) -> dict:
    """Manually clear a tripped breaker (audit log gets the user)."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    frappe.cache().delete_value(f"efris:breaker:{company}:{interface_code}")
    return {"ok": True}


@frappe.whitelist()
def invalidate_session_key(company: str) -> dict:
    """Drop the cached AES key so the next call re-handshakes via T104."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    s = frappe.get_value(
        "E Invoicing Settings",
        {"company": company, "enabled": 1},
        ["tin", "device_no", "sandbox_mode", "sandbox_portal_url", "live_portal_url"],
        as_dict=True,
    )
    if not s:
        return {"ok": False, "error": "No enabled E Invoicing Settings for company"}
    mode_url = s.get("sandbox_portal_url") if s.get("sandbox_mode") else s.get("live_portal_url")
    session_cache.invalidate(s.get("tin"), s.get("device_no"), mode_url or "")
    return {"ok": True}
