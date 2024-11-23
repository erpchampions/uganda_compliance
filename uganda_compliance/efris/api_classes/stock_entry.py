import frappe
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
import json

@frappe.whitelist()
def stock_in_T131(doc, method):
    efris_log_info(f"The Stock Entry doc: {doc}")

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
            
            
@frappe.whitelist()
def before_save_on_stock_entry(doc, method):
    efris_log_info(f"The Stock Entry doc: {doc}")
    
    # Loop through items in the Stock Entry
    for item in doc.get("items", []):
        efris_log_info(f"Processing item: {item.item_code}")
        
        # Fetch the corresponding Purchase Receipt based on the item.efris_purchase_receipt_no
        if item.efris_purchase_receipt_no:
            purchase_doc = frappe.get_doc('Purchase Receipt', item.efris_purchase_receipt_no)
            efris_log_info(f"Reference Purchase Receipt for {doc.name}: {purchase_doc.name}")
            
            if purchase_doc:
                # Get efris_currency from Purchase Receipt
                efris_currency = purchase_doc.get('currency')
                efris_log_info(f"The efris currency is {efris_currency}")
                
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



