# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this app is

`uganda_compliance` is a Frappe/ERPNext app that integrates ERPNext with Uganda's URA **EFRIS** (Electronic Fiscal Receipting and Invoicing Solution). It is installed inside a `frappe-bench` and depends on `frappe>=16.0.0,<17.0.0`. There is no standalone way to run it — every command goes through `bench`.

Note: `pyproject.toml` declares `requires-python = ">=3.14"` but `README.md` and CI pin Python 3.10. Treat 3.10 as the supported version; the pyproject value is likely a typo.

## Common commands

All commands run from the bench root (parent of `apps/`), not from this app's directory.

```bash
# Install / update after pulling
bench get-app uganda_compliance <path-or-url>
bench --site <site> install-app uganda_compliance
bench --site <site> migrate

# Run the full test suite (matches CI)
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app uganda_compliance

# Run a single module / test
bench --site <site> run-tests --app uganda_compliance --module uganda_compliance.tests.test_vat_compliance
bench --site <site> run-tests --app uganda_compliance --doctype "E Invoicing Settings"

# Rebuild JS/CSS assets after editing public/ or client_scripts/
bench build --app uganda_compliance

# Tail logs while debugging EFRIS calls
bench --site <site> console      # interactive Frappe shell
tail -f sites/<site>/logs/*.log
```

Linting uses ruff (configured in `pyproject.toml`, ignoring `F401` and `F841`): `ruff check apps/uganda_compliance`.

CI (`.github/workflows/ci.yml`) provisions a fresh bench, installs the app on a `test_site`, and runs the same `run-tests` command — reproduce failures locally with the steps above.

## Architecture

The Frappe wiring lives in `uganda_compliance/hooks.py` — read this first when tracing behavior. It declares:

- **`doc_events`** — the entire EFRIS integration is driven by hooks on standard ERPNext doctypes (Sales Invoice, Purchase Receipt, Stock Entry, Stock Reconciliation, Item, Customer, Company, E Invoicing Settings). For example, submitting a Sales Invoice fires `efris.api_classes.e_invoice.on_submit_sales_invoice`, which posts the invoice to URA. To find what a UI action triggers, grep `hooks.py` for the doctype name.
- **`scheduler_events`** — daily and hourly retries for unsynced invoices and stock entries. Background reconciliation lives in `efris.api_classes.efris_invoice_sync` and `efris.page.efris_synchronizatio.efris_synchronization_center`.
- **`fixtures`** — EFRIS-specific reference data (`E Tax Category`, `EFRIS Commodity Code`, EFRIS print formats, currency codes, payment modes) ships as fixtures and is reloaded on `bench migrate`.
- **`doctype_list_js`** + `app_include_js` — per-doctype client scripts under `efris/client_scripts/` augment the standard ERPNext list/form views.

### EFRIS request pipeline

All outbound calls funnel through `uganda_compliance/efris/api_classes/efris_api.py::make_post(interfaceCode, content, company_name, ...)`:

1. `e_invoicing_settings.get_e_company_settings(company)` resolves per-company TIN, device number, BRN, sandbox flag, private-key path, and the sandbox/production URL.
2. `encryption_utils` loads the RSA private key, derives an AES key from URA, AES-ECB-encrypts the JSON payload, and signs it.
3. `request_utils.post_req` posts to URA; the encrypted response is decrypted and returned.
4. Every request/response is persisted to **E Invoice Request Log** via `log_request_to_efris` — when debugging a failed sync, start there before re-reading code.

Each business flow (`e_invoice.py`, `e_goods_services.py`, `e_customer.py`, `e_company.py`, `stock_in.py`) builds the `content` dict for a specific URA `interfaceCode` (e.g. `T109` invoice upload, `T131` stock-in) and calls `make_post`. Adding a new EFRIS interaction = new builder function + new `doc_events` hook, not a new transport layer.

### Custom fields vs. new doctypes

`efris/custom/*.json` contains **Custom Field / Property Setter** definitions that extend stock ERPNext doctypes (Sales Invoice, Item, Customer, Warehouse, etc.) with EFRIS fields. New doctypes owned by this app (E Invoice, E Invoicing Settings, E Tax Category, EFRIS Commodity Code, EFRIS Payment Mode, etc.) live in `efris/doctype/`. When adding an EFRIS-specific field, prefer extending an existing ERPNext doctype via `efris/custom/<doctype>.json` rather than creating a new child doctype.

### Multi-company

EFRIS settings are per-company. Always pass `company_name` through the call chain — never read a "default" device/key. `get_e_company_settings` is the single source of truth for resolving credentials.

### Sandbox vs production

`E Invoicing Settings.sandbox_mode` switches both the post URL (`get_mode_post_url`) and the private-key path (`get_mode_private_key_path`). Tests and local development should run with sandbox on; never check in production keys.

## Branch convention

`main` is the PR target. Work in progress on `hotfix-v-16` targets the v16 line.
