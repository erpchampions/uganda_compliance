frappe.ui.form.on('Sales Invoice', {
    refresh: async function(frm) {
        if (frm.is_dirty()) return;

        // Check if EFRIS Invoice
        const is_efris = frm.doc.efris_invoice;
        const add_einvoice_button = (label, action) => {
                    if (!frm.custom_buttons[label]) {
                        frm.add_custom_button(label, action, __('E-Invoicing'));
                    }
                };

        if (is_efris == 1) {
            try {
                const einvoice_status  = frm.doc.efris_einvoice_status;
                console.log(`EFRIS Invoice Status: ${einvoice_status}`);

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
        add_custom_buttons(frm);        
        frm.refresh_field('items');      
    },
    validate: async function(frm,cdt, cdn) {
        set_efris_flag_based_on_items(frm);
        set_efris_invoice_details(frm);
        apply_item_tax_template(frm, cdt, cdn);

    },
    before_save: function(frm,cdt, cdn) {
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
        apply_item_tax_template(frm, cdt, cdn)
        frm.refresh_field('payments');
    },
    on_submit: function(frm) {
        setTimeout(() => {            
            frm.reload_doc();
        }, 1000);
    },   
    after_submit: async function(frm) {         
         add_custom_buttons(frm);
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
    onload: function(frm,cdt,cdn) {
        if (!frm.doc.efris_non_resident_flag) {
            frm.set_value('efris_invoice_industry_code', '101:General Industry');                     
        }
    },
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
    },
    customer: function(frm) {        
        if (frm.doc.efris_non_resident_flag) {
            frappe.db.get_value('Customer', frm.doc.customer, 'tax_category', (r) => { 
                if (!r.tax_category || r.tax_category !== 'Foreign') {
                    frm.set_value('tax_category', 'Foreign');
                }
            });
        }
    },
    efris_non_resident_flag: function(frm,cdt, cdn) {        
        if (frm.doc.efris_non_resident_flag) {         
            if (!frm.doc.tax_category || frm.doc.tax_category !== 'Foreign') {
                frm.set_value('tax_category', 'Foreign');                            
                
            }
            frm.set_value("efris_invoice_industry_code","102:Export"); 
            set_export_fields_reqd(frm,cdt, cdn);
        }else{           
            frm.set_value('efris_invoice_industry_code', '101:General Industry');            
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

function get_auto_send_submitted_invoice_flag(frm) {    
    return new Promise((resolve) => {
        if (!frm.doc.efris_company || frm.doc.efris_invoice !== 1) {
            return resolve(0);
        }

        frappe.call({
            method: "uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.get_e_company_settings",
            args: { company_name: frm.doc.company },
            callback: function(r) {
                if (r.message && r.message.auto_send_submitted_invoice == 1) {
                    console.log("Auto send submitted invoice is enabled in EFRIS settings");
                    resolve(1);
                } else {
                    resolve(0);
                }
            }
        });
    });
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

async function add_custom_buttons(frm) {  

    if (frm.doc.docstatus != 1 || !frm.doc.efris_company || frm.doc.efris_irn || !frm.doc.efris_invoice || frm.doc.efris_e_invoice) {
        console.log("Skipping EFRIS submission button for non-EFRIS or return invoices");
        return;
    }

    const auto_send_submitted_invoice = await get_auto_send_submitted_invoice_flag(frm);   

    if (auto_send_submitted_invoice != 1) {
        frm.add_custom_button(__('Submit To EFRIS'), async function () {
            frappe.confirm(
                __('Are you sure you want to submit?'),
                async function () {
                    // Yes callback
                    try {
                        const response = await frappe.call({
                            method: 'uganda_compliance.efris.api_classes.e_invoice.send_to_efris',
                            args: { doc: frm.doc },
                            freeze: true,
                            freeze_message: __('Submitting to EFRIS...')
                        });

                        if (response.message) {
                            frappe.msgprint(__('Sales Invoice submitted to EFRIS successfully.'));
                            frm.reload_doc();
                        } else {
                            console.log(__('Failed to submit Sales Invoice to EFRIS.'));
                        }
                    } catch (error) {
                        console.error("Error submitting to EFRIS:", error);
                        frappe.msgprint(__('An error occurred while submitting to EFRIS.'));
                    }
                },
                function () {
                    // No callback (do nothing)
                    console.log("Submission to EFRIS was cancelled by the user.");
                }
            );
        });
    }
}

frappe.ui.form.on('Sales Invoice Item', {   
    qty: function(frm, cdt, cdn) {        
        calculate_piece_qty(frm, cdt, cdn);
        set_export_fields_reqd(frm, cdt, cdn)
    },
    item_code: function(frm, cdt, cdn) {              
        calculate_piece_qty(frm, cdt, cdn);
        set_export_fields_reqd(frm, cdt, cdn)
    }
});

// 3️⃣ Set export fields required based on non-resident flag

function set_export_fields_reqd(frm, cdt, cdn) {
    let efris_nonResidentFlag = frm.doc.efris_non_resident_flag;   
    if (!efris_nonResidentFlag) return;
    let row = locals[cdt][cdn];
    if (efris_nonResidentFlag === 1) {
        frm.fields_dict.items.grid.toggle_reqd('efris_total_weight', true);
        frm.fields_dict.items.grid.toggle_reqd('efris_piece_qty', true);
        frm.fields_dict.items.grid.toggle_reqd('efris_piece_measure_unit', true);
        frm.fields_dict.items.grid.toggle_display('efris_total_weight', true);
        frm.fields_dict.items.grid.toggle_display('efris_piece_qty', true);
        frm.fields_dict.items.grid.toggle_display('efris_piece_measure_unit', true);
    } else {        
        frm.fields_dict.items.grid.toggle_display('efris_total_weight', false);
        frm.fields_dict.items.grid.toggle_display('efris_piece_qty', false);
        frm.fields_dict.items.grid.toggle_display('efris_piece_measure_unit', false);
    }
}

// 2️⃣ Calculate pieceQty and set measure unit from Item Master → UOMs
function calculate_piece_qty(frm, cdt, cdn) {
    console.log("Calculating piece qty...");
    let row = locals[cdt][cdn];
    if (frm.doc.efris_non_resident_flag !== 1) return;
    frappe.db.get_doc('Item', row.item_code).then(item_doc => {
        if (!item_doc.uoms || !item_doc.uoms.length) return;
        // Find weight(KG) unit row in Item UOMs table
        let weight_row = item_doc.uoms.find(u => {
            return u.uom === 'Kg' || u.uom === "KG";
        }); 
        console.log("Row Quantity:", row.qty);
        if(weight_row && row.qty) {            
            console.log(`Found weight UOM: ${weight_row.uom} with scale value ${weight_row.efris_package_scale_value} for Item ${row.item_code}`); 
            let qty = row.qty * weight_row.efris_package_scale_value;
            frappe.model.set_value(cdt, cdn, 'efris_total_weight', qty);
        } else {
            console.warn(`No UOM with Kg found for Item ${row.item_code}`);
        }

        // Find piece unit row in Item UOMs table
        let piece_uom_row = item_doc.uoms.find(u => {
            return u.efris_is_piece_unit === 1 || u.efris_is_piece_unit === true;
        });      
        if (piece_uom_row && row.qty) {         
                console.log(`Found piece UOM: ${piece_uom_row.uom} with scale value ${piece_uom_row.efris_package_scale_value} for Item ${row.item_code}`);
            // Set the measure unit field
            frappe.model.set_value(cdt, cdn, 'efris_piece_measure_unit', piece_uom_row.uom);
            // --- Calculate qty ---          
            let qty = row.qty * piece_uom_row.efris_package_scale_value;
            frappe.model.set_value(cdt, cdn, 'efris_piece_qty', qty);
        } else {
            console.warn(`No UOM with efris_is_piece_unit = 1 found for Item ${row.item_code}`);
        }
        
    });
}

// -----------------------------------------------------------
// 🔁 Auto-set Item Tax Template based on `custom_is_default`
// -----------------------------------------------------------
frappe.ui.form.on('Sales Invoice Item', {

    // When checkbox toggled
    custom_is_default: function(frm, cdt, cdn) {
        console.log("Custom is default toggled, applying item tax template...");
        apply_item_tax_template(frm, cdt, cdn);
    },

    // When item selected or changed
    item_code: function(frm, cdt, cdn) {
        console.log("Item code changed, applying item tax template...");
        apply_item_tax_template(frm, cdt, cdn);
    },

    // When a new row is added
    items_add: function(frm, cdt, cdn) {
        console.log("New item row added, applying item tax template...");
        apply_item_tax_template(frm, cdt, cdn);
    }
});

// -----------------------------------------------------------
// 🔁 Apply Item Tax Template based on custom_is_default flag
// -----------------------------------------------------------
async function apply_item_tax_template(frm, cdt, cdn) {
    console.log("Applying item tax template...");
    if (!frm.doc.efris_invoice) return;  // Only for EFRIS invoices

    let row = locals[cdt][cdn];
    if (!row.item_code) return;

    try {
        // Fetch the Item document including taxes child table
        const item_doc = await frappe.db.get_doc('Item', row.item_code);

        if (!item_doc.taxes || !item_doc.taxes.length) {
            console.warn(`No taxes configured for Item ${row.item_code}`);
            return;
        }

        // Decide which tax row to pick
        let tax_row;
        if (row.custom_is_default) {
            console.log("Custom is default is checked, looking for Default tax category...");   
            tax_row = item_doc.taxes.find(r => r.tax_category === "Default");
        } else {
            tax_row = item_doc.taxes.find(r => !r.tax_category);
        }
            frappe.model.set_value(cdt, cdn, "item_tax_template", ""); // Clear previous value
            frm.refresh_field('items');
        if (tax_row && tax_row.item_tax_template) {
            console.log(`Applying tax template "${tax_row.item_tax_template}" for item ${row.item_code}`);
            
            frappe.model.set_value(cdt, cdn, "item_tax_template", tax_row.item_tax_template);
        } else {
            console.warn(`No matching tax template found for item ${row.item_code} (custom_is_default=${row.custom_is_default})`);
            frappe.model.set_value(cdt, cdn, "item_tax_template", "");
        }

    } catch (error) {
        console.error("Error applying item tax template:", error);
    }
}
