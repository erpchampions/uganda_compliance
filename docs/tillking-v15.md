# `tillking-v15` branch: EFRIS for Till King POS tenants

Frappe v15.108 / ERPNext v15.108.3. This branch is the pinned `uganda_compliance` line for the
Till King tenant bench. Do not merge it into `develop`, `version-15` or `master` without review
by the EFRIS owner.

## 1. Branch decision (28 Sep 2026)

| Branch | Tip | Relation to `develop` | What it adds | Verdict |
|---|---|---|---|---|
| `develop` | 2026-09-22 `cc4f451` (ERP Champions) | — | Newest SI fixes: UoM/commodity codes, export invoicing, multi-tax category, credit-note auto-submit off, `efris_flag` on all-EFRIS items. **HEAD is uninstallable** (`dit[project]` in `pyproject.toml`). | **Base** |
| `pos_invoice` (underscore) | 2026-05-18 `511cfc4` (Mugula Abbey) | forked from `develop@c5edc51`, 9 ahead / 1 behind | POS Invoice path through the shared `E Invoice` (`source_doctype`), POS custom fields, `send_pos_invoice_to_efris`, discount-percentage sync, request/encryption refactor | **Merged** (clean merge). This is what FB-Fashions ran (sandbox/UAT only). |
| `pos-invoice` (hyphen) | 2026-06-30 `27bf2be` (erpchampions) | forked 2025-07-23, 6 ahead / 16 behind | Separate `POS E Invoice` doctype family + POS page button (`pos_send_efris.js`). Installed at MOGAS for the SI path. | Not merged: parallel design, far behind. Ported only the consolidated-invoice guard from `27bf2be`. |
| `version-15` | 2025-07-23 | 12 merge commits, 16 behind | Release snapshot of develop (what `bench-ecl-v15` runs) | Superseded by develop |
| `erpchamps` | 2025-01-29 | 3 ahead / 134 behind | Early UoM/commodity work | Obsolete |
| `efris-import` | 2026-07-04 | unrelated history | Ignite Digital `efris` app for v16 / Python 3.14 | Reference only (third-party) |
| `version-16` | 2026-06-17 | 55 ahead / 16 behind | v16 port (`requires-python >=3.14`, frappe 16) | Not for v15 |

Most recent production use: the Sales Invoice path of `develop`/`pos-invoice` (MOGAS, Medequip).
The POS path has only run against the URA sandbox (FB-Fashions UAT, 17 POS e-invoices, May–Jun 2026).

## 2. What this branch changes

* **Background submission with retry** (`efris/efris_queue.py`). POS Invoice (always) and Sales
  Invoice (setting *Sales Invoice EFRIS Submission* = Background, default) are flagged
  `efris_status = Pending` on submit and sent by a `default`-queue job
  (`job_id` per invoice, `deduplicate`, `enqueue_after_commit`). The sale never waits for URA.
  * Failure: `efris_status = Failed`, `efris_attempts`, `efris_last_error`, `efris_next_retry`
    (15 min doubling, max 12 h) and an `E Invoice Request Log` with `status = Failed`.
  * Hourly `retry_pending_efris_submissions` re-queues due Failed and stale Pending invoices until
    *Max EFRIS Submission Attempts* (default 8). "Send to EFRIS"/"Retry EFRIS" still works after that.
  * Idempotency: the job locks the invoice row, skips invoices that already have an FDN (or, for a
    return, a credit note application); on a retry it first looks the invoice up at URA (T106 by
    seller reference = invoice name, T108 for details) and adopts that FDN instead of sending again.
* **POS returns / cancel.** A submitted POS return sends the T110 credit note application (same code
  as Sales Invoice credit notes, now source-doctype aware) and waits if the original is not fiscalised
  yet. The hourly `check_credit_note_approval_status` (was daily and broken) polls T111 for Sales and
  POS returns; approval stores the credit-note FDN and marks the original *EFRIS Cancelled* when fully
  reversed; rejection flags the return (`EFRIS Credit Note Rejected`, `efris_status = Failed`).
  Cancelling a fiscalised invoice is blocked (`before_cancel`): make a Return instead.
* **Endpoints** `send_to_efris`, `send_pos_invoice_to_efris`, `generate_irn`, `cancel_irn`,
  `confirm_irn_cancellation`: check permission, then load the invoice by name (a client-sent doc is
  reduced to its name), POST only, rate limited. `get_e_company_settings` is no longer whitelisted;
  forms use `get_e_company_client_settings` (flags only, Company read permission).
* **80 mm receipt** `EFRIS POS Receipt 80mm` (POS Invoice): FDN, verification code, QR, device no,
  original FDN on credit notes, and clear *EFRIS PENDING* / *CREDIT NOTE PENDING URA APPROVAL* /
  *SANDBOX* states. Data comes from the Jinja method `efris_receipt_data(doc)`.
* **Provisioning** `uganda_compliance.tillking.configure_efris / set_efris_mode / get_efris_config`.
* Sandbox-run fixes: request logs are written after commit (they were lost for new items/invoices,
  which breaks credit notes), `efris_registered` is persisted (every item save re-uploaded it),
  UGX documents no longer call T121, no bogus `''` key-password default, and every HTTP call to URA
  is logged as `EFRIS POST <interface> -> <url>` in `logs/uganda_compliance.efris_http.log`.
* Fixes: `pyproject.toml` parse error and pins below Frappe 15.108's Pillow/pyOpenSSL; FB-Fashions
  fields removed from the POS fixture; form JS via `doctype_js`; per-request settings cache (the old
  per-process cache kept sandbox settings after a mode switch); `efris_log_info` writes to
  `logs/uganda_compliance.log` instead of creating an Error Log per call.

## 3. Provisioning

```bash
# sandbox at provisioning (EFRIS stays disabled until ops upload the key + password)
bench --site <tenant> execute uganda_compliance.tillking.configure_efris \
  --kwargs "{'company': '<Company>', 'tin': '<TIN>', 'device_no': '<TIN>_01', 'output_vat_account': '<VAT account>'}"
# go-live (requires live key + password; runs a T119 TIN lookup; raises and keeps sandbox on failure)
bench --site <tenant> execute uganda_compliance.tillking.set_efris_mode \
  --kwargs "{'company': '<Company>', 'mode': 'Production'}"
bench --site <tenant> execute uganda_compliance.tillking.get_efris_config --kwargs "{'company': '<Company>'}"
```

Keys/passwords are uploaded in *E Invoicing Settings* by ops; they are never command-line arguments.

## 4. Known gaps

* URA sandbox run (28 Sep 2026, see `artifacts/tillking/efris-sandbox/RESULT.md`): T109, T110, T111,
  T106 and T108 field names used by the code were confirmed against the real sandbox. Credit-note
  *approval* (T111 `approveStatus` 101 → T108 of the credit note) was not exercised: the sandbox
  application stays at 102 until approved on the URA portal.
* URA rejects a Seller Reference No. already used under the TIN ("Invoice(s)/receipt(s) (...) with the
  same Seller's Reference Number have already been issued"), including references issued by other
  systems on the same TIN. References are therefore `<seller_reference_prefix>-<invoice name>`
  (prefix generated per E Invoicing Settings) and fixed on the invoice before the first attempt.
  A tenant migrating from another EFRIS system on the same TIN keeps the generated prefix.
* **Restore from backup.** A restored site forgets the invoices fiscalised after the backup and
  its naming series go back with it, so new sales reuse names (and references) URA already
  accepted. Guard: when URA answers "same Seller's Reference Number have already been issued",
  or the retry lookup finds a record, the reference is looked up (T106, 60 days back). A record
  that is this invoice (same device and gross, not issued before the invoice was created — URA's
  `issuedDate` is its own Uganda time, not ours) is adopted; any other record moves the invoice to
  `<reference>-R1`, `-R2` … (logged as a Comment on the invoice) and it is sent again. Before
  reopening the tills after a restore, ops run
  `bench --site <tenant> execute uganda_compliance.tillking.advance_series_after_restore --kwargs
  "{'company': '<Company>', 'dry_run': 0}"` (dry run by default): it reads the invoices URA issued
  on the device (T106, paged) and moves each Sales/POS Invoice series counter past the highest
  fiscalised number (forward only, recorded as a Version of the Series).
* The Point-of-Sale page (Past Orders) has no EFRIS button/badge yet; the retail pack should call
  `send_pos_invoice_to_efris(name=...)` / `get_efris_status`.
* The job holds a row lock on the invoice during the URA call (≤ 2 × 120 s). A POS Closing that
  consolidates that invoice at the same moment can hit a lock-wait timeout and must be retried.
* Pre-existing, not changed here: the app takes over ERPNext's `Tax Category` doctype (module EFRIS);
  `create_item_tax_templates`, `check_efris_flag_for_sales_invoice`, `get_e_tax_template` are
  whitelisted without permission checks; `e_invoicing_settings.before_save` is whitelisted.
