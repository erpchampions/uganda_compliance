frappe.pages['efris-synchronizatio'].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'EFRIS Synchronization Center',
        single_column: true
    });

    // Create section for buttons
    $(wrapper).find('.layout-main-section').append(`
        <div class="mb-4">
            <button class="btn btn-primary" id="send-stock-entry">Send EFRIS Stock Entry</button>
            <button class="btn btn-secondary" id="send-e-invoice">Send E-Invoice</button>
            <button class="btn btn-outline-info" id="check-status">Check Approval Status</button>
        </div>
        <div id="efris-report-table"></div>
    `);

    // Bind button click events
    $('#send-stock-entry').on('click', async function () {
        frappe.call({
            method: 'uganda_compliance.efris.page.efris_synchronizatio.efris_synchronization_center.process_pending_efris_stock_entries',
            callback: function(r) {
				frappe.msgprint(__('Processing EFRIS Stock Entries...', r.message));
				if (!r.message || !Array.isArray(r.message)) {	
				
                frappe.msgprint(__('EFRIS Stock Entries processed.'));

            } else {
				let message = r.message.length > 0 ? r.message.join('<br>') : 'No EFRIS Stock Entries to process.';
				frappe.msgprint(__('EFRIS Stock Entries processed: <br>' + message));
				render_report_table(r.message);
			}
		}
        });
    });

    $('#send-e-invoice').on('click', function () {
        frappe.msgprint('Sending E-Invoice... (hook up logic)');
    });

    $('#check-status').on('click', function () {
        frappe.msgprint('Checking status... (hook up logic)');
    });

    // Fetch and render report table
    load_efris_sync_report();
};

function load_efris_sync_report() {
    frappe.call({
        method: 'uganda_compliance.efris.page.efris_synchronizatio.efris_synchronization_center.get_recent_efris_statuses',
        callback: function (r) {
            if (r.message && r.message.length) {
                render_report_table(r.message);
            } else {
                $('#efris-report-table').html('<p>No EFRIS records found.</p>');
            }
        }
    });
}

function render_report_table(data) {
    let html = `
        <table class="table table-bordered">
            <thead>
                <tr>
                    <th>DocType</th>
                    <th>Document</th>
					<th>Stock Entry Type</th>
                    <th>Status</th>
                    <th>Date</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.forEach(row => {
        html += `
            <tr>
                <td>${row.doctype}</td>
                <td><a href="/app/${row.doctype}/${row.name}" target="_blank">${row.name}</a></td>
				<td>${row.type || 'N/A'}</td>
                <td>${row.efris_status || 'Pending'}</td>
                <td>${frappe.datetime.str_to_user(row.modified)}</td>
            </tr>
        `;
    });

    html += `</tbody></table>`;

    $('#efris-report-table').html(html);
}
