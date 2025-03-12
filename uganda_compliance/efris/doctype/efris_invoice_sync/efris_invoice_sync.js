// Copyright (c) 2024, ERP Champions Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on('EFRIS invoice Sync', {
	refresh: function(frm) {
		frm.refresh_field('sync_invoice');
	},
	sync_invoice:function(frm){
		frappe.call({
			'method':'uganda_compliance.efris.api_classes.efris_invoice_sync.efris_invoice_sync',
			callback: function (r) {
				if (r.message) {
					frappe.msgprint(r.message);
				}
				else{
					frappe.msgprint("Sync unsuccessful");
				}
				frm.reload_doc(); 
			  }		
		})
	}
});
