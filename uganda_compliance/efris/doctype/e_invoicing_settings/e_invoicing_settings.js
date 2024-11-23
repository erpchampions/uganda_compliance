frappe.ui.form.on('E Invoicing Settings', {
    refresh: function(frm) {
        console.log("refresh")
        // if (doc.purchase_taxes_and_charges_template) {
        //     console.log("template is set...")
        //     // Call the custom server-side method to get the account_head
        //     frappe.call({
        //         method: "uganda_compliance.efris.doctype.vat_account.vat_account.get_account_head",
        //         args: {
        //             tax_template: doc.purchase_taxes_and_charges_template,
        //             tax_type: child.tax_type
        //         },
        //         callback: function(r) {
        //             if (r.message) {
        //                 doc.input_vat_acount = r.message;
        //             }
        //         }
        //     });
        // }

        // if (doc.sales_taxes_and_charges_template) {
        //     console.log("template is set...")
        //     // Call the custom server-side method to get the account_head
        //     frappe.call({
        //         method: "uganda_compliance.efris.doctype.vat_account.vat_account.get_account_head",
        //         args: {
        //             tax_template: doc.sales_taxes_and_charges_template,
        //             tax_type: child.tax_type
        //         },
        //         callback: function(r) {
        //             if (r.message) {
        //                 doc.output_vat_acount = r.message;
        //             }
        //         }
        //     });
        // }
    }
});
