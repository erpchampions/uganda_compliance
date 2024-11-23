frappe.ui.form.on("Purchase Receipt", {
    refresh: function(frm) {
        console.log("on refresh");        
    },
    validate: function(frm) {
        // Iterate over all items in the child table to set `is_efris`
        frm.doc.items.forEach(function(item) {
            if (item.warehouse && item.item_code) {
                check_efris_stockin(frm, item.doctype, item.name);
            }
            
        });      
        
        set_efris_exchange_rate(frm)
    },
    
});
function set_efris_exchange_rate(frm) {
    console.log(`After Save is Called to Update Exchange Rate.`)
    // Check if any item has `is_efris` set to true
    let found_efris = frm.doc.items.some(row => row.is_efris);

    // Set efris_currency_exchange_rate if any item is marked as `is_efris`
    if (frm.doc.currency != 'UGX' && found_efris) {
        console.log("Found Is EFRIS item, setting exchange rate.");

        frappe.call({
            method: 'uganda_compliance.efris.api_classes.stock_in.query_currency_exchange_rate',
            args: {
                doc: frm.doc                
            },
            callback: function(r) {
                if (r.message) {
                    frm.set_value('efris_currency_exchange_rate', r.message.rate);
                    frm.refresh_field('efris_currency_exchange_rate');
                    console.log(`The Exchange Rate for currency ${r.message.currency} to UGX is ${r.message.rate}`);
                }
            }
        });
    }
}

function check_efris_stockin(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    if (row.warehouse && row.item_code) {
        // Check `is_efris` asynchronously
        frappe.call({
            method: 'uganda_compliance.efris.api_classes.e_goods_services.check_efris_item_for_purchase_receipt',
            args: {
                accept_warehouse: row.warehouse,
                item_code: row.item_code
            },
            callback: function(r) {
                if (r.message) {
                    frappe.model.set_value(cdt, cdn, 'is_efris', r.message.is_efris);
                    console.log(`The is_efris flag is set to: ${r.message.is_efris}`);
                }
            }
        });
    }
}
