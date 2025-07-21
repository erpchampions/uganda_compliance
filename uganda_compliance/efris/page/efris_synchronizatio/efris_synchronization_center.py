from __future__ import unicode_literals
import frappe

import json
from collections import defaultdict
from frappe import _
from json import JSONEncoder
from frappe.model.document import Document
from datetime import datetime
from uganda_compliance.efris.utils.utils import efris_log_info
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings
from uganda_compliance.efris.api_classes.e_invoice import EInvoiceAPI, decode_e_tax_rate, validate_company,check_credit_note_approval_status
from uganda_compliance.efris.api_classes.stock_in import process_pending_efris_stock_entries
from uganda_compliance.efris.api_classes.efris_invoice_sync import efris_invoice_sync

@frappe.whitelist()
def process_pending_efris_entries():
    """
    Function processes all Pending EFRIS Processes Like EFRIS Invoices, EFRIS Credit Notes, EFRIS Debit Notes, EFRIS Purchase Receipts, and EFRIS Stock Entries.
    """
    synchronization_settings = get_e_company_settings()
    if not synchronization_settings:
        frappe.throw(_("E-Invoicing Settings not found. Please configure E-Invoicing Settings first."))
    if not validate_company(synchronization_settings.company):
        frappe.throw(_("Invalid Company in E-Invoicing Settings. Please check the company configuration."))
    try:
        process_pending_efris_stock_entries()
        efris_log_info("Processing Pending EFRIS Entries", "EFRIS Synchronization Center")
 
    except Exception as e:        
        error_message = f"❌ EFRIS post failed for Stock Entry: {str(e)}"
        frappe.log_error(title=error_message[:140], message=frappe.get_traceback())

import frappe
@frappe.whitelist()
def get_recent_efris_statuses():
    stock_entries = frappe.db.sql("""
        SELECT
            se.name,
            se.modified,
            'Stock Entry' AS doctype,
            se.stock_entry_type AS type,
            se.efris_posted AS efris_status
        FROM `tabStock Entry` se
        WHERE
            se.docstatus = 1
            AND se.efris_posted = 0
            AND se.stock_entry_type IN ('Manufacture', 'Material Transfer')
            AND EXISTS (
                SELECT 1
                FROM `tabStock Entry Detail` sed
                WHERE sed.parent = se.name
                AND sed.efris_transfer = 1                
            )
        ORDER BY se.modified DESC
        LIMIT 10
    """, as_dict=True)

    sales_invoices = frappe.get_all("Sales Invoice",
        filters={
            "docstatus": 1,
            "efris_invoice": 0
        },
        fields=[
            "name",
            "modified",
            "'Sales Invoice' as doctype",
            "efris_invoice as efris_status"
        ],
        order_by="modified desc",
        limit=5
    )

    return stock_entries + sales_invoices

@frappe.whitelist()
def check_invoice_statuses():
    invoices = frappe.get_all("Sales Invoice", filters={
        "docstatus": 1,
    }, fields=["name", "doctype", "posting_date", "efris_invoice"], limit=10)

    return invoices

