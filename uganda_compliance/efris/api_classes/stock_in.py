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
        frappe.msgprint(f"No EFRIS data found for {item_code}")
        return {}

@frappe.whitelist()
def stock_in_T131(doc, method):
    doctype = doc.get("doctype")
    efris_log_info(f"The Stock In Type is {doctype}")
    if doctype=="Stock Entry":
        stock_entry_data(doc)
    if doctype=="Stock Reconciliation":
        stock_reconciliation_date(doc)
    if doctype=="Purchase Receipt":
        purchase_receipt_data(doc)


def stock_entry_data(doc):
    ################################################
    # STOCK ENTRY
    ################################################
    # Get the company from the doc
    e_company = doc.get("company")
    efris_log_info(f"The Company is: {e_company}")

    purpose = doc.get("purpose")
    efris_log_info(f"The Stock Entry Type Selected is {purpose}")

    if purpose == "Material Transfer": 

        # Group items by reference purchase receipt number
        items_by_receipt = {}
        reference_purchase = ""
        for data in doc.get("items", []):
            
            reference_purchase = data.get("efris_purchase_receipt_no") or "" 
            
            if reference_purchase not in items_by_receipt:
                items_by_receipt[reference_purchase] = []
            items_by_receipt[reference_purchase].append(data)

        # Process each group of items based on their reference purchase receipt

        for reference_purchase, items in items_by_receipt.items():
            efris_log_info(f"Processing items for Purchase Receipt: {reference_purchase}")

            # Initialize goodsStockInItem list for the current purchase receipt
            goodsStockInItem = []
            supplier = ""
            tax_Id = ""
            stockInType = "102"
            goodsCode = ""
            item_code = ""
            for data in items:
                is_efris = data.get("efris_transfer")
                efris_log_info(f"efris_transfer: {is_efris}")

                
                if is_efris:
                    item_uom = data.get("uom")
                    item_code = data.get("item_code")  # Ensure item_code is defined within this scope
                    goodsCode = frappe.db.get_value("Item",{"item_code":item_code},"efris_product_code")
                    efris_log_info(f"EFRIS Product Code is {goodsCode}")
                    if goodsCode:
                        item_code = goodsCode
                    efris_log_info(f"UOM from items table: {item_uom}")
                    efris_uom_code = frappe.db.get_value('UOM', {'uom_name': item_uom}, 'efris_uom_code') or ''
                    efris_log_info(f"EFRIS UOM code is: {efris_uom_code}")
                    efris_unit_price = data.get("efris_unit_price")
                    #if efris_unit_price:
                    #    efris_unit_price = round(efris_unit_price,2) 

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

            # Ensure 'item_code' is defined before using it
            if not goodsStockInItem:
                efris_log_info(f"Skipping, no items found for Purchase Receipt: {reference_purchase}")
                continue

            # Construct the EFRIS payload for the current purchase receipt
            stockin_date = doc.get("posting_date") or frappe.utils.today()
            efris_log_info(f"stockin_date: {stockin_date}")

            supplierTin=tax_Id if tax_Id else ""
            remarks=doc.get("remarks") if doc.get('remarks') else ""
            stockInDate=str(stockin_date)
            supplier=supplier if supplier else ""
            goods_Stock_upload_T131 = goods_Stock_T131_data("101", "", remarks,stockInDate, stockInType, "", "", "", "", "", "", "101", goodsStockInItem, supplier, supplierTin)
            # Make the post request to EFRIS for the current purchase receipt
            success, response = make_post(interfaceCode="T131", content=goods_Stock_upload_T131, company_name=e_company, reference_doc_type=doc.doctype, reference_document=doc.name)
            
            handle_response(success,"Stock Entry Detail", response, items, e_company, reference_purchase)
            
            
def stock_reconciliation_date(doc):
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

    # Get the company from the doc
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

        # Initialize goodsStockInItem list for the current group
        goodsStockInItem = []
        adjustment_code = ""
        supplier = ""
        tax_Id = ""
        remark = ""
        stockIntype = "101"
        item_code = ""
        goodsCode = ""
        
        
        goodsStockInItem, adjustment_code, supplier,tax_Id, stockIntype, remark = goods_stock_recon_item(goodsStockInItem, items, purpose)
        
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
        

def goods_stock_recon_item(goodsStockInItem, items, purpose):
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

def purchase_receipt_data(doc):
        e_company = doc.get("company")
        e_currency = doc.get('currency')
        purchase_currency = doc.get('currency')
        is_efris_count = 0
        exchange_rate = 0.0
        item_currency = 'UGX'
        unitPrice = 0
        goodsCode = ""
        item_code = ""

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
            efris_log_info(f"The EFRIS Registered flag for item: {item.item_code} is set to true")
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
def before_save_on_stock_entry(doc, method):
    purpose = doc.get('purpose')
    efris_log_info(f"The Stock Entry Purpose is {purpose}")
    is_efris_warehouse = ''
    efris_log_info(f"The Stock Entry doc: {doc}")
    
    # Loop through items in the Stock Entry
    is_efris_count = 0
    for item in doc.get("items", []):
        efris_log_info(f"Processing item: {item.item_code}")     
            
        is_efris = item.get('efris_transfer')
        item_code = item.get('item_code')
        item_company = frappe.db.get_value('Item',{'item_code':item_code},'efris_e_company')
        efris_log_info(f"The Item Company is {item_company}")
        t_warehouse = item.get('t_warehouse')
        efris_log_info(f"The Target warehouse is {t_warehouse}")
        is_efris_warehouse = frappe.db.get_value('Warehouse',{'warehouse_name':t_warehouse},'efris_warehouse')
        efris_log_info(f"The Target warehouse {t_warehouse} is IS EFRIS Warehouse {is_efris_warehouse}")
    
        if is_efris:
            is_efris_count +=1
            efris_log_info(f"The number of efris Items in Items table is {is_efris_count}")
    if purpose == 'Material Receipt' and not is_efris_warehouse:
        return
    if purpose == 'Material Receipt' and is_efris_warehouse:
        return
    if not is_efris_count:
        efris_log_info(f"Purchase Receipt List Items are Non EFRIS")
        return        
    # Fetch the corresponding Purchase Receipt based on the item.efris_purchase_receipt_no
    if item.efris_purchase_receipt_no:
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
        else:
            efris_log_info(f"Purchase Receipt not found for {item.efris_purchase_receipt_no}")
    else:
        efris_log_info(f"No Purchase Receipt linked for item {item.item_code}")
    if not item.efris_purchase_receipt_no:
        frappe.throw(f"The Purchase Receipt Reference No field Can't be Empty For EFRIS Material Transfer")


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
    efris_log_info(f"query_currency_exchange_rate called with doc: {doc}")
    e_company = doc.get('company')
    efris_log_info(f"The Company is {e_company}")
    today = date.today().strftime("%Y-%m-%d")
    e_currency = doc.get('currency')
    if e_company == 'UGX':
        efris_log_info(f"The Currency is Default {e_company}")
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
       #TODO: update the Curency Exchange Rate in the system based on a setting/ check field
    #    exchange_rate_exists = frappe.get_all('Currency Exchange',filters ={
    #                                 'date': today,
    #                                 'from_currency': response.get('currency'),
    #                                 'to_currency' : 'UGX',
    #                                 'exchange_rate': response.get('rate'),
    #                                 'for_buying' :1,
    #                                 'for_selling' : 1  
    #                             })  
       #if not exchange_rate_exists:
            # If an existing exchange rate is found, update it with the new rate
            #exchange_rate_doc = frappe.get_doc('Currency Exchange', exchange_rate_exists[0].name)
            #exchange_rate_doc.exchange_rate = response.get('rate')
            #exchange_rate_doc.save(ignore_permissions=True)
            #frappe.msgprint(f"Exchange rate updated for {response.get('currency')} to {exchange_rate_doc.exchange_rate}")
       #else:
            # currency_exchange = frappe.get_doc({"doctype":"Currency Exchange",
            #                             'date': today,
            #                             'from_currency': response.get('currency'),
            #                             'to_currency' : 'UGX',
            #                             'exchange_rate': response.get('rate'),
            #                             'for_buying' :1,
            #                             'for_selling' : 1                                   
                                            
            #                                 })
       
            #currency_exchange.insert(ignore_permissions=True)
            #frappe.msgprint(f"The Exchange Rate for {response.get('currency')} is created {currency_exchange.name}")
        
       return response  # Assuming response contains information if item exists
    
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
            # Check if purchase_uom exists in uoms_detail
            uom_exists = any(row.uom == purchase_uom for row in uoms_detail)
            
            if not uom_exists:
                frappe.throw(f"The Purchase UOM ({purchase_uom}) must be in the Item's UOMs list for item {item_code}.")


