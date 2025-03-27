frappe.ui.form.on('Warehouse', {
    refresh: function(frm) {
        frm.refresh_field('company');
    },
    onload: function(frm) { 
        console.log(`Onload Called to Set EFRIS warehouse...`);

        // Fetch E Invoicing Settings based on Company
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
                    frm.set_df_property('efris_warehouse', 'hidden', 0);  // Show field
                } else {
                    console.log(`The company ${frm.doc.company} does not have E Invoicing Settings.`);
                    frm.set_df_property('efris_warehouse', 'hidden', 1);  // Hide field
                }
            }
        });

        // Check If Warehouse has Transactions and set read_only accordingly
        let warehouse_name = frm.doc.name;
        console.log("Warehouse name:", warehouse_name);
        let company = frm.doc.company;
        console.log("Company:", company );

        frappe.call({
            method: 'uganda_compliance.efris.api_classes.e_goods_services.has_efris_item_in_stock_ledger_entry',
                args: {
                    warehouse: warehouse_name,
                    company: company                   
                },
                callback: function(r) {
                    if (r.message) {
                    console.log(`The Warehouse ${warehouse_name} has EFRIS Transactions , response ${r.message}`);  
                    frm.set_df_property('efris_warehouse', 'read_only', 1); // Make it read-only
                } else {
                    console.log(`The Warehouse ${warehouse_name} has no EFRIS Transactions response ${r.message}`);
                    frm.set_df_property('efris_warehouse', 'read_only', 0); // Keep it editable
                }
            }
        });
    }
});
