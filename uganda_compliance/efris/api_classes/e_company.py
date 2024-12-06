import frappe
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
import json
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings

@frappe.whitelist()
def before_save_query_company(doc, method):
    
    company_sync_efris = doc.get('company_sync_efris')
    efris_log_info(f"The sync Efris Data Flag is {company_sync_efris}")
    if not company_sync_efris:
        efris_log_info('The Sync Efris Data flag is not Set {company_sync_efris}')
        return

    try:
        
        efris_log_info(f"Company query initiated for: {doc.name}")
        
        company_name = doc.get('company_name')
        efris_log_info(f"Company Name :{company_name}")
    
        if not company_name:
            frappe.throw("Company name is not provided.")
            
        company =  get_e_company_settings(company_name).company
       
        if company:
            # e_company = company_settings[0].get("company")
            efris_log_info(f"Company: {company}")
        else:
            efris_log_error("No E Invoicing Settings found.")
            frappe.throw("No E Invoicing Settings found.")

        # Customer details from the document
        tax_id = doc.get('tax_id')
        ninBrn = doc.get('nin_or_brn')

        efris_log_info(f"Company: {doc.name}, Tax ID: {tax_id}, NIN/BRN: {ninBrn}")

        # Check if either tax_id or ninBrn is provided
        if tax_id or ninBrn:
            
            query_customer_details_T119 = {
                "tin": tax_id,
                "ninBrn": ninBrn
            }

            # Make the post request to EFRIS
            success, response = make_post(interfaceCode="T119", content=query_customer_details_T119, company_name=company, reference_doc_type=doc.doctype, reference_document=doc.name)
                                 

            if success:
                efris_log_info(f"Company details successfully fetched for {doc.name}")

                # Parse response from EFRIS
                company_data = response.get('taxpayer', {})
                
                # Log the fetched data
                efris_log_info(f"Fetched data: {json.dumps(company_data, indent=2)}")
                
                # Extract details from the response
                legal_name = company_data.get('legalName')                
                address = company_data.get('address') or ""                
                contact_mobile = company_data.get('contactMobile') or ""
                contact_email = company_data.get('contactEmail') or ""
                contact_number = company_data.get('contactNumber') or ""
               
                tin = company_data.get('tin') or ""
                ninBrn = company_data.get('ninBrn') or ""
                             

                if legal_name:
                    doc.company_name = legal_name
                    efris_log_info(f"The Company name has been updated to {legal_name}")
                
                if address:
                    doc.address_html = '\n'.join([address,contact_mobile,contact_number,contact_email])
                    efris_log_info(f"The Address is {doc.address_html}")

                if contact_number:
                    doc.seller_mobile = contact_number
                    doc.phone_no = contact_number
                if tin:
                    doc.tax_id = tin
                if ninBrn:
                    doc.nin_or_brn = ninBrn

                if contact_email:
                    doc.email = contact_email   

                doc.company_sync_efris = 0   

                # Now, handle Address creation or updating
                address_title = f"{legal_name} - Address"               
                
                new_address = frappe.get_doc({
                    "doctype": "Address",
                    "address_title": address_title,
                    "address_type":"Billing",
                    "address_line1": address,
                    "city": "KAMPALA",
                    "country": "Uganda",
                    "phone":contact_number,
                    "email_id":contact_email,
                    "links": [{
                        "link_doctype": "Company",
                        "link_name": doc.name
                        }],
                    "is_your_company_address":1,
                    "is_primary_address":1
                    # Other mandatory fields
                })
                new_address.insert()
                                    
                    
                frappe.msgprint(f"Company details successfully updated for {doc.name}")
                efris_log_info(f"Company {doc.name} has been Updated successfully {response}")

            else:
                efris_log_error(f"Failed to fetch Company details for {doc.name}: {response}")
                frappe.throw(f"Failed to fetch Company details for {doc.name}: {response}")
        else:
            efris_log_info(f"Company {doc.name} is not tax registered (No TIN/NIN/BRN provided)")
            frappe.msgprint(f"Company {doc.name} is not tax registered")

    except Exception as e:
        efris_log_error(f"Error in query_customer: {str(e)}")
        frappe.throw(f"Error querying customer: {str(e)}")


