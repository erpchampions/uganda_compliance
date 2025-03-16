frappe.ui.form.on('Company', {
    refresh: function(frm) {
        if (!frm.is_new()) {
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'E Invoicing Settings',
                    filters: {
                        company: frm.doc.name
                    },
                    fields: ['company']
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        console.log(`The Company ${frm.doc.name} exists in E Invoicing Settings`);

                        if (frm.doc.tax_id || frm.doc.efris_nin_or_brn) {
                            frm.set_df_property('efris_company_sync', 'hidden', 0);  // Show field
                        } else {
                            frm.set_df_property('efris_company_sync', 'hidden', 1);  // Hide field if both are empty
                        }
                    } else {
                        // If the company does not exist in E Invoicing Settings, don't display the field
                        console.log(`The company ${frm.doc.name} does not have E Invoicing Settings.`);
                        frm.set_df_property('efris_company_sync', 'hidden', 1);  // Hide field
                    }
                }
            });
        } else {
            frm.set_df_property('efris_company_sync', 'hidden', 1);
        }
    },
    tax_id: function(frm) {
        // Recheck when tax_id is modified
        frm.trigger('refresh');
    },
    efris_nin_or_brn: function(frm) {
        // Recheck when efris_nin_or_brn is modified
        frm.trigger('refresh');
    }
});
