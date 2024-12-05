frappe.ui.form.on("Item", {
  
       stock_uom: function(frm) {
        console.log("on stock_uom change");
        if (frm.doc.stock_uom) {
            add_default_uom_to_uoms(frm);  // Add default UOM row when stock_uom is changed
            frm.refresh_field("uoms");
        }
    },
    standard_rate: function(frm) {
        console.log("on standard_rate change");
        if (frm.doc.stock_uom) {
            add_default_uom_to_uoms(frm);  // Add default UOM row when standard_rate is changed
            frm.refresh_field("uoms");
        }
    },
    efris_currency: function(frm) {
        let efris_currency = frm.doc.efris_currency;
        if (efris_currency) {
            console.log(`Currency is ${efris_currency}`);
            
            // Using a Frappe.call to handle the asynchronous get_value call
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Currency",
                    fieldname: "efris_currency_code",
                    filters: { name: efris_currency }
                },
                callback: function(r) {
                    if (r.message) {
                        let efris_code = r.message.efris_currency_code;
                        console.log(`The Efris Currency Code is ${efris_code}`);
                        
                        if (!efris_code) {
                            frappe.throw("The Selected Currency is an Invalid Efris Currency");
                        } else {
                            console.log(`The Currency Code is ${efris_code}`);
                        }
                    } else {
                        frappe.throw("Failed to fetch Efris Currency Code.");
                    }
                }
            });
        }
    },
    efris_commodity_code: function(frm){
        set_item_tax_template(frm)
        frm.refresh_field("efris_commodity_code")
    },
    validate:function(frm){
        set_item_tax_template(frm)
        frm.refresh_field("taxes")
    },
    item_code:function(frm){
        // console.log(`On Item Code Change...`)
        let item_code = frm.doc.item_code;
        // console.log(`Item Code ${item_code} is ${item_code.length} characters long`)
        if (item_code && item_code !== ''){
            item_code = item_code.trim()
            // console.log(`Trimmed Item Code :${item_code} is ${item_code.length} characters long`)
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
            
            // Fetch the E Tax Category from the Efris Commodity Code
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'Efris Commodity Code',
                    fieldname: "e_tax_category",
                    filters: { name: efris_commodity_code }
                },
                callback: function(r) {
                    if (r.message) {
                        let e_tax_category = r.message.e_tax_category;
                        console.log(`The E Tax Category on ${efris_commodity_code} is ${e_tax_category}`);
                        
                        if (e_tax_category) {
                            console.log(`E Tax Category is ${e_tax_category}`);
                            const company = frm.doc.e_company;
                            console.log(`Item E Company is ${company}`);
                            
                            // Fetch the Item Tax Template based on E Tax Category and Company
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
        console.log("After Save is called...")
        frappe.call({
            method: 'uganda_compliance.efris.api_classes.e_goods_services.create_item_prices',
            args: {
                item_code: frm.doc.item_code,
                uoms: frm.doc.uoms,
                currency: frm.doc.efris_currency
            },
            callback: function(r) {
                if (r.message) {
                    frappe.msgprint(r.message);
                    console.log(r.message.currency)
                }
            }
        });
    },
    purchase_uom: function(frm) {
        if (frm.doc.purchase_uom) {
            console.log(`Purchase UOM listener called ...`);
            let purchase_uom = frm.doc.purchase_uom;
            console.log(`Purchase UOM is ${purchase_uom}`);

            // Check if the purchase_uom exists in the UOMs table
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

            // Check if the sales_uom exists in the UOMs table
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

frappe.ui.form.on('UOM Conversion Detail', {  // 'UOM Conversion Detail' is the correct child doctype name
    uoms_add: function(frm, cdt, cdn) {
        console.log("Adding UOM");
        //add_default_uom_to_uoms(frm);
    },
    uoms_remove: function(frm, cdt, cdn) {
        console.log("Removing UOM");
        add_default_uom_to_uoms(frm);
    },
    uom: function(frm, cdt, cdn) {
        console.log("Checking UOM");
        add_default_uom_to_uoms(frm);

        frm.doc.uoms.forEach((data) => {
            let uom = data.uom;
            console.log(`UOM is ${uom}`);

            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "UOM",
                    fieldname: "efris_uom_code",
                    filters: { name: uom }
                },
                callback: function(r) {
                    if (r.message) {
                        let uom_code = r.message.efris_uom_code;
                        console.log(`The Efris UOM Code is ${uom_code}`);

                        if (!uom_code) {
                            frappe.throw("The Selected UOM is an Invalid Efris UOM");
                        } else {
                            console.log(`The UOM Code is ${uom_code}`);
                        }
                    } else {
                        frappe.throw("Failed to fetch Efris UOM Code.");
                    }
                }
            });
        });
    }
});

const add_default_uom_to_uoms = function(frm) {
    // Ensure both stock_uom and standard_rate are provided before proceeding
    const default_uom = frm.doc.stock_uom;
    const default_rate = frm.doc.standard_rate;
    const efris_item = frm.doc.is_efris_item;
    console.log(`Is Efris Item ${efris_item}`);
    if (efris_item == 1){

        if (!default_uom || default_rate == null) {
            console.log("Either stock_uom or standard_rate is not set, skipping UOM update.");
            return;  // Exit the function if either field is not set
        }
    
        console.log(`Default UOM: ${default_uom}, Standard Rate: ${default_rate}`);
    
        // Initialize the uoms child table if it doesn't exist
        if (!frm.doc.uoms) {
            frm.doc.uoms = [];
        }
    
        // Remove any default 'Nos' UOM if it exists and doesn't match the selected stock_uom
        frm.doc.uoms = frm.doc.uoms.filter(row => {
            if (row.conversion_factor === 0) {
                console.log("Removing invalid UOM row.");
                return false;  // This will remove the row
            }
            return true;  // Keep all other rows
        });
    
        const existing_row = frm.doc.uoms.find(row => row.uom === default_uom);
    
        if (existing_row) {
            // Update existing row if it already exists
            console.log(`Updating existing UOM row for UOM: ${default_uom}`);
            existing_row.conversion_factor = 1;        
            existing_row.is_efris_uom = 1;       
           
            existing_row.efris_unit_price = default_rate;
        } else {
            // Add a new row if it does not exist
            console.log(`Adding new UOM row for UOM: ${default_uom}`);
            const new_row = frm.add_child("uoms");
            new_row.uom = default_uom;
            new_row.conversion_factor = 1;      
                new_row.is_efris_uom = 1; 
            
            // new_row.is_efris_uom = 1;  // Assuming is_efris_uom is a checkbox field (boolean in JS)
            new_row.efris_unit_price = default_rate;
        }
    
        // Reset conversion factor for other rows if more than one row has conversion factor 1
        const rows_with_conversion_factor_one = frm.doc.uoms.filter(row => row.conversion_factor === 1);
        if (rows_with_conversion_factor_one.length > 1) {
            rows_with_conversion_factor_one.forEach(row => {
                if (row.uom !== default_uom) {
                    row.conversion_factor = 0;
                    console.log(`Resetting conversion factor for UOM: ${row.uom}`);                
                }
            });
        }

        frm.refresh_field("uoms");
    
    }
   
};
