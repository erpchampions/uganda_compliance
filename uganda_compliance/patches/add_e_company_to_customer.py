import frappe

def execute():
    try:
        # Check if the custom field already exists
        custom_fields = frappe.get_all('Custom Field', filters={
            'dt': 'Customer',
            'fieldname': ['in', ['company', 'custom_company']]
        })

        if not custom_fields:
            # Define the custom field properties
            custom_field = frappe.get_doc({
                'doctype': 'Custom Field',
                'dt': 'Customer',  # Doctype to which this field is added
                'fieldname': 'company',
                'label': 'Company',
                'fieldtype': 'Link',
                'options': 'Company',  # Link to Company doctype
                'insert_after': 'territory',  # Insert after territory field                
                'depends_on': 'eval: doc.efris_customer_type',  # Depends on efris_customer_type
                'mandatory_depends_on': 'eval: doc.efris_customer_type',
                'in_list_view': 1,  # Visible in the list view
                'hidden': 0,  # Field is not hidden
            })
            custom_field.insert()
            #frappe.db.commit()
            frappe.msgprint(f"Field 'e_company' added to Customer doctype.")
        else:
            frappe.msgprint("'e_company' field already exists in the Customer doctype.")

    except Exception as e:
        frappe.msgprint(f"An error occurred: {str(e)}")
