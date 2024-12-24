frappe.ui.form.on('E Invoicing Settings', {
    refresh: function(frm) {
        // Filter for Output VAT Account
        frm.set_query('output_vat_account', function() {
            return {
                filters: {
                    company: frm.doc.company,
                    account_type: 'Tax',
                    is_group: 0
                }
            };
        });

        // Filter for Input VAT Account
        frm.set_query('input_vat_account', function() {
            return {
                filters: {
                    company: frm.doc.company,
                    account_type: 'Tax',
                    is_group: 0
                }
            };
        });

        // Filter for Selling Price Lists in Child Table
        frm.fields_dict['efris_price_list'].grid.get_field('price_list').get_query = function() {
            return {
                filters: {
                    selling: 1
                }
            };
        };
    }
});
