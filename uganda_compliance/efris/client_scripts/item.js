frappe.ui.form.on("Item", {  
  
    efris_currency: function(frm) {
        let efris_currency = frm.doc.efris_currency;
        if (efris_currency) {
            console.log(`Currency is ${efris_currency}`);
            
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Currency",
                    fieldname: "efris_currency_code",
                    filters: { name: efris_currency }
                },
                callback: function(r) {
                    if (r.message) {
                        let efris_currency_code = r.message.efris_currency_code;
                        console.log(`The EFRIS Currency Code is ${efris_currency_code}`);
                        
                        if (!efris_currency_code) {
                            frappe.throw("The Selected Currency is an Invalid EFRIS Currency");
                        } else {
                            console.log(`The Currency Code is ${efris_currency_code}`);
                        }
                    } else {
                        frappe.throw("Failed to fetch EFRIS Currency Code.");
                    }
                }
            });
        }
    },
    efris_commodity_code: function(frm){
        set_item_tax_template(frm)
        frm.refresh_field("taxes");
        frm.refresh_field("efris_commodity_code")
    },
    validate:function(frm){
        set_item_tax_template(frm)
        frm.refresh_field("taxes")
    },
    item_code:function(frm){
        let item_code = frm.doc.item_code;
      if (item_code && item_code !== ''){
            item_code = item_code.trim()
            frm.set_value('item_code',item_code);
            frm.refresh_field('item_code');
        }
    }
});
function set_item_tax_template(frm){
   
        console.log(`EFRIS Commodity Code Added...`);
        let efris_commodity_code = frm.doc.efris_commodity_code;
        if (efris_commodity_code) {
            console.log(`The EFRIS commodity code is ${efris_commodity_code}`);
            
          frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'EFRIS Commodity Code',
                    fieldname: "e_tax_category",
                    filters: { name: efris_commodity_code }
                },
                callback: function(r) {
                    if (r.message) {
                        let e_tax_category = r.message.e_tax_category;
                        console.log(`The E Tax Category on ${efris_commodity_code} is ${e_tax_category}`);
                        
                        if (e_tax_category) {
                            console.log(`E Tax Category is ${e_tax_category}`);
                            const company = frm.doc.efris_e_company;
                            console.log(`Item E Company is ${company}`);
                            
                            frappe.call({
                                method: 'uganda_compliance.efris.api_classes.e_goods_services.get_item_tax_template',
                                args: {
                                    company: company,
                                    e_tax_category: e_tax_category
                                },
                                callback: function(r) {
                                    if (r.message && r.message.length > 0) {
                                        
                                          frm.clear_table("taxes");
                                          let row = frm.add_child("taxes");
                                          row.item_tax_template = r.message
                                          frm.refresh_field('taxes');
                                        } else {
                                            frappe.msgprint('No matching Item Tax Template found.');
                                    }
                                       
                                        
                            }

                            });
                        }
                    } else {
                        frappe.throw("Failed to fetch E Tax Category from the EFRIS Commodity Code.");
                    }
                }
            });
        }
    }

       
frappe.ui.form.on('Item', {
    after_save: function(frm) {
        console.log("After Save is called...");

        if (frm.doc.efris_item && frm.doc.efris_registered) {
            console.log("Item is EFRIS tracked and registered. Proceeding to create item prices...");

            frappe.call({
                method: 'uganda_compliance.efris.api_classes.e_goods_services.create_item_prices',
                args: {
                    item_code: frm.doc.item_code,
                    uoms: frm.doc.uoms,
                    currency: frm.doc.efris_currency,
                    company: frm.doc.efris_e_company
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint(r.message);
                        console.log(r.message.currency);
                    }
                }
            });
        } else {
            console.log("Item is not EFRIS tracked or not registered. Skipping create_item_prices call.");
        }
    },    
    purchase_uom: function(frm) {
        if (frm.doc.purchase_uom) {
            console.log(`Purchase UOM listener called ...`);
            let purchase_uom = frm.doc.purchase_uom;
            console.log(`Purchase UOM is ${purchase_uom}`);

            let uom_exists = frm.doc.uoms.some(row => row.uom === purchase_uom);
            if (!uom_exists) {
                frappe.throw(`The Default Purchase UOM (${purchase_uom}) must be in the item's UOMs list.`);
            }
        }
    },

    sales_uom: function(frm) {
        if (frm.doc.sales_uom) {
            console.log(`Sales UOM listener called ...`);
            let sales_uom = frm.doc.sales_uom;
            console.log(`Sales UOM is ${sales_uom}`);

            let uom_exists = frm.doc.uoms.some(row => row.uom === sales_uom);
            if (!uom_exists) {
                frappe.throw(`The Default Sales UOM (${sales_uom}) must be in the item's UOMs list.`);
            }
        }
    },    
    item_code: function(frm){
        console.log(`listening to Item Code`)
        let efris_product_code = frm.doc.item_code; 
        frm.set_value('efris_product_code',frm.doc.item_code);         
        frm.refresh_field("efris_product_code");
    }
         
});

frappe.ui.form.on('UOM Conversion Detail', { 

    uoms_add: function(frm, cdt, cdn) {   
             if (frm.doc.efris_has_multiple_uom) {
            console.log("Row added to UOMs table.");
            update_default_uom_row(frm);
            frm.refresh_field("uoms"); 
        }
    },
    uoms_remove: function(frm, cdt, cdn) {
        if (frm.doc.efris_has_multiple_uom) {
            console.log("Row removed from UOMs table.");
            update_default_uom_row(frm);
            frm.refresh_field("uoms"); 
        }
    },
    uom: function(frm, cdt, cdn){
        if (frm.doc.efris_has_multiple_uom) {
        console.log("UOM changed on table.");
            update_default_uom_row(frm);
            frm.refresh_field("uoms"); 
        }
    }
 });

frappe.ui.form.on("Item", {
    stock_uom: function(frm) {
        console.log(`Listening to Stock UOM ${frm.doc.stock_uom}`)
        update_default_uom_row(frm)
        handle_stock_uom_change(frm);
    },
    standard_rate: function(frm) {
        console.log(`Listening to Standard rate ${frm.doc.standard_rate}`)
        update_default_uom_row(frm)
        handle_standard_rate_change(frm);
    },
    validate: function(frm) {
        frm.refresh_field("uoms");
        if (frm.doc.efris_has_multiple_uom) {
            validate_uoms_table(frm);
        }
    }
});

function handle_stock_uom_change(frm) {
    if (frm.doc.efris_has_multiple_uom) {
        update_default_uom_row(frm);
        frm.refresh_field("uoms"); 
    }
}

function handle_standard_rate_change(frm) {
    if (frm.doc.efris_has_multiple_uom) {
        update_default_uom_row(frm);
        frm.refresh_field("uoms"); 
    }
}

// Updates or resets rows in the `uoms` table based on the default UOM
function update_default_uom_row(frm) {
    const default_uom = frm.doc.stock_uom;
    const default_rate = frm.doc.standard_rate;

    if (!default_uom || default_rate == null) {
        console.log("Stock UOM or Standard Rate is not set. Skipping UOM update.");
        return;
    }

    console.log(`Updating UOM rows: Default UOM = ${default_uom}, Standard Rate = ${default_rate}`);

    if (!frm.doc.uoms) frm.doc.uoms = [];

    // Filter out rows that are outdated (not matching default_uom and with conversion_factor = 1)
    frm.doc.uoms = frm.doc.uoms.filter(row => {
        if (row.uom !== default_uom && row.conversion_factor === 1) {
            console.log(`Removing outdated UOM row: ${row.uom}`);
            return false; 
        }
        return true; 
    });

    const existing_row = frm.doc.uoms.find(row => row.uom === default_uom);

    if (existing_row) {
        existing_row.conversion_factor = 1;
        existing_row.efris_uom = 1;
        existing_row.efris_unit_price = default_rate;
    } else {
        const new_row = frm.add_child("uoms");
        new_row.uom = default_uom;
        new_row.conversion_factor = 1;
        new_row.efris_uom = 1;
        new_row.efris_unit_price = default_rate;
    }

    frm.refresh_field("uoms");
}

function validate_uoms_table(frm) {
    const uoms = frm.doc.uoms;

    if (!uoms || uoms.length === 0) {
        frappe.throw("Please configure the UOMs table for this item.");
    }

    // Ensure only one row has conversion_factor = 1
    const default_rows = uoms.filter(row => row.conversion_factor === 1);
    if (default_rows.length > 1) {
        frappe.throw("Only one UOM can have a conversion factor of 1.");
    }

    uoms.forEach(row => {
        if (row.efris_uom) {
            if (!row.efris_unit_price) {
                frappe.throw(`Please set the EFRIS Unit Price for UOM: ${row.uom}`);
            }
            if (!row.efris_package_scale_value) {
                frappe.throw(`Please set the Package Scale Value for UOM: ${row.uom}`);
            }
        }
    });
}
