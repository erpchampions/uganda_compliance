# Copyright (c) 2021, Frappe Technologied Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document
import frappe
from frappe.utils import now
from frappe import enqueue

class EInvoiceRequestLog(Document):
	pass

def log_request_to_efris(request_data, request_full, response_data, response_full, reference_doc_type=None, reference_document=None):
    try:        
        # Enqueue the logging operation
        enqueue(
            "uganda_compliance.efris.doctype.e_invoice_request_log.e_invoice_request_log.enqueue_log_request",
            queue="short",
            request_data=request_data,
            request_full=request_full,
            response_data=response_data,
            response_full=response_full,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )
    except Exception as e:
        frappe.log_error(f"Failed to enqueue request log. Error: {str(e)}")


def enqueue_log_request(request_data, request_full, response_data, response_full, reference_doc_type, reference_document):
    try:
        frappe.log_error("enqueue_log_request called.")
        user = frappe.session.user
        log_entry = frappe.get_doc({
            "doctype": "E Invoice Request Log",
            "user": user or "",
            "request_full": frappe.as_json(request_full),
            "request_data": frappe.as_json(request_data),
            "response_full": frappe.as_json(response_full),
            "response_data": frappe.as_json(response_data),
            "timestamp": now(),
            "reference_doc_type": reference_doc_type,
            "reference_document": reference_document,
        })
        log_entry.insert(ignore_permissions=True)
        frappe.db.commit()  # Explicitly commit since this is outside the main transaction
    except Exception as e:
        frappe.log_error(f"Failed to create log entry in enqueue. Error: {str(e)}")
