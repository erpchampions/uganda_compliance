import frappe
from frappe import _
from uganda_compliance.efris.api_classes.efris_api import make_post
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.request_utils import get_ug_time_str
from json import loads, dumps, JSONDecodeError
from datetime import datetime
from pyqrcode import create as qrcreate
import io
import os
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings
from uganda_compliance.efris.api_classes.e_invoice import EInvoiceAPI


@frappe.whitelist()
def format_date(date_string, current_format="%d/%m/%Y", target_format="%Y-%m-%d"):
    try:
        return datetime.strptime(date_string, current_format).strftime(target_format)
    except ValueError:
        frappe.throw(f"Invalid date format: {date_string}")

@frappe.whitelist()
def efris_invoice_sync():
    # Fetch the E Invoicing Settings (assuming it's single doctype or use limit=1)
    reference_doc_type = ""
    reference_document = ""
    company_list = []
    enabled = ""
    enable_sync_from_efris = ""
    startDate = "2024-12-15"
    efris_log_info("efris_invoice_sync called...")
    company_list = frappe.get_all("E Invoicing Settings",filters = [{"enabled":1,},{'enable_sync_from_efris':1}],fields=["*"])
    for company in company_list:
        # company_settings = frappe.db.get_doc("E Invoicing Settings",{'name':company.name})
        company_name = company.company
        deviceNo = company.device_no
        output_vat_account = company.output_vat_account
        sales_taxes_template = company.sales_taxes_and_charges_template
        efris_log_info(f"The Fetched Company is {company_name}")
        efris_log_info(f"The Fetched Device No is {deviceNo}")        
        efris_log_info(f"Vat output Account :{output_vat_account}")        
        efris_log_info(f"Sales Tax Template :{sales_taxes_template}")        
        enabled = company.enabled       
        enable_sync_from_efris = company.enable_sync_from_efris       
        reference_doc_type = company.name
        efris_log_info(f"The Fetched company name  is {reference_doc_type}")
        reference_document = company.name
        # Get the current date for the query
        if company_name and enabled and enable_sync_from_efris:
            current_date = frappe.utils.today()    
            warehouse = frappe.db.get_value("Warehouse",{"company":company_name,"efris_warehouse": 1},"name")  
            efris_log_info(f"The Active EFRIS Warehouse is {warehouse}")  
            pos_profile =   frappe.db.get_value("POS Profile",{"company":company_name,"warehouse": warehouse},"name")  
            efris_log_info(f"The Active EFRIS Pos Profile is {pos_profile}")  

            # Prepare the query for fetching invoice records from EFRIS (T107)
            query_invoice_credit_note_eligibilty_T07 = {
                "invoiceNo": "",  # Leave empty to get all invoices
                "deviceNo": "",  # Device number from EFRIS
                "buyerTin": "",
                "buyerLegalName": "",
                "invoiceType": "1",  # Assuming 1 is the correct type
                "startDate": current_date,
                "endDate": current_date,
                "pageNo": "1",  # Pagination parameters
                "pageSize": "99",  # Fetch 10 records at a time (adjust as necessary)
                "branchName": ""
            }
            
            # Log the info
            efris_log_info(f"Fetching invoices from EFRIS for company: {company_name} on {current_date}")
            
            # Make the request to EFRIS using the T107 interface
            status, response = make_post(interfaceCode = "T107", content = query_invoice_credit_note_eligibilty_T07, company_name = company_name,reference_doc_type = None, reference_document = reference_document)
            
            if not status:
                # Log the error and return if request fails
                efris_log_error(f"Failed to fetch invoices from EFRIS: {response}")
                frappe.throw(f"Failed to fetch invoices from EFRIS: {response}")
                return
            
            # If successful, process the response
            efris_log_info(f"Successfully fetched invoices from EFRIS: {response}")
            invoices = response.get("records", [])  # Assuming the response contains a 'data' key with the invoice records
            
            for invoice in invoices:
                fdn = invoice.get("invoiceNo")
                
                # Check if this FDN (invoiceNo) exists in ERPNext Sales Invoice
                existing_invoice = frappe.db.exists("Sales Invoice", {"efris_irn": fdn})
            
            
                if existing_invoice:
                    invoice_record = frappe.get_doc("Sales Invoice",{"name":existing_invoice})
                    efris_log_info(f"Invoice with FDN {fdn} already exists in ERPNext, skipping.")
                    if invoice_record.docstatus == 1:
                        # If the invoice already exists, skip it
                        efris_log_info(f"Invoice with FDN {fdn} already exists in ERPNext, skipping.")
                    continue
                
                
                # If invoice does not exist, fetch its details using the T108 interface
                efris_log_info(f"Invoice with FDN {fdn} not found in ERPNext. Fetching details.")
                
                Query_Credit_Notes_Invoice_details_T108 = {
                    "invoiceNo": fdn
                }
                
                # Make the post request to fetch detailed invoice information
                status, invoice_details_response = make_post(interfaceCode = "T108",content =  Query_Credit_Notes_Invoice_details_T108, company_name = company_name,reference_doc_type = None, reference_document = reference_document)
               
                if not status:
                    efris_log_error(f"Failed to fetch invoice details for FDN {fdn}: {invoice_details_response}")
                    continue
                
                # Create Sales Invoice in ERPNext using the fetched details
                invoice_data = invoice_details_response  # Assuming 'data' contains the invoice details
                
                if not invoice_data:
                    efris_log_error(f"No invoice data found for FDN {fdn}, skipping.")
                    continue
                customer_name = invoice_data["buyerDetails"]["buyerLegalName"]
                buyer_type = invoice_data["buyerDetails"]["buyerType"]
                buyer_tin = invoice_data["buyerDetails"].get("buyerTin") or ""
                efris_customer_type = get_customer_type(buyer_type)
                invoice_id = invoice_data["basicInformation"].get("invoiceId") or ""
                efris_log_info(f"Invoice ID :{invoice_id}")
                antifakeCode = invoice_data["basicInformation"].get("antifakeCode")  or ""
                efris_log_info(f"Antifake Code :{antifakeCode}") 
                grossAmount = invoice_data["summary"].get("grossAmount")  or ""
                payway = invoice_data["payWay"]
                payment_method_ = ""
                payment_amount = 0.0
                discount_flag = 0
                discount_total = 0.0
                total_discount_tax = 0.0
                efris_dsct_item_discount =" ",
                efris_dsct_taxable_amount = 0.0,
                efris_dsct_item_tax = 0.0,
                efris_dsct_discountTotal = 0.0,
                efris_dsct_discount_tax = 0.0,
                efris_dsct_discount_tax_rate = 0.0                
                efris_additional_discount_percentage = 0.0
                for data in invoice_data["goodsDetails"]:
                    discount_flag = data.get("discountFlag")
                    if discount_flag == 0:
                        efris_log_info(f"The Row has Discount Flag {discount_flag}")
                        efris_dsct_discount_tax = data.get("tax", 0)
                        efris_dsct_item_discount = data.get("item")
                        efris_dsct_discount_tax_rate = data.get("discountTaxRate", 0)
                
                efris_log_info(f"Gross Amount is {grossAmount}")
                #TODO: we may have more than 1 
                for tax_details in invoice_data["taxDetails"]:
                    taxAmount =  tax_details.get("taxAmount")  or ""
                    efris_log_info(f"Tax Amount {taxAmount}") 
                    #grossAmount = tax_details.get("grossAmount")  or ""
                    #efris_log_info(f"Gross Amount is {grossAmount}")
                qrcode_path = invoice_data["summary"]["qrCode"]
                if qrcode_path:
                    efris_log_info(f"QR Code Path exists...")
                


                # Check if the customer exists
                customer = frappe.db.exists("Customer", customer_name)
                if not customer:
                    # Create a new customer
                    customer = frappe.get_doc({
                        "doctype": "Customer",
                        "customer_name": customer_name,
                        "customer_type": "Individual",  # Assuming buyer is a company
                        "customer_group": "Individual",  # Adjust based on your setup
                        "territory": "All Territories",  # Adjust based on your setup
                        "tax_id": buyer_tin,
                        "efris_customer_type": efris_customer_type,
                        "efris_sync":0
                    })
                    customer.insert(ignore_permissions=True)
                    frappe.log(f"Created new customer: {customer_name}")
                
                # Assuming 'issuedDate' and 'dueDate' are in DD/MM/YYYY format
                issued_date = datetime.strptime(invoice_data["basicInformation"]["issuedDate"], '%d/%m/%Y %H:%M:%S')
                due_date = datetime.strptime(invoice_data["basicInformation"]["issuedDate"], '%d/%m/%Y %H:%M:%S')
                # Prepare the sales invoice document in ERPNext   
                tax_rate = "" 
                is_pos = 0   
            
                sales_invoice = frappe.get_doc({
                    "doctype": "Sales Invoice",
                    "customer": customer_name,
                    "is_efris": 1,
                    "posting_date": current_date,
                    "efris_customer_type": efris_customer_type,
                    "efris_einvoice_status": "EFRIS Generated",
                    "efris_irn": fdn,
                    "company": company_name,
                    "disable_rounded_total": 1,
                    "disable_rounded_tax": 1,
                    "grand_total": float(grossAmount),
                    "net_total": float(invoice_data["summary"].get("netAmount", 0)),
                    "update_stock": 1,
                    "set_warehouse":warehouse
                })

                for tax in invoice_data["taxDetails"]:
                    tax_rate_raw = tax.get("taxRate", "0").strip()  # Get raw tax rate and remove whitespace
                    tax_rate = 0.0

                    try:
                        # Ensure the tax rate can be converted to float
                        tax_rate = float(tax_rate_raw)
                    except ValueError:
                        efris_log_info(f"Invalid tax rate '{tax_rate_raw}' encountered. Defaulting to 0.0")
                        continue  # Skip this tax entry if taxRate is invalid

                    efris_log_info(f"Tax Rate on Item: {tax_rate}")
                    
                    if tax_rate != 0.0:
                        tax_rate = tax_rate + 1  # Increment tax rate if not zero

                    # Append the tax to the Sales Invoice
                    sales_invoice.append("taxes", {
                        "charge_type": "On Net Total",
                        "account_head": output_vat_account,
                        "rate": tax_rate * 100,  # Convert rate to percentage
                        "tax_amount": float(tax.get("taxAmount", 0)),
                        "total": float(tax.get("grossAmount", 0)),
                        "description": f"VAT @ {tax_rate * 100}%",
                        "included_in_print_rate": 1
                    })

                for item in invoice_data["goodsDetails"]:
                    item_code = item["itemCode"]
                    discount_flag = int(item.get("discountFlag", 0))  # Ensure it's treated as an integer
                   
                    efris_log_info(f"Processing item: {item_code}")

                    if discount_flag == 1:
                        # Extract discount-related fields
                        # efris_dsct_item_discount = item.get("item", "")
                        efris_dsct_taxable_amount = float(item.get("total", 0))
                        efris_dsct_item_tax = float(item.get("tax", 0))
                        efris_dsct_discountTotal = float(item.get("discountTotal", 0))
                        # efris_dsct_discount_tax = float(item.get("tax", 0))
                        # efris_dsct_discount_tax_rate = float(item.get("discountTaxRate", 0))
                        efris_log_info(f"Discount applied for item {item_code}: Total Discount: {efris_dsct_discountTotal}, Taxable Amount: {efris_dsct_taxable_amount}, Discount Tax: {efris_dsct_discount_tax}")
                        efris_additional_discount_percentage = float((efris_dsct_discountTotal / efris_dsct_taxable_amount) * 100)
                        efris_log_info(f" Additional Disccount is {efris_additional_discount_percentage}")
                     # Fetch the item using efris_product_code or item_code
                    item_master = frappe.db.get_value("Item", {"efris_product_code": item_code}, "name")
                    
                    if not item_master:
                        # If not found by efris_product_code, try to fetch directly by item_code
                        item_master = frappe.db.get_value("Item", {"name": item_code}, "name")
                    
                    if not item_master:
                        frappe.throw(
                            _(f"Item {item_code} not found. Please check the EFRIS Product Code or Item Code.")
                        )    
                    # Safely retrieve 'qty', default to 0 if not found
                    qty = float(item.get("qty", 0))
                    
                    # Log a warning if 'qty' is missing or zero
                    if qty == 0:
                        efris_log_info(f"Missing or invalid 'qty' for item: {item.get('itemCode', 'Unknown')}. Skipping item.")
                        continue  # Skip this item if qty is invalid          
                    sales_invoice.append("items", {
                                        "item_code": item_master,
                                        "qty": qty,
                                        "rate": float(item.get("unitPrice", 0)),
                                        "amount": float(item.get("total", 0)),
                                        "description": item.get("item", ""),
                                        "efris_dsct_item_discount": efris_dsct_item_discount,
                                        "efris_dsct_taxable_amount": efris_dsct_taxable_amount,
                                        "efris_dsct_item_tax": efris_dsct_item_tax,
                                        "efris_dsct_discountTotal": efris_dsct_discountTotal,
                                        "efris_dsct_discount_tax": efris_dsct_discount_tax,
                                        "efris_dsct_discount_tax_rate": efris_dsct_discount_tax_rate
                                    })
                    
                if payway:
                # Define the mapping for mode_of_payment to EFRIS payment codes
                    is_pos = 1
                    
                    payment_code_map = {
                        "101":"Credit",
                        "102":"Cash",
                        "103" :"Cheque",
                        "104" :"Demand draft",
                        "105" :"Mobile money",
                        "106" : "Visa/Master card",
                        "107" :"EFT",
                        "108" :"POS",
                        "109" :"RTGS",
                        "110":"Swift transfer"
                    }
                    for payments in payway:
                        payment_amount = payments.get("paymentAmount") or 0.0
                        efris_log_info(f"Payment Amount is {payment_amount}")
                        payment_mode = payments.get("paymentMode")
                        payment_method = payment_code_map.get(payment_mode, "Unknown")
                        efris_log_info(f"The Payment Method is {payment_method}")
                        if payment_method == "Credit":
                            efris_log_info(f"Credit Not Included in payments table {payment_method}")
                            continue

                        sales_invoice.append('payments',{
                            "amount": payment_amount,
                            "mode_of_payment": payment_method                            
                        })
                total_discount = sum(float(item.get("discountTotal", 0)) for item in invoice_data["goodsDetails"] if int(item.get("discountFlag", 0)) == 1)
                sales_invoice.discount_amount = abs(total_discount)
                sales_invoice.additional_discount_percentage = abs(efris_additional_discount_percentage)

                if sales_invoice.payments:
                    sales_invoice.is_pos = is_pos
                    sales_invoice.pos_profile = pos_profile
                sales_invoice.flags.ignore_tax = True  # Skip tax recalculation
                sales_invoice.taxes_and_charges = sales_taxes_template
                #sales_invoice.taxes = get_taxes_and_charges("Sales Taxes and Charges Template",sales_taxes_template)
                # sales_invoice.save()
                sales_invoice.insert(ignore_permissions=True)
                efris_log_info(f"Sales Invoice :{sales_invoice.name}")
                efris_log_info(f"The Invoice IRN is {sales_invoice.efris_irn}")
                sales_invoice.submit()              
                einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)
                efris_log_info(f"The einvoice status is {einvoice.status}")
                einvoice.status = "EFRIS Generated"
                einvoice.invoice_id = invoice_id
                einvoice.antifake_code = antifakeCode
                einvoice.irn = sales_invoice.efris_irn
                qrCode = EInvoiceAPI.generate_qrcode(qrcode_path, einvoice)
                if qrCode:
                    einvoice.qrcode_path = qrCode
                einvoice.submit()
                efris_log_info(f"E Invoice {einvoice.name} created successfuly")
                
                efris_log_info(f"Successfully created and submitted Sales Invoice for FDN {fdn}")
                frappe.msgprint(f"Sales Invoice:{sales_invoice.name} created successfully")

            frappe.msgprint("EFRIS Invoice Sync Completed.")
@frappe.whitelist()
def get_customer_type(buyer_type):
    efris_customer_type = ''
    if buyer_type == '0': 
        efris_customer_type = 'B2B'
    elif buyer_type == '1': 
        efris_customer_type = 'B2C'
    elif buyer_type == '2':
        efris_customer_type = 'Foreigner'
    elif buyer_type == '3':
         efris_customer_type = 'B2G'
    return efris_customer_type


