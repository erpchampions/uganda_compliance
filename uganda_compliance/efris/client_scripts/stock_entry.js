frappe.ui.form.on("Stock Entry", {
    refresh: function(frm) {
        console.log("✅ Stock Entry Refreshed");
    },
    stock_entry_type: async function(frm) {
        console.log("🔄 Stock Entry Type Changed");
        await set_efris_stockin_for_all_items(frm);
    },
    before_save: async function(frm) {
        console.log("💾 Before Save Triggered");
        await process_efris_fields(frm);
        await set_efris_stockin_for_all_items(frm);
    },
    before_submit: async function(frm) {
        console.log("🚀 Before Submit Triggered");
        await process_efris_fields(frm);
        await set_efris_stockin_for_all_items(frm);
    }
});

frappe.ui.form.on("Stock Entry Detail", {
    item_code: async function(frm, cdt, cdn) {
        console.log("🛠️ Item Code Changed");
        setTimeout(async () => {
            await set_efris_fields_for_row(frm, cdt, cdn);
            await set_efris_stockin(frm, cdt, cdn);
        }, 100);
    },
    s_warehouse: async function(frm, cdt, cdn) {
        console.log("🏢 Source Warehouse Changed");
        await set_efris_stockin(frm, cdt, cdn);
    },
    t_warehouse: async function(frm, cdt, cdn) {
        console.log("📦 Target Warehouse Changed");
        await set_efris_stockin(frm, cdt, cdn);
    }
});

/**
 * 🔄 Process EFRIS fields for all items in the Stock Entry.
 */
async function process_efris_fields(frm) {
    console.log("🔄 Processing EFRIS fields for all items");

    for (let row of frm.doc.items) {
        await set_efris_fields_for_row(frm, row.doctype, row.name);
    }
}

/**
 * 🔄 Set EFRIS stock-in validation for all items.
 */
async function set_efris_stockin_for_all_items(frm) {
    console.log("🔄 Setting EFRIS stock-in for all items");

    for (let row of frm.doc.items) {
        await set_efris_stockin(frm, row.doctype, row.name);
    }
}

/**
 * 🛠️ Set EFRIS stock-in validation for a single row.
 */
async function set_efris_stockin(frm, cdt, cdn) {
    let row = locals[cdt][cdn];

    if (frm.doc.purpose === "Material Transfer") {
        console.log(`🔄 Handling Material Transfer for Item: ${row.item_code}`);

        if (row.s_warehouse && row.t_warehouse) {
            let [s_warehouse, t_warehouse] = await Promise.all([
                frappe.db.get_value('Warehouse', row.s_warehouse, 'efris_warehouse'),
                frappe.db.get_value('Warehouse', row.t_warehouse, 'efris_warehouse')
            ]);

            let s_is_efris = s_warehouse?.message?.efris_warehouse;
            let t_is_efris = t_warehouse?.message?.efris_warehouse;

            if (!s_is_efris && t_is_efris) {
                frappe.model.set_value(cdt, cdn, 'efris_transfer', 1);
                frappe.meta.get_docfield(cdt, 'efris_purchase_receipt_no', frm.doc.name).reqd = 1;
                console.log("✅ EFRIS Transfer Flag Set: TRUE");
            } else if (s_is_efris && !t_is_efris) {
                frappe.throw(`❌ Transfer from EFRIS warehouse ${row.s_warehouse} to Non-EFRIS warehouse ${row.t_warehouse} is not allowed.`);
            } else if (s_is_efris && t_is_efris) {
                console.warn("⚠️ Internal EFRIS transfers are not permitted.");
                frappe.msgprint("Stock Transfer From EFRIS warehouse to EFRIS warehouse does not Stock In");
            } else {
                frappe.model.set_value(cdt, cdn, 'efris_transfer', 0);
                frappe.meta.get_docfield(cdt, 'efris_purchase_receipt_no', frm.doc.name).reqd = 0;
            }
        }
    } else if (frm.doc.purpose === "Material Receipt" && row.t_warehouse) {
        console.log(`📥 Handling Material Receipt for Item: ${row.item_code}`);
        let t_warehouse = await frappe.db.get_value('Warehouse', row.t_warehouse, 'efris_warehouse');

        if (t_warehouse?.message?.efris_warehouse) {
            frappe.throw("❌ EFRIS stock-in via Material Receipt is not allowed.");
        }
    }
}

/**
 * 🔄 Map reference_purchase_receipt to efris_purchase_receipt_no.
 * Fetch and set efris_unit_price and efris_currency.
 */
async function set_efris_fields_for_row(frm, cdt, cdn) {
    let row = locals[cdt][cdn];

    // Map reference_purchase_receipt → efris_purchase_receipt_no
    if (!row.efris_purchase_receipt_no && row.reference_purchase_receipt) {
        console.log(`🔄 Mapping reference_purchase_receipt → efris_purchase_receipt_no for ${row.item_code}`);
        frappe.model.set_value(cdt, cdn, 'efris_purchase_receipt_no', row.reference_purchase_receipt);
    }

    // Fetch efris_unit_price and efris_currency
    if (row.efris_purchase_receipt_no) {
        try {
            let response = await frappe.call({
                method: 'uganda_compliance.efris.api_classes.stock_in.get_efris_unit_price',
                args: {
                    purchase_receipt_no: row.efris_purchase_receipt_no,
                    item_code: row.item_code
                }
            });

            if (response?.message) {
                if (response.message.efris_unit_price) {
                    frappe.model.set_value(cdt, cdn, 'efris_unit_price', response.message.efris_unit_price);
                    console.log(`✅ efris_unit_price set: ${response.message.efris_unit_price} for ${row.item_code}`);
                }
                if (response.message.efris_currency) {
                    frappe.model.set_value(cdt, cdn, 'efris_currency', response.message.efris_currency);
                    console.log(`✅ efris_currency set: ${response.message.efris_currency} for ${row.item_code}`);
                }
            }
        } catch (error) {
            console.error(`❌ Error fetching EFRIS data for ${row.item_code}:`, error);
        }
    }
}
