frappe.ui.form.on('Sales Invoice', {
    async refresh(frm) {
        console.log("refresh here");
        if (frm.is_dirty()) return;

        let is_efris = frm.doc.efris_invoice;
        console.log(`Is EFRIS Sales Invoice set to ${is_efris}`);

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
                                freeze: true,
                                callback: function(r) {
                                    if (!r.exc) {
                                        console.log('E-Invoice successfully created.');
                                        frm.reload_doc(); // Reload the form here
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
    
    validate: function(frm) {
        console.log(`validate called`);        
        set_efris_customer_type(frm);
        set_efris_flag_based_on_items(frm);    
        //check EFRIS UOM    
    },

    efris_invoice: async function(frm) {
        console.log(`is_efris here:${frm.doc.efris_invoice}`);

        if (frm.doc.efris_invoice && !frm.doc.is_return) {
            console.log('This is EFRIS Invoice');
            try {
                const response = await frappe.call({
                    method: 'uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.get_e_tax_template',
                    args: { company_name: frm.doc.company, tax_type: 'Sales Tax' },
                    freeze: true
                });
                refresh_field('taxes');
                console.log('sales tax template sought');
            } catch (error) {
                console.error(`Error fetching tax template: ${error}`);
            }
        } else {
            console.log('either not efris, or is efris return, tax template not set  ');
        }
    },

    customer: function(frm) {
        set_efris_customer_type(frm);
    },
    on_submit: function(frm){
        frm.reload_doc(); // Reload the form here
       
    },
    efris_invoice: function(frm){
        console.log(`Is EFRIS is called ...`);
        let is_efris = frm.doc.efris_invoice;
        if(is_efris && is_efris == 1){
            frm.set_value("update_stock",1);
            frm.refresh_field("update_stock")
        }
    }  
});

// Bind child table events
frappe.ui.form.on('Sales Invoice Item', {
    items_add: function(frm) {
        console.log("Adding Item");
        set_efris_flag_based_on_items(frm);
    },
    items_remove: function(frm) {
        console.log("Removing Item");
        set_efris_flag_based_on_items(frm);
    },
    item_code: function(frm) {
        console.log("Checking Item Code");
        set_efris_flag_based_on_items(frm);
    }
});

const set_efris_flag_based_on_items = (frm) => {
    let is_efris_flag = 0;
    frm.doc.items.forEach(item => {
        console.log(`The Item Code is ${item.item_code}, EFRIS: ${item.efris_commodity_code}`);
        if (item.efris_commodity_code) {
            is_efris_flag = 1;                       
        }
    });
    frm.set_value('efris_invoice', is_efris_flag);
    console.log(`The Is EFRIS Flag is ${frm.doc.efris_invoice}`);
};


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

const set_efris_customer_type = (frm) => {
    console.log(`set_efris_customer_type called`);
    let customer = frm.doc.customer;
    
    if (!customer) {
        return;
    }

    frappe.db.get_doc('Customer', customer).then(doc => {
        const efris_customer_type = doc.efris_customer_type;
        frm.set_value('efris_customer_type', efris_customer_type);
        refresh_field('efris_customer_type');
    }).catch(err => {
        console.error(`Failed to retrieve customer details: ${err}`);
        frappe.msgprint(__('Unable to fetch customer details.'));
    });
};

frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        // Refresh the field in case changes are not reflected automatically
       // frm.refresh_field("efris_payment_mode");
    },

    efris_payment_mode: function (frm) {
        console.log(`Listening to EFRIS PAYMENT MODE...`);
        const efris_payment_mode = frm.doc.efris_payment_mode;

        if (efris_payment_mode) {
            console.log(`The EFRIS Payment Mode is ${efris_payment_mode}`);

            // Fetch the efris_payment_mode value from the linked Mode of Payment
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'Mode of Payment',
                    filters: { name: efris_payment_mode },
                    fieldname: 'efris_payment_mode'
                },
                callback: function (response) {
                    const include_payment = response.message.efris_payment_mode;
                    console.log(`The Payment Mode is ${response.message.efris_payment_mode}`);

                    if (include_payment) {
                        // Fetch the include_payment flag from EFRIS Payment Mode
                        frappe.call({
                            method: 'frappe.client.get_value',
                            args: {
                                doctype: 'EFRIS Payment Mode',
                                filters: { name: include_payment },
                                fieldname: 'include_payment'
                            },
                            callback: function (response) {
                                const include_payment_flag = response.message.include_payment;
                                console.log(`The Include Payment is ${response.message.include_payment}`);
                                // frm.clear("payments");
                                if (include_payment_flag) {
                                    console.log("include_payment is true. Updating Sales Invoice...");
                                    // Set is_pos to true
                                    frm.set_value('is_pos', 1);

                                    // Make is_pos read-only
                                    frm.set_df_property('is_pos', 'read_only', 0);

                                    // Clear existing rows in the payments table
                                    frm.clear_table("payments");
                                    // Add the selected Mode of Payment to the payments table
                                    
                                    const payment_row = frm.add_child('payments');
                                    payment_row.mode_of_payment = frm.doc.efris_payment_mode;

                                    frm.refresh_field('payments');
                                } else {
                                    console.log("include_payment is false. Making is_pos read-only...");
                                    // Ensure is_pos is read-only
                                    frm.set_df_property('is_pos', 'read_only', 1);
                                    frm.clear_table("payments"); // Use clear_table
                                }
                            }
                        });
                    } else {
                        console.log(`The response is ${response.message.efris_payment_mode} not set`);
                    }
                }
            });
        }
    },
    before_save: function (frm) {
        console.log("Assigning amounts to payment rows...");
        if(frm.doc.efris_payment_mode){

            let remaining_amount = frm.doc.grand_total;

        // Iterate over each row in payments table to distribute the total amount
        frm.doc.payments.forEach((payment_row, index) => {
            // Assign amount only if it hasn't been set manually
            if (!payment_row.amount) {
                payment_row.amount = remaining_amount; // Set the remaining amount to the last row
            }
            // Reset remaining_amount if this is the last row
            if (index === frm.doc.payments.length - 1) {
                remaining_amount = 0;
            }
        });

        // Refresh payments table
        frm.refresh_field('payments');
        }

        
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

function update_parent_field(frm) {
    // Iterate through the child table to calculate the total payment amount
    frm.doc.payments.forEach(row => {
        frm.set_value('efris_payment_mode', null);
    });

    // Update the parent field (e.g., total_payment_amount)
    frm.refresh_field("efris_payment_mode");
}

