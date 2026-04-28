frappe.pages["efris-diagnostics"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("EFRIS Diagnostics"),
        single_column: true,
    });

    const $body = $(`
        <div class="efris-diagnostics" style="padding: 12px;">
            <div class="row">
                <div class="col-md-6">
                    <h4>${__("Last 24h")}</h4>
                    <div class="overview-status text-muted">${__("Loading…")}</div>
                    <table class="table table-sm interface-table" style="margin-top: 8px;">
                        <thead><tr>
                            <th>${__("Interface")}</th>
                            <th class="text-right">${__("Total")}</th>
                            <th class="text-right">${__("Synced")}</th>
                            <th class="text-right">${__("Failed")}</th>
                            <th class="text-right">${__("Pending")}</th>
                            <th class="text-right">${__("Success %")}</th>
                        </tr></thead>
                        <tbody></tbody>
                    </table>
                </div>
                <div class="col-md-6">
                    <h4>${__("AES Sessions")}</h4>
                    <table class="table table-sm sessions-table">
                        <thead><tr>
                            <th>${__("Company")}</th>
                            <th>${__("TIN")}</th>
                            <th>${__("Device")}</th>
                            <th>${__("Mode")}</th>
                            <th>${__("Cached")}</th>
                            <th></th>
                        </tr></thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>

            <h4 style="margin-top: 24px;">${__("Circuit Breakers")}</h4>
            <table class="table table-sm breakers-table">
                <thead><tr>
                    <th>${__("Company")}</th>
                    <th>${__("Interface")}</th>
                    <th>${__("State")}</th>
                    <th class="text-right">${__("Failures")}</th>
                    <th class="text-right">${__("Open age (s)")}</th>
                    <th></th>
                </tr></thead>
                <tbody></tbody>
            </table>

            <h4 style="margin-top: 24px;">${__("Recent Failures")}</h4>
            <table class="table table-sm failures-table">
                <thead><tr>
                    <th>${__("Job")}</th>
                    <th>${__("Company")}</th>
                    <th>${__("Interface")}</th>
                    <th>${__("Status")}</th>
                    <th class="text-right">${__("Attempts")}</th>
                    <th>${__("Reference")}</th>
                    <th>${__("Last Error")}</th>
                </tr></thead>
                <tbody></tbody>
            </table>
        </div>
    `).appendTo(page.body);

    page.set_primary_action(__("Refresh"), () => refresh(), "refresh");

    function refresh() {
        load_overview();
        load_breakers();
        load_sessions();
        load_failures();
    }

    function call(method, args, cb) {
        frappe.call({
            method: `uganda_compliance.efris.page.efris_diagnostics.efris_diagnostics.${method}`,
            args: args || {},
            callback: r => cb(r.message),
        });
    }

    function load_overview() {
        call("get_overview", null, data => {
            const status_text = Object.entries(data.by_status || {})
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ") || __("No jobs in window");
            $body.find(".overview-status").text(status_text);
            const $tbody = $body.find(".interface-table tbody").empty();
            (data.by_interface || []).forEach(r => {
                $tbody.append(`<tr>
                    <td><code>${r.interface_code}</code></td>
                    <td class="text-right">${r.total}</td>
                    <td class="text-right">${r.synced}</td>
                    <td class="text-right text-danger">${r.failed}</td>
                    <td class="text-right">${r.pending}</td>
                    <td class="text-right">${r.success_rate ?? "—"}</td>
                </tr>`);
            });
        });
    }

    function load_breakers() {
        call("get_breaker_states", null, rows => {
            const $tbody = $body.find(".breakers-table tbody").empty();
            if (!rows || !rows.length) {
                $tbody.append(`<tr><td colspan="6" class="text-muted">${__("All breakers CLOSED")}</td></tr>`);
                return;
            }
            rows.forEach(r => {
                const cls = r.state === "OPEN" ? "text-danger" : (r.state === "HALF_OPEN" ? "text-warning" : "");
                $tbody.append(`<tr>
                    <td>${frappe.utils.escape_html(r.company)}</td>
                    <td><code>${r.interface_code}</code></td>
                    <td class="${cls}">${r.state}</td>
                    <td class="text-right">${r.failures || 0}</td>
                    <td class="text-right">${r.opened_age_seconds ?? "—"}</td>
                    <td><button class="btn btn-xs btn-default reset-breaker"
                        data-company="${frappe.utils.escape_html(r.company)}"
                        data-interface="${r.interface_code}">${__("Reset")}</button></td>
                </tr>`);
            });
        });
    }

    function load_sessions() {
        call("get_session_keys", null, rows => {
            const $tbody = $body.find(".sessions-table tbody").empty();
            (rows || []).forEach(r => {
                $tbody.append(`<tr>
                    <td>${frappe.utils.escape_html(r.company)}</td>
                    <td>${frappe.utils.escape_html(r.tin || "")}</td>
                    <td>${frappe.utils.escape_html(r.device_no || "")}</td>
                    <td>${r.sandbox_mode ? __("Sandbox") : __("Live")}</td>
                    <td>${r.key_cached ? "✓" : "—"}</td>
                    <td><button class="btn btn-xs btn-default invalidate-key"
                        data-company="${frappe.utils.escape_html(r.company)}">${__("Invalidate")}</button></td>
                </tr>`);
            });
        });
    }

    function load_failures() {
        call("get_recent_failures", { limit: 20 }, rows => {
            const $tbody = $body.find(".failures-table tbody").empty();
            if (!rows || !rows.length) {
                $tbody.append(`<tr><td colspan="7" class="text-muted">${__("No recent failures")}</td></tr>`);
                return;
            }
            rows.forEach(r => {
                const ref = r.reference_doctype && r.reference_name
                    ? `<a href="/app/${frappe.router.slug(r.reference_doctype)}/${encodeURIComponent(r.reference_name)}">${frappe.utils.escape_html(r.reference_name)}</a>`
                    : "";
                $tbody.append(`<tr>
                    <td><a href="/app/efris-sync-job/${r.name}">${r.name}</a></td>
                    <td>${frappe.utils.escape_html(r.company)}</td>
                    <td><code>${r.interface_code}</code></td>
                    <td>${r.status}</td>
                    <td class="text-right">${r.attempts}/${r.max_attempts}</td>
                    <td>${ref}</td>
                    <td><small>${frappe.utils.escape_html(r.last_error || "")}</small></td>
                </tr>`);
            });
        });
    }

    $body.on("click", ".reset-breaker", function () {
        const company = $(this).data("company");
        const interface_code = $(this).data("interface");
        call("reset_breaker", { company, interface_code }, () => {
            frappe.show_alert({ message: __("Breaker reset"), indicator: "green" });
            load_breakers();
        });
    });

    $body.on("click", ".invalidate-key", function () {
        const company = $(this).data("company");
        call("invalidate_session_key", { company }, () => {
            frappe.show_alert({ message: __("AES key invalidated"), indicator: "green" });
            load_sessions();
        });
    });

    refresh();
};
