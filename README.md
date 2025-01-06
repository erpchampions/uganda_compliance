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
```

---

## **Getting Started with EFRIS: Quick Configuration Steps**

1. **Set up Company E Invoicing Details:**  
   - Add **VAT-TIN (Tax ID)** and **Email** in the **Company Master**.

2. **Configure E Invoicing Settings:**  
   - Enable Integration.  
   - Enter Device Number.  
   - Verify and Configure **Tax Accounts** (Input VAT, Output VAT).  

3. **Verify Tax Templates:**  
   - Confirm **Standard Rated (18%)**, **Zero Rated (0%)**, and **Exempt** templates.  
   - Map them to appropriate **Commodity Codes**.

4. **Set up EFRIS Warehouses:**  
   - Enable the **EFRIS Warehouse Flag** on your warehouses.  
   - Ensure stock operations align with EFRIS requirements.

5. **Run a Test Transaction in Sandbox Mode:**  
   - Test your integration with **Sandbox Portal** before switching to **Live Mode**.

6. **Monitor EFRIS Logs:**  
   - View all requests/responses in the **E Invoicing Request Log** table.
   - Validate statuses and troubleshoot any communication issues.

For **detailed configuration and advanced setup**, refer to the full documentation below:  
👉 **[Uganda Compliance Documentation](https://docs.uganda_compliance.app)**

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

---
