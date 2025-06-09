frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        if (frm.is_dirty()) return;

        let is_efris = frm.doc.efris_invoice;

        if (is_efris == 1) {
            try {
                const { einvoice_status } = frm.doc;

                if (einvoice_status === 'EFRIS Credit Note Pending') {
                    add_einvoice_button(__('Check EFRIS Approval Status'), async () => {
                        if (frm.is_dirty()) return raise_form_is_dirty_error();

                        await frm.reload_doc();

                        try {
                            await frappe.call({
                                method: 'uganda_compliance.efris.api_classes.e_invoice.confirm_irn_cancellation',
                                args: { sales_invoice: frm.doc },
                                freeze: false, 
                                callback: function(r) {
                                    if (!r.exc) {
                                        frm.reload_doc(); 
                                    }
                                }
                            });
                        } catch (error) {
                            console.error(`Error confirming IRN cancellation: ${error}`);
                        }
                    });
                }
            } catch (error) {
                console.error(`Error in refresh: ${error}`);
            }
        }
    },
    validate: async function(frm) {
        set_efris_flag_based_on_items(frm);
        set_efris_invoice_details(frm);
    },
    before_save: function(frm) {
        if (frm.doc.is_return) {
            reset_discounts(frm);
        }
        if (frm.doc.efris_payment_mode) {
            if (frm.doc.payments.length > 1) {
                frm.set_value('efris_payment_mode', '');
            } else if (frm.doc.payments.length === 1) {
                let payment_row = frm.doc.payments[0];

                if (payment_row.amount <= 0) {
                console.log("Here is a payment with an amoyunt", payment_row.base_amount);
                    payment_row.amount = frm.doc.grand_total;
                }
            }
        }

        frm.refresh_field('payments');
    },
    on_submit: function(frm) {
        setTimeout(() => {
            frm.reload_doc();
        }, 1000);
    }
});

// Bind child table events
frappe.ui.form.on('Sales Invoice Item', {
    items_add: function(frm) {
        set_efris_flag_based_on_items(frm);
    },
    items_remove: function(frm) {
        set_efris_flag_based_on_items(frm);
    },
    item_code: function(frm) {
        set_efris_flag_based_on_items(frm);
    }
});

frappe.ui.form.on('Sales Invoice', {
    efris_payment_mode: function (frm) {
        const selected_payment_mode = frm.doc.efris_payment_mode;
        const number_of_payments = frm.doc.payments.length;

        if (!selected_payment_mode) {
            if (number_of_payments == 0) {
                frm.set_value('is_pos', 0);
                frm.refresh_field('is_pos');
            } else if (number_of_payments == 1) {
                frm.clear_table("payments");
                frm.set_value('is_pos', 0);
                frm.refresh_field('payments');
                frm.refresh_field('is_pos');
            }
            return;
        }

        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Mode of Payment',
                filters: { name: selected_payment_mode },
                fields: ['efris_payment_mode']
            },
            callback: function (response) {
                if (response.message && response.message.length > 0) {
                    const efris_payment_mode_name = response.message[0].efris_payment_mode;

                    frappe.call({
                        method: 'frappe.client.get_list',
                        args: {
                            doctype: 'EFRIS Payment Mode',
                            filters: { name: efris_payment_mode_name },
                            fields: ['include_payment']
                        },
                        callback: function (response) {
                            const include_payment_flag = response.message?.[0]?.include_payment || 0;

                            if (include_payment_flag) {
                                frm.set_value('is_pos', 1);
                                frm.set_df_property('is_pos', 'read_only', 0);

                                // Update the payments table with selected payment mode
                                frm.clear_table("payments");
                                let payment_row = frm.add_child('payments');
                                payment_row.mode_of_payment = selected_payment_mode;
                                payment_row.amount = frm.doc.grand_total;

                                frm.refresh_field('payments');
                            } else {
                                frm.set_value('is_pos', 0);
                                frm.set_df_property('is_pos', 'read_only', 1);
                                frm.clear_table("payments");
                                frm.refresh_field('payments');
                            }
                        }
                    });
                } else {
                    frm.clear_table("payments");
                    frm.refresh_field('payments');
                }
            }
        });
    }
});

frappe.ui.form.on('Sales Invoice Payment', {
    payments_add: function(frm, cdt, cdn) {
        update_parent_field(frm);
    },
    payments_remove: function(frm, cdt, cdn) {
        update_parent_field(frm);
    }
});

// Separate function for EFRIS logic
// async function set_efris_invoice_details(frm) {
function set_efris_invoice_details(frm) {
    if (frm.doc.efris_invoice && !frm.doc.is_return) {

        try {
            const response = frappe.call({
                method: 'uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.get_e_tax_template',
                args: { company_name: frm.doc.company, tax_type: 'Sales Tax' },
                freeze: false 
            });

            if (response && response.message) {
                const { template_name, taxes } = response.message;

                console.log('Sales tax template fetched:', template_name);

                frm.set_value('taxes_and_charges', template_name);

                frm.clear_table('taxes');

                taxes.forEach(tax => {
                    let child = frm.add_child('taxes');
                    frappe.model.set_value(child.doctype, child.name, 'charge_type', tax.charge_type);
                    frappe.model.set_value(child.doctype, child.name, 'account_head', tax.account_head);
                    frappe.model.set_value(child.doctype, child.name, 'rate', tax.rate);
                    frappe.model.set_value(child.doctype, child.name, 'included_in_print_rate', tax.included_in_print_rate);
                });

                // Refresh taxes child table to reflect changes
                frm.refresh_field('taxes');

                console.log('Taxes child table updated successfully');
            } else {
                console.warn('No template or tax details found in the response');
            }
        } catch (error) {
            console.error(`Error fetching or applying tax template: ${error}`);
        }
    } else {
        console.log('Either not EFRIS or it is a return invoice. Tax template not set.');
    }

    // Set `update_stock` field when `efris_invoice` is enabled
    const is_efris_invoice = frm.doc.efris_invoice == 1;

    handle_update_stock_setting(frm);
    frm.refresh_field("update_stock");

    frm.set_value("disable_rounded_total", is_efris_invoice ? 1 : 0);
    frm.refresh_field("disable_rounded_total");
}

const set_efris_flag_based_on_items = (frm) => {
    let is_efris_flag = 0;
    frm.doc.items.forEach(item => {
        if (item.efris_commodity_code) {
            is_efris_flag = 1;                       
        }
    });
    frm.set_value('efris_invoice', is_efris_flag);
};

function handle_update_stock_setting(frm) {
    if (frm.doc.is_return) {
        return;
    }
    
    let is_efris_invoice = frm.doc.efris_invoice === 1;
    
    if (is_efris_invoice) {
        frappe.call({
            method: "uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.get_e_company_settings",
            args: { company_name: frm.doc.company },
            callback: function(r) {
                if (r.message && r.message.enforce_update_stock == 1) {
                    frm.set_value("update_stock", 1);
                    frm.refresh_field("update_stock");
                }
                // If enforce_update_stock = 0, do nothing - let user/ERPNext decide
            }
        });
    }
}

const get_irn_cancellation_fields = () => {
    return [
        {
            label: "Reason Code",
            fieldname: "reason",
            fieldtype: "Select",
            reqd: 1,
            default: "102:Cancellation of the purchase",
            options: [
                "102:Cancellation of the purchase", 
                "103:Invoice amount wrongly stated due to miscalculation", 
                "104:Partial or complete waive off of the product", 
                "105:Others (Please specify in Remarks below)"
            ]
        },
        {
            label: "Remark",
            fieldname: "remark",
            default: "Cancellation of the purchase",
            fieldtype: "Data",
            reqd: 1
        }
    ];
};

const raise_form_is_dirty_error = () => {
    frappe.throw({
        message: __('You must save the document before making e-invoicing request.'),
        title: __('Unsaved Document')
    });
};

function update_parent_field(frm) {
    frm.doc.payments.forEach(row => {
        frm.set_value('efris_payment_mode', null);
    });

    frm.refresh_field("efris_payment_mode");
}

function reset_discounts(frm) {
    (frm.doc.items || []).forEach(function(row) {
        row.discount_percentage = 0;
        row.discount_amount = 0;
    });

    frm.set_value('discount_amount', 0);
    frm.set_value('additional_discount_percentage', 0);

    frm.refresh_field('items');
    frm.refresh_field('discount_amount');
    frm.refresh_field('additional_discount_percentage');
}