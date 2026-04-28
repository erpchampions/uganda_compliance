"""Sync vs async dispatch for EFRIS calls.

Business code calls `dispatch(...)` instead of `make_post(...)` directly.
Whether the call runs in-process (legacy behaviour) or is queued as an
EFRIS Sync Job depends on the per-company `async_mode` flag on E Invoicing
Settings.

Why this exists: the legacy hooks call URA inside `before_save` / `on_submit`,
so any URA hiccup rolls back the user's save. Async mode persists the intent
into a queue row and lets a background worker reconcile state — the user's
save succeeds even if URA is down. Sync mode is preserved for migration
safety and for flows where URA must succeed before the local doc is valid
(e.g. credit notes that need an FDN immediately).
"""
import json

import frappe
from frappe.utils import now_datetime

from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import (
    get_e_company_settings,
)

from . import partial as partial_failures
from .logger import get_logger
from .result import EfrisResponse
from .transport import make_post


_STAMP_FIELDS = ("efris_sync_status", "efris_sync_error", "efris_sync_job")


def _stamp_source(
    doctype: str | None,
    name: str | None,
    *,
    status: str,
    job_name: str | None,
    error: str | None = None,
) -> None:
    """Best-effort stamp of sync state on the source document.

    The custom fields are installed by `efris.setup.sync_status_fields.install`;
    if a doctype hasn't had them installed yet (or the doc was deleted), this
    silently no-ops — the EFRIS Sync Job row is the source of truth.
    """
    if not doctype or not name:
        return
    try:
        if not frappe.db.exists(doctype, name):
            return
        meta = frappe.get_meta(doctype)
        updates = {}
        if meta.has_field("efris_sync_status"):
            updates["efris_sync_status"] = status
        if meta.has_field("efris_sync_job") and job_name:
            updates["efris_sync_job"] = job_name
        if meta.has_field("efris_sync_error"):
            updates["efris_sync_error"] = (error or "")[:1000]
        if updates:
            frappe.db.set_value(doctype, name, updates, update_modified=False)
    except Exception as e:
        get_logger().warning(f"EFRIS source-stamp failed {doctype}/{name}: {e}")


JOB_QUEUE = "long"


def is_async_mode(company: str) -> bool:
    """Read the per-company async toggle. Defaults to False on any error."""
    try:
        settings = get_e_company_settings(company)
        return bool(getattr(settings, "async_mode", 0))
    except Exception:
        return False


def dispatch(
    *,
    company: str,
    interface_code: str,
    payload,
    doc=None,
    force_sync: bool = False,
) -> EfrisResponse:
    """Run an EFRIS call now or queue it.

    `force_sync=True` bypasses the company toggle — use it for flows that
    cannot tolerate eventual consistency (e.g. cancellation confirmation).
    """
    if force_sync or not is_async_mode(company):
        return make_post(
            interfaceCode=interface_code,
            content=payload,
            company_name=company,
            reference_doc_type=getattr(doc, "doctype", None),
            reference_document=getattr(doc, "name", None),
        )

    job_name = enqueue_job(
        company=company,
        interface_code=interface_code,
        payload=payload,
        doc=doc,
    )
    _stamp_source(
        getattr(doc, "doctype", None),
        getattr(doc, "name", None),
        status="Pending",
        job_name=job_name,
    )
    get_logger().info(
        f"EFRIS dispatch queued interfaceCode={interface_code} "
        f"company={company} job={job_name}"
    )
    return EfrisResponse(
        ok=True,
        interface_code=interface_code,
        request_id="",
        data={"queued": True, "job": job_name},
    )


def dispatch_legacy(
    *,
    company: str,
    interface_code: str,
    payload,
    doc=None,
    force_sync: bool = False,
):
    """Drop-in replacement for the legacy `make_post` tuple return.

    Same routing rules as `dispatch`. When the call is queued in async mode,
    returns `(True, {"queued": True, "job": "..."})` so callers that don't
    consume the response data don't blow up; callers that DO consume the
    response should pass `force_sync=True`.
    """
    resp = dispatch(
        company=company,
        interface_code=interface_code,
        payload=payload,
        doc=doc,
        force_sync=force_sync,
    )
    if resp.ok:
        return True, resp.data
    msg = resp.error_message or "EFRIS call failed"
    if resp.partial_failures:
        msg = f"{msg}\n{partial_failures.format_summary(resp.partial_failures)}"
    return False, msg


def enqueue_job(
    *,
    company: str,
    interface_code: str,
    payload,
    doc=None,
    max_attempts: int | None = None,
) -> str:
    """Persist an EFRIS Sync Job row and trigger immediate background processing."""
    settings_max = None
    try:
        settings_max = getattr(
            get_e_company_settings(company), "async_max_attempts", None
        )
    except Exception:
        pass

    job = frappe.get_doc(
        {
            "doctype": "EFRIS Sync Job",
            "company": company,
            "interface_code": interface_code,
            "status": "Pending",
            "payload": json.dumps(payload, default=str),
            "reference_doctype": getattr(doc, "doctype", None),
            "reference_name": getattr(doc, "name", None),
            "max_attempts": max_attempts or settings_max or 5,
            "scheduled_at": now_datetime(),
        }
    )
    job.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "uganda_compliance.efris.client.dispatch.run_job",
        queue=JOB_QUEUE,
        job_name=f"efris_sync_job:{job.name}",
        job=job.name,
        enqueue_after_commit=True,
    )
    return job.name


def run_job(job: str) -> None:
    """Background entry point. Loads the job, calls URA, updates state."""
    log = get_logger()
    j = frappe.get_doc("EFRIS Sync Job", job)
    if j.status not in ("Pending", "Failed"):
        log.info(f"EFRIS Sync Job {job} already in status {j.status}; skipping")
        return

    j.mark_in_progress()
    payload = j.get_payload()

    response = make_post(
        interfaceCode=j.interface_code,
        content=payload,
        company_name=j.company,
        reference_doc_type=j.reference_doctype,
        reference_document=j.reference_name,
    )

    if response.ok:
        j.mark_synced(response_data=response.data)
        _stamp_source(
            j.reference_doctype,
            j.reference_name,
            status="Synced",
            job_name=j.name,
            error=None,
        )
        return

    error = response.error_message or "EFRIS call failed"
    if response.partial_failures:
        error = f"{error}\n{partial_failures.format_summary(response.partial_failures)}"

    if (j.attempts or 0) >= (j.max_attempts or 5):
        j.mark_failed(
            error_message=f"Max attempts reached: {error}",
            response_data={
                "error_code": response.error_code,
                "partial_failures": response.partial_failures,
            },
        )
        _stamp_source(
            j.reference_doctype,
            j.reference_name,
            status="Failed",
            job_name=j.name,
            error=error,
        )
        return

    j.schedule_retry(
        error_message=error,
        response_data={
            "error_code": response.error_code,
            "partial_failures": response.partial_failures,
        },
    )
    _stamp_source(
        j.reference_doctype,
        j.reference_name,
        status="Pending",
        job_name=j.name,
        error=error,
    )


def process_due_jobs(batch_size: int = 50) -> None:
    """Scheduler entry point — pick up Pending jobs whose retry window has elapsed."""
    log = get_logger()
    rows = frappe.get_all(
        "EFRIS Sync Job",
        filters={"status": "Pending"},
        or_filters=[
            ["next_attempt_at", "<=", now_datetime()],
            ["next_attempt_at", "is", "not set"],
        ],
        fields=["name"],
        order_by="creation asc",
        limit=batch_size,
    )
    log.info(f"EFRIS dispatch process_due_jobs found {len(rows)} due")
    for row in rows:
        frappe.enqueue(
            "uganda_compliance.efris.client.dispatch.run_job",
            queue=JOB_QUEUE,
            job_name=f"efris_sync_job:{row['name']}",
            job=row["name"],
        )
