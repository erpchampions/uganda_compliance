import frappe
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
import json
from datetime import date

@frappe.whitelist()
def stock_in_T131(doc, method):
 
    doctype = doc.get("doctype")
    efris_log_info(f"The Stock In Type is {doctype}")
    if doctype == 'Stock Entry': 
        efris_log_info(f"The {doctype} doc Number: {doc}")

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

                for data in items:
                    is_efris = data.get("is_efris")
                    efris_log_info(f"is_efris: {is_efris}")

                    
                    if is_efris:
                        item_uom = data.get("uom")
                        item_code = data.get("item_code")  # Ensure item_code is defined within this scope
                        efris_log_info(f"UOM from items table: {item_uom}")
                        efris_uom_code = frappe.db.get_value('UOM', {'uom_name': item_uom}, 'efris_uom_code') or ''
                        efris_log_info(f"Efris UOM code is: {efris_uom_code}")
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

                # Ensure 'item_code' is defined before using it
                if not goodsStockInItem:
                    efris_log_info(f"Skipping, no items found for Purchase Receipt: {reference_purchase}")
                    continue

                # Construct the EFRIS payload for the current purchase receipt
                stockin_date = doc.get("posting_date") or frappe.utils.today()
                efris_log_info(f"stockin_date: {stockin_date}")

                goods_Stock_upload_T131 = {
                    "goodsStockIn": {
                        "operationType": "101",
                        "supplierTin": tax_Id if tax_Id else "",
                        "supplierName": supplier if supplier else "",
                        "adjustType": "",
                        "remarks": doc.get("remarks") if doc.get('remarks') else "",
                        "stockInDate": stockin_date,
                        "stockInType": stockInType,
                        "productionBatchNo": "",
                        "productionDate": "",
                        "branchId": "",
                        "invoiceNo": "",
                        "isCheckBatchNo": "",
                        "rollBackIfError": "",
                        "goodsTypeCode": "101",
                    },
                    "goodsStockInItem": goodsStockInItem
                }

                # Make the post request to EFRIS for the current purchase receipt
                success, response = make_post("T131", goods_Stock_upload_T131, e_company)

                if success:
                    efris_log_info(f"Stock is successfully uploaded to EFRIS for {e_company} under Purchase Receipt {reference_purchase}")
                    frappe.msgprint(f"Stock is successfully uploaded to EFRIS for {e_company} under Purchase Receipt {reference_purchase}")
                    for item in items:
                        frappe.db.set_value('Stock Entry Detail', item.name, 'is_efris_registered', 1)
                        efris_log_info(f"The Efris Registered flag for item_code: {item.item_code} is set to true")
                else:
                    efris_log_error(f"Failed to upload Stock to EFRIS for {e_company} under Purchase Receipt {reference_purchase}: {response}")
                    frappe.throw(f"Failed to upload Stock to EFRIS for {e_company} under Purchase Receipt {reference_purchase}: {response}")

    if doctype == 'Purchase Receipt': 
 
            efris_log_info(f"The {doctype} has been fetched successfully for: {doc}")
            # Get the company from the doc
            e_company = doc.get("company")
            efris_log_info(f"The Company is: {e_company}")
            e_currency = doc.get('currency')
            efris_log_info(f"The Company Currency is {e_currency}")
            is_efris_count = 0
            exchange_rate = 0.0
            item_currency = 'UGX'
            unitPrice = 0

            for efris_item in doc.get("items", []):
                is_efris = efris_item.get('is_efris')                
            
            
                if is_efris:
                    is_efris_count +=1
                    efris_log_info(f"The number of efris Items in Items table is {is_efris_count}")
            if not is_efris_count:
                efris_log_info(f"Purchase Receipt List Items are Non Efris")
                return
            # Initialize goodsStockInItem list outside the loop
            goodsStockInItem = []
            stockInType = ""
            stockInOption = doc.get("efris_stockin_type",'')
            efris_log_info(f"Stock In Type for  Purchase Receipt {doc} is {stockInOption}")
            stockInType = stockInOption.split(":")[0]
            efris_log_info(f"The Stock In type for Purchase Receipt {doc} is {stockInType}")

            for item_stock in doc.get("items", []):
                item = frappe.get_doc("Item", item_stock.get("item_code"))
                efris_log_info(f"The Item fetched is: {item.item_code}")                
                efris_log_info(f"Stock UOM from items table: {item_stock.get('uom')}")
                if item_stock.get('uom'):
                    purchase_uom_code = frappe.db.get_value('UOM',{'uom_name':item_stock.get('uom')},'efris_uom_code')
                    efris_log_info(f"Package Uom is {purchase_uom_code}")
                stock_uom_code = frappe.db.get_value('UOM', {'uom_name': item.stock_uom}, 'efris_uom_code') or ''
                efris_log_info(f"Efris UOM code is: {stock_uom_code}")
                unitPrice = item_stock.get("rate")
                is_efris_item = item.is_efris_item
                efris_log_info(f"The Item {item.item_code} 's is Efris Item State is {is_efris_item}")
                # Get the accept warehouse from the doc
                item_currency = frappe.get_value('Item',{'item_code':item_stock.item_code},'efris_currency')
                efris_log_info(f"The Item Currency is {item_currency}")
                if not e_currency == 'UGX' and item_currency != e_currency:
                    exchange_rate = float(doc.get('efris_currency_exchange_rate',0.0) or 0.0)
                    efris_log_info(f"The {e_currency} Exchange Rate to UGX is {exchange_rate}")
                    unitPrice = item_stock.get("rate",0.0)
                    unit_price_in_ugx = float(unitPrice) * exchange_rate
                    efris_log_info(f"Unit Price is {e_currency} is :{unitPrice}")
                else:
                    unit_price_in_ugx = unitPrice

                accept_warehouse = item_stock.get("warehouse")
                efris_log_info(f"The Accept Warehouse is: {accept_warehouse}")
                if is_efris_item:
                    is_efris = item_stock.get("is_efris")
                    efris_log_info(f"The Item added to the table is efris")

                    if is_efris:
                        efris_log_info(f"The warehouse '{accept_warehouse}' is not a Bonded Warehouse. Proceeding with the function.")
                        
                    
                        goodsStockInItem.append(
                            {
                                "commodityGoodsId": "",
                                "goodsCode": item_stock.get("item_code"),
                                "measureUnit": purchase_uom_code ,
                                "quantity": item_stock.get("qty"),
                                "unitPrice": round(unit_price_in_ugx,0) ,
                                "remarks": item_stock.get("remarks") if item_stock.get('remarks') else "",
                                "fuelTankId": "",
                                "lossQuantity": "",
                                "originalQuantity": "",
                            }
                        )
                        efris_log_info(f"Item {item.item_code} added to goodsStockInItem. Total items: {len(goodsStockInItem)}")

                    else:
                        efris_log_info(f"The warehouse '{accept_warehouse}' is a Bonded Wahrehouse. Skipping this item.")
                        
                else:
                    efris_log_info(f"The Item '{item.item_code}' is a non efris Item. Skipping this item.")
                    

            if not goodsStockInItem:
                efris_log_info("No items to process for EFRIS stock-in.")
                return

            goods_Stock_upload_T131 = {
                "goodsStockIn": {
                    "operationType": "101",
                    "supplierTin": doc.get("supplier_tin") if doc.get('supplier_tin') else "",
                    "supplierName": doc.get("supplier_name"),
                    "adjustType": "",
                    "remarks": doc.get("remarks") if doc.get('remarks') else "",
                    "stockInDate": doc.get("posting_date"),
                    "stockInType": stockInType,
                    "productionBatchNo": "",
                    "productionDate": "",
                    "branchId": doc.get("branch_id") if doc.get('branch_id') else "",
                    "invoiceNo": "",
                    "isCheckBatchNo": "",
                    "rollBackIfError": "",
                    "goodsTypeCode": "101",
                },
                "goodsStockInItem": goodsStockInItem
            }



            # Make the post request to EFRIS
            success, response = make_post("T131", goods_Stock_upload_T131, e_company)

            if success:
                efris_log_info(f"Stock is successfully uploaded to EFRIS for {e_company}")
                frappe.msgprint(f"Stock is successfully uploaded to EFRIS for {e_company}")
                for item in doc.items:
                    if item.is_efris == 1:
                        frappe.db.set_value('Purchase Receipt Item', item.name, 'is_efris_registered', 1)
                        efris_log_info(f"The Efris Registered flag for :{item.item_code} is set to true")
                    else:
                        efris_log_info(f"The is efris flag for :{item.item_code} is not updated:{item.is_efris_registered}")
                
            else:
                efris_log_error(f"Failed to upload Stock to EFRIS for {e_company}: {response}")
                frappe.throw(f"Failed to upload Stock to EFRIS for {e_company}: {response}")

    if doctype == 'Stock Reconciliation':
    
        efris_log_info(f"The {doctype} has been fetched successfully: {doc}")
        purpose = doc.get("purpose")
        efris_log_info(f"The Selected Stock Reconciliation Purpose is {purpose}")
        is_efris_count = 0
        for efris_item in doc.get("items", []):
            is_efris = efris_item.get('is_efris')
            if is_efris:
                is_efris_count +=1
                efris_log_info(f"The number of efris Items in Items table is {is_efris_count}")
        if not is_efris_count:
            efris_log_info(f"Purchase Receipt List Items are Non Efris")
            return

        # Get the company from the doc
        e_company = doc.get("company")
        efris_log_info(f"The Company is: {e_company}")

        # Initialize the dictionary to group items
        items_map = {}

        for item_stock in doc.get("items", []):
            if purpose == "Opening Stock":
                # Group by efris_purchase_receipt_no and adjustment_type for Opening Stock
                key = (item_stock.get("efris_purchase_receipt_no"))
            elif purpose == "Stock Reconciliation":
                # Group by adjustment_type only for Stock Reconciliation
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

            for item_stock in items:
                adjustment_type = item_stock.adjustment_type
                efris_log_info(f"The Adjustment type is: {adjustment_type}")
                adjustment_code = adjustment_type.split(":")[0]
                
                quantity_variance = str(round(abs(item_stock.quantity_difference),3))
                efris_log_info(f"The Stock Adjustment variance is: {quantity_variance}")
                remark = item_stock.get("remarks")
                efris_log_info(f"The Adjustment Remark is: {remark}")

                is_efris = item_stock.get("is_efris")
                efris_log_info(f"The Item added to the table is EFRIS relevant: {is_efris}")

                if is_efris:
                    item = frappe.get_doc("Item", item_stock.get("item_code"))
                    standard_rate = item.standard_rate or 0
                    efris_log_info(f"The Item fetched is: {item.item_code}")
                    uom_code = frappe.db.get_value('UOM', {'uom_name': item.stock_uom}, 'efris_uom_code') or ''
                    efris_log_info(f"EFRIS UOM code is: {uom_code}")
                    accept_warehouse = item_stock.get("warehouse")
                    efris_log_info(f"The Accept Warehouse is: {accept_warehouse}")
                    if purpose == "Opening Stock":
                        # Fetch purchase receipt details
                        efris_log_info(f"The target Purchase Receipt is: {key}")                
                        purchase_rec = frappe.get_doc("Purchase Receipt", key)
                        supplier = purchase_rec.supplier_name
                        stockIntype = purchase_rec.efris_stockin_type.split(":")[0]
                        efris_log_info(f"The Efris Stock In Type for {purchase_rec} is {stockIntype}")
                        efris_log_info(f"The supplier name is: {supplier}")
                        tax_Id = frappe.db.get_value("Supplier", {'supplier_name': supplier}, "tax_id")

                    # Skip positive adjustments for Stock Reconciliation
                    if purpose == "Stock Reconciliation" and item_stock.quantity_difference > 0:
                        frappe.msgprint(f"EFRIS cannot adjust positive stock: {item_stock.item_code}. {item_stock.quantity_difference}")
                        efris_log_error(f"EFRIS cannot adjust positive stock: {item_stock.item_code}, {item_stock.quantity_difference}")
                        continue

                    goodsStockInItem.append(
                        {
                            "commodityGoodsId": "",
                            "goodsCode": item_stock.get("item_code"),
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

            if not goodsStockInItem:
                efris_log_info("No items to process for EFRIS stock-in.")
                continue

            # Construct the EFRIS payload based on the purpose
            if purpose == "Opening Stock":

                goods_Stock_Reconciliation_T131 = {
                    "goodsStockIn": {
                        "operationType": "101",
                        "supplierTin": tax_Id if tax_Id else "",
                        "supplierName": supplier,
                        "adjustType": "",
                        "remarks": remark,
                        "stockInDate": doc.get("posting_date"),
                        "stockInType": stockIntype,
                        "productionBatchNo": "",
                        "productionDate": "",
                        "branchId":  "",
                        "invoiceNo": "",
                        "isCheckBatchNo": "",
                        "rollBackIfError": "",
                        "goodsTypeCode": "101",
                    },
                    "goodsStockInItem": goodsStockInItem
                }
            elif purpose == "Stock Reconciliation":
                if not remark:
                    remark = "Stock Reconciliation"
                goods_Stock_Reconciliation_T131 = {
                    "goodsStockIn": {
                        "operationType": "102",
                        "supplierTin": "",
                        "supplierName": "",
                        "adjustType": adjustment_code,
                        "remarks": remark ,
                        "stockInDate": doc.get("posting_date"),
                        "stockInType": "",
                        "productionBatchNo": "",
                        "productionDate": "",
                        "branchId": "",
                        "invoiceNo": "",
                        "isCheckBatchNo": "",
                        "rollBackIfError": "",
                        "goodsTypeCode": "101",
                    },
                    "goodsStockInItem": goodsStockInItem
                }

            # Make the post request to EFRIS for the current group
            success, response = make_post("T131", goods_Stock_Reconciliation_T131, e_company)

            if success:
                efris_log_info(f"Stock is successfully uploaded to EFRIS for {e_company}")
                frappe.msgprint(f"Stock is successfully uploaded to EFRIS for {e_company}")
                for item in items:
                    frappe.db.set_value('Stock Reconciliation Item', item.name, 'is_efris_registered', 1)
                    efris_log_info(f"The EFRIS Registered flag for item: {item.item_code} is set to true")
            else:
                efris_log_error(f"Failed to upload Stock to EFRIS for {e_company} under key {key}: {response}")
                frappe.throw(f"Failed to upload Stock to EFRIS for {e_company} under key {key}: {response}")

            
            
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
            
        is_efris = item.get('is_efris')
        item_code = item.get('item_code')
        item_company = frappe.db.get_value('Item',{'item_code':item_code},'e_company')
        efris_log_info(f"The Item Company is {item_company}")
        t_warehouse = item.get('t_warehouse')
        efris_log_info(f"The Target warehouse is {t_warehouse}")
        is_efris_warehouse = frappe.db.get_value('Warehouse',{'warehouse_name':t_warehouse},'is_efris_warehouse')
        efris_log_info(f"The Target warehouse {t_warehouse} is IS EFRIS Warehouse {is_efris_warehouse}")
    
        if is_efris:
            is_efris_count +=1
            efris_log_info(f"The number of efris Items in Items table is {is_efris_count}")
    if purpose == 'Material Receipt' and not is_efris_warehouse:
        return
    if purpose == 'Material Receipt' and is_efris_warehouse:
        return
    if not is_efris_count:
        efris_log_info(f"Purchase Receipt List Items are Non Efris")
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
            
        is_efris = item.get('is_efris')
        if not is_efris:
            efris_log_info(f"The Purchase {doc.name} is non Efris")
            return
        item_code = item.get('item_code')
        item_company = frappe.db.get_value('Item',{'item_code':item_code},'e_company')
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
    efris_log_info(f"Querying EFRIS with: {exchange_rate_T121}")
    success, response = make_post("T121", exchange_rate_T121, e_company)
    if success and response:
       efris_log_info(f"Query successful, response: {response}")   
       exchange_rate_exists = frappe.get_all('Currency Exchange',filters ={
                                    'date': today,
                                    'from_currency': response.get('currency'),
                                    'to_currency' : 'UGX',
                                    'exchange_rate': response.get('rate'),
                                    'for_buying' :1,
                                    'for_selling' : 1  
                                })  
       if exchange_rate_exists:
            # If an existing exchange rate is found, update it with the new rate
            exchange_rate_doc = frappe.get_doc('Currency Exchange', exchange_rate_exists[0].name)
            exchange_rate_doc.exchange_rate = response.get('rate')
            exchange_rate_doc.save(ignore_permissions=True)
            frappe.msgprint(f"Exchange rate updated for {response.get('currency')} to {exchange_rate_doc.exchange_rate}")
       currency_exchange = frappe.get_doc({"doctype":"Currency Exchange",
                                    'date': today,
                                    'from_currency': response.get('currency'),
                                    'to_currency' : 'UGX',
                                    'exchange_rate': response.get('rate'),
                                    'for_buying' :1,
                                    'for_selling' : 1                                   
                                           
                                           })
       
       currency_exchange.insert(ignore_permissions=True)
       frappe.msgprint(f"The Exchange Rate for {response.get('currency')} is created {currency_exchange.name}")
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


