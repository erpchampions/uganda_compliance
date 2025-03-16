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
