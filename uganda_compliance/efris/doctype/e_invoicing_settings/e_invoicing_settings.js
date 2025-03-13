frappe.ui.form.on('E Invoicing Settings', {
    refresh: function(frm) {
        set_account_query(frm, 'output_vat_account', 'Tax');
        set_account_query(frm, 'input_vat_account', 'Tax');

        // Filter for Selling Price Lists in Child Table
        frm.fields_dict['efris_price_list'].grid.get_field('price_list').get_query = function() {
            return {
                filters: {
                    selling: 1
                }
            };
        };
              
    },
    output_vat_account: function(frm) {
        frm.set_value('sales_taxes_and_charges_template', '');
    }, input_vat_account: function(frm) {
        frm.set_value('purchase_taxes_and_charges_template', '');
    },
    
    test_connection: function(frm) {
        frappe.call({
            method: 'uganda_compliance.efris.api_classes.e_company.check_efris_company',
            args: {
                'tax_id': frm.doc.tin,
                'company_name': frm.doc.company_name
            },
            callback: function(r) {
                if (r.message !== undefined) { 
                    console.log(r.message);
                    let connection_status = r.message;

                    if (connection_status === true) {
                        // Success: Green
                        frm.fields_dict.connection_status_display.$wrapper.html(
                            `<div style="width: 20px; height: 20px; background-color: #28a745; border-radius: 4px;"></div>`
                        );
                        frappe.show_alert({ message: __('Connection Successful'), indicator: 'green' });
                    } else {
                        // Failure: Red
                        frm.fields_dict.connection_status_display.$wrapper.html(
                            `<div style="width: 20px; height: 20px; background-color: #dc3545; border-radius: 4px;"></div>`
                        );
                        frappe.show_alert({ message: __('Connection Failed'), indicator: 'red' });
                    }

                    frm.refresh_field('connection_status_display');
                } else {
                    frappe.msgprint(__('Invalid response from server. Please try again.'));
                    console.error('Invalid response:', r);
                }
            },
            error: function(err) {
                console.error('Error during connection check:', err);
                frm.fields_dict.connection_status_display.$wrapper.html(
                    `<div style="width: 20px; height: 20px; background-color: #dc3545; border-radius: 4px;"></div>`
                );
                frappe.msgprint(__('Connection check failed. Please contact support.'));
            }
        });
    }

        




});

function set_account_query(frm, fieldname, account_type) {
    frm.set_query(fieldname, function() {
        return {
            filters: {
                company: frm.doc.company,
                account_type: account_type,
                is_group: 0
            }
        };
    });
}