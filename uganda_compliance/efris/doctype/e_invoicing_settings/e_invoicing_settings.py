import frappe
from frappe.model.document import Document
from frappe import _
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error

from frappe.utils.password import get_decrypted_password, set_encrypted_password    


# Global cache to store E Invoicing Settings by company name
e_company_settings_cache = {}

def before_save_e_invoicing_settings(doc):
    old_doc = doc.get_doc_before_save()

    if not old_doc or old_doc.sandbox_private_key_password != doc.sandbox_private_key_password:
        if doc.sandbox_private_key_password:
            set_encrypted_password(doc.doctype, doc.name, doc.sandbox_private_key_password, 'sandbox_private_key_password')
    
    if not old_doc or old_doc.live_private_key_password != doc.live_private_key_password:
        if doc.live_private_key_password:
            set_encrypted_password(doc.doctype, doc.name, doc.live_private_key_password, 'live_private_key_password')


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

@frappe.whitelist()    
def get_e_company_settings(company_name):
    if company_name in e_company_settings_cache:
        return e_company_settings_cache[company_name]
    
    # Fetch entire record from the database
    einvoicing_settings = frappe.get_all(
        "E Invoicing Settings",
        fields=["*"],  
        filters={"company": company_name}
    )
   
    if not einvoicing_settings:
        frappe.throw(f"No E Invoicing Settings found for company: {company_name}")

    settings = einvoicing_settings[0]
    e_invoice_enabled = settings.enabled
    if not e_invoice_enabled:
        frappe.throw(f"E Invoicing Settings are disabled for company: {company_name}")

    # Cache the entire settings record
    e_company_settings_cache[company_name] = settings
    
    return settings

#################################

class EInvoicingSettings(Document):
    def before_save(self):
        e_company_settings_cache.pop(self.company, None)
        self.validate()
        before_save_e_invoicing_settings(self)

    def validate(self):
        """
        Validate E Invoicing Settings before saving.
        """
        self.create_tax_templates()

    def create_tax_templates(self):
        """
        Create or retrieve Sales and Purchase Tax Templates for EFRIS compliance.
        """
        self._create_or_retrieve_sales_tax_template()
        self._create_or_retrieve_purchase_tax_template()
        create_item_tax_templates(self)


    def _create_or_retrieve_sales_tax_template(self):
        """
        Create or retrieve the Sales Tax Template if it doesn't exist.
        """
        if not self.sales_taxes_and_charges_template and self.output_vat_account:
            try:
                template_name = self._get_existing_template("Sales Taxes and Charges Template", "EFRIS Sales VAT Taxes")
                if template_name:
                    self.sales_taxes_and_charges_template = template_name
                else:
                    sales_template = self._create_sales_tax_template()
                    self.sales_taxes_and_charges_template = sales_template.name
            except Exception as e:
                efris_log_error(f"Failed to create or retrieve Sales Tax Template: {str(e)}")


    def _create_or_retrieve_purchase_tax_template(self):
        """
        Create or retrieve the Purchase Tax Template if it doesn't exist.
        """
        if self.input_vat_account and not self.purchase_taxes_and_charges_template:
            try:
                template_name = self._get_existing_template("Purchase Taxes and Charges Template", "EFRIS Purchase VAT Taxes")
                if template_name:
                    self.purchase_taxes_and_charges_template = template_name
                else:
                    purchase_template = self._create_purchase_tax_template()
                    self.purchase_taxes_and_charges_template = purchase_template.name
            except Exception as e:
                frappe.log_error(f"Failed to create or retrieve Purchase Tax Template: {str(e)}")
        else:
            efris_log_info("No Input VAT Account provided; skipping Purchase Tax Template creation.")


    def _get_existing_template(self, doctype, title):
        """
        Retrieve an existing template by title and company.
        """
        return frappe.get_value(
            doctype,
            {"title": title, "company": self.company},
            "name"
        )


    def _create_sales_tax_template(self):
        """
        Create a new Sales Tax Template.
        """
        sales_template = frappe.new_doc("Sales Taxes and Charges Template")
        sales_template.title = "EFRIS Sales VAT Taxes"
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
        return sales_template


    def _create_purchase_tax_template(self):
        """
        Create a new Purchase Tax Template.
        """
        purchase_template = frappe.new_doc("Purchase Taxes and Charges Template")
        purchase_template.title = "EFRIS Purchase VAT Taxes"
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
        return purchase_template

@frappe.whitelist()
def create_item_tax_templates(doc):
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
        
        # Check if Item Tax Template already exists
        item_tax_template = frappe.get_all('Item Tax Template', filters={
            'title': item_tax_name,
            'company': e_company
        })

        if item_tax_template:
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

def update_efris_company(doc, method):
    company = frappe.get_doc("Company",{"name":doc.company})
    if company:
        if not company.efris_company:
            company.efris_company = 1 
            company.save()

        
def clear_e_company_settings_cache(company_name):
    if company_name in e_company_settings_cache:
        del e_company_settings_cache[company_name]
   
def on_update(doc, method=None):
    clear_e_company_settings_cache(doc.company)