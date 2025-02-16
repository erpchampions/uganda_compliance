# Uganda Compliance App for ERPNext

Uganda Compliance is a localization app for ERPNext designed to ensure compliance with Uganda's statutory requirements, focusing on **EFRIS (Electronic Fiscal Receipting and Invoicing Solution)** integration.

## **Key Features**
- Multi-company EFRIS Integration  
- Automatic Tax Template Generation  
- EFRIS Commodity Code Mapping  
- Company & Customer Synchronization with EFRIS  
- Goods & Services Synchronization with EFRIS  
- Multi-Currency & Multi-UOM Support  
- Stock-in / Stock Adjustments  
- Invoicing, including Item-level Discounts  
- Payment Mode Support (e.g. Credit, Cash, Cheque, SWIFT Transfer, Mobile Money)  
- POS Awesome Integration  
- EFRIS Sales Invoice / POS Invoice Print Formats  
- Credit Note Management  
- Request/Response Logging

---

## **System Requirements**
- **ERPNext Versions Supported:** V13, V14, V15  
- **Python Version:** 3.10  

Ensure Python 3.10 is set under **Bench Dependency** before or after creating your site.

---

## **Installation**
Run the following commands on your bench instance:

```bash
bench get-app ugandan_compliance
bench install-app ugandan_compliance
bench migrate
```

---

## **Getting Started with EFRIS: Quick Configuration Steps**

**Prerequisites**:

* Register EFRIS Device and Thumbprint in TEST-Portal. Follow documentation **Step by step guide for EFRIS device and thumbprint registration (TEST).pdf** under **Downloads** section of this page: https://efristest.ura.go.ug/efrissite/canvas/site_index
* The result should be a virtual Device Number and a Private Key file.

1. **Set up E Company**

    - Add VAT-TIN (Tax ID) and EFRIS contact Email in the Company Master.

2. **Configure E Invoicing Settings**:

    - Enable Integration.

    - Select E Company.

    - Enter URA Device No

    - Set path to Private Key file. Default mode is Sandbox.

    - Set the password of the Private Key

    - Save and Test connection. Ensure status is Green before proceeding.

    - *Optional*: Set Tax Accounts (Output VAT and Input VAT) and save. EFRIS Tax templates will be auto-created with your Tax Accounts - i.e. Sales/Purchases Tax & Charges and Item Tax Templates


For **detailed configuration and advanced setup**, refer to the full documentation below:  
👉 **[Uganda Compliance Documentation](https://github.com/erpchampions/uganda_compliance/wiki)**

---

## **Contribution**
We welcome contributions to enhance the Uganda Compliance app!  
- Fork the repository  
- Submit a Pull Request  

**Repository:** [https://github.com/erpchampions/uganda_compliance](https://github.com/erpchampions/uganda_compliance)

---

## **Support**
For assistance, contact us via:  
📧 **efris@erpchampions.com**

Include the following details in your support request:  
- **TIN**  
- **Device Number**  
- **JSON Request/Response Samples**  
