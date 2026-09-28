frappe.ui.form.on('POS Invoice', {
    refresh: function(frm) {
        if (frm.is_dirty()) return;
        show_efris_status_pos(frm);
        add_custom_buttons_pos(frm);
    },
    after_submit: function(frm) {
        add_custom_buttons_pos(frm);
    }
});

const EFRIS_STATUS_COLOURS = {
    'Pending': 'orange',
    'Submitting': 'blue',
    'Submitted': 'green',
    'Failed': 'red',
    'Cancelled': 'grey'
};

function show_efris_status_pos(frm) {
    if (frm.doc.docstatus != 1 || !frm.doc.efris_invoice || !frm.doc.efris_status) return;
    const colour = EFRIS_STATUS_COLOURS[frm.doc.efris_status] || 'blue';
    let label = __('EFRIS: {0}', [__(frm.doc.efris_status)]);
    if (frm.doc.efris_status === 'Failed' && frm.doc.efris_next_retry) {
        label += ' · ' + __('retry {0}', [frappe.datetime.comment_when(frm.doc.efris_next_retry)]);
    }
    frm.dashboard.add_indicator(label, colour);
    if (frm.doc.efris_status === 'Failed' && frm.doc.efris_last_error) {
        frm.dashboard.set_headline_alert(
            `<div class="text-danger">${__('EFRIS submission failed')}: ${frappe.utils.escape_html(frm.doc.efris_last_error)}</div>`
        );
    }
}

function add_custom_buttons_pos(frm) {
    if (frm.doc.docstatus != 1 || !frm.doc.efris_invoice || frm.doc.is_consolidated) return;
    if (frm.doc.efris_irn || frm.doc.efris_status === 'Submitted' || frm.doc.efris_status === 'Cancelled') return;

    const label = frm.doc.efris_status === 'Failed' ? __('Retry EFRIS') : __('Send To EFRIS');
    frm.add_custom_button(label, function () {
        frappe.confirm(__('Send this invoice to EFRIS now?'), function () {
            frappe.call({
                method: 'uganda_compliance.efris.api_classes.e_invoice.send_pos_invoice_to_efris',
                args: { name: frm.doc.name },
                freeze: true,
                freeze_message: __('Submitting to EFRIS...'),
                callback: function (r) {
                    const res = r.message || {};
                    frappe.show_alert({
                        message: res.message || __('Done'),
                        indicator: res.status === 'success' ? 'green' : 'red'
                    }, 10);
                    frm.reload_doc();
                }
            });
        });
    }, __('E-Invoicing'));
}
