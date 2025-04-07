import frappe
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings


@frappe.whitelist()
def before_save_query_company(doc, method):
  
    if not doc.get('efris_company_sync'):
        efris_log_info('The Sync EFRIS Data flag is not set.')
        return

    efris_log_info(f"Company query initiated for: {doc.name}")
    
    company_name = doc.get('company_name')
    if not company_name:
        frappe.throw("Company name is not provided.")
    
    company = validate_company_name(company_name)
    
    tax_id, nin_brn = doc.get('tax_id'), doc.get('efris_nin_or_brn')
    if not (tax_id or nin_brn):
        efris_log_info(f"Company {doc.name} is not tax registered (No TIN/NIN/BRN provided).")
        frappe.msgprint(f"Company {doc.name} is not tax registered.")
        return

    query_customer_details(doc, company, tax_id, nin_brn)


def validate_company_name(company_name):
    company_settings = get_e_company_settings(company_name)
    company = company_settings.company if company_settings else None
    if not company:
        efris_log_error("No E Invoicing Settings found.")
        frappe.throw("No E Invoicing Settings found.")
    return company


def query_customer_details(doc, company, tax_id, nin_brn):
    query_data = {"tin": tax_id, "ninBrn": nin_brn}
    success, response = make_post(
        interfaceCode="T119",
        content=query_data,
        company_name=company,
        reference_doc_type=doc.doctype,
        reference_document=doc.name,
    )

    if success:
        company_data = response.get('taxpayer', {})
        update_company_details(doc, company_data)
        create_or_update_address(doc, company_data)
    else:
        frappe.throw(f"Failed to fetch Company details for {doc.name}: {response}")


def update_company_details(doc, company_data):
    doc.company_name = company_data.get('legalName', doc.company_name)
    doc.tax_id = company_data.get('tin', doc.tax_id)
    doc.efris_nin_or_brn = company_data.get('ninBrn', doc.efris_nin_or_brn)

    contact_mobile = company_data.get('contactMobile', "")
    contact_email = company_data.get('contactEmail', "")
    contact_number = company_data.get('contactNumber', "")
    address = company_data.get('address', "")

    doc.address_html = '\n'.join([address, contact_mobile, contact_number, contact_email])
    doc.efris_seller_mobile = contact_number or doc.efris_seller_mobile
    doc.phone_no = contact_number or doc.phone_no
    doc.email = contact_email or doc.email
    doc.efris_company_sync = 0


def create_or_update_address(doc, company_data):
    legal_name = company_data.get('legalName', doc.company_name)
    address_title = f"{legal_name} - Address"
    address = company_data.get('address', "")
    contact_email = company_data.get('contactEmail', "")
    contact_number = company_data.get('contactNumber', "")

    address_data = {
        "doctype": "Address",
        "address_title": address_title,
        "address_type": "Billing",
        "address_line1": address,
        "city": "KAMPALA",
        "country": "Uganda",
        "phone": contact_number,
        "email_id": contact_email,
        "links": [{
            "link_doctype": "Company",
            "link_name": doc.name
        }],
        "is_your_company_address": 1,
        "is_primary_address": 1,
    }

    try:
        frappe.get_doc(address_data).insert()
    except Exception as e:
        frappe.throw(f"Error creating address: {str(e)}")

@frappe.whitelist()
def check_efris_company(tax_id, company_name):
    if tax_id:
        
        query_tax_details_T119 = {
            "tin": tax_id,
            "ninBrn": ""
        }

        connection_status, response = make_post(interfaceCode="T119", content=query_tax_details_T119, company_name=company_name)
                        
        return connection_status
