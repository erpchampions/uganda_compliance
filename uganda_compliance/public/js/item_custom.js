frappe.ui.form.on('Item', {
    validate(frm) {
        if (frm.doc.has_multiple_uom) {
            console.log("has_multiple_uom is checked, validating e_companies and uoms...");
            //Validate uoms table
            if (frm.doc.uoms && frm.doc.uoms.length > 0) {
                frm.doc.uoms.forEach(function(row) {
                    console.log("Validating uoms row:", row);
                    
                    //TODO: improve validations
                    // 1) throw error if not found more than 1 UOM: "The UOMs table must have at least one other  EFRIS UOM when Multiple UOM is checked." 
                    // 
                    if (!row.uom || !row.conversion_factor) {
                        frappe.throw(__('For item with Multiple UOM, set UOM, and Conversion Factor in the UOMs table.'));
                    }
                });
            } else {
                frappe.throw(__('The UOMs table must have at least one entry when Multiple UOM is checked.'));
            }
        }
    }
});
