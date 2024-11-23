frappe.ui.form.on('Sales Invoice', {
    async refresh(frm) {
        console.log("refresh here");
        if (frm.is_dirty()) return;

        let is_efris = frm.doc.is_efris;
        console.log(`Is Efris Sales Invoice set to ${is_efris}`);

        if (is_efris == 1) {
            try {
                const { einvoice_status } = frm.doc;

                const add_einvoice_button = (label, action) => {
                    if (!frm.custom_buttons[label]) {
                        frm.add_custom_button(label, action, __('E-Invoicing'));
                    }
                };

                if (einvoice_status === 'EFRIS Credit Note Pending') {
                    add_einvoice_button(__('Check Efris Approval Status'), async () => {
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

    is_efris: async function(frm) {
        console.log(`is_efris here:${frm.doc.is_efris}`);

        if (frm.doc.is_efris && !frm.doc.is_return) {
            console.log('This is EFris Invoice');
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
    },
    is_efris: function(frm) {
        console.log("Checking is_efris flag");
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
    frm.set_value('is_efris', is_efris_flag);
    console.log(`The Is Efris Flag is ${frm.doc.is_efris}`);
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
    console.log(`The Customer is ${customer}`);

    if (!customer) {
        console.log("No customer selected.");
        return;
    }

    frappe.db.get_doc('Customer', customer).then(doc => {
        const customer_type = doc.customer_type;
        const efris_customer_type = doc.efris_customer_type;
        console.log(`Customer Type: ${customer_type}, Efris Type: ${efris_customer_type}`);
        frm.set_value('efris_customer_type', efris_customer_type);
        refresh_field('efris_customer_type');
    }).catch(err => {
        console.error(`Failed to retrieve customer details: ${err}`);
        frappe.msgprint(__('Unable to fetch customer details.'));
    });
};

