import frappe
from frappe import _
from uganda_compliance.efris.api_classes.efris_api import make_post
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error

from datetime import datetime, timedelta

from uganda_compliance.efris.api_classes.e_invoice import EInvoiceAPI


@frappe.whitelist()
def format_date(date_string, current_format="%d/%m/%Y", target_format="%Y-%m-%d"):
    try:
        return datetime.strptime(date_string, current_format).strftime(target_format)
    except ValueError:
        frappe.throw(f"Invalid date format: {date_string}")


@frappe.whitelist()
def efris_invoice_sync():
    company_settings_list = get_company_settings()
    
    for company in company_settings_list:
        if not company.enabled or not company.enable_sync_from_efris:
            continue
        
        process_company_invoices(company)
        
def get_company_settings():
    return frappe.get_all("E Invoicing Settings", filters=[{"enabled": 1}, {'enable_sync_from_efris': 1}], fields=["*"])

def process_company_invoices(company):
    company_name = company.company
    device_no = company.device_no
    output_vat_account = company.output_vat_account
    sales_taxes_template = company.sales_taxes_and_charges_template
    sync_days_ago = company.sync_days_ago
        
    warehouse = frappe.db.get_value("Warehouse", {"company": company_name, "efris_warehouse": 1}, "name")
    
    pos_profile = frappe.db.get_value("POS Profile", {"company": company_name, "warehouse": warehouse}, "name")
    
    start_date, end_date = calculate_date_range(sync_days_ago)
    
    query_invoice_credit_note_eligibilty_T07 = prepare_query_invoice_credit_note_eligibilty_T07(device_no, start_date, end_date)

    status, response = make_post(interfaceCode="T107", content=query_invoice_credit_note_eligibilty_T07, company_name=company_name, reference_doc_type="E Invoicing Settings", reference_document=company.name)
  
    if not status:
        frappe.throw(f"Failed to fetch invoices from EFRIS: {response}")
        return
    
    invoices = response.get("records", [])
    invoice_counter = 0
    
    for invoice in invoices:
        fdn = invoice.get("invoiceNo")
        if frappe.db.exists("Sales Invoice", {"efris_irn": fdn}):
            frappe.log_error(f"Invoice with FDN {fdn} already exists in ERPNext, skipping.")
            efris_log_info(f"Invoice with FDN {fdn} already exists in ERPNext, skipping.")
            continue
        
        invoice_details = fetch_invoice_details(fdn, company_name, company.name)
        if not invoice_details:
            continue
        
        customer = create_or_get_customer(invoice_details["buyerDetails"])
        sales_invoice = create_sales_invoice(invoice_details, customer, company_name, warehouse, pos_profile, output_vat_account, sales_taxes_template)
        
        if sales_invoice:
            einvoice = create_and_submit_einvoice(sales_invoice, invoice_details)
            invoice_counter += 1

    frappe.msgprint(f"EFRIS Invoice Sync Completed. {invoice_counter} Invoices Synchronized from EFRIS")


def create_or_get_customer(buyer_details):
    customer_name = buyer_details["buyerLegalName"]
    buyer_tin = buyer_details.get("buyerTin", "")
    buyer_type = buyer_details["buyerType"]
    efris_customer_type = get_customer_type(buyer_type)
    
    if not frappe.db.exists("Customer", customer_name):
        customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": "Individual",
            "customer_group": "Individual",
            "territory": "All Territories",
            "tax_id": buyer_tin,
            "efris_customer_type": efris_customer_type,
            "efris_sync": 0
        })
        customer.insert(ignore_permissions=True)
        frappe.log(f"Created new customer: {customer_name}")
    
    return customer_name

def calculate_date_range(sync_days_ago):
    end_date = frappe.utils.today()
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=sync_days_ago)).strftime("%Y-%m-%d")
    return start_date, end_date

def prepare_query_invoice_credit_note_eligibilty_T07(device_no, start_date, end_date):
    return {
        "invoiceNo": "",
        "deviceNo": device_no,
        "buyerTin": "",
        "buyerLegalName": "",
        "invoiceType": "1",
        "startDate": start_date,
        "endDate": end_date,
        "pageNo": "1",
        "pageSize": "99",
        "branchName": ""
    }

def fetch_invoice_details(fdn, company_name, reference_document):
    query_credit_notes_invoice_details_T108 = {"invoiceNo": fdn}
    status, response = make_post(interfaceCode="T108", content=query_credit_notes_invoice_details_T108, company_name=company_name, reference_doc_type=None, reference_document=reference_document)
    
    if not status:
        frappe.log_error(f"Failed to fetch invoice details for FDN {fdn}: {response}")
        efris_log_error(f"Failed to fetch invoice details for FDN {fdn}: {response}")
        return None
    
    return response

def create_sales_invoice(invoice_data, customer, company_name, warehouse, pos_profile, output_vat_account, sales_taxes_template):
    invoice_details = invoice_data["basicInformation"]
    goods_details = invoice_data["goodsDetails"]
    tax_details = invoice_data["taxDetails"]
    payway = invoice_data["payWay"]

    sales_invoice = create_base_sales_invoice(invoice_details, customer, company_name, warehouse)

    add_taxes_to_invoice(sales_invoice, tax_details, output_vat_account)

    add_items_to_invoice(sales_invoice, goods_details)

    if payway:
        add_payments_to_invoice(sales_invoice, payway, pos_profile)

    apply_discounts_to_invoice(sales_invoice, goods_details)

    finalize_sales_invoice(sales_invoice, sales_taxes_template)

    return sales_invoice


def create_base_sales_invoice(invoice_details, customer, company_name, warehouse):
    """Create the base Sales Invoice document."""
    return frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": customer,
        "is_efris": 1,
        "posting_date": frappe.utils.today(),
        "efris_customer_type": get_customer_type(invoice_details["buyerDetails"]["buyerType"]),
        "efris_einvoice_status": "EFRIS Generated",
        "efris_irn": invoice_details["invoiceNo"],
        "company": company_name,
        "disable_rounded_total": 1,
        "disable_rounded_tax": 1,
        "grand_total": float(invoice_details["summary"].get("grossAmount", 0)),
        "net_total": float(invoice_details["summary"].get("netAmount", 0)),
        "update_stock": 1,
        "set_warehouse": warehouse
    })


def add_taxes_to_invoice(sales_invoice, tax_details, output_vat_account):
    """Add taxes to the Sales Invoice."""
    for tax in tax_details:
        tax_rate = float(tax.get("taxRate", "0").strip())
        if tax_rate != 0.0:
            tax_rate += 1
        
        sales_invoice.append("taxes", {
            "charge_type": "On Net Total",
            "account_head": output_vat_account,
            "rate": tax_rate * 100,
            "tax_amount": float(tax.get("taxAmount", 0)),
            "total": float(tax.get("grossAmount", 0)),
            "description": f"VAT @ {tax_rate * 100}%",
            "included_in_print_rate": 1
        })


def add_items_to_invoice(sales_invoice, goods_details):
    """Add items to the Sales Invoice."""
    for item in goods_details:
        item_code = item["itemCode"]
        discount_flag = int(item.get("discountFlag", 0))
        
        item_master = frappe.db.get_value("Item", {"efris_product_code": item_code}, "name") or frappe.db.get_value("Item", {"name": item_code}, "name")
        
        if not item_master:
            frappe.throw(f"Item {item_code} not found. Please check the EFRIS Product Code or Item Code.")
        
        qty = float(item.get("qty", 0))
        if qty == 0:
            frappe.log_error(f"Missing or invalid 'qty' for item: {item.get('itemCode', 'Unknown')}. Skipping item.")
            efris_log_info(f"Missing or invalid 'qty' for item: {item.get('itemCode', 'Unknown')}. Skipping item.")
            continue
        
        sales_invoice.append("items", {
            "item_code": item_master,
            "qty": qty,
            "rate": float(item.get("unitPrice", 0)),
            "amount": float(item.get("total", 0)),
            "description": item.get("item", ""),
            "efris_dsct_item_discount": item.get("discountFlag", 0),
            "efris_dsct_taxable_amount": float(item.get("total", 0)),
            "efris_dsct_item_tax": float(item.get("tax", 0)),
            "efris_dsct_discount_total": float(item.get("discountTotal", 0)),
            "efris_dsct_discount_tax": float(item.get("discountTax", 0)),
            "efris_dsct_discount_tax_rate": float(item.get("discountTaxRate", 0))
        })


def add_payments_to_invoice(sales_invoice, payway, pos_profile):
    """Add payments to the Sales Invoice."""
    is_pos = 1
    payment_code_map = {
        "101": "Credit",
        "102": "Cash",
        "103": "Cheque",
        "104": "Demand draft",
        "105": "Mobile money",
        "106": "Visa/Master card",
        "107": "EFT",
        "108": "POS",
        "109": "RTGS",
        "110": "Swift transfer"
    }
    
    for payment in payway:
        payment_amount = payment.get("paymentAmount", 0.0)
        payment_mode = payment.get("paymentMode")
        payment_method = payment_code_map.get(payment_mode, "Unknown")
        
        if payment_method == "Credit":
            continue
        
        sales_invoice.append('payments', {
            "amount": payment_amount,
            "mode_of_payment": payment_method
        })
    
    if sales_invoice.payments:
        sales_invoice.is_pos = is_pos
        sales_invoice.pos_profile = pos_profile


def apply_discounts_to_invoice(sales_invoice, goods_details):
    """Apply discounts to the Sales Invoice."""
    total_discount = sum(float(item.get("discountTotal", 0)) for item in goods_details if int(item.get("discountFlag", 0)) == 1)
    sales_invoice.discount_amount = abs(total_discount)
    sales_invoice.additional_discount_percentage = abs(calculate_additional_discount_percentage(goods_details))


def finalize_sales_invoice(sales_invoice, sales_taxes_template):
    """Finalize and submit the Sales Invoice."""
    sales_invoice.flags.ignore_tax = True
    sales_invoice.taxes_and_charges = sales_taxes_template
    sales_invoice.insert(ignore_permissions=True)
    sales_invoice.submit()

def calculate_additional_discount_percentage(goods_details):
    total_discount = sum(float(item.get("discountTotal", 0)) for item in goods_details if int(item.get("discountFlag", 0)) == 1)
    total_taxable_amount = sum(float(item.get("total", 0)) for item in goods_details if int(item.get("discountFlag", 0)) == 1)
    
    if total_taxable_amount == 0:
        return 0.0
    
    return (total_discount / total_taxable_amount) * 100

def create_and_submit_einvoice(sales_invoice, invoice_data):
    einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)
    einvoice.status = "EFRIS Generated"
    einvoice.invoice_id = invoice_data["basicInformation"].get("invoiceId", "")
    einvoice.antifake_code = invoice_data["basicInformation"].get("antifakeCode", "")
    einvoice.irn = sales_invoice.efris_irn
    
    qrcode_path = invoice_data["summary"].get("qrCode", "")
    if qrcode_path:
        qrCode = EInvoiceAPI.generate_qrcode(qrcode_path, einvoice)
        if qrCode:
            einvoice.qrcode_path = qrCode
    
    einvoice.submit()
    return einvoice

def get_customer_type(buyer_type):
    return "Individual"

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

