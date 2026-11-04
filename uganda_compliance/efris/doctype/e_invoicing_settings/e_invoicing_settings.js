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
        // T101 (server time) through the selected connection mode; the server checks roles.
        const show = (ok) => frm.fields_dict.connection_status_display.$wrapper.html(
            `<div style="width: 20px; height: 20px; background-color: ${ok ? '#28a745' : '#dc3545'}; border-radius: 4px;"></div>`
        );
        frappe.call({
            method: 'uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.test_connection',
            args: { company: frm.doc.company },
            freeze: true,
            freeze_message: __('Contacting EFRIS...'),
        }).then((r) => {
            const res = r.message || {};
            show(res.ok);
            frappe.msgprint({
                title: res.ok ? __('Connection Successful') : __('Connection Failed'),
                indicator: res.ok ? 'green' : 'red',
                message: `${frappe.utils.escape_html(res.mode || '')}<br>`
                    + (res.ok ? __('Server time: {0}', [frappe.utils.escape_html(res.message || '')])
                              : frappe.utils.escape_html(res.message || '')),
            });
        }, () => show(false));
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