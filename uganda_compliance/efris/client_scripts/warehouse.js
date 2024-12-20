frappe.ui.form.on('Warehouse', {
    refresh: function(frm) {
        frm.refresh_field('company');

    },
    onload:function(frm){ 
        // Check if the document is new
        if(!frm.is_new()){
            console.log(`Onload Called to Set EFRIS warehouse...`)
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'E Invoicing Settings',
                    filters: {
                        company: frm.doc.company
                    },
                    fields: ['company']
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        // If the company exists in E Invoicing Settings, proceed with showing/hiding the field
                        console.log(`The Company ${frm.doc.company} exists in E Invoicing Settings`);
                       
                        frm.set_df_property('efris_warehouse', 'hidden', 0);  // Show field
                       
                    } else {
                        // If the company does not exist in E Invoicing Settings, don't display the field
                        console.log(`The company ${frm.doc.name} does not have E Invoicing Settings.`);
                        frm.set_df_property('efris_warehouse', 'hidden', 1);  // Hide field
                    }
                }
            });
        
           // Check If Warehouse has any Transactions. If Yes, set efris_warehouse to ready_only.
           frappe.call({
                method:'frappe.client.get_list',
                args:{
                    doctype:'Stock Ledger Entry',
                    filters:{
                        warehouse:frm.doc.name,
                        docstatus:1
                    },
                    fields:['warehouse']
                },
                callback:function(r){
                    if (r.message && r.message.length > 0)
                    {
                        console.log(`The Warehouse ${r.message[0].warehouse} has Transactions`)
                        frm.set_df_property('efris_warehouse', 'read_only', 1);
                    } else {
                        console.log(`The Warehouse ${frm.doc.name} has no Transactions`)
                        frm.set_df_property('efris_warehouse', 'read_only', 0);
                    }
                          
                }
           }); 
        }else {
            frm.set_df_property('efris_warehouse', 'read_only', 1);
        }
       
    }
});
