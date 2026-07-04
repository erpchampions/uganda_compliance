# EFRIS ↔ ERPNext Integration: Comprehensive Technical Guide

**Version**: Based on EFRIS API v24.0.1 (URA Uganda)
**ERPNext**: v14/v15 + Frappe Framework

---

## 1. Overview & Architecture

EFRIS (Electronic Fiscal Receipting and Invoicing System) is Uganda Revenue Authority's (URA) mandatory e-invoicing platform. Every VAT-registered taxpayer must submit fiscal documents in real time via a system-to-system API.

### Integration Architecture

```
ERPNext (Frappe)
  ├── Sales Invoice (submit trigger)
  ├── Purchase Invoice (for imports)
  ├── Stock Entry / Delivery Note
  └── Custom App: erpnext_efris
          ├── hooks.py (doc_events)
          ├── API client (T101–T139)
          ├── Encryption layer (RSA/AES)
          ├── Retry/queue mechanism
          └── Sync scheduler (T115, T127)
                    │
                    │ HTTPS + JSON
                    │ AES-encrypted content
                    │ RSA signature
                    ▼
          EFRIS Server (URA)
          ├── T109 — Invoice upload
          ├── T110 — Credit note
          ├── T130 — Goods upload
          ├── T131 — Stock management
          └── T119 — TIN validation
```

---

## 2. EFRIS API Protocol

### 2.1 Outer Envelope (All Requests)

Every EFRIS API call wraps its payload in this JSON envelope:

```json
{
  "data": {
    "content": "<BASE64(AES-encrypted inner payload)>",
    "signature": "<RSA signature of content>",
    "dataDescription": {
      "codeType": "1",
      "encryptCode": "2",
      "zipCode": "0"
    }
  },
  "globalInfo": {
    "appId": "AP04",
    "version": "1.1.20191201",
    "dataExchangeId": "<UUID>",
    "interfaceCode": "T109",
    "requestCode": "TP",
    "requestTime": "2025-02-19 10:00:00",
    "responseCode": "TA",
    "userName": "<efris_username>",
    "deviceMAC": "FFFFFFFFFFFF",
    "deviceNo": "<your_device_no>",
    "tin": "<your_tin>",
    "brn": "",
    "taxpayerID": "1",
    "longitude": "32.58",
    "latitude": "0.31",
    "agentType": "0",
    "extendField": {
      "responseDateFormat": "dd/MM/yyyy",
      "responseTimeFormat": "dd/MM/yyyy HH:mm:ss",
      "referenceNo": "<sales_invoice_name>",
      "operatorName": "<frappe_user>",
      "currency": "UGX",
      "grossAmount": "<grand_total>",
      "taxAmount": "<total_taxes>"
    }
  },
  "returnStateInfo": {
    "returnCode": "",
    "returnMessage": ""
  }
}
```

**Key fields:**
| Field | Value for S2S |
|---|---|
| `appId` | `AP04` (system-to-system) |
| `codeType` | `1` = encrypted, `0` = plain text (testing only) |
| `encryptCode` | `1` = RSA, `2` = AES (use AES for content) |
| `dataExchangeId` | UUID per request — use Python `uuid.uuid4()` |
| `requestCode` | `TP` (taxpayer request) |
| `responseCode` | `TA` (taxpayer receives response) |

---

## 3. Key Interface Codes

| Code | Name | ERPNext Trigger |
|---|---|---|
| **T101** | Get server time | Startup / health check |
| **T103** | Log in | Session init |
| **T104** | Get symmetric key | Online mode setup |
| **T109** | Invoice upload | Sales Invoice submit |
| **T110** | Credit note upload | Credit note submit |
| **T113** | Credit note approval | After T110 |
| **T115** | System dictionary update | Scheduler (daily) |
| **T119** | TIN validation | Customer / Supplier save |
| **T121** | Exchange rates | Scheduler (daily) |
| **T127** | Goods/services inquiry | Item sync check |
| **T130** | Goods/services upload | New Item save |
| **T131** | Stock maintenance | Stock Entry submit |
| **T138** | Get all branches | Setup wizard |
| **T139** | Stock transfer | Inter-branch transfer |

---

## 4. Custom App Structure

### 4.1 Create the App

```bash
cd /home/frappe/frappe-bench
bench new-app erpnext_efris
bench --site your-site.com install-app erpnext_efris
```

### 4.2 App Directory Layout

```
erpnext_efris/
├── hooks.py
├── erpnext_efris/
│   ├── api/
│   │   ├── client.py         # HTTP + encryption
│   │   ├── interfaces.py     # T101–T139 wrappers
│   │   └── crypto.py         # RSA + AES helpers
│   ├── doctype/
│   │   ├── efris_log/        # Audit log DocType
│   │   ├── efris_settings/   # Credentials DocType
│   │   └── efris_queue/      # Retry queue DocType
│   ├── overrides/
│   │   ├── sales_invoice.py
│   │   └── stock_entry.py
│   └── tasks.py              # Scheduled jobs
└── setup.py
```

---

## 5. hooks.py

```python
# erpnext_efris/hooks.py

app_name = "erpnext_efris"

doc_events = {
    "Sales Invoice": {
        "on_submit":  "erpnext_efris.overrides.sales_invoice.on_submit",
        "on_cancel":  "erpnext_efris.overrides.sales_invoice.on_cancel",
        "validate":   "erpnext_efris.overrides.sales_invoice.validate",
    },
    "Stock Entry": {
        "on_submit":  "erpnext_efris.overrides.stock_entry.on_submit",
    },
    "Item": {
        "after_insert": "erpnext_efris.overrides.item.upload_to_efris",
        "on_update":    "erpnext_efris.overrides.item.update_on_efris",
    },
    "Customer": {
        "validate": "erpnext_efris.overrides.customer.validate_tin",
    },
    "Supplier": {
        "validate": "erpnext_efris.overrides.supplier.validate_tin",
    },
}

scheduler_events = {
    "daily": [
        "erpnext_efris.tasks.sync_dictionary",    # T115
        "erpnext_efris.tasks.sync_exchange_rates", # T121
    ],
    "hourly": [
        "erpnext_efris.tasks.retry_failed_queue",
    ],
}

# Custom fields added to standard DocTypes
fixtures = [
    {"dt": "Custom Field", "filters": [["name", "like", "%-efris%"]]},
]
```

---

## 6. Custom Fields on Standard DocTypes

Add these via `Customize Form` or fixtures:

### Sales Invoice
| Field | Type | Description |
|---|---|---|
| `custom_efris_status` | Select (Pending/Submitted/Failed) | EFRIS submission status |
| `custom_efris_invoice_id` | Data | ID returned by EFRIS |
| `custom_efris_fdn` | Data | Fiscal Document Number |
| `custom_efris_qr_code` | Data | QR code string |
| `custom_efris_antifake_code` | Data | Anti-fake code |
| `custom_invoice_type` | Select (1=Invoice,4=Debit,5=Credit) | EFRIS invoice type |
| `custom_invoice_kind` | Select (1=Invoice, 2=Receipt) | |
| `custom_invoice_industry_code` | Select (101=General,102=Export…) | |
| `custom_efris_error` | Small Text | Last error message |
| `custom_efris_retries` | Int | Retry count |

### Item
| Field | Type | Description |
|---|---|---|
| `custom_efris_goods_id` | Data | EFRIS goods ID |
| `custom_efris_goods_code` | Data | EFRIS goods code |
| `custom_commodity_category_id` | Data | URA commodity category |
| `custom_have_excise_tax` | Select (101=Yes, 102=No) | |
| `custom_excise_duty_code` | Data | Excise duty code |

### Customer
| Field | Type | Description |
|---|---|---|
| `custom_tin` | Data | Uganda TIN |
| `custom_buyer_type` | Select (0=B2B,1=B2C,2=Foreign,3=B2G) | |
| `custom_nin_brn` | Data | National ID / Business Reg No |

---

## 7. EFRIS Settings DocType

Create `EFRIS Settings` as a **Single** DocType:

```python
# DocType fields:
# tin, username, password, device_no, device_mac
# branch_id, private_key (Password), public_key
# is_online_mode (Check), environment (Select: sandbox/production)
# efris_server_url (Data)
```

Usage:
```python
settings = frappe.get_single("EFRIS Settings")
```

---

## 8. Encryption Layer (crypto.py)

```python
# erpnext_efris/api/crypto.py
import base64
import json
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from Crypto.Util.Padding import pad, unpad

def encrypt_content(payload: dict, aes_key: bytes) -> str:
    """AES-256-ECB encrypt the inner payload, return BASE64."""
    data = json.dumps(payload).encode("utf-8")
    cipher = AES.new(aes_key, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(data, AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")

def decrypt_content(content_b64: str, aes_key: bytes) -> dict:
    """Decrypt BASE64 AES content and return dict."""
    raw = base64.b64decode(content_b64)
    cipher = AES.new(aes_key, AES.MODE_ECB)
    decrypted = unpad(cipher.decrypt(raw), AES.block_size)
    return json.loads(decrypted.decode("utf-8"))

def sign_content(content_b64: str, private_key_pem: str) -> str:
    """RSA-SHA256 sign content, return BASE64 signature."""
    key = RSA.import_key(private_key_pem)
    h = SHA256.new(content_b64.encode("utf-8"))
    signature = pkcs1_15.new(key).sign(h)
    return base64.b64encode(signature).decode("utf-8")
```

---

## 9. API Client (client.py)

```python
# erpnext_efris/api/client.py
import uuid
import frappe
import requests
from datetime import datetime
from .crypto import encrypt_content, decrypt_content, sign_content

class EFRISClient:
    def __init__(self):
        s = frappe.get_single("EFRIS Settings")
        self.tin = s.tin
        self.username = s.username
        self.device_no = s.device_no
        self.device_mac = s.device_mac or "FFFFFFFFFFFF"
        self.branch_id = s.branch_id
        self.private_key = s.get_password("private_key")
        self.aes_key = s.get_password("aes_key").encode()  # 32 bytes
        self.base_url = s.efris_server_url  # e.g. https://efris.ura.go.ug/efrisws/ws/taapp

    def call(self, interface_code: str, payload: dict,
             reference_no: str = "", operator: str = "") -> dict:
        content_b64 = encrypt_content(payload, self.aes_key)
        signature = sign_content(content_b64, self.private_key)

        envelope = {
            "data": {
                "content": content_b64,
                "signature": signature,
                "dataDescription": {
                    "codeType": "1",
                    "encryptCode": "2",
                    "zipCode": "0"
                }
            },
            "globalInfo": {
                "appId": "AP04",
                "version": "1.1.20191201",
                "dataExchangeId": str(uuid.uuid4()).replace("-", ""),
                "interfaceCode": interface_code,
                "requestCode": "TP",
                "requestTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "responseCode": "TA",
                "userName": self.username,
                "deviceMAC": self.device_mac,
                "deviceNo": self.device_no,
                "tin": self.tin,
                "brn": "",
                "taxpayerID": "1",
                "longitude": "32.58",
                "latitude": "0.31",
                "agentType": "0",
                "extendField": {
                    "responseDateFormat": "dd/MM/yyyy",
                    "responseTimeFormat": "dd/MM/yyyy HH:mm:ss",
                    "referenceNo": reference_no,
                    "operatorName": operator or frappe.session.user,
                }
            },
            "returnStateInfo": {"returnCode": "", "returnMessage": ""}
        }

        response = requests.post(
            f"{self.base_url}/applyForInvoice",
            json=envelope,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()

        return_code = result.get("returnStateInfo", {}).get("returnCode", "")
        if return_code not in ("00", ""):
            raise EFRISError(return_code,
                result.get("returnStateInfo", {}).get("returnMessage", ""))

        # Decrypt response content if present
        content = result.get("data", {}).get("content", "")
        if content:
            return decrypt_content(content, self.aes_key)
        return result

class EFRISError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"EFRIS Error {code}: {message}")
```

---

## 10. Invoice Upload (T109) — Core Integration

```python
# erpnext_efris/overrides/sales_invoice.py
import frappe
from frappe.utils import flt, nowdate, get_datetime_str
from erpnext_efris.api.client import EFRISClient, EFRISError

def on_submit(doc, method=None):
    """Called when Sales Invoice is submitted."""
    settings = frappe.get_single("EFRIS Settings")
    if not settings.enabled:
        return
    try:
        upload_invoice(doc)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"EFRIS: {doc.name}")
        frappe.db.set_value("Sales Invoice", doc.name, {
            "custom_efris_status": "Failed",
            "custom_efris_error": str(e)
        })
        # Enqueue for retry
        enqueue_retry(doc.name)
        frappe.msgprint(
            f"⚠️ Invoice submitted but EFRIS upload failed: {e}. "
            f"Queued for retry.",
            alert=True
        )

def upload_invoice(doc):
    client = EFRISClient()
    settings = frappe.get_single("EFRIS Settings")

    # Build goodsDetails from invoice items
    goods_details = []
    for idx, item in enumerate(doc.items, start=1):
        item_doc = frappe.get_doc("Item", item.item_code)
        tax_rate = get_item_tax_rate(doc, item)

        goods_details.append({
            "item": item.item_name,
            "itemCode": item_doc.custom_efris_goods_code or item.item_code,
            "qty": str(flt(item.qty, 2)),
            "unitOfMeasure": get_uom_code(item.uom),
            "unitPrice": str(flt(item.rate, 2)),
            "total": str(flt(item.net_amount, 2)),
            "taxRate": str(flt(tax_rate / 100, 2)),
            "tax": str(flt(item.net_amount * tax_rate / 100, 2)),
            "discountTotal": str(flt(item.discount_amount or 0, 2)),
            "orderNumber": str(idx),
            "discountFlag": "2" if item.discount_percentage else "0",
            "deemedFlag": "0",
            "exciseFlag": "2",
            "goodsCategoryId": item_doc.custom_commodity_category_id or "",
            "goodsCategoryName": "",
            "vatApplicableFlag": "1",
        })

    # Build taxDetails grouped by tax rate
    tax_details = build_tax_details(doc)

    # Build buyer details
    customer = frappe.get_doc("Customer", doc.customer)
    buyer_details = {
        "buyerTin": customer.custom_tin or "",
        "buyerNinBrn": customer.custom_nin_brn or "",
        "buyerLegalName": doc.customer_name,
        "buyerBusinessName": doc.customer_name,
        "buyerAddress": "",
        "buyerEmail": "",
        "buyerType": customer.custom_buyer_type or "1",
        "buyerCitizenship": "",
        "buyerReferenceNo": doc.name,
        "nonResidentFlag": "0",
    }

    payload = {
        "sellerDetails": {
            "tin": settings.tin,
            "legalName": settings.company_legal_name,
            "businessName": frappe.defaults.get_global_default("company"),
            "address": settings.company_address or "",
            "mobilePhone": settings.mobile_phone or "",
            "linePhone": settings.line_phone or "",
            "emailAddress": settings.email_address or "",
            "placeOfBusiness": settings.place_of_business or "",
            "branchId": settings.branch_id,
        },
        "basicInformation": {
            "invoiceNo": doc.name,
            "antifakeCode": generate_antifake_code(doc),
            "deviceNo": settings.device_no,
            "issuedDate": get_datetime_str(doc.posting_date + " " +
                          (doc.posting_time or "00:00:00")),
            "operator": frappe.get_fullname(doc.owner),
            "currency": doc.currency,
            "oriInvoiceId": "",
            "invoiceType": doc.custom_invoice_type or "1",
            "invoiceKind": doc.custom_invoice_kind or "1",
            "dataSource": "103",  # WebService API
            "invoiceIndustryCode": doc.custom_invoice_industry_code or "101",
            "isBatch": "0",
        },
        "buyerDetails": buyer_details,
        "goodsDetails": goods_details,
        "taxDetails": tax_details,
        "summary": {
            "netAmount": str(flt(doc.net_total, 2)),
            "taxAmount": str(flt(doc.total_taxes_and_charges, 2)),
            "grossAmount": str(flt(doc.grand_total, 2)),
            "itemCount": str(len(doc.items)),
            "modeCode": "0",
            "remarks": doc.remarks or "",
            "qrCode": "",
        },
    }

    result = client.call("T109", payload,
                         reference_no=doc.name,
                         operator=frappe.get_fullname(doc.owner))

    # Store EFRIS response fields
    frappe.db.set_value("Sales Invoice", doc.name, {
        "custom_efris_status": "Submitted",
        "custom_efris_invoice_id": result.get("basicInformation", {}).get("invoiceId", ""),
        "custom_efris_fdn": result.get("basicInformation", {}).get("invoiceNo", ""),
        "custom_efris_qr_code": result.get("summary", {}).get("qrCode", ""),
        "custom_efris_antifake_code": result.get("basicInformation", {}).get("antifakeCode", ""),
        "custom_efris_error": "",
    })

    # Log the transaction
    create_efris_log("T109", doc.name, "Sales Invoice", "Success", result)
    frappe.msgprint("✅ Invoice submitted to EFRIS successfully.", alert=True)


def on_cancel(doc, method=None):
    """Cancel = raise credit note via T110."""
    if doc.custom_efris_invoice_id:
        # The cancel flow requires T110 (credit note), not a simple void
        frappe.msgprint(
            "To cancel an EFRIS-submitted invoice, create a Credit Note "
            "via the ERPNext credit note flow. EFRIS will be updated automatically.",
            title="EFRIS Cancellation",
        )
```

---

## 11. Credit Note (T110)

```python
# In sales_invoice.py — handles credit notes automatically
def validate(doc, method=None):
    """Set invoice type for credit notes."""
    if doc.is_return and doc.return_against:
        doc.custom_invoice_type = "5"  # Credit Memo / rebate
        original = frappe.db.get_value("Sales Invoice",
            doc.return_against, "custom_efris_invoice_id")
        if original:
            doc.custom_efris_ori_invoice_id = original
```

```python
# Credit note upload via T110
def upload_credit_note(doc):
    client = EFRISClient()
    payload = {
        # Same structure as T109 but invoiceType = "5"
        # plus oriInvoiceId = original EFRIS invoice ID
        "basicInformation": {
            "invoiceType": "5",
            "oriInvoiceId": doc.custom_efris_ori_invoice_id,
            # ... rest same as T109
        },
        "reasonCode": "101",  # 101=Sales return, 102=Wrong amount, etc.
        "remark": doc.remarks or "Credit note",
        # ... goods/tax/summary same as T109
    }
    result = client.call("T110", payload, reference_no=doc.name)
    return result
```

---

## 12. Goods Upload (T130)

```python
# erpnext_efris/overrides/item.py
import frappe
from erpnext_efris.api.client import EFRISClient

def upload_to_efris(doc, method=None):
    """Upload new item to EFRIS goods registry."""
    settings = frappe.get_single("EFRIS Settings")
    if not settings.enabled:
        return

    client = EFRISClient()
    payload = {
        "goodsCode": doc.item_code,
        "goodsName": doc.item_name,
        "goodsDescription": doc.description or doc.item_name,
        "measureUnit": get_uom_code(doc.stock_uom),
        "unitPrice": str(frappe.db.get_value("Item Price",
            {"item_code": doc.item_code, "price_list": "Standard Selling"},
            "price_list_rate") or 0),
        "currency": "UGX",
        "commodityCategoryId": doc.custom_commodity_category_id or "",
        "haveExciseTax": doc.custom_have_excise_tax or "102",
        "exciseDutyCode": doc.custom_excise_duty_code or "",
        "description": doc.description or "",
        "stockPrewarning": "0",
        "operationType": "101",  # 101=Add, 102=Modify, 103=Delete
    }

    result = client.call("T130", payload, reference_no=doc.item_code)
    frappe.db.set_value("Item", doc.name, {
        "custom_efris_goods_id": result.get("commodityGoodsId", ""),
        "custom_efris_goods_code": doc.item_code,
    })
```

---

## 13. Stock Management (T131)

```python
# erpnext_efris/overrides/stock_entry.py
import frappe
from erpnext_efris.api.client import EFRISClient

EFRIS_STOCK_TYPES = {
    "Material Receipt": "101",   # Purchase stock in
    "Material Issue": None,       # No EFRIS sync for issues
    "Stock Entry": "101",
}

def on_submit(doc, method=None):
    """Sync stock entries to EFRIS T131."""
    if doc.stock_entry_type not in EFRIS_STOCK_TYPES:
        return
    stock_in_type = EFRIS_STOCK_TYPES.get(doc.stock_entry_type)
    if not stock_in_type:
        return

    client = EFRISClient()
    items = []
    for item in doc.items:
        if not item.t_warehouse:  # Only items going INTO a warehouse
            continue
        item_doc = frappe.get_doc("Item", item.item_code)
        items.append({
            "commodityGoodsId": item_doc.custom_efris_goods_id or "",
            "goodsCode": item.item_code,
            "measureUnit": get_uom_code(item.uom),
            "quantity": str(abs(item.qty)),
            "unitPrice": str(item.basic_rate),
            "currency": "UGX",
            "remarks": doc.remarks or "",
        })

    payload = {
        "stockInType": stock_in_type,
        "invoiceNo": doc.name,
        "stockInDate": str(doc.posting_date),
        "operationType": "101",
        "goodsStockInItem": items,
    }

    client.call("T131", payload, reference_no=doc.name)
```

---

## 14. TIN Validation (T119)

```python
# erpnext_efris/overrides/customer.py
import frappe
from erpnext_efris.api.client import EFRISClient

def validate_tin(doc, method=None):
    """Validate TIN against EFRIS before saving Customer."""
    if not doc.custom_tin or doc.custom_buyer_type == "1":  # B2C = no TIN
        return

    try:
        client = EFRISClient()
        result = client.call("T119", {
            "tin": doc.custom_tin,
            "ninBrn": doc.custom_nin_brn or "",
        })
        # Populate name from EFRIS if blank
        if not doc.customer_name and result.get("taxpayerName"):
            doc.customer_name = result["taxpayerName"]
        frappe.msgprint(
            f"✅ TIN {doc.custom_tin} validated with URA.",
            alert=True
        )
    except Exception as e:
        frappe.msgprint(
            f"⚠️ TIN validation warning: {e}. Please verify manually.",
            alert=True
        )
```

---

## 15. Retry Queue

```python
# erpnext_efris/tasks.py
import frappe

def retry_failed_queue():
    """Retry failed EFRIS submissions (runs hourly)."""
    failed = frappe.get_all("Sales Invoice",
        filters={
            "custom_efris_status": "Failed",
            "custom_efris_retries": ("<", 5),
            "docstatus": 1,
        },
        fields=["name", "custom_efris_retries"]
    )
    from erpnext_efris.overrides.sales_invoice import upload_invoice

    for inv in failed:
        try:
            doc = frappe.get_doc("Sales Invoice", inv.name)
            upload_invoice(doc)
            frappe.db.set_value("Sales Invoice", inv.name, {
                "custom_efris_status": "Submitted",
                "custom_efris_error": "",
            })
        except Exception as e:
            retries = (inv.custom_efris_retries or 0) + 1
            frappe.db.set_value("Sales Invoice", inv.name, {
                "custom_efris_retries": retries,
                "custom_efris_error": str(e),
            })

def sync_dictionary():
    """Daily sync of UoM, currencies, etc. via T115."""
    from erpnext_efris.api.client import EFRISClient
    client = EFRISClient()
    result = client.call("T115", {})
    # Store locally in EFRIS Settings or a cache table
    frappe.cache().set_value("efris_dictionary", result, expires_in_sec=86400)

def sync_exchange_rates():
    """Sync EFRIS exchange rates via T121."""
    from erpnext_efris.api.client import EFRISClient
    client = EFRISClient()
    result = client.call("T121", {})
    # Update ERPNext currency exchange rates from result
```

---

## 16. EFRIS Log DocType

Create a `EFRIS Log` DocType with fields:

| Field | Type |
|---|---|
| `interface_code` | Data |
| `reference_doctype` | Link (DocType) |
| `reference_name` | Dynamic Link |
| `status` | Select (Success/Failed) |
| `request_payload` | Code (JSON) |
| `response_payload` | Code (JSON) |
| `error_message` | Small Text |
| `timestamp` | Datetime |

```python
def create_efris_log(interface_code, ref_name, ref_doctype, status, response):
    frappe.get_doc({
        "doctype": "EFRIS Log",
        "interface_code": interface_code,
        "reference_name": ref_name,
        "reference_doctype": ref_doctype,
        "status": status,
        "response_payload": frappe.as_json(response),
        "timestamp": frappe.utils.now(),
    }).insert(ignore_permissions=True)
```

---

## 17. Helper Functions

```python
# Common helpers used across the integration

UOM_MAP = {
    "Nos": "101", "Kg": "102", "g": "103", "Ltr": "104",
    "Mtr": "105", "Pcs": "101", "Pair": "106", "Box": "107",
    "Bag": "108", "Dozen": "109", "Roll": "110",
}

def get_uom_code(uom: str) -> str:
    """Map ERPNext UoM to EFRIS unit code. Falls back to '101'."""
    return UOM_MAP.get(uom, "101")

def get_item_tax_rate(invoice_doc, item_row) -> float:
    """Extract the effective VAT rate for an item."""
    for tax in invoice_doc.taxes:
        if tax.charge_type == "On Net Total":
            return abs(tax.rate)
    return 18.0  # Uganda standard VAT rate

def build_tax_details(doc) -> list:
    """Group invoice taxes into EFRIS taxDetails array."""
    groups = {}
    for tax in doc.taxes:
        key = str(round(abs(tax.rate), 4))
        if key not in groups:
            groups[key] = {
                "taxCategoryCode": "01",  # VAT
                "netAmount": 0,
                "taxRate": abs(tax.rate) / 100,
                "taxAmount": 0,
                "grossAmount": 0,
                "taxRateName": f"VAT {abs(tax.rate)}%",
            }
        groups[key]["taxAmount"] += abs(tax.tax_amount)
        groups[key]["netAmount"] = (groups[key]["taxAmount"] /
                                    groups[key]["taxRate"])
        groups[key]["grossAmount"] = (groups[key]["netAmount"] +
                                      groups[key]["taxAmount"])

    return [
        {**v, "netAmount": str(round(v["netAmount"], 2)),
               "taxAmount": str(round(v["taxAmount"], 2)),
               "grossAmount": str(round(v["grossAmount"], 2)),
               "taxRate": str(round(v["taxRate"], 4))}
        for v in groups.values()
    ]

def generate_antifake_code(doc) -> str:
    """Generate anti-fake code from invoice name and date."""
    import hashlib
    raw = f"{doc.name}{doc.posting_date}{doc.grand_total}"
    return hashlib.md5(raw.encode()).hexdigest()[:12].upper()

def enqueue_retry(invoice_name: str):
    frappe.enqueue(
        "erpnext_efris.overrides.sales_invoice.upload_invoice",
        queue="long",
        timeout=120,
        invoice_name=invoice_name,
        at_front=False,
    )
```

---

## 18. Return Code Handling

Key return codes to handle explicitly:

| Code | Meaning | Handling Strategy |
|---|---|---|
| `00` | Success | Mark submitted |
| `99` | Unknown error | Log + retry |
| `45` | Partial failure | Log warning, check items |
| `1040` | Invoice already exists | Mark as submitted (idempotent) |
| `300` | Original invoice not found | Block credit note |
| `306` | Credit note already issued | Block duplicate |
| `1029` | Inventory shortage | Warn + block if stock-linked |
| `2075` | Invoice amount exceeds limit | Escalate to admin |
| `400-403` | Device errors | Alert + disable auto-submission |

```python
IDEMPOTENT_CODES = {"1040"}  # Already submitted — treat as success

def handle_efris_error(code: str, message: str, invoice_name: str):
    if code in IDEMPOTENT_CODES:
        # Already on EFRIS — just update status
        frappe.db.set_value("Sales Invoice", invoice_name,
                            "custom_efris_status", "Submitted")
        return
    raise EFRISError(code, message)
```

---

## 19. Testing Approach

### Unit Tests
```python
# erpnext_efris/tests/test_invoice_upload.py
import frappe
import unittest
from unittest.mock import patch, MagicMock

class TestInvoiceUpload(unittest.TestCase):
    def setUp(self):
        self.invoice = frappe.get_doc("Sales Invoice", "_Test Invoice 001")

    @patch("erpnext_efris.api.client.EFRISClient.call")
    def test_successful_upload(self, mock_call):
        mock_call.return_value = {
            "basicInformation": {"invoiceId": "EFRIS001", "invoiceNo": "FDN001"},
            "summary": {"qrCode": "QRDATA"}
        }
        from erpnext_efris.overrides.sales_invoice import upload_invoice
        upload_invoice(self.invoice)
        self.assertEqual(self.invoice.custom_efris_status, "Submitted")

    @patch("erpnext_efris.api.client.EFRISClient.call")
    def test_duplicate_invoice_handled(self, mock_call):
        from erpnext_efris.api.client import EFRISError
        mock_call.side_effect = EFRISError("1040", "Invoice already exists")
        # Should not raise, should mark as Submitted
        from erpnext_efris.overrides.sales_invoice import on_submit
        on_submit(self.invoice)
```

### Sandbox Testing Checklist
- [ ] T101 server time sync works
- [ ] T103 login returns session key
- [ ] T130 goods upload creates item in EFRIS
- [ ] T109 B2C invoice uploads successfully (returnCode: 00)
- [ ] T109 B2B invoice with buyer TIN uploads successfully
- [ ] T110 credit note references original invoice correctly
- [ ] T131 stock-in sync updates EFRIS inventory
- [ ] Retry queue clears failed invoices on re-run
- [ ] Duplicate submission (code 1040) handled gracefully

---

## 20. Implementation Phases

### Phase 1 — Foundation (Week 1–2)
- Create `erpnext_efris` custom app skeleton
- Implement `EFRIS Settings` DocType
- Implement encryption/decryption layer
- Test T101 (server time) and T103 (login) in sandbox

### Phase 2 — Goods Registry (Week 2–3)
- Add custom fields to Item
- Implement T130 (goods upload)
- Sync existing item catalog to EFRIS
- Implement T127 (goods inquiry) for validation

### Phase 3 — Invoice Integration (Week 3–5)
- Add custom fields to Sales Invoice
- Implement T109 on Sales Invoice submit
- Implement T110 for credit notes / cancellations
- Implement retry queue
- Test with real transactions in sandbox

### Phase 4 — Stock & Dictionary (Week 5–6)
- Implement T131 (stock management)
- Implement T115 daily dictionary sync
- Implement T121 exchange rate sync
- Implement T119 TIN validation on Customer save

### Phase 5 — Go-Live Hardening (Week 7–8)
- Switch to production EFRIS endpoint
- Implement EFRIS Log dashboard
- Set up monitoring/alerting for failed queue
- User training on EFRIS status fields
- Load test with batch invoices (T129)

---

## 21. Dependencies

```txt
# requirements.txt for erpnext_efris
pycryptodome>=3.19.0   # AES + RSA encryption
requests>=2.31.0        # HTTP client (usually already in Frappe)
```

Install: `bench pip install pycryptodome`

---

## 22. EFRIS Server Endpoints

| Environment | URL |
|---|---|
| Sandbox | `https://efristest.ura.go.ug/efrisws/ws/taapp` |
| Production | `https://efris.ura.go.ug/efrisws/ws/taapp` |

Contact URA at **kakasa@ura.go.ug** for sandbox credentials and device registration.
