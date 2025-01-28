import frappe
from frappe.model.document import Document
from frappe import _
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error

import json
import subprocess
from frappe.utils.password import get_decrypted_password, set_encrypted_password    


# Global cache to store E Invoicing Settings by company name
e_company_settings_cache = {}

def before_save_e_invoicing_settings(doc):
    old_doc = doc.get_doc_before_save()

    if not old_doc or old_doc.sandbox_private_key_password != doc.sandbox_private_key_password:
        if doc.sandbox_private_key_password:
            set_encrypted_password(doc.doctype, doc.name, doc.sandbox_private_key_password, 'sandbox_private_key_password')
            efris_log_info("Sandbox private key password encrypted and saved successfully.")
    
    if not old_doc or old_doc.live_private_key_password != doc.live_private_key_password:
        if doc.live_private_key_password:
            set_encrypted_password(doc.doctype, doc.name, doc.live_private_key_password, 'live_private_key_password')
            efris_log_info("Live private key password encrypted and saved successfully.")


def get_mode_decrypted_password(doc):
    try:
        if doc.sandbox_mode:
            decrypted_password = get_decrypted_password('E Invoicing Settings', doc.name, 'sandbox_private_key_password')
            efris_log_info("Decrypted sandbox private key password successfully.")
            return decrypted_password
        else:
            decrypted_password = get_decrypted_password('E Invoicing Settings', doc.name, 'live_private_key_password')
            efris_log_info("Decrypted live private key password successfully.")
            return decrypted_password
    except frappe.AuthenticationError as e:
        efris_log_info(f"Error decrypting password: {str(e)}")
    return None


@frappe.whitelist()
def before_save(doc, method):
    doc.before_save()

@frappe.whitelist()
def get_e_tax_template(company_name, tax_type):
    efris_log_info(f"get_e_tax_template called with company_name, tax_type: {company_name}, {tax_type} ")
    e_settings = get_e_company_settings(company_name)
    template_name = None
    if tax_type == 'Sales Tax':
        template_name = e_settings.sales_taxes_and_charges_template
    elif tax_type == 'Purchase Tax':
        template_name = e_settings.purchase_taxes_and_charges_template
    else:
        frappe.throw(f"Unsupported Tax Type: {tax_type}")
    
    # Fetch the template and its child table details
    template_doc = frappe.get_doc('Sales Taxes and Charges Template', template_name)
    taxes_details = [
        {
            'charge_type': tax.charge_type,
            'account_head': tax.account_head,
            'rate': tax.rate,
            'included_in_print_rate': True  
        }
        for tax in template_doc.taxes
    ]

    return {
        'template_name': template_name,
        'taxes': taxes_details
    }


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
        before_save_e_invoicing_settings(self)

    def validate(self):
        """
        Validate E Invoicing Settings before saving.
        """
        efris_log_info("validate called")
        self.create_tax_templates()

    
    def create_tax_templates(self):
        efris_log_info("Creating Tax Templates...")

        # Sales Tax Template (Mandatory)
        if not self.sales_taxes_and_charges_template and self.output_vat_account:
            try:
                if frappe.db.exists("Sales Taxes and Charges Template", {"title": "EFRIS Sales VAT Taxes", "company": self.company}):
                    existing_template = frappe.get_value(
                        "Sales Taxes and Charges Template",
                        {"title": "EFRIS Sales VAT Taxes", "company": self.company},
                        "name"
                    )
                    self.sales_taxes_and_charges_template = existing_template
                    efris_log_info(f"Sales Tax Template already exists: {existing_template}")
                else:
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
            except Exception as e:
                efris_log_error(f"Failed to create or retrieve Sales Tax Template: {str(e)}")

        # Purchase Tax Template (Optional)
        if self.input_vat_account and not self.purchase_taxes_and_charges_template:
            try:
                if frappe.db.exists("Purchase Taxes and Charges Template", {"title": "EFRIS Purchase VAT Taxes", "company": self.company}):
                    existing_template = frappe.get_value(
                        "Purchase Taxes and Charges Template",
                        {"title": "EFRIS Purchase VAT Taxes", "company": self.company},
                        "name"
                    )
                    self.purchase_taxes_and_charges_template = existing_template
                    efris_log_info(f"Purchase Tax Template already exists: {existing_template}")
                else:
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
            except Exception as e:
                efris_log_error(f"Failed to create or retrieve Purchase Tax Template: {str(e)}")
        else:
            efris_log_info("No Input VAT Account provided; skipping Purchase Tax Template creation.")

        # Create Item Tax Templates after ensuring at least Sales Template exists
        create_item_tax_templates(self)


@frappe.whitelist()
def create_item_tax_templates(doc):
    efris_log_info("Create Item Tax Templates called ...")
    output_vat_account = doc.get("output_vat_account")
    e_company = doc.get("company")
    
    if not output_vat_account:
        efris_log_error("Output VAT Account is missing. Cannot create Item Tax Templates.")
        return
    
    e_tax_categories = frappe.get_all("E Tax Category", fields=["name", "tax_rate"])

    for tax in e_tax_categories:
        tax_category = tax.name
        tax_name = tax_category.split(':').pop()
        tax_rate = tax.tax_rate 
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
        if tax_rate is not None:  
            item_tax_template.append("taxes", {
                "tax_type": output_vat_account,
                "tax_rate": tax_rate,
                "efris_e_tax_category": tax_category
            })
        item_tax_template.insert(ignore_permissions=True)
        efris_log_info(f"Item Tax Template Created successfully: {item_tax_template.name}")

def update_efris_company(doc, method):
    efris_log_info(f"Update EFRIS Company called...")
    company = frappe.get_doc("Company",{"name":doc.company})
    if company:
        efris_log_info(f"The Company Doc is fetched... {company}")
        if not company.efris_company:
            company.efris_company = 1 
            efris_log_info(f"EFRIS Company is true...")
            company.save()

        
def clear_e_company_settings_cache(company_name):
    if company_name in e_company_settings_cache:
        del e_company_settings_cache[company_name]
   
def on_update(doc, method=None):
    clear_e_company_settings_cache(doc.company)