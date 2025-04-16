import frappe
from uganda_compliance.efris.utils.utils import efris_log_info
from uganda_compliance.efris.api_classes.efris_api import make_post

@frappe.whitelist()
def before_save_query_customer(doc, method):
    sync_from_efris = doc.get('efris_sync')
    
    if doc.is_new():
        handle_new_customer(doc)
    elif sync_from_efris:
        handle_customer_update_with_efris_sync(doc)

        
def handle_new_customer(doc):
    efris_log_info(f"Please Save Customer: {doc.name}")
       
def handle_customer_update_with_efris_sync(doc):    
    e_company_name = get_enabled_e_company()
    if not e_company_name:
        frappe.throw("No enabled E Invoicing Settings found.")

    tax_id = doc.get('tax_id')
    ninBrn = doc.get('efris_nin_or_brn')

    if tax_id or ninBrn:
        query_customer_details(doc, e_company_name, tax_id, ninBrn)
    else:
        frappe.msgprint(f"Customer {doc.customer_name} does not have a valid TIN/NIN/BRN")
        
def query_customer_details(doc, e_company_name, tax_id, ninBrn):
    query_customer_details_T119 = {
        "tin": tax_id,
        "ninBrn": ninBrn
    }

    success, response = make_post(
        interfaceCode="T119",
        content=query_customer_details_T119,
        company_name=e_company_name,
        reference_doc_type=doc.doctype,
        reference_document=doc.name
    )

    if success:
        update_customer_details(doc, response)
    else:
        frappe.throw(f"Failed to fetch Customer details for {doc.customer_name}: {response}")

       
def get_enabled_e_company():
    enabled_e_company = frappe.get_all(
        "E Invoicing Settings",
        filters={"enabled": 1},
        fields=["company_name"],
        limit_page_length=1
    )
    return enabled_e_company[0]["company_name"] if enabled_e_company else None
        
def update_customer_details(doc, response):
    taxpayer_data = response.get('taxpayer', {})
    legal_name = taxpayer_data.get('legalName')
    address = taxpayer_data.get('address')
    contact_mobile = taxpayer_data.get('contactMobile')
    taxpayer_type = taxpayer_data.get('taxpayerType')
    tin = taxpayer_data.get('tin')
    ninBrn = taxpayer_data.get('ninBrn')
    email_id = taxpayer_data.get('email') or ''
    governmentTIN = taxpayer_data.get('governmentTIN')

    if legal_name:
        doc.customer_name = legal_name
    if contact_mobile:
        doc.mobile_no = contact_mobile
    if tin:
        doc.tax_id = tin
    if ninBrn:
        doc.efris_nin_or_brn = ninBrn

    if taxpayer_type:
        doc.customer_type = map_taxpayer_type(taxpayer_type)

    if taxpayer_type == "201":
        doc.efris_customer_type = "B2C"
    elif taxpayer_type == "202":
        doc.efris_customer_type = "B2B"
    elif governmentTIN == 1:
        doc.efris_customer_type = "B2G"

    doc.efris_sync = 0

    update_or_create_address(doc, legal_name, address, contact_mobile, email_id)
    
def update_or_create_address(doc, legal_name, address, contact_mobile, email_id):
    address_title = f"{legal_name} - Address"
    existing_address = frappe.db.exists('Address', {'address_title': address_title})

    if len(address) > 140:
        efris_log_info(f"Address for {doc.customer_name} is too long. Truncating to 140 characters.")
        address = address[:140]

    if not existing_address:
        create_new_address(doc, address_title, address, contact_mobile, email_id)
    else:
        update_existing_address(existing_address, address, contact_mobile, doc)
               
def create_new_address(doc, address_title, address, contact_mobile, email_id):
    new_address = frappe.get_doc({
        "doctype": "Address",
        "address_title": address_title,
        "address_type": "Billing",
        "address_line1": address,
        "city": "city", 
        "country": "Uganda",
        "phone": contact_mobile,
        "email_id": email_id,
        "links": [{
            "link_doctype": "Customer",
            "link_name": doc.name
        }],
        "is_your_customer_address": 1,
        "is_primary_address": 1
    })
    new_address.insert(ignore_permissions=True)
    doc.customer_primary_address = new_address.name
    frappe.msgprint(f"Address created and linked for {doc.customer_name}")
    
def update_existing_address(existing_address, address, contact_mobile, doc):
    existing_address_doc = frappe.get_doc("Address", existing_address)
    existing_address_doc.address_line1 = address
    existing_address_doc.phone = contact_mobile
    existing_address_doc.save(ignore_permissions=True)
    doc.customer_primary_address = existing_address_doc.name

def map_taxpayer_type(taxpayer_type):
    mapping = {
        "201": "Individual",
        "202": "Company",
    }
    return mapping.get(taxpayer_type, "Individual") 

