import frappe

def execute():
    try:
        custom_fields = frappe.get_all('Custom Field', filters={
            'dt': 'Customer',
            'fieldname': ['in', ['company', 'custom_company']]
        })

        if not custom_fields:
            custom_field = frappe.get_doc({
                'doctype': 'Custom Field',
                'dt': 'Customer',  
                'fieldname': 'company',
                'label': 'Company',
                'fieldtype': 'Link',
                'options': 'Company',  
                'insert_after': 'territory',                
                'depends_on': 'eval: doc.efris_customer_type', 
                'mandatory_depends_on': 'eval: doc.efris_customer_type',
                'in_list_view': 1,  
                'hidden': 0,  
            })
            custom_field.insert()
            frappe.msgprint(f"Field 'e_company' added to Customer doctype.")
        else:
            frappe.msgprint("'e_company' field already exists in the Customer doctype.")

    except Exception as e:
        frappe.msgprint(f"An error occurred: {str(e)}")
