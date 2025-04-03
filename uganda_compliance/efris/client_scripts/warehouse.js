frappe.ui.form.on('Warehouse', {
    refresh: function(frm) {
        frm.refresh_field('company');

    },
    onload:function(frm){ 
        if(!frm.is_new()){
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
                        frm.set_df_property('efris_warehouse', 'hidden', 0); 
                       
                    } else {
                        frm.set_df_property('efris_warehouse', 'hidden', 1);  
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
