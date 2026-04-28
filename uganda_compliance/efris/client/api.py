"""High-level typed client for EFRIS interfaces.

`EfrisClient(company)` exposes one method per URA interfaceCode used in this
app. Each method returns an `EfrisResponse`; call `.raise_for_error()` to
convert URA failures into typed `EfrisError` exceptions.

Usage:

    client = EfrisClient(company="Acme Ltd", doc=sales_invoice)
    resp = client.upload_invoice(invoice_payload)
    resp.raise_for_error()
    fdn = resp.data["basicInformation"]["invoiceNo"]

The string interfaceCodes (`"T130"`, etc.) stop leaking into business logic.
For interfaces not yet wrapped, use `client.call("Txxx", payload)`.
"""
from dataclasses import dataclass

from .result import EfrisResponse
from .transport import make_post


@dataclass
class EfrisClient:
    """Per-company entry point for EFRIS calls.

    `doc` is optional and only used to set `reference_doc_type` /
    `reference_document` on the audit log row. Pass it when the call is made
    on behalf of a Frappe document so the log row links back.
    """

    company: str
    doc: object | None = None

    # ---- Generic escape hatch for unmapped interfaces ---------------------

    def call(self, interface_code: str, content) -> EfrisResponse:
        return make_post(
            interfaceCode=interface_code,
            content=content,
            company_name=self.company,
            reference_doc_type=getattr(self.doc, "doctype", None),
            reference_document=getattr(self.doc, "name", None),
        )

    # ---- Goods / Items ----------------------------------------------------

    def upload_goods(self, goods_payload) -> EfrisResponse:
        """T130 — upload or update goods/items."""
        return self.call("T130", goods_payload)

    def query_goods(self, query) -> EfrisResponse:
        """T144 — query goods registered against the TIN."""
        return self.call("T144", query)

    # ---- Stock ------------------------------------------------------------

    def stock_in_out(self, payload) -> EfrisResponse:
        """T131 — stock in / out movements."""
        return self.call("T131", payload)

    # ---- Invoices ---------------------------------------------------------

    def upload_invoice(self, payload) -> EfrisResponse:
        """T109 — invoice / credit note upload."""
        return self.call("T109", payload)

    def cancel_invoice(self, payload) -> EfrisResponse:
        """T110 — request invoice cancellation."""
        return self.call("T110", payload)

    def confirm_cancellation(self, payload) -> EfrisResponse:
        """T111 — confirm a previously requested cancellation."""
        return self.call("T111", payload)

    # ---- Reference / lookup -----------------------------------------------

    def query_taxpayer(self, query) -> EfrisResponse:
        """T119 — query taxpayer / customer details by TIN or NIN/BRN."""
        return self.call("T119", query)

    def call_t107(self, payload) -> EfrisResponse:
        return self.call("T107", payload)

    def call_t108(self, payload) -> EfrisResponse:
        return self.call("T108", payload)

    def call_t121(self, payload) -> EfrisResponse:
        return self.call("T121", payload)
