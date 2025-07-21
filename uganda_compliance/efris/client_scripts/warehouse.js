frappe.ui.form.on('Warehouse', {
    refresh: function(frm) {
        frm.refresh_field('company');
    },
    
    onload: function(frm) { 
        if (!frm.is_new()) {
            console.log(`Onload Called to Set EFRIS warehouse...`);
            
            // Check if company has E Invoicing Settings
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'E Invoicing Settings',
                    filters: { company: frm.doc.company },
                    fields: ['company']
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        console.log(`The Company ${frm.doc.company} exists in E Invoicing Settings`);
                        frm.set_df_property('efris_warehouse', 'hidden', 0);
                        
                        // Only check EFRIS transactions if E Invoicing Settings exist
                        let warehouse_name = frm.doc.name;
                        let company = frm.doc.company;
                        console.log("Warehouse name:", warehouse_name);
                        console.log("Company:", company);
                        
                        frappe.call({
                            method: 'uganda_compliance.efris.api_classes.e_goods_services.has_efris_item_in_stock_ledger_entry',
                            args: {
                                warehouse: warehouse_name,
                                company: company                   
                            },
                            callback: function(r) {
                                if (r.message) {
                                    console.log(`The Warehouse ${warehouse_name} has EFRIS Transactions, response ${r.message}`);  
                                    frm.set_df_property('efris_warehouse', 'read_only', 1);
                                } else {
                                    console.log(`The Warehouse ${warehouse_name} has no EFRIS Transactions, response ${r.message}`);
                                    frm.set_df_property('efris_warehouse', 'read_only', 0);
                                }
                            }
                        });
                    } else {
                        console.log(`The company ${frm.doc.company} does not have E Invoicing Settings.`);
                        frm.set_df_property('efris_warehouse', 'hidden', 1);
                    }
                }
            });
        } else {
            // For new warehouses, make efris_warehouse read_only until saved
            frm.set_df_property('efris_warehouse', 'read_only', 1);
        }
    }
});