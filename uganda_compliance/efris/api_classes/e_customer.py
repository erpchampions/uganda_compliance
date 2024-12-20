import frappe
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
import json
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings

@frappe.whitelist()
def before_save_query_customer(doc, method):
    sync_from_efris = doc.get('efris_sync')
    efris_log_info(f"The sync EFRIS Data Flag is {sync_from_efris}")
    
    # Scenario 1: Handling new customer creation
    if doc.is_new():
        efris_log_info(f"Please Save Customer: {doc.name}")        
        # if not doc.tax_id and not doc.efris_nin_or_brn:
        return  # Skip if neither tax_id nor NIN/BRN is provided

    # Scenario 2: Handling customer update with sync_from_efris checked
    if sync_from_efris:
        efris_log_info(f"Customer {doc.name} is being updated with EFRIS sync.")
        
        # Check for E Company when syncing with EFRIS
      # Fetch an enabled company from e_invoicing_settings
        enabled_e_company = frappe.get_all(
            "E Invoicing Settings",
            filters={"enabled": 1},
            fields=["company_name"],
            limit_page_length=1
        )

        # Ensure there is at least one enabled company
        if not enabled_e_company:
            efris_log_error("No enabled E Invoicing Settings found.")
            frappe.throw("No enabled E Invoicing Settings found.")

        # Access the first company's name
        e_company_name = enabled_e_company[0]["company_name"]

        # Log the company name for debugging
        efris_log_info(f"Company Name: {e_company_name}")

        # Proceed to query the customer if tax_id or NIN/BRN is provided
        tax_id = doc.get('tax_id')
        ninBrn = doc.get('efris_nin_or_brn')

        if tax_id or ninBrn:
            query_customer_details_T119 = {
                "tin": tax_id,
                "ninBrn": ninBrn
            }

            # Make the post request to EFRIS
            success, response = make_post(interfaceCode="T119", content=query_customer_details_T119, company_name=e_company_name, reference_doc_type=doc.doctype, reference_document=doc.name)
            if success:
                efris_log_info(f"Customer details successfully fetched for {doc.customer_name}")

                taxpayer_data = response.get('taxpayer', {})
                legal_name = taxpayer_data.get('legalName')
                address = taxpayer_data.get('address')
                contact_mobile = taxpayer_data.get('contactMobile')
                taxpayer_type = taxpayer_data.get('taxpayerType')
                tin = taxpayer_data.get('tin')
                ninBrn = taxpayer_data.get('ninBrn')
                email_id = taxpayer_data.get('email') or ''
                governmentTIN = taxpayer_data.get('governmentTIN')

                # Update document fields
                if legal_name:
                    doc.customer_name = legal_name
                    
                if contact_mobile:
                    doc.mobile_no = contact_mobile
                if tin:
                    doc.tax_id = tin
                if ninBrn:
                    doc.efris_nin_or_brn = ninBrn

                if taxpayer_type:
                    doc.customer_type = map_taxpayer_type(taxpayer_type)  # Map EFRIS taxpayer type to ERPNext
                
                if taxpayer_type == "201":
                    doc.efris_customer_type = "B2C"
                elif taxpayer_type == "202":
                    doc.efris_customer_type = "B2B"
                elif governmentTIN == 1:
                    doc.efris_customer_type = "B2G"

                doc.efris_sync = 0    

                # Create or update Address
                address_title = f"{legal_name} - Address"
                existing_address = frappe.db.exists('Address', {'address_title': address_title})
                
                if not existing_address:
                    # Create new address if not exists
                    new_address = frappe.get_doc({
                        "doctype": "Address",
                        "address_title": address_title,
                        "address_type": "Billing",
                        "address_line1": address,
                        "city": "city",  # Replace with actual city
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
                else:
                    # Update the existing address
                    existing_address_doc = frappe.get_doc("Address", existing_address)
                    existing_address_doc.address_line1 = address
                    existing_address_doc.phone = contact_mobile
                    existing_address_doc.save(ignore_permissions=True)
                    doc.customer_primary_address = existing_address_doc.name

            else:
                efris_log_error(f"Failed to fetch Customer details for {doc.customer_name}: {response}")
                frappe.throw(f"Failed to fetch Customer details for {doc.customer_name}: {response}")
        else:
            frappe.msgprint(f"Customer {doc.customer_name} does not have a valid TIN/NIN/BRN")
    
    else:
        efris_log_info("No EFRIS sync or customer creation triggered.")



def map_taxpayer_type(taxpayer_type):
    # Mapping EFRIS taxpayer type to ERPNext customer type
    mapping = {
        "201": "Individual",
        "202": "Company",
        # Add other mappings as needed
    }
    return mapping.get(taxpayer_type, "Individual")  # Default to Individual if not found

