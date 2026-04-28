"""Sales Invoice EFRIS service.

Public surface: import from this package; submodules are implementation
detail. The legacy `efris.api_classes.e_invoice` module re-exports everything
here so existing call sites keep working.
"""
from .api import EInvoiceAPI
from .build import (
    get_basic_information,
    get_buyer_details,
    get_einvoice,
    get_goods_details,
    get_import_service_seller,
    get_payment_details,
    get_summary_details,
    get_tax_details,
    validate_payment,
)
from .credit_note import (
    create_buyer_details,
    create_credit_note,
    create_goods_details,
    create_payment_details,
    create_summary,
    create_tax_details,
    fetch_fdn_details,
    get_credit_note_reason,
    get_original_invoice_details,
    handle_approved_credit_note,
    handle_rejected_credit_note,
    initialize_credit_note,
    negate_credit_note_values,
    notify_system_managers,
    update_einvoice_with_fdn_details,
    update_original_invoice_status,
    update_sales_invoice_return_status,
)
from .discounts import (
    _calculate_tax_adjustments,
    _process_items,
    _update_row_values,
    calculate_additional_discounts,
)
from .hooks import (
    Sales_invoice_is_efris_validation,
    _check_efris_items,
    _handle_efris_logic,
    _handle_sales_invoice,
    _handle_sales_return,
    _set_sales_taxes_template,
    _validate_item_uom,
    after_save_sales_invoice,
    before_save,
    cancel_irn,
    check_credit_note_approval_status,
    check_efris_flag_for_sales_invoice,
    confirm_irn_cancellation,
    generate_irn,
    on_cancel_sales_invoice,
    on_submit_sales_invoice,
    on_update_sales_invoice,
    sales_uom_validation,
    send_to_efris,
    set_efris_based_on_items,
    validate_efris_warehouse,
    validate_sales_invoice,
)
from .utils import (
    _parse_doc,
    decode_e_tax_rate,
    get_efris_product_code,
    get_order_no,
    new_credit_note_rate,
    validate_company,
)
