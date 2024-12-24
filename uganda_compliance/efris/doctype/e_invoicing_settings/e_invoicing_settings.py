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
        """
        Validate E Invoicing Settings before saving.
        """
        efris_log_info("validate called")
        self.create_tax_templates()

    
    def create_tax_templates(self):
        efris_log_info("Creating Tax Templates...")

        # Sales Tax Template (Mandatory)
        if not self.sales_taxes_and_charges_template:
            sales_template = frappe.new_doc("Sales Taxes and Charges Template")
            sales_template.title = f"EFRIS Sales VAT Taxes"
            sales_template.company = self.company
            sales_template.append("taxes", {
                "charge_type": "On Net Total",
                "account_head": self.output_vat_account,
                "rate": 18,
                "description": "VAT@18.0",
                "included_in_print_rate": 1,
                "included_in_paid_amount": 1,
            })
            sales_template.insert(ignore_permissions=True)
            self.sales_taxes_and_charges_template = sales_template.name
            efris_log_info(f"Sales Tax Template created: {sales_template.name}")
        
        # Purchase Tax Template (Optional)
        if self.input_vat_account and not self.purchase_taxes_and_charges_template:
            purchase_template = frappe.new_doc("Purchase Taxes and Charges Template")
            purchase_template.title = f"EFRIS Purchase VAT Taxes"
            purchase_template.company = self.company
            purchase_template.append("taxes", {
                "category": "Total",
                "add_deduct_tax": "Add",
                "charge_type": "On Net Total",
                "account_head": self.input_vat_account,
                "rate": 18,
                "description": "VAT@18.0",
                "included_in_print_rate": 1,
                "included_in_paid_amount": 1,
            })
            purchase_template.insert(ignore_permissions=True)
            self.purchase_taxes_and_charges_template = purchase_template.name
            efris_log_info(f"Purchase Tax Template created: {purchase_template.name}")
        else:
            efris_log_info("No Input VAT Account provided; skipping Purchase Tax Template creation.")

        # Create Item Tax Templates after ensuring at least Sales Template exists
        create_item_tax_templates(self, "validate")


#@frappe.whitelist()
@frappe.whitelist()
def create_item_tax_templates(doc, method=None):
    efris_log_info("Create Item Tax Templates called ...")
    output_vat_account = doc.get("output_vat_account")
    e_company = doc.get("company")
    
    if not output_vat_account:
        efris_log_error("Output VAT Account is missing. Cannot create Item Tax Templates.")
        return
    
    e_tax_category = frappe.db.get_all("E Tax Category")

    for tax in e_tax_category:
        tax_category = tax.name
        tax_name = tax_category.split(':').pop()
        tax_category_code = tax_category.split(':')[0]
        tax_rate_map = {'01': '18', '02': '0', '03': '-', '04': '18'}  # Added 04:D: Deemed (18%)
        tax_rate = tax_rate_map.get(tax_category_code)
        item_tax_name = f"EFRIS {tax_name}"

        efris_log_info(f"Processing Tax Category: {tax_category} | Tax Name: {tax_name} | Rate: {tax_rate}")
        
        # Check if Item Tax Template already exists
        item_tax_template = frappe.get_all('Item Tax Template', filters={
            'title': item_tax_name,
            'company': e_company
        })

        if item_tax_template:
            efris_log_info(f"Item Tax Template already exists: {item_tax_name}")
            continue

        # Create a new Item Tax Template
        item_tax_template = frappe.new_doc("Item Tax Template")
        item_tax_template.title = item_tax_name
        item_tax_template.company = e_company
        item_tax_template.append("taxes", {
            "tax_type": output_vat_account,
            "tax_rate": tax_rate,
            "efris_e_tax_category": tax_category
        })
        item_tax_template.insert(ignore_permissions=True)
        efris_log_info(f"Item Tax Template Created successfully: {item_tax_template.name}")
   
def update_efris_company(doc,mehtod):
    efris_log_info(f"Update EFRIS Company called...")
    company = frappe.get_doc("Company",{"name":doc.company})
    if company:
        efris_log_info(f"The Comopany Doc is fetched... {company}")
        if not company.efris_company:
            company.efris_company = 1 
            efris_log_info(f"EFRIS Company is true...")
            company.save()

