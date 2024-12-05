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


@frappe.whitelist()
def create_item_tax_templates(doc,method):
    efris_log_info(f"Create Item Tax Templates called ...")
    if not doc.sales_taxes_and_charges_template and doc.purchase_taxes_and_charges_template:
        return
    output_vat_account = doc.get("output_vat_account")
    e_company = doc.get("company")
    efris_log_info(f"E Company is {e_company}")
    efris_log_info(f" VAT Account Head is {output_vat_account}")
    e_tax_category = frappe.db.get_all("E Tax Category")
    efris_log_info(f"E Tax Categories data:{e_tax_category}")
    for tax in e_tax_category:
        tax_category = tax.name
        efris_log_info(f"The E Tax category is {tax_category}")
        if tax_category == '04:D: Deemed (18%)':
            efris_log_info("This E Tax Category is Deemed Tax :{tax_category}")
            continue
        #  Extract the part after the last colon and trim any extra spaces
        tax_name = tax_category.split(':').pop()
        efris_log_error(f"The Tax Name is {tax_name}")
        tax_category_code = tax_category.split(':')[0]
        efris_log_info(f"The E Tax Category Code is {tax_category_code}")
        tax_rate_map = {'01':'18',
                        '02':'0',
                        '03':'-'}
        tax_rate = tax_rate_map.get(tax_category_code)
        efris_log_info(f"The Tax Rate is {tax_rate}")
        item_tax_name = "EFRIS"+tax_name
        efris_log_error(f"The Tax category is {tax_category}")
        item_tax_template = frappe.get_all('Item Tax Template', filters={
                    'title': item_tax_name,
                    'company':e_company
                    })
        if item_tax_template:
            efris_log_info(f"Item Tax Template Exists")
            return
        item_tax_template = frappe.new_doc("Item Tax Template")
        item_tax_template.title = item_tax_name
        item_tax_template.company = e_company
        item_tax_template.append("taxes", {
        "tax_type": output_vat_account,
        "tax_rate": tax_rate,
        "custom_e_tax_category": tax_category
        })
        item_tax_template.insert(ignore_permissions=True)
        frappe.db.commit() 
        efris_log_info(f"Item Tax Template Created successfully {item_tax_template.name}")
        # frappe.throw(f"Item Tax Template Created successfully {item_tax_template.name}")


