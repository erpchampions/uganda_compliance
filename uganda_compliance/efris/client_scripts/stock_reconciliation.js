frappe.ui.form.on('Stock Reconciliation', {
    refresh: function(frm) {
        toggle_efris_purchase_receipt_no(frm);
    },

    validate: function(frm) {
        toggle_efris_purchase_receipt_no(frm);
    },

    before_save: function(frm) {
        // Before saving, validate that efris_purchase_receipt_no is set when required
        frm.doc.items.forEach(item => {
            if (item.is_efris && frm.doc.purpose === 'Opening Stock' && !item.efris_purchase_receipt_no) {
                frappe.throw(__('EFRIS Purchase Receipt No must be provided for EFRIS items in Opening Stock.'));
            }
        });
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
        // Check if the field should be shown or hidden
        let show_field = (frm.doc.purpose === 'Opening Stock' && item.is_efris);
        
        // Use the standard toggle method for child table fields
        frappe.meta.get_docfield("Stock Reconciliation Item", "efris_purchase_receipt_no", frm.doc.name).hidden = !show_field;
        frm.refresh_field("items");
    });
}

function check_efris_stockin(frm, cdt, cdn) {
    let row = locals[cdt][cdn]; 

    if (row.warehouse) {
        frappe.db.get_value('Warehouse', row.warehouse, 'is_efris_warehouse').then(r => {
            if (r.message) {
                let is_efris_flag = r.message.is_efris_warehouse;                
                frappe.model.set_value(cdt, cdn, 'is_efris', is_efris_flag);

                // Update visibility and mandatory status of the field
                toggle_efris_purchase_receipt_no(frm);
            }
        });
    }
}
