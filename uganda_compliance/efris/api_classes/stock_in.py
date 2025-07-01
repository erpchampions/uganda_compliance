import frappe
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
import json
from datetime import date

@frappe.whitelist()
def get_efris_unit_price(purchase_receipt_no, item_code):
    """
    Securely fetch efris_unit_price and efris_currency from Purchase Receipt Item.
    """
    if not purchase_receipt_no or not item_code:
        frappe.throw("Both Purchase Receipt No and Item Code are required.")

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

@frappe.whitelist()
def stock_in_T131(doc, method):

    doctype = doc.get("doctype")
    efris_log_info(f"The Stock In Type is {doctype}")
    # Removed direct submssion to EFRIS for stock-entry.   
    if doctype=="Stock Reconciliation":
        send_stock_reconciliation(doc)
    if doctype=="Purchase Receipt":
        send_purchase_receipt(doc)

@frappe.whitelist()
def send_stock_entry(doc):
    # If doc is a stringified JSON (sometimes happens), convert to dict
    if isinstance(doc, str):
        doc = json.loads(doc)
    # Convert dict to Frappe Document
    if isinstance(doc, dict):
        doc = frappe.get_doc(doc) 

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
    is_efris_count = 0
    for efris_item in doc.get("items", []):
        is_efris = efris_item.get('efris_reconcilliation')
        if is_efris:
            is_efris_count +=1
            efris_log_info(f"The number of efris Items in Items table is {is_efris_count}")
    if not is_efris_count:
        efris_log_info(f"Purchase Receipt List Items are Non EFRIS")
        return

    e_company = doc.get("company")
    efris_log_info(f"The Company is: {e_company}")
    # Initialize the dictionary to group items
    items_map = {}

    for item_stock in doc.get("items", []):
        if purpose == "Opening Stock":
            key = doc.name 
        elif purpose == "Stock Reconciliation":
            key = (item_stock.get("adjustment_type"))

        if key not in items_map:
            items_map[key] = []
        items_map[key].append(item_stock)

    # Process each group of items based on the grouping key
    for key, items in items_map.items():
        efris_log_info(f"Processing items for key: {key}")

        item_code = ""
        goodsCode = ""
        
        goodsStockInItem, adjustment_code, supplier,tax_Id, stockIntype, remark = goods_stock_recon_item(items, purpose)
        
        # Construct the EFRIS payload based on the purpose
        if purpose == "Opening Stock":
            supplierTin=tax_Id if tax_Id else ""
            goods_Stock_Reconciliation_T131 = goods_Stock_T131_data("101", "", remark,doc.get("posting_date"), stockIntype, "", "", "", "", "", "", "101", goodsStockInItem, supplier, supplierTin)
        
        elif purpose == "Stock Reconciliation":
            if not remark:
                remark = "Stock Reconciliation"
            
            goods_Stock_Reconciliation_T131 = goods_Stock_T131_data("102", adjustment_code, remark,doc.get("posting_date"), "", "", "", "", "", "", "", "101", goodsStockInItem)

        # Make the post request to EFRIS for the current group
        success, response = make_post(interfaceCode="T131", content=goods_Stock_Reconciliation_T131, company_name=e_company, reference_doc_type=doc.doctype, reference_document=doc.name)
        child_table="Stock Reconciliation Item"
        handle_response(success,child_table, response, items, e_company, key)
        

def goods_stock_recon_item(items, purpose):
    goodsStockInItem = []
    adjustment_code = ""
    supplier = ""
    tax_Id = ""
    remark = ""
    stockIntype = "101"
    item_code = ""
    goodsCode = ""
    for item_stock in items:
        adjustment_type = item_stock.efris_adjustment_type
        adjustment_code = adjustment_type.split(":")[0]
        
        quantity_variance = str(round(abs(item_stock.quantity_difference),3))
        remark = item_stock.get("efris_remarks")

        is_efris = item_stock.get("efris_reconcilliation")
        supplier=""
        if is_efris:
            item = frappe.get_doc("Item", item_stock.get("item_code"))
            standard_rate = item.standard_rate or 0
            item_code = item.item_code
            goodsCode = item.efris_product_code
            if goodsCode: 
                item_code = goodsCode
            uom_code = frappe.db.get_value('UOM', {'uom_name': item.stock_uom}, 'efris_uom_code') or ''
            accept_warehouse = item_stock.get("warehouse")
            if purpose == "Opening Stock":
                # Fetch purchase receipt details
                supplier = "Opening Balance"
                stockIntype = "102"                        
                tax_Id = ""

            # Skip positive adjustments for Stock Reconciliation
            if purpose == "Stock Reconciliation" and item_stock.quantity_difference > 0:
                frappe.msgprint(f"EFRIS cannot adjust positive stock: {item_code}. {item_stock.quantity_difference}")
                efris_log_error(f"EFRIS cannot adjust positive stock: {item_code}, {item_stock.quantity_difference}")
                continue
            goodsStockInItem.append(
                {
                    "commodityGoodsId": "",
                    "goodsCode": item_code,
                    "measureUnit": uom_code,
                    "quantity": quantity_variance,
                    "unitPrice": str(standard_rate),
                    "remarks": remark if remark else "adjustment",
                    "fuelTankId": "",
                    "lossQuantity": "",
                    "originalQuantity": "",
                }
            )
            efris_log_info(f"Item {item.item_code} added to goodsStockInItem. Total items: {len(goodsStockInItem)}")
        else:
            efris_log_info(f"Item not relevant for EFRIS. Skipping this item.")
            continue
    return goodsStockInItem, adjustment_code, supplier,tax_Id, stockIntype, remark

def send_purchase_receipt(doc):
        e_company = doc.get("company")     
      
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

        # Make the post request to EFRIS
        success, response = make_post(interfaceCode="T131", content=goods_Stock_upload_T131, company_name=e_company, reference_doc_type=doc.doctype, reference_document=doc.name)
        handle_response(success,"Purchase Receipt Item", response, doc.items, e_company, doc.name)

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


def handle_response(success,child_table, response, items, e_company, key):
    if success:
        efris_log_info(f"Stock is successfully uploaded to EFRIS for {e_company}")
        frappe.msgprint(f"Stock is successfully uploaded to EFRIS for {e_company}")

        for item in items:
            frappe.db.set_value(child_table, item.name, 'efris_registered', 1)

        # Update parent document's efris_posted if the field exists
        doctype = frappe.get_value(child_table, items[0].name, 'parenttype')
        docname = frappe.get_value(child_table, items[0].name, 'parent')

        if doctype == 'Stock Entry' and docname:
            stock_entry_doc = frappe.get_doc(doctype, docname)

            if hasattr(stock_entry_doc, 'efris_posted'):
                item_details = stock_entry_doc.get('items', [])
                
                # Filter items that are marked for EFRIS
                efris_items = [item for item in item_details if item.get('efris_transfer') and item.get('t_warehouse')]

                # Check if ALL EFRIS items are registered
                if efris_items and all(item.get('efris_registered') for item in efris_items):
                    frappe.db.set_value(doctype, docname, 'efris_posted', 1)
                    efris_log_info(f"Stock Entry {docname} marked as posted to EFRIS.")
                stock_entry_doc.reload()

    else:
        error_message = f"Failed to upload Stock to EFRIS for {e_company} under key {key}: {response}"
        frappe.log_error(error_message)
        efris_log_error(error_message)
        frappe.throw(error_message)

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


@frappe.whitelist()
def before_submit_on_stock_entry(doc, method):
    frappe.log_error(f"Before Save is Called on Stock Entry: {doc}")
    
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
        if purpose == 'Manufacture':
            has_batch_no = frappe.db.get_value('Item', {'item_code': item_code}, 'has_batch_no')
            if not has_batch_no and item.get("efris_transfer") and not item.get("efris_production_batch_no"):
                frappe.throw(f"The Item {item_code} does not have Batch No enabled. Please enter the EFRIS producntion batch no.")

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
    

@frappe.whitelist()
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
    today = date.today().strftime("%Y-%m-%d")
    e_currency = doc.get('currency')
    if e_company == 'UGX':
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
    

@frappe.whitelist()
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


@frappe.whitelist()
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

@frappe.whitelist()
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
           
            frappe.log_error(f"✅ EFRIS posted for Stock Entry {doc.name}")
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