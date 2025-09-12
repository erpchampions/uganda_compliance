frappe.ui.form.on('POS Invoice', {
    refresh: function(frm) {
        // Add Send To EFRIS button based on conditions
        if (frm.doc.docstatus === 1 && !frm.doc.efris_posted) {
            // Check if auto submit is disabled for this company
            frappe.db.get_single_value('E Invoicing Settings', 'auto_send_submitted_pos_invoice')
                .then(auto_submit => {
                    if (!auto_submit) {
                        frm.add_custom_button(__('Send To EFRIS'), function() {
                            send_pos_to_efris(frm);
                        }, __('EFRIS'));
                    }
                });
        }
        
        // Show E Invoice link if exists
        if (frm.doc.efris_e_invoice) {
            frm.add_custom_button(__('View E Invoice'), function() {
                frappe.set_route('Form', 'E Invoice', frm.doc.efris_e_invoice);
            }, __('EFRIS'));
        }
        
        // Show print EFRIS receipt if FDN exists
        if (frm.doc.efris_irn) {
            frm.add_custom_button(__('Print EFRIS Receipt'), function() {
                print_efris_receipt(frm);
            }, __('EFRIS'));
        }
        
        // Status indicators
        if (frm.doc.efris_posted) {
            frm.dashboard.add_indicator(__('Posted to EFRIS'), 'green');
        } else if (frm.doc.docstatus === 1) {
            frm.dashboard.add_indicator(__('Not Posted to EFRIS'), 'orange');
        }
    },
    
    company: function(frm) {
        // Fetch EFRIS customer type when company changes
        if (frm.doc.customer && frm.doc.company) {
            frappe.db.get_value('Customer', frm.doc.customer, 'efris_customer_type')
                .then(r => {
                    if (r.message && r.message.efris_customer_type) {
                        frm.set_value('efris_customer_type', r.message.efris_customer_type);
                    }
                });
        }
    },
    
    customer: function(frm) {
        // Auto-populate EFRIS customer type
        if (frm.doc.customer) {
            frappe.db.get_value('Customer', frm.doc.customer, 'efris_customer_type')
                .then(r => {
                    if (r.message && r.message.efris_customer_type) {
                        frm.set_value('efris_customer_type', r.message.efris_customer_type);
                    }
                });
        }
    }
});

function send_pos_to_efris(frm) {
    frappe.confirm(__('Send this POS Invoice to EFRIS?'), function() {
        frappe.call({
            method: "uganda_compliance.efris.api_classes.e_invoice.send_pos_invoice_to_efris",
            args: {
                pos_invoice_name: frm.doc.name
            },
            freeze: true,
            freeze_message: __('Sending to EFRIS...'),
            callback: function(r) {
                if (r.message && r.message.status === 'success') {
                    frappe.show_alert({
                        message: __('EFRIS Invoice generated successfully. FDN: {0}', [r.message.fdn]),
                        indicator: 'green'
                    });
                    frm.reload_doc();
                } else {
                    frappe.msgprint({
                        title: __('EFRIS Submission Failed'),
                        message: r.message ? r.message.message : __('Unknown error occurred'),
                        indicator: 'red'
                    });
                }
            }
        });
    });
}

function print_efris_receipt(frm) {
    const print_format = "POS EFRIS Invoice";
    const url = frappe.urllib.get_base_url() + "/printview"
        + "?doctype=" + encodeURIComponent("POS Invoice")
        + "&name=" + encodeURIComponent(frm.doc.name)
        + "&trigger_print=1"
        + "&format=" + encodeURIComponent(print_format)
        + "&no_letterhead=0";
    
    const printWindow = window.open(url, "_blank");
    printWindow.focus();
}

// List view customizations
frappe.listview_settings['POS Invoice'] = {
    onload: function(listview) {
        // Add bulk EFRIS submission button
        listview.page.add_menu_item(__("Send Selected to EFRIS"), function() {
            const selected = listview.get_checked_items();
            if (selected.length === 0) {
                frappe.msgprint(__("Please select at least one POS Invoice"));
                return;
            }
            
            const not_posted = selected.filter(d => !d.efris_posted);
            if (not_posted.length === 0) {
                frappe.msgprint(__("All selected invoices are already posted to EFRIS"));
                return;
            }
            
            frappe.confirm(__('Send {0} POS Invoice(s) to EFRIS?', [not_posted.length]), function() {
                bulk_send_to_efris(not_posted.map(d => d.name), listview);
            });
        });
    },
    
    add_fields: ["efris_posted", "efris_einvoice_status", "efris_irn"],
    
    formatters: {
        efris_posted: function(value) {
            return value ? `<span class="indicator green">Posted</span>` : `<span class="indicator orange">Not Posted</span>`;
        },
        efris_einvoice_status: function(value) {
            if (value === "EFRIS Generated") {
                return `<span class="indicator green">${value}</span>`;
            } else if (value === "EFRIS Pending") {
                return `<span class="indicator orange">${value}</span>`;
            } else if (value === "EFRIS Cancelled") {
                return `<span class="indicator red">${value}</span>`;
            }
            return value || "";
        }
    }
};

function bulk_send_to_efris(invoice_names, listview) {
    frappe.call({
        method: "uganda_compliance.efris.api_classes.e_invoice.bulk_send_pos_to_efris",
        args: {
            pos_invoice_names: invoice_names
        },
        freeze: true,
        freeze_message: __('Sending to EFRIS...'),
        callback: function(r) {
            if (r.message) {
                frappe.show_alert({
                    message: __('Bulk EFRIS submission completed. Check individual invoices for results.'),
                    indicator: 'green'
                });
                listview.refresh();
            }
        }
    });
}