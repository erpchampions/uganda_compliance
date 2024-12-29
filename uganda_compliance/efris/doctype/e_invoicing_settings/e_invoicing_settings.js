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