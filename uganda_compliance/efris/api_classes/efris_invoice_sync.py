import six
import frappe
from frappe import _
from frappe.utils.data import get_link_to_form
from uganda_compliance.efris.api_classes.efris_api import make_post
from uganda_compliance.efris.doctype.e_invoice.e_invoice import validate_company
from uganda_compliance.efris.utils.utils import efris_log_info, safe_load_json, efris_log_error
from uganda_compliance.efris.api_classes.request_utils import get_ug_time_str
from json import loads, dumps, JSONDecodeError
from datetime import datetime
from pyqrcode import create as qrcreate
import io
import os
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings



@frappe.whitelist()
def efris_invoice_sync():
    # Fetch the E Invoicing Settings (assuming it's single doctype or use limit=1)
    efris_log_info("efris_invoice_sync called...")
    enable_sync_from_efris = ""
    is_enabled = ""
    company_name = ""
    enabled_e_company = frappe.get_all(
        "E Invoicing Settings",
        filters=[{"enabled": 1},{"enable_sync_from_efris":1}],
        fields=["*"],
        limit_page_length=1
    )
    
    # Ensure there is at least one enabled company
    if not enabled_e_company:
        efris_log_error("No enabled E Invoicing Settings found.")
        return

    # Access the first company's name
    company_name = enabled_e_company[0]["company_name"]
    efris_log_info(f"The Fetched Company is {company_name}")
    is_enabled = enabled_e_company[0]['enabled']
    # device_No = esettings.device_no
    efris_log_info(f"The Fetched Company {company_name} is {is_enabled} ")
    enable_sync_from_efris = enabled_e_company[0]['enable_sync_from_efris']
    # reference_doc_type = enabled_e_company[0]['doctype']
    # reference_document = enabled_e_company[0]['name']
    # efris_log_info(f"Doctype is {reference_doc_type}")
    # efris_log_info(f"Document is {reference_document}")
    if company_name and is_enabled and enable_sync_from_efris:
    
            # Get the current date for the query
            current_date = frappe.utils.today()

            # Prepare the query for fetching invoice records from EFRIS (T107)
            query_invoice_credit_note_eligibilty_T07 = {
                "invoiceNo": "",  # Leave empty to get all invoices
                "deviceNo": "1017460267_01",  # Device number from EFRIS
                "buyerTin": "",
                "buyerLegalName": "",
                "invoiceType": "1",  # Assuming 1 is the correct type
                "startDate": current_date,
                "endDate": current_date,
                "pageNo": "1",  # Pagination parameters
                "pageSize": "10",  # Fetch 10 records at a time (adjust as necessary)
                "branchName": ""
            }
            
            # Log the info
            efris_log_info(f"Fetching invoices from EFRIS for company: {company_name} on {current_date}")
            
            # Make the request to EFRIS using the T107 interface
            status, response = make_post(interfaceCode = "T107", content = query_invoice_credit_note_eligibilty_T07, company_name = company_name,reference_doc_type=enabled_e_company[0]['doctype'], reference_document= enabled_e_company[0]['name'])
            
            if not status:
                # Log the error and return if request fails
                efris_log_error(f"Failed to fetch invoices from EFRIS: {response}")
                frappe.throw(f"Failed to fetch invoices from EFRIS: {response}")
                return
            
            # If successful, process the response
            efris_log_info(f"Successfully fetched invoices from EFRIS: {response}")
            invoices = response.get("data", [])  # Assuming the response contains a 'data' key with the invoice records
            
            for invoice in invoices:
                fdn = invoice.get("invoiceNo")
                
                # Check if this FDN (invoiceNo) exists in ERPNext Sales Invoice
                existing_invoice = frappe.db.exists("Sales Invoice", {"irn": fdn})
                
                if existing_invoice:
                    # If the invoice already exists, skip it
                    efris_log_info(f"Invoice with FDN {fdn} already exists in ERPNext, skipping.")
                    continue
                
                # If invoice does not exist, fetch its details using the T108 interface
                efris_log_info(f"Invoice with FDN {fdn} not found in ERPNext. Fetching details.")
                
                Query_Credit_Notes_Invoice_details_T108 = {
                    "invoiceNo": fdn
                }
                
                # Make the post request to fetch detailed invoice information
                status, invoice_details_response = make_post("T108", Query_Credit_Notes_Invoice_details_T108, company_name)
                
                if not status:
                    efris_log_error(f"Failed to fetch invoice details for FDN {fdn}: {invoice_details_response}")
                    continue
                
                # Create Sales Invoice in ERPNext using the fetched details
                invoice_data = invoice_details_response.get("data", {})  # Assuming 'data' contains the invoice details
                
                if not invoice_data:
                    efris_log_error(f"No invoice data found for FDN {fdn}, skipping.")
                    continue
                
                # Prepare the sales invoice document in ERPNext
                sales_invoice = frappe.get_doc({
                    "doctype": "Sales Invoice",
                    "customer": invoice_data.get("buyerLegalName"),
                    "posting_date": invoice_data.get("invoiceDate"),
                    "irn": fdn,  # Store the FDN (IRN) in the custom field
                    "items": [{
                        "item_code": item.get("itemCode"),  # Assumed field names
                        "qty": item.get("quantity"),
                        "rate": item.get("unitPrice"),
                        "description": item.get("itemName")
                    } for item in invoice_data.get("items", [])],  # Assuming items come in a list
                    "company": company_name,
                    "einvoice_status": "Efris Generated"  # Mark the status as "Efris Generated"
                })
                
                # Insert and submit the sales invoice
                sales_invoice.insert(ignore_permissions=True)
                sales_invoice.submit()
                
                efris_log_info(f"Successfully created and submitted Sales Invoice for FDN {fdn}")

            frappe.msgprint("EFRIS Invoice Sync Completed.")
    else:
         return 
            

