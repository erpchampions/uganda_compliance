"""EFRIS Sync Job — queued URA call.

A row represents a single intent to call URA on behalf of a source document.
The runner (`uganda_compliance.efris.client.dispatch.run_job`) picks rows up,
posts them via the typed transport, and writes the result back. Backoff is
linear-with-cap, computed in `schedule_retry`.
"""
import json

from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime


# Cap retry backoff so a stuck job retries roughly hourly forever rather than
# drifting out to days.
RETRY_BACKOFF_BASE_SECONDS = 60
RETRY_BACKOFF_CAP_SECONDS = 60 * 60


class EFRISSyncJob(Document):
    def mark_in_progress(self):
        self.db_set(
            {
                "status": "In Progress",
                "last_attempt": now_datetime(),
                "attempts": (self.attempts or 0) + 1,
            },
            commit=True,
        )

    def mark_synced(self, response_data=None):
        self.db_set(
            {
                "status": "Synced",
                "last_error": None,
                "next_attempt_at": None,
                "response": json.dumps(response_data, default=str)[:140000]
                if response_data is not None
                else None,
            },
            commit=True,
        )

    def mark_failed(self, error_message: str, response_data=None):
        self.db_set(
            {
                "status": "Failed",
                "last_error": error_message,
                "next_attempt_at": None,
                "response": json.dumps(response_data, default=str)[:140000]
                if response_data is not None
                else None,
            },
            commit=True,
        )

    def schedule_retry(self, error_message: str, response_data=None):
        attempt = self.attempts or 0
        delay = min(
            RETRY_BACKOFF_BASE_SECONDS * (2 ** max(attempt - 1, 0)),
            RETRY_BACKOFF_CAP_SECONDS,
        )
        self.db_set(
            {
                "status": "Pending",
                "last_error": error_message,
                "next_attempt_at": add_to_date(now_datetime(), seconds=delay),
                "response": json.dumps(response_data, default=str)[:140000]
                if response_data is not None
                else None,
            },
            commit=True,
        )

    def get_payload(self):
        if not self.payload:
            return None
        return json.loads(self.payload)
