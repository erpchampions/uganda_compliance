import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import get_e_company_settings, make_post
import json
from datetime import date

# Only the functions marked @frappe.whitelist() below are browser APIs. Each checks the user's
# permission first and loads documents by name. The doc_event and scheduler functions in this
# module are not whitelisted: they send stock to URA for whatever document they are given.


@frappe.whitelist()
def get_efris_unit_price(purchase_receipt_no, item_code):
    """
    Securely fetch efris_unit_price and efris_currency from Purchase Receipt Item.
    """
    if not purchase_receipt_no or not item_code:
        frappe.throw("Both Purchase Receipt No and Item Code are required.")
    frappe.has_permission("Purchase Receipt", "read", purchase_receipt_no, throw=True)

    result = frappe.db.get_value(
        'Purchase Receipt Item',
        {'parent': purchase_receipt_no, 'item_code': item_code},
        ['efris_unit_price', 'efris_currency']
    )

    if result:
        return {
            'efris_unit_price': result[0],
            'efris_currency': result[1]
        }
    else:
        frappe.msgprint(f"No EFRIS Unit price found for {item_code}")
        return {}

def stock_in_T131(doc, method):
    # Purchase Receipt / Stock Reconciliation on_submit: a company without enabled E Invoicing
    # Settings sends nothing (get_e_company_settings throws for it, which failed every submit)
    if not frappe.db.get_value("E Invoicing Settings", {"company": doc.get("company"), "enabled": 1}):
        return
    auto_send_submitted_invoice = get_e_company_settings(doc.get("company")).auto_send_submitted_invoice    
    if (auto_send_submitted_invoice == 1) or (method == 'manual_submit'):
        doctype = doc.get("doctype")
        efris_log_info(f"The Stock In Type is {doctype}")
        # Removed direct submssion to EFRIS for stock-entry.   
        if doctype=="Stock Reconciliation":
            send_stock_reconciliation(doc)
        if doctype=="Purchase Receipt":
            send_purchase_receipt(doc)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=60)
def submit_stock_in(doctype, name):
    """Desk "Submit To EFRIS" on a submitted Purchase Receipt, Stock Reconciliation or Stock Entry.

    Replaces calling send_purchase_receipt / send_stock_entry from the browser, which sent any
    document (or, for Stock Entry, a document dict built by the caller) to URA without a
    permission check. The user needs submit permission on the document."""
    if doctype not in STOCK_IN_SENDERS:
        frappe.throw(_("{0} is not sent to EFRIS as a stock-in").format(doctype))
    frappe.has_permission(doctype, "submit", name, throw=True)
    doc = frappe.get_doc(doctype, name)
    if doc.docstatus != 1:
        frappe.throw(_("Only submitted documents are sent to EFRIS"))
    if not frappe.db.get_value("E Invoicing Settings", {"company": doc.company, "enabled": 1}):
        frappe.throw(_("E Invoicing is not enabled for company {0}").format(doc.company))
    STOCK_IN_SENDERS[doctype](doc)
    return True


def send_stock_entry(doc):
    if doc.get("efris_posted"):
        efris_log_info(f"Stock Entry {doc.name} is already at EFRIS")
        return
    e_company = doc.get("company") or ""
    efris_log_info(f"The Company is: {e_company}")
    purpose = doc.get("purpose")
    items = doc.get("items", [])
    if not items:
        efris_log_info(f"No items found in Stock Entry: {doc.name}")
        return
    if purpose not in ["Manufacture", "Material Transfer"]:
        efris_log_info(f"Skipping EFRIS processing for Material Transfer for Manufacture purpose.")
        return    
    details = get_stock_entry_item_type(items) or {}
    
    stock_in_type = details.get("type")

    efris_log_info(f"EFRIS Stock-in Type: {stock_in_type}")
    
    if not details:
        efris_log_info(f"No EFRIS details found in Stock Entry: {doc.name}")
        return
    
    if purpose == "Material Transfer" and stock_in_type == "purchase": 

        # Group items by reference purchase receipt number
        items_by_receipt = {}
      
        for data in doc.get("items", []):
            if data.get("efris_registered"):
                # sent by an earlier attempt whose other groups failed
                continue
            reference_purchase = data.get("efris_purchase_receipt_no") or "" 
            
            if reference_purchase not in items_by_receipt:
                items_by_receipt[reference_purchase] = []
            items_by_receipt[reference_purchase].append(data)

        # Process each group of items based on their reference purchase receipt
        for reference_purchase, items in items_by_receipt.items():
            efris_log_info(f"Processing items for Purchase Receipt: {reference_purchase}")

            goodsStockInItem, supplier, tax_Id, stockInType = stock_entry_item_data(items, reference_purchase)

            if not goodsStockInItem:
                efris_log_info(f"Skipping, no items found for Purchase Receipt: {reference_purchase}")
                continue

            # Construct the EFRIS payload for the current purchase receipt
            stockin_date = doc.get("posting_date") or frappe.utils.today()
            supplierTin=tax_Id if tax_Id else ""
            remarks=doc.get("remarks") if doc.get('remarks') else ""
            stockInDate=str(stockin_date)
            supplier=supplier if supplier else ""
            goods_Stock_upload_T131 = goods_Stock_T131_data("101", "", remarks,stockInDate, stockInType, "", "", "", "", "", "", "101", goodsStockInItem, supplier, supplierTin)

            success, response = make_post(interfaceCode="T131", content=goods_Stock_upload_T131, company_name=e_company, reference_doc_type=doc.doctype, reference_document=doc.name)
            handle_response(success,"Stock Entry Detail", response, items, e_company, reference_purchase)

    if (purpose == "Manufacture" or purpose == "Material Transfer") and stock_in_type == "manufacture":
        efris_log_info(f"Processing Stock Entry for Manufacture: {doc.name}")        
        items = doc.get("items", [])
       # Group items by batch  number
        items_by_batch = {}
        for data in doc.get("items", []):
            if not data.get("efris_transfer"):
                efris_log_info(f"Item {data.get('item_code')} is not marked for EFRIS transfer. Skipping.")
                continue
            is_efris_sent = data.get("efris_registered")
            if not data.get("t_warehouse") and not data.get("efris_production_batch_no"):
                efris_log_info(f"Item {data.get('item_code')} is not marked for EFRIS transfer. Skipping.")
                continue
            if is_efris_sent:
                efris_log_info(f"Item {data.get('item_code')} is already sent to  EFRIS,  Skipping.")
                continue 
            if not data.get("efris_production_batch_no"):  
                batch_no = data.get("batch_no") or get_serial_batch_no(data.get("serial_and_batch_bundle")) 
                if not batch_no and data.get("t_warehouse"):
                    frappe.throw(f"Batch number is required for EFRIS transfer for item {data.get('item_code')}. Please ensure the batch number is set.")    
            else:
                batch_no = data.get("efris_production_batch_no")
            # Set efris_production_batch_no on the actual child doc
            for row in doc.items:
                if row.name == data.get("name") and not row.get("efris_production_batch_no"):
                    row.efris_production_batch_no = batch_no
                    row.db_set("efris_production_batch_no", batch_no)

            # Now use batch_no for grouping
            if batch_no not in items_by_batch:
                items_by_batch[batch_no] = []
            items_by_batch[batch_no].append(data)            

            # Process each group of items based on their batch number
        for batch_no, items in items_by_batch.items():
            efris_log_info(f"Processing items for Batch or EFRIS Production Batch No: {batch_no}")        
            productionBatchNo = batch_no
            productionDate = str(doc.get("posting_date")) or frappe.utils.today()
            efris_log_info(f"Production Batch No: {productionBatchNo}, Production Date: {productionDate}")
            goodsStockInItem = stock_entry_item_data(items, None)[0]  # Get the first item from the list
       
            if not goodsStockInItem:
                efris_log_info(f"No EFRIS items found in Manufacture Stock Entry: {doc.name}")
                return

            stockInDate=str(doc.get("posting_date"))
            remarks=doc.get("remarks") if doc.get('remarks') else f"{doc.get('work_order')} Stock Entry"
            branchId=doc.get("branch_id") if doc.get('branch_id') else ""
            goods_Stock_upload_T131 = goods_Stock_T131_data("101", "", remarks,stockInDate, "103", productionBatchNo, productionDate, branchId, "", "", "", "101", goodsStockInItem)

            success, response = make_post(interfaceCode="T131", content=goods_Stock_upload_T131, company_name=e_company, reference_doc_type=doc.doctype, reference_document=doc.name)
            handle_response(success,"Stock Entry Detail", response, items, e_company, doc.name)
        

              
def stock_entry_item_data(items, reference_purchase):
    goodsStockInItem = []
    supplier = ""
    tax_Id = ""
    stockInType = "102"
    goodsCode = ""
    item_code = ""
    for data in items:
        is_efris = data.get("efris_transfer")
        if not is_efris:
            efris_log_info(f"Item {data.get('item_code')} is not marked for EFRIS transfer. Skipping.")
            continue    
         
        if is_efris:
            item_uom = data.get("uom")
            item_code = data.get("item_code")  # Ensure item_code is defined within this scope
            goodsCode = frappe.db.get_value("Item",{"item_code":item_code},"efris_product_code")
            if goodsCode:
                item_code = goodsCode
            efris_uom_code = frappe.db.get_value('UOM', {'uom_name': item_uom}, 'efris_uom_code') or ''
            efris_unit_price = data.get("efris_unit_price")
            if efris_unit_price:
               efris_unit_price = round(efris_unit_price,2) 

            # Fetch purchase receipt details
            if reference_purchase:                       
                efris_log_info(f"The target Purchase Receipt is: {reference_purchase}")
                purchase_rec = frappe.get_doc("Purchase Receipt", reference_purchase)
                supplier = purchase_rec.supplier_name
                efris_log_info(f"The supplier name is: {supplier}")
                stockInType = purchase_rec.efris_stockin_type.split(":")[0]
                efris_log_info(f"The Stock In type for {purchase_rec} is {stockInType}")
                
                tax_Id = frappe.db.get_value("Supplier", {'supplier_name': supplier}, "tax_id")
            
            goodsStockInItem.append(
                {
                    "commodityGoodsId": "",
                    "goodsCode": item_code,
                    "measureUnit": efris_uom_code,
                    "quantity": data.get("qty"),
                    "unitPrice": efris_unit_price,
                    "remarks": data.get("remarks") if data.get('remarks') else "",
                    "fuelTankId": "",
                    "lossQuantity": "",
                    "originalQuantity": "",
                }
            )
            efris_log_info(f"Total items to be processed: {len(goodsStockInItem)}")
            
    return goodsStockInItem, supplier, tax_Id, stockInType


def send_stock_reconciliation(doc):
    purpose = doc.get("purpose")
    efris_log_info(f"The Selected Stock Reconciliation Purpose is {purpose}")
    if purpose not in ("Opening Stock", "Stock Reconciliation"):
        return
    # rows sent by an earlier attempt (Submit To EFRIS after a partial failure) are skipped
    rows = [d for d in doc.get("items", []) if d.get("efris_reconcilliation") and not d.get("efris_registered")]
    if not rows:
        efris_log_info(f"Stock Reconciliation {doc.name} has no EFRIS lines to send")
        return

    # Opening Stock is one stock-in. A count is one T131 per adjustment reason, since URA takes
    # one adjustType per request. (The rows used to be grouped on `adjustment_type`, a field
    # that does not exist, so every reason went in one request under the last row's reason.)
    groups = {}
    for row in rows:
        key = doc.name if purpose == "Opening Stock" else row.get("efris_adjustment_type")
        if not key:
            frappe.throw(_("Row {0}: select the EFRIS Adjustment Type").format(row.idx))
        groups.setdefault(key, []).append(row)

    stock_in_date = str(doc.get("posting_date"))
    for key, items in groups.items():
        efris_log_info(f"Processing items for key: {key}")
        goods, sent_rows = goods_stock_recon_item(items, purpose)
        if not goods:
            continue
        remark = "; ".join(dict.fromkeys(r.get("efris_remarks") for r in sent_rows if r.get("efris_remarks")))
        if purpose == "Opening Stock":
            content = goods_Stock_T131_data("101", "", remark, stock_in_date, "102", "", "", "", "", "", "", "101", goods, "Opening Balance", "")
        else:
            content = goods_Stock_T131_data("102", key.split(":")[0], remark or "Stock Reconciliation", stock_in_date, "", "", "", "", "", "", "", "101", goods)
        _send_t131(doc, content, "Stock Reconciliation Item", sent_rows, key)


def goods_stock_recon_item(items, purpose):
    """``(goods, rows)``: the T131 lines of these rows and the rows they came from. A count
    sends decreases only (URA's stock adjustment cannot add stock)."""
    goods, sent_rows = [], []
    for item_stock in items:
        item = frappe.get_doc("Item", item_stock.get("item_code"))
        item_code = item.efris_product_code or item.item_code
        if purpose == "Stock Reconciliation" and item_stock.quantity_difference > 0:
            frappe.msgprint(f"EFRIS cannot adjust positive stock: {item_code}. {item_stock.quantity_difference}")
            efris_log_error(f"EFRIS cannot adjust positive stock: {item_code}, {item_stock.quantity_difference}")
            continue
        uom_code = frappe.db.get_value('UOM', {'uom_name': item.stock_uom}, 'efris_uom_code') or ''
        goods.append(
            {
                "commodityGoodsId": "",
                "goodsCode": item_code,
                "measureUnit": uom_code,
                "quantity": str(round(abs(item_stock.quantity_difference), 3)),
                "unitPrice": str(item.standard_rate or 0),
                "remarks": item_stock.get("efris_remarks") or "adjustment",
                "fuelTankId": "",
                "lossQuantity": "",
                "originalQuantity": "",
            }
        )
        sent_rows.append(item_stock)
        efris_log_info(f"Item {item.item_code} added to goodsStockInItem. Total items: {len(goods)}")
    return goods, sent_rows

def send_purchase_receipt(doc):
    if doc.get("efris_submitted"):
        efris_log_info(f"Purchase Receipt {doc.name} is already at EFRIS")
        return
    is_efris_count = 0  

    items = doc.get("items", [])
    for efris_item in doc.get("items", []):
        is_efris = efris_item.get('efris_receipt')                
    
        if is_efris:
            is_efris_count +=1
    if not is_efris_count:
        return
    # Initialize goodsStockInItem list outside the loop
    goodsStockInItem = []
    stockInType = ""
    stockInOption = doc.get("efris_stockin_type",'')
    efris_log_info(f"Stock In Type for  Purchase Receipt {doc} is {stockInOption}")
    stockInType = stockInOption.split(":")[0]
    efris_log_info(f"The Stock In type for Purchase Receipt {doc} is {stockInType}")
    goodsStockInItem = goods_stock_in_item_data(goodsStockInItem, items)
    
    if not goodsStockInItem:
        efris_log_info("No items to process for EFRIS stock-in.")
        return

    supplier_Tin=doc.get("supplier_tin") if doc.get('supplier_tin') else ""
    supplier=doc.get("supplier_name")
    stockInDate=str(doc.get("posting_date"))
    remarks=doc.get("remarks") if doc.get('remarks') else ""
    branchId=doc.get("branch_id") if doc.get('branch_id') else ""
    goods_Stock_upload_T131 = goods_Stock_T131_data("101", "", remarks,stockInDate, stockInType, "", "", branchId, "", "", "", "101", goodsStockInItem, supplier, supplier_Tin)

    _send_t131(doc, goods_Stock_upload_T131, "Purchase Receipt Item", doc.items, doc.name)

def goods_stock_in_item_data(goodsStockInItem, items):
    for item_stock in items:
        item_master = frappe.get_doc("Item", item_stock.get("item_code"))
        if item_stock.get('uom'):
            purchase_uom_code = frappe.db.get_value('UOM',{'uom_name':item_stock.get('uom')},'efris_uom_code')
        stock_uom_code = frappe.db.get_value('UOM', {'uom_name': item_master.stock_uom}, 'efris_uom_code') or ''
        unitPrice = item_stock.get("rate")
        is_efris_item = item_master.efris_item
        item_code = item_stock.get("item_code")
        goodsCode = item_master.efris_product_code
        if goodsCode:
            item_code = goodsCode

        accept_warehouse = item_stock.get("warehouse")
        if is_efris_item:
            is_efris = item_stock.get("efris_receipt")
            unitPrice = item_stock.get("efris_unit_price",0.0)

            if is_efris:                
                goodsStockInItem.append(
                    {
                        "commodityGoodsId": "",
                        "goodsCode": item_code,
                        "measureUnit": purchase_uom_code ,
                        "quantity": item_stock.get("qty"),
                        "unitPrice": unitPrice,
                        "remarks": item_stock.get("remarks") if item_stock.get('remarks') else "",
                        "fuelTankId": "",
                        "lossQuantity": "",
                        "originalQuantity": "",
                    }
                )
                efris_log_info(f"Item {item_master.item_code} added to goodsStockInItem. Total items: {len(goodsStockInItem)}")
            else:
                efris_log_info(f"The warehouse '{accept_warehouse}' is a Bonded Wahrehouse. Skipping this item.")                
        else:
            efris_log_info(f"The Item '{item_master.item_code}' is a non efris Item. Skipping this item.")
    return goodsStockInItem


def _send_t131(doc, content, child_table, items, key):
    """Send one T131 stock-in of ``doc`` (a Purchase Receipt or Stock Reconciliation) and mark
    ``items`` sent.

    T131 runs inside the document's transaction (on_submit, after ERPNext's own on_submit has
    posted the stock and GL), so URA refusing it still stops the submit. If the transaction is
    rolled back after URA accepted it, the stock would stay at URA with no trace in ERPNext (the
    request log is written after the commit): it is then recorded outside the transaction and
    flagged, and the next attempt for the same document does not send it again."""
    if _accepted_before(doc, content):
        frappe.msgprint(
            _("URA already has this stock-in of {0} {1} from an earlier attempt that was not saved. It was not sent again.").format(
                _(doc.doctype), doc.name
            )
        )
        _mark_sent(child_table, items)
        return
    success, response = make_post(interfaceCode="T131", content=content, company_name=doc.company, reference_doc_type=doc.doctype, reference_document=doc.name)
    if success:
        _record_if_rolled_back(doc, content, response)
    handle_response(success, child_table, response, items, doc.company, key)


def _t131_lines(content):
    return json.loads(frappe.as_json(content["goodsStockInItem"]))


def _accepted_before(doc, content):
    """Whether URA accepted these lines for ``doc`` in an attempt that ERPNext rolled back.

    Only attempts since the document was created count, so a later document that reuses the
    name of one that was rolled back away is sent normally. The same request (operation and
    adjustment reason) with other lines is a mismatch the user has to resolve."""
    head = content["goodsStockIn"]
    logs = frappe.get_all(
        "E Invoice Request Log",
        filters={
            "reference_doc_type": doc.doctype,
            "reference_document": doc.name,
            "interface_code": "T131",
            "status": "Success",
            "timestamp": (">=", doc.creation),
        },
        fields=["name", "request_data"],
    )
    for log in logs:
        sent = json.loads(log.request_data or "{}")
        sent_head = sent.get("goodsStockIn") or {}
        if (sent_head.get("operationType"), sent_head.get("adjustType")) != (head["operationType"], head["adjustType"]):
            continue
        if sent.get("goodsStockInItem") == _t131_lines(content):
            return True
        frappe.throw(
            _(
                "URA already accepted a stock-in for {0} {1} with other lines, in an earlier attempt that was not saved "
                "(E Invoice Request Log {2}). Submit the lines URA has, or correct URA's stock in the EFRIS portal "
                "and then delete that log."
            ).format(_(doc.doctype), doc.name, log.name),
            title=_("EFRIS stock-in mismatch"),
        )
    return False


def _record_if_rolled_back(doc, content, response):
    doctype, name, user = doc.doctype, doc.name, frappe.session.user

    def record():
        log = frappe.get_doc(
            {
                "doctype": "E Invoice Request Log",
                "user": user,
                "request_data": frappe.as_json(content),
                "response_data": frappe.as_json(response),
                "timestamp": frappe.utils.now(),
                "reference_doc_type": doctype,
                "reference_document": name,
                "status": "Success",
                "interface_code": "T131",
            }
        )
        log.flags.ignore_links = True
        log.insert(ignore_permissions=True)
        frappe.log_error(
            title=f"EFRIS stock-in accepted by URA but {doctype} {name} was not saved"[:140],
            message=(
                f"URA accepted the T131 stock-in of {doctype} {name} (E Invoice Request Log {log.name}), "
                "then ERPNext rolled the document back, so URA's stock and ERPNext's differ.\n"
                "Submit the document again: the stock-in is not sent twice. If it will not be submitted, "
                "reverse the stock at URA.\n\n" + frappe.as_json(content)
            ),
            reference_doctype=doctype,
            reference_name=name,
        )
        # the request is over and nothing else commits after a rollback. A raw COMMIT, not
        # frappe.db.commit(), which would drop the other after-rollback callbacks still queued
        frappe.db.sql("commit")
        frappe.db.begin()

    # a commit clears this; it runs only if the transaction holding the submit is rolled back
    frappe.db.after_rollback.add(record)


def handle_response(success, child_table, response, items, e_company, key):
    if not success:
        error_message = f"Failed to upload Stock to EFRIS for {e_company} under key {key}: {response}"
        efris_log_error(error_message)
        frappe.throw(error_message)
    efris_log_info(f"Stock is successfully uploaded to EFRIS for {e_company}")
    frappe.msgprint(f"Stock is successfully uploaded to EFRIS for {e_company}")
    _mark_sent(child_table, items)


def _mark_sent(child_table, items):
    # Mark child rows as registered (used by Stock Entry etc.)
    for item in items:
        frappe.db.set_value(child_table, item.name, 'efris_registered', 1)
        item.efris_registered = 1

    # Determine parent document
    doctype = frappe.get_value(child_table, items[0].name, 'parenttype')
    docname = frappe.get_value(child_table, items[0].name, 'parent')

    if doctype and docname:
        parent_doc = frappe.get_doc(doctype, docname)

        # ---- Stock Entry logic (existing) ----
        if doctype == 'Stock Entry' and hasattr(parent_doc, 'efris_posted'):
            item_details = parent_doc.get('items', [])
            efris_items = [
                d for d in item_details
                if d.get('efris_transfer') and d.get('t_warehouse')
            ]

            if efris_items and all(d.get('efris_registered') for d in efris_items):
                frappe.db.set_value(doctype, docname, 'efris_posted', 1)
                efris_log_info(f"Stock Entry {docname} marked as posted to EFRIS.")

        # ---- Purchase Receipt logic (NEW) ----
        elif doctype == 'Purchase Receipt' and hasattr(parent_doc, 'efris_submitted'):
            frappe.db.set_value(doctype, docname, 'efris_submitted', 1)
            efris_log_info(f"Purchase Receipt {docname} marked as submitted to EFRIS.")


def goods_Stock_T131_data(operation_type, adjustment_code, remarks,stockInDate, stockInType, productionBatchNo, productionDate, branchId, invoiceNo, isCheckBatchNo, rollBackIfError, goodsTypeCode, goodsStockInItem, supplier=None, supplierTin=None):
    goods_Stock_upload_T131 = {
        "goodsStockIn": {
            "operationType": operation_type,
            "supplierTin": supplierTin,
            "supplierName": supplier,
            "adjustType": adjustment_code,
            "remarks": remarks,
            "stockInDate": stockInDate,
            "stockInType": stockInType,
            "productionBatchNo": productionBatchNo,
            "productionDate": productionDate,
            "branchId": branchId,
            "invoiceNo": invoiceNo,
            "isCheckBatchNo": isCheckBatchNo,
            "rollBackIfError": rollBackIfError,
            "goodsTypeCode": goodsTypeCode,
        },
        "goodsStockInItem": goodsStockInItem
    }
    return goods_Stock_upload_T131


def before_submit_on_stock_entry(doc, method):
    purpose = doc.get('purpose')
    efris_log_info(f"The Stock Entry Purpose is {purpose}")
    is_efris_warehouse = ''
    efris_log_info(f"The Stock Entry doc: {doc}")
    efris_currency = ''    
    purchase_company = ''  
    efris_production_batch_no =  ''
    efris_purchase_receipt_no = '' 
    item_code = '' 
    if purpose not in ['Manufacture','Material Transfer']:
        return
    
    # Loop through items in the Stock Entry    
    for item in doc.get("items", []):
        efris_log_info(f"Processing item: {item.item_code}")     
            
        is_efris = item.get('efris_transfer')
        item_code = item.get('item_code')
        item_company = frappe.db.get_value('Item',{'item_code':item_code},'efris_e_company')
        # check if item has_batch_no flag checked
        s_warehouse = item.get('s_warehouse')   
        efris_log_info(f"The Source warehouse is {s_warehouse}")
        t_warehouse = item.get('t_warehouse')   
        if not t_warehouse and s_warehouse:
            continue
        if purpose == 'Manufacture' or (purpose == 'Material Transfer' and not item.get('efris_purchase_receipt_no')):
            has_batch_no = frappe.db.get_value('Item', {'item_code': item_code}, 'has_batch_no')
            if not has_batch_no and item.get("efris_transfer") and not item.get("efris_production_batch_no") and purpose == 'Manufacture':
                frappe.throw(f"The Item {item_code} does not have Batch No enabled. Please enter the EFRIS production batch no.")
            elif item.get("efris_transfer") and not item.get("efris_purchase_receipt_no") and purpose == 'Material Transfer':
                frappe.throw(f"The Item {item_code} does not have Purchase Receipt No Reference. Please enter the Purchase Receipt Reference no.")
        efris_log_info(f"The Item Company is {item_company}")
        t_warehouse = item.get('t_warehouse')
        efris_log_info(f"The Target warehouse is {t_warehouse}")
        efris_production_batch_no = item.get('efris_production_batch_no') or ''
        efris_purchase_receipt_no = item.get('efris_purchase_receipt_no') or ''
        if not item.get("efris_production_batch_no") and item.get("serial_and_batch_bundle"):
            item.efris_production_batch_no = get_serial_batch_no(item.serial_and_batch_bundle)

        efris_log_info(f"The EFRIS Production Batch No is {efris_production_batch_no}")
                
        if t_warehouse:            
            warehouse = frappe.get_doc('Warehouse', t_warehouse)
            if warehouse:
                is_efris_warehouse = warehouse.get('efris_warehouse', False)
                efris_log_info(f"The Target warehouse {t_warehouse} is IS EFRIS Warehouse {is_efris_warehouse}")
    
        if not is_efris:
            efris_log_info(f"The Stock Entry {doc.name} is non EFRIS")
            continue
              
    # Fetch the corresponding Purchase Receipt based on the item.efris_purchase_receipt_no
    if efris_purchase_receipt_no:
        purchase_doc = frappe.get_doc('Purchase Receipt', item.efris_purchase_receipt_no)
        efris_log_info(f"Reference Purchase Receipt for {doc.name}: {purchase_doc.name}")        
        if purchase_doc:
            # Get efris_currency from Purchase Receipt
            efris_currency = purchase_doc.get('currency')
            efris_log_info(f"The efris currency is {efris_currency}")
            purchase_company = purchase_doc.company
            efris_log_info(f"The Purchase receipt company is {purchase_company}")
            if not item_company == purchase_company:
                frappe.throw(f"The Item E-Company Must be the same as the Purchase Receipt Company ")
            # Match item codes in both Stock Entry and Purchase Receipt
            purchase_item = next((pi for pi in purchase_doc.get('items', []) if pi.item_code == item.item_code), None)
            
            if purchase_item:
                # Set the currency and unit price for the matched item
                unit_price = purchase_item.rate
                efris_log_info(f"The efris Unit Price for {item.item_code} is {unit_price}")
                
                # Set the values for this specific item in Stock Entry
                item.efris_currency = efris_currency
                item.efris_unit_price = unit_price
            else:
                efris_log_info(f"Item {item.item_code} not found in Purchase Receipt {purchase_doc.name}")
    elif (purpose == 'Manufacture' or purpose == 'Material Transfer') and is_efris_warehouse:     
       
        item_master = frappe.get_doc('Item', item_code)        
        efris_log_info(f"Processing Manufacture Stock Entry for Item: {item_code}")
        efris_currency = item_master.get('efris_currency') or 'UGX'
        efris_log_info(f"The efris currency is {efris_currency}")           
        
        unit_price = item.basic_rate
        efris_log_info(f"The efris Unit Price for {item_code} is {unit_price}")        
        # Set the values for this specific item in Stock Entry
        item.efris_currency = efris_currency
        item.efris_unit_price = unit_price          
    else:
        efris_log_info(f"Purchase Receipt not found for {item.efris_purchase_receipt_no}")
    

def before_save_on_purchase_receipt(doc,method):
    efris_log_info(f"Before Save is Called on Purchase Receipt: {doc}") 
    
    for item in doc.get("items", []):
        efris_log_info(f"Processing item: {item.item_code}")    
            
        is_efris = item.get('efris_receipt')
        if not is_efris:
            efris_log_info(f"The Purchase {doc.name} is non EFRIS")
            return
        item_code = item.get('item_code')
        item_company = frappe.db.get_value('Item',{'item_code':item_code},'efris_e_company')
        efris_log_info(f"The Item Company is {item_company}") 
        company = doc.get('company')
        efris_log_info(f"The Purchase Receipt Company is {company}") 
        if not  item_company ==  company:
            frappe.throw(f"The Purchase Receipt Company and Item's E- Company Should Be the same") 

@frappe.whitelist()
def query_currency_exchange_rate(doc):   
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except json.JSONDecodeError:
            frappe.log_error("Failed to decode `doc` JSON string", "query_currency_exchange_rate Error")
            return {"error": "Failed to decode `doc` JSON string"}
    e_company = doc.get('company')
    # asks URA with the company's EFRIS credentials: Purchase Receipt users of that company only
    frappe.has_permission("Purchase Receipt", "create", throw=True)
    frappe.has_permission("Company", "read", e_company, throw=True)
    today = date.today().strftime("%Y-%m-%d")
    e_currency = doc.get('currency')
    if not e_currency or e_currency == 'UGX':
        # was `e_company == 'UGX'` (never true): UGX documents queried URA T121 needlessly
        return 
    efris_log_info(f"The E-currency is {e_currency}")
    exchange_rate_T121 = {
    "currency": e_currency,
    "issueDate": today
    }
    reference_doc_type = doc.get('doctype')
    reference_document = doc.get('name')
    efris_log_info(f"Querying EFRIS with: {exchange_rate_T121}")
    success, response = make_post(interfaceCode="T121", content=exchange_rate_T121, company_name=e_company, reference_doc_type=reference_doc_type, reference_document=reference_document)
    
    if success and response:
       efris_log_info(f"Query successful, response: {response}")
       
       return response 
    
    else:
        efris_log_info("Exchange Rate  not found in EFRIS.")
        return None
    

def purchase_uom_validation(doc,mehtod):
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except json.JSONDecodeError:
            frappe.log_error("Failed to decode `doc` JSON string", "purchase_uom_validation Error")
            return {"error": "Failed to decode `doc` JSON string"}
    efris_log_info(f"purchase_uom_validation called with doc: {doc}")
    
    item = doc.get('items',[])
    for data in item:
        item_code = data.item_code
        efris_log_info(f"Item Code :{item_code}")
        purchase_uom = data.uom
        efris_log_info(f"Purchase UOM on Items Child Table {purchase_uom}")
        if purchase_uom:
            items = frappe.get_doc('Item',{'item_code':item_code})
            uoms_detail = items.get('uoms',[])
            efris_log_info(f"Item UOm is {uoms_detail}")
            uom_exists = any(row.uom == purchase_uom for row in uoms_detail)
            
            if not uom_exists:
                frappe.throw(f"The Purchase UOM ({purchase_uom}) must be in the Item's UOMs list for item {item_code}.")


def get_stock_entry_item_type(items):
    """
    Determines the EFRIS stock-in type: 'purchase' or 'manufacture'.
    Throws an error if both types are present.
    """
    try:
        has_purchase = False
        has_manufacture = False

        for item in items:
            if not item.get("efris_transfer"):
                continue

            if item.get("efris_purchase_receipt_no"):
                has_purchase = True

            if item.get("efris_production_batch_no") or item.get("batch_no") or item.get("serial_and_batch_bundle") :
                has_manufacture = True        

        if has_purchase and has_manufacture:
            frappe.throw("Cannot mix purchase and manufacture items in the same EFRIS stock-in entry.")

        if has_purchase:
            return {"type": "purchase"}

        if has_manufacture:
            return {"type": "manufacture"}

        return None

    except Exception as e:
        frappe.throw(f"Error determining EFRIS stock-in type: {str(e)}")       
        

@frappe.whitelist()
def get_serial_batch_no(serial_and_batch_bundle):
    """
    Returns the first available batch_no from the 'entries' table
    of a Serial and Batch Bundle document.
    
    Args:
        serial_and_batch_bundle (str): The name of the Serial and Batch Bundle doc.

    Returns:
        str or None: The batch number, or None if not found or error occurs.
    """
    if not serial_and_batch_bundle :
        frappe.log_error("Serial and Batch Bundle name is required.", "EFRIS Batch Fetch")
        return None
    frappe.has_permission("Serial and Batch Bundle", "read", serial_and_batch_bundle, throw=True)

    try:
        doc = frappe.get_doc("Serial and Batch Bundle", serial_and_batch_bundle)
    except frappe.DoesNotExistError:
        frappe.log_error(f"Serial and Batch Bundle '{serial_and_batch_bundle}' not found.", "EFRIS Batch Fetch")
        return None
    except Exception as e:
        frappe.log_error(f"Error loading Serial and Batch Bundle '{serial_and_batch_bundle}': {e}", "EFRIS Batch Fetch")
        return None

    for entry in doc.get("entries", []):
        batch_no = entry.get("batch_no")
        if batch_no:
            frappe.logger().info(f"[EFRIS] Found batch_no: {batch_no} in bundle {serial_and_batch_bundle}")
            return batch_no

    frappe.logger().info(f"[EFRIS] No batch_no found in entries for {serial_and_batch_bundle}")
    return None

def process_pending_efris_stock_entries():
    processed_entries = []    
    stock_entries = frappe.db.sql("""
    SELECT se.*
    FROM `tabStock Entry` se
    WHERE se.docstatus = 1
    AND se.efris_posted = 0
    AND se.purpose IN ('Manufacture', 'Material Transfer')
    AND exists(select * from `tabStock Entry Detail` sed
    where sed.parent = se.name
    AND sed.efris_transfer = 1     
    ) order by se.name
    """, as_dict=True)   

    if not stock_entries:
        frappe.logger().info("No pending EFRIS Stock Entries found.")
        return processed_entries
    for entry in stock_entries:
        try:
            doc = frappe.get_doc("Stock Entry", entry.name)            
            send_stock_entry(doc)           
            doc.db_set("efris_posted", 1,True,False,True)          
           
            efris_log_info(f"EFRIS posted for Stock Entry {doc.name}")
            processed_entries.append({
                "name": doc.name,
                "posting_date": doc.posting_date,
                "efris_posted": doc.efris_posted,
                "docstatus": doc.docstatus
            })
        except Exception as e:            
            error_title = f"❌ Failed Stock Entry {entry.name}: {str(e)}"
            error_title = (error_title[:137] + "...") if len(error_title) > 140 else error_title
            frappe.log_error(title=error_title, message=frappe.get_traceback())
  
    return processed_entries

@frappe.whitelist()
def is_efris_warehouse(warehouse_name):
    if not warehouse_name:
        return False

    frappe.has_permission("Warehouse", "read", warehouse_name, throw=True)
    return bool(frappe.db.get_value("Warehouse", warehouse_name, "efris_warehouse"))


STOCK_IN_SENDERS = {
    "Purchase Receipt": send_purchase_receipt,
    "Stock Reconciliation": send_stock_reconciliation,
    "Stock Entry": send_stock_entry,
}
