frappe.ui.form.on('Stock Reconciliation', {
    refresh: function(frm) {
        toggle_efris_purchase_receipt_no(frm);
    },

    validate: function(frm) {
        toggle_efris_purchase_receipt_no(frm);
    }
   
});

frappe.ui.form.on('Stock Reconciliation Item', {
    warehouse: function(frm, cdt, cdn) {
        check_efris_stockin(frm, cdt, cdn);
    },
    item_code: function(frm, cdt, cdn) {
        setTimeout(() => {
            let row = locals[cdt][cdn]; 
            if (row.warehouse) {
                check_efris_stockin(frm, cdt, cdn);
            }
        }, 100);
    }
});

function toggle_efris_purchase_receipt_no(frm) {
    frm.doc.items.forEach(item => {
        let show_field = (frm.doc.purpose === 'Opening Stock' && item.efris_reconcilliation);
        
        frappe.meta.get_docfield("Stock Reconciliation Item", "efris_purchase_receipt_no", frm.doc.name).hidden = !show_field;
        frm.refresh_field("items");
    });
}

function check_efris_stockin(frm, cdt, cdn) {
    let row = locals[cdt][cdn]; 

    if (row.warehouse) {
        frappe.db.get_value('Warehouse', row.warehouse, 'efris_warehouse').then(r => {
            if (r.message) {
                let is_efris_flag = r.message.efris_warehouse;                
                frappe.model.set_value(cdt, cdn, 'efris_reconcilliation', is_efris_flag);

                toggle_efris_purchase_receipt_no(frm);
            }
        });
    }
}


function add_custom_buttons(frm) {
    // EFRIS lines not sent yet (a count sends decreases only; Stock Reconciliation has no
    // efris_posted field, so the old check never showed the button)
    const has_unsent_efris_items = (frm.doc.items || []).some(row =>
        row.efris_reconcilliation && !row.efris_registered &&
        (frm.doc.purpose === "Opening Stock" || row.quantity_difference < 0)
    );

    if (frm.doc.docstatus === 1 && has_unsent_efris_items) {
        frm.add_custom_button(__('Submit To EFRIS'), async function() {
            frappe.confirm(
                __('Are you sure you want to submit?'),
                async function () {
                    // Yes callback
                    try {
                        const response = await frappe.call({
                        method: 'uganda_compliance.efris.api_classes.stock_in.submit_stock_in',
                        args: { doctype: frm.doc.doctype, name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Submitting to EFRIS...')
                         });
                        if (response.message) {
                            frappe.msgprint(__('Stock Reconciliation submitted to EFRIS successfully.'));
                            frm.reload_doc();
                        } else {
                            console.log(__('Failed to submit Stock Entry to EFRIS.'));
                        }
                        } catch (error) {
                            console.error("Error submitting to EFRIS:", error);
                            frappe.msgprint(__('An error occurred while submitting to EFRIS.'));
                        }
                },function(){
                // No callback (do nothing)
                    console.log("Submission to EFRIS was cancelled by the user."); 
                }

            );
        });
        
    }
}

