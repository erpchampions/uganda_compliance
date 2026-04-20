frappe.ui.form.on('POS Invoice', {
    refresh: async function(frm) {
        if (frm.is_dirty()) return;
        add_custom_buttons_pos(frm);
    },
    after_submit: async function(frm) {
        add_custom_buttons_pos(frm);
    }
});

const raise_form_is_dirty_error_pos = () => {
    frappe.throw({
        message: __('You must save the document before making e-invoicing request.'),
        title: __('Unsaved Document')
    });
};

function get_auto_send_pos_invoice_flag(frm) {
    return new Promise((resolve) => {
        if (!frm.doc.efris_invoice) {
            return resolve(0);
        }

        frappe.call({
            method: "uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.get_e_company_settings",
            args: { company_name: frm.doc.company },
            callback: function(r) {
                if (r.message && r.message.auto_send_submitted_invoice == 1) {
                    resolve(1);
                } else {
                    resolve(0);
                }
            }
        });
    });
}

async function add_custom_buttons_pos(frm) {
    if (frm.doc.docstatus != 1 || !frm.doc.efris_invoice || frm.doc.efris_irn || frm.doc.efris_e_invoice) {
        return;
    }

    const auto_send = await get_auto_send_pos_invoice_flag(frm);

    if (auto_send != 1) {
        frm.add_custom_button(__('Submit To EFRIS'), async function () {
            frappe.confirm(
                __('Are you sure you want to submit?'),
                async function () {
                    try {
                        const response = await frappe.call({
                            method: 'uganda_compliance.efris.api_classes.e_invoice.send_pos_invoice_to_efris',
                            args: { doc: frm.doc },
                            freeze: true,
                            freeze_message: __('Submitting to EFRIS...')
                        });

                        if (response.message) {
                            frappe.msgprint(__('POS Invoice submitted to EFRIS successfully.'));
                            frm.reload_doc();
                        } else {
                            console.log(__('Failed to submit POS Invoice to EFRIS.'));
                        }
                    } catch (error) {
                        console.error("Error submitting to EFRIS:", error);
                        frappe.msgprint(__('An error occurred while submitting to EFRIS.'));
                    }
                },
                function () {
                    console.log("Submission to EFRIS was cancelled by the user.");
                }
            );
        }, __('E-Invoicing'));
    }
}
