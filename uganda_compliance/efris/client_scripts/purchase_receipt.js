frappe.ui.form.on("Purchase Receipt", {
    validate: async function(frm) {
        console.log("validate called");

        // Process each item sequentially to ensure efris_receipt is set correctly
        for (let item of frm.doc.items) {
            if (item.warehouse && item.item_code) {
                console.log(`Before check_efris_stockin: efris_receipt=${item.efris_receipt}, item=${item.item_code}`);
                await check_efris_stockin(frm, item.doctype, item.name);
                console.log(`After check_efris_stockin: efris_receipt=${item.efris_receipt}, item=${item.item_code}`);
            }

            // Ensure default value if undefined
            item.efris_receipt = item.efris_receipt || false;

            // Handle efris_receipt logic
            if (item.efris_receipt) {
                console.log(`EFRIS Receipt TRUE: ${item.item_code}`);
                let response = await frappe.call({
                    method: 'frappe.client.get_value',
                    args: {
                        doctype: 'Item',
                        fieldname: 'efris_currency',
                        filters: { name: item.item_code }
                    }
                });
                if (response.message) {
                    let efris_currency = response.message.efris_currency;
                    console.log(`EFRIS Currency for ${item.item_code}: ${efris_currency}`);
                    console.log(`Document Currency: ${frm.doc.currency}`);

                    let efris_unit_price = (frm.doc.currency !== 'UGX' && frm.doc.currency !== efris_currency)
                        ? item.base_rate
                        : item.rate;

                    frappe.model.set_value(item.doctype, item.name, 'efris_unit_price', efris_unit_price);
                } else {
                    console.warn(`No EFRIS currency found for ${item.item_code}`);
                }
            } else {
                console.log(`The item ${item.item_code} is not marked as EFRIS`);
                frappe.model.set_value(item.doctype, item.name, 'efris_unit_price', item.rate);
            }
        }
    },

    conversion_rate: function(frm) {
        console.log("conversion_rate changed:" + frm.doc.conversion_rate);
        set_efris_exchange_rate(frm);
    }
});


function set_efris_exchange_rate(frm) {
       
    
    if (!frm.doc.efris_company) {
        console.log("Efris Company not set.");
        return;
    }

    console.log("Current EFRIS Exchange Rate value: " + frm.doc.efris_currency_exchange_rate);
    // Set efris_currency_exchange_rate if any item is marked as `is_efris`
    if (frm.doc.currency != 'UGX' && !frm.doc.efris_currency_exchange_rate) {
        console.log("Fetching Exchange Rate for currency: " + frm.doc.currency);

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
                    if (frm.doc.conversion_rate == 0) {
                        console.log("Conversion rate is 0. Setting efris_currency_exchange_rate to conversion_rate");
                        frm.set_value('conversion_rate', r.message.rate);
                        frm.refresh_field('conversion_rate');
                    }
                }
            }
        });

        if (frm.doc.conversion_rate == 0 && frm.doc.efris_currency_exchange_rate > 0) {
            console.log("Conversion rate is 0. Setting efris_currency_exchange_rate to conversion_rate");
            frm.set_value('conversion_rate', frm.doc.efris_currency_exchange_rate);
            frm.refresh_field('conversion_rate');
        }
    }
}
function check_efris_stockin(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    return new Promise((resolve) => {
        if (row.warehouse && row.item_code) {
            frappe.call({
                method: 'uganda_compliance.efris.api_classes.e_goods_services.check_efris_item_for_purchase_receipt',
                args: {
                    accept_warehouse: row.warehouse,
                    item_code: row.item_code
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.model.set_value(cdt, cdn, 'efris_receipt', r.message.is_efris);
                        console.log(`The efris_receipt flag is set to: ${r.message.is_efris}`);
                    }
                    resolve(); // Resolve after setting value
                }
            });
        } else {
            resolve(); // Resolve even if conditions are not met
        }
    });
}

function check_efris_stockins(frm, cdt, cdn) {
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
                    frappe.model.set_value(cdt, cdn, 'efris_receipt', r.message.is_efris);
                    console.log(`The efris_receipt flag is set to: ${r.message.is_efris}`);
                }
            }
        });
    }
}
