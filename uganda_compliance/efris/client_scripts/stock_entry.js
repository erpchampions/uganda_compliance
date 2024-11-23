frappe.ui.form.on("Stock Entry", {
    refresh: function(frm) {
        console.log("on refresh");
    },
    stock_entry_type: function(frm, cdt, cdn) {
        console.log("on stock_entry_type change");
        set_efris_stockin(frm, cdt, cdn);
    },
    before_save: function(frm) {
        console.log("before save");
        set_efris_stockin_for_all_items(frm);
    },
    before_submit: function(frm) {
        console.log("before submit");
        set_efris_stockin_for_all_items(frm);
    }
});

frappe.ui.form.on("Stock Entry Detail", {
    s_warehouse: function(frm, cdt, cdn) {
        console.log("on s_warehouse change");
        set_efris_stockin(frm, cdt, cdn);
    },
    t_warehouse: function(frm, cdt, cdn) {
        console.log("on t_warehouse change");
        set_efris_stockin(frm, cdt, cdn);
    },
    item_code: function(frm, cdt, cdn) {
        console.log("on item_code");
        setTimeout(() => {
            set_efris_stockin(frm, cdt, cdn);
        }, 100);
    }
});

async function set_efris_stockin(frm, cdt, cdn) {
    let row = locals[cdt][cdn]; // Get the current row

    if (frm.doc.purpose === "Material Transfer") {
        console.log("Handling Material Transfer");
        if (row.s_warehouse && row.t_warehouse) {
            let s_warehouse_res = await frappe.db.get_value('Warehouse', row.s_warehouse, 'is_efris_warehouse');
            let t_warehouse_res = await frappe.db.get_value('Warehouse', row.t_warehouse, 'is_efris_warehouse');

            if (s_warehouse_res?.message && t_warehouse_res?.message) {
                let s_is_efris = s_warehouse_res.message.is_efris_warehouse;
                let t_is_efris = t_warehouse_res.message.is_efris_warehouse;

                // Check conditions and handle accordingly
                if (!s_is_efris && t_is_efris) {
                    frappe.model.set_value(cdt, cdn, 'is_efris', 1);
                    frappe.meta.get_docfield(cdt, 'efris_purchase_receipt_no', frm.doc.name).reqd = 1;
                    console.log("Is EFRIS flag set to true.");
                } else if (s_is_efris && !t_is_efris) {
                    frappe.throw(`Transfer from EFRIS warehouse ${row.s_warehouse} to Non-EFRIS warehouse ${row.t_warehouse} is not possible`);
                } else if (s_is_efris && t_is_efris) {
                    console.log("Internal EFRIS transfers are currently not permitted.");
                    frappe.msgprint("Stock Transfer From EFRIS warehouse to EFRIS warehouse doesnot Stock In")
                    return;
                } else {
                    frappe.model.set_value(cdt, cdn, 'is_efris', 0);
                    frappe.meta.get_docfield(cdt, 'efris_purchase_receipt_no', frm.doc.name).reqd = 0;
                }
            }
        }
    } else if (frm.doc.purpose === "Material Receipt" && row.t_warehouse) {
        console.log("Handling Material Receipt");                
            let t_warehouse_res = await frappe.db.get_value('Warehouse', row.t_warehouse, 'is_efris_warehouse');
            if (t_warehouse_res?.message) {
                let t_is_efris = t_warehouse_res.message.is_efris_warehouse;
                if (t_is_efris) {
                    frappe.throw("EFRIS stock-in via Material Receipt not allowed");
                }
            }
     
    }
}

// Function to ensure all items are processed before saving or submitting
async function set_efris_stockin_for_all_items(frm) {
    // Loop through all items in the Stock Entry Detail child table
    for (let i = 0; i < frm.doc.items.length; i++) {
        let item = frm.doc.items[i];
        await set_efris_stockin(frm, item.doctype, item.name);

    }
}
