import frappe
from frappe.model.document import Document
from frappe import _
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
import json

# Global cache to store E Invoicing Settings by company name
e_company_settings_cache = {}

@frappe.whitelist()
def before_save(doc, method):
    doc.before_save()

@frappe.whitelist()
def get_e_tax_template(company_name, tax_type):
    efris_log_info(f"get_e_tax_template called with company_name, tax_type: {company_name}, {tax_type} ")
    if tax_type == 'Sales Tax':
        return get_e_company_settings(company_name).sales_taxes_and_charges_template
    elif tax_type == 'Purchase Tax':
        return get_e_company_settings(company_name).purchase_taxes_and_charges_template
    else:
        frappe.throw(f"Unsupported Tax Type: {tax_type}")


def get_mode_private_key_path(e_settings):
    
    if e_settings.enabled:
        if e_settings.sandbox_mode:
            return e_settings.sandbox_private_key
        else:
            return e_settings.live_private_key
    else:
        frappe.throw("E Invoicing Settings are disabled")

    
def get_e_company_settings(company_name):
    # Check if settings are already cached
    if company_name in e_company_settings_cache:
        return e_company_settings_cache[company_name]
    
    # Fetch entire record from the database
    einvoicing_settings = frappe.get_all(
        "E Invoicing Settings",
        fields=["*"],  # Fetch all fields
        filters={"company": company_name}
    )
   
    if not einvoicing_settings:
        efris_log_error(f"No E Invoicing Settings found for company: {company_name}")
        frappe.throw(f"No E Invoicing Settings found for company: {company_name}")

    settings = einvoicing_settings[0]
    e_invoice_enabled = settings.enabled
    if not e_invoice_enabled:
        efris_log_error(f"E Invoicing Settings are disabled for company: {company_name}")
        frappe.throw(f"E Invoicing Settings are disabled for company: {company_name}")

    # Cache the entire settings record
    e_company_settings_cache[company_name] = settings
    
    return settings

#################################

class EInvoicingSettings(Document):
    def before_save(self):
        efris_log_info("EInvoicingSettings before_save")
        self.validate()

    def validate(self):
        efris_log_info("validate called")
        self.validate_set_vat_accounts()        
  
    
    def validate_set_vat_accounts(self):
        efris_log_info(f"sel validate_vat_accounts called, doc:{self}")
        doc_json = frappe.as_json(self)
        doc_dict = json.loads(doc_json)
        efris_log_info("doc parsed OK")

        required_flags = ["included_in_print_rate", "included_in_paid_amount", "account_head"]

        purchase_tax_template = doc_dict.get('purchase_taxes_and_charges_template')
        sales_tax_template = doc_dict.get('sales_taxes_and_charges_template')
            
        # Fetch child table entries and check both flags are true
        
        doctype = "Purchase Taxes and Charges" 
        taxes = frappe.get_all(doctype, filters={'parent': purchase_tax_template}, fields=required_flags)

        if not all(taxes[0].get(flag) for flag in required_flags):  # Check first entry's flags
            frappe.throw(_(
                f"The selected template for Purchase Tax must have both 'included_in_print_rate' and 'included_in_paid_amount' set to true."
            ))

        self.input_vat_account = taxes[0].account_head
        efris_log_info(f"Purchase Tax is OK, VAT account is: {self.input_vat_account}")

        doctype = "Sales Taxes and Charges"
        taxes = frappe.get_all(doctype, filters={'parent': sales_tax_template}, fields=required_flags)

        if not all(taxes[0].get(flag) for flag in required_flags):  # Check first entry's flags
            frappe.throw(_(
                f"The selected template for Sales Tax  must have both 'included_in_print_rate' and 'included_in_paid_amount' set to true."
            ))

        self.output_vat_account = taxes[0].account_head
        efris_log_info(f"Sales Tax is OK, VAT account is: {self.output_vat_account}")
        

