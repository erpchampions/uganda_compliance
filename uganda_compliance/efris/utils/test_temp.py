import frappe

def get_private_key_for_company(company):
   
    einvoicing_settings = frappe.get_all(
        "E Company",
        fields=["parent", "tin", "private_key"],
        filters={"company_name": "EZZY COMPANY GROUP LTD", "parenttype": "E Invoicing Settings"}
    )

def main():
    print("Starting...")
    
    invoice_data = invoiceUpload_test[0]
    tin = invoice_data["sellerDetails"]["tin"]
    deviceNo = invoice_data["basicInformation"]["deviceNo"]
    businessName = invoice_data["sellerDetails"]["businessName"]
    print(f"Tin:{tin}")
    print(f"DeviceNo:{deviceNo}")
    print(f"BusinessName:{businessName}")
    private_key = get_private_key_for_company(businessName)


print(f"Main finished")



invoiceUpload_test =    [
    {
      "extend": {},
      "importServicesSeller": {},
      "airlineGoodsDetails": [
         {}
      ],
      "edcDetails": {},
      "agentEntity": {},
      "sellerDetails": {
         "tin": "1017460267",
         "ninBrn": "",
         "legalName": "EZZY COMPANY GROUP LTD",
         "businessName": "EZZY COMPANY GROUP LTD",
         "mobilePhone": "+256772095478",
         "linePhone": "",
         "emailAddress": "moki@erpchampions.com",
         "referenceNo": "EFRIS-SIV-LOC009",
         "branchId": "",
         "isCheckReferenceNo": "0",
         "branchName": "Test",
         "branchCode": ""
      },
      "basicInformation": {
         "invoiceNo": "",
         "antifakeCode": "",
         "deviceNo": "1017460267_01",
         "issuedDate": "2024-08-02 13:54:04.169890",
         "operator": "Administrator",
         "currency": "UGX",
         "oriInvoiceId": "",
         "invoiceType": "1",
         "invoiceKind": "1",
         "dataSource": "101",
         "invoiceIndustryCode": "101",
         "isBatch": "0"
      },
      "buyerDetails": {
         "buyerTin": "",
         "buyerNinBrn": "",
         "buyerPassportNum": "",
         "buyerLegalName": "Test Customer 1",
         "buyerBusinessName": "Test Customer 1",
         "buyerType": 1,
         "buyerCitizenship": "",
         "buyerSector": "",
         "buyerReferenceNo": "",
         "nonResidentFlag": 0
      },
      "buyerExtend": {
         "propertyType": "",
         "district": "",
         "municipalityCounty": "",
         "divisionSubcounty": "",
         "town": "",
         "cellVillage": "",
         "effectiveRegistrationDate": "",
         "meterStatus": ""
      },
      "goodsDetails": [
         {
            "item": "AZHAR LASER 080G A4 5RM CARTON",
            "itemCode": "AZHAR LASER 080G A4 5RM CARTON",
            "qty": "2.0",
            "unitOfMeasure": "CT",
            "unitPrice": "81522.0",
            "total": "163044.0",
            "taxRate": "0.18",
            "tax": "24871.12",
            "discountTotal": "",
            "discountTaxRate": "0.00",
            "orderNumber": "0",
            "discountFlag": "2",
            "deemedFlag": "2",
            "exciseFlag": "2",
            "categoryId": "",
            "categoryName": "",
            "goodsCategoryId": "14111601",
            "goodsCategoryName": "SVETO COPY CLASSIC ",
            "exciseRate": "",
            "exciseRule": "",
            "exciseTax": "",
            "pack": "",
            "stick": "",
            "exciseUnit": "101",
            "exciseCurrency": "UGX",
            "exciseRateName": "",
            "vatApplicableFlag": "1",
            "deemedExemptCode": "",
            "vatProjectId": "",
            "vatProjectName": ""
         }
      ],
      "taxDetails": [
         {
            "taxCategoryCode": "01",
            "netAmount": "138172.88",
            "taxRate": "0.18",
            "taxAmount": "24871.12",
            "grossAmount": "163044.0",
            "exciseUnit": "",
            "exciseCurrency": "",
            "taxRateName": ""
         }
      ],
      "summary": {
         "netAmount": "138172.88",
         "taxAmount": "24871.12",
         "grossAmount": "163044.0",
         "itemCount": "1",
         "modeCode": "1",
         "remarks": "",
         "qrCode": ""
      }
   }
]

if __name__ == "__main__":
    #setup_frappe()
    main()
    frappe.destroy()