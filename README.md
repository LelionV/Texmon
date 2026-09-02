# Texmon

**Texmon Logistics ERP** is a Django-based logistics and financial management system designed to manage the complete business workflow from master data and quotations through proforma invoices, invoices, payments, receipts, expenses, and customer statements.

The system is being developed incrementally in phases, with each phase building on the previous foundation while maintaining automated tests and end-to-end verification.

---

## Current Status

**Completed through Phase 9 + subsequent UI/PDF enhancements**

* Custom authentication and user management
* Django Groups and permissions
* Master data management
* Audit trail and change history
* Document numbering
* Quotations
* Proforma Invoices
* Invoices
* Payments
* Receipts
* Expenses
* Supplier Payments
* Accounting ledger
* Statements of Account
* Role-based dashboard
* Searchable dropdowns
* Reference document uploads and traceability
* Item codes and live item autofill
* Company letterhead and document branding
* PDF generation and visual verification

**Current test status: 85/85 tests passing.**

---

# Architecture

```text
                         ┌──────────────────┐
                         │   Custom Users   │
                         │ Accounts / Groups│
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │   Master Data    │
                         │ Client / Supplier│
                         │ Items / Ports    │
                         │ Currency / Terms │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │    Quotation     │
                         │   QT-YYYY-0001   │
                         └────────┬─────────┘
                                  │ Approved
                                  ▼
                         ┌──────────────────┐
                         │ Proforma Invoice │
                         │   PI-YYYY-0001   │
                         └────────┬─────────┘
                                  │ Approved
                                  ▼
                         ┌──────────────────┐
                         │     Invoice      │
                         │   INV-YYYY-0001  │
                         └────────┬─────────┘
                                  │
                         ┌────────┴─────────┐
                         ▼                  ▼
                  ┌──────────────┐   ┌──────────────┐
                  │   Payment    │   │    Ledger    │
                  └──────┬───────┘   └──────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │    Receipt   │
                  │ RCPT-YYYY-0001│
                  └──────────────┘

Expenses ───────────────► Supplier Payments
                              │
                              ▼
                           Ledger

Client ─────────────────► Statement of Account
```

---

# Applications

```text
accounts/
masters/
quotations/
proforma/
invoicing/
expenses/
accounting/
dashboard/
core/
```

### `accounts`

Custom user model and authentication.

Includes:

* Phone
* Department
* Job title
* Django Groups
* User activity logging
* Login/logout auditing
* User management

Roles are implemented using Django Groups rather than a custom `role` field.

---

### `masters`

Central reference data for the ERP.

Includes:

* Client
* Supplier
* Currency
* Payment Terms
* Commodity
* Item
* Port
* Transporter
* Company Information
* Document Settings
* Reference Documents

Master records have custom CRUD interfaces, Django admin support, searchable fields, audit history, and deletion protection where appropriate.

---

### `quotations`

Quotation management.

Features:

* Automatic quotation numbering
* Client selection
* Client autofill
* Shipment type
* Commodity
* POL
* POD
* FPOD
* Quantity/unit
* Reference documents
* Line items
* Item codes
* Descriptions
* Unit prices
* Per-line VAT
* Subtotal
* VAT
* Grand total
* Approval workflow
* Sales-representative visibility rules
* PDF generation

Workflow:

```text
Draft
  │
  ▼
Submitted
  │
  ├──► Rejected
  │
  ▼
Approved
  │
  ▼
Converted
```

Quotation numbering:

```text
QT-YYYY-0001
```

---

### `proforma`

Proforma Invoice management.

A Proforma Invoice can only be generated from an approved quotation.

Features:

* Independent copy of quotation data
* Independent line items
* BL number
* Shipment reference
* Container number
* Vessel
* ETA
* ETD
* Approval workflow
* PDF generation

Numbering:

```text
PI-YYYY-0001
```

Converting a quotation to a Proforma Invoice locks the quotation.

---

### `invoicing`

Invoice, Payment and Receipt management.

An Invoice can only be generated from an approved Proforma Invoice.

Features:

* Independent invoice data
* Automatic invoice numbering
* Payment tracking
* Balance calculation
* Overpayment protection
* Paid/Partially Paid/Unpaid status
* Automatic receipt creation
* Invoice PDF
* Receipt PDF

Numbering:

```text
INV-YYYY-0001
RCPT-YYYY-0001
```

Workflow:

```text
Approved Proforma
       │
       ▼
    Invoice
       │
       ▼
    Payment
       │
       ▼
    Receipt
```

Both the quotation and Proforma Invoice become locked once the invoice is created.

---

### `expenses`

Expense and supplier payment management.

Features:

* Expense categories
* Operations/Administration classification
* Expense numbering
* Supplier
* Amount
* VAT
* Attachments
* Approval workflow
* Supplier payments
* Balance tracking
* Overpayment protection

Numbering:

```text
EXP-YYYY-0001
```

Default seeded categories:

**Operations**

* Transport
* Fuel
* Warehouse
* Customs

**Administration**

* Rent
* Utilities
* Salaries

---

### `accounting`

Accounting and customer statements.

Includes:

* Append-only ledger
* Automatic invoice debit entries
* Automatic payment credit entries
* Running balances
* Statement of Account
* Statement PDF

Ledger entries are generated from actual business events rather than being manually entered.

Example:

```text
Invoice       500,000
Payment      -200,000
---------------------
Balance       300,000
```

---

### `dashboard`

Role-aware ERP dashboard.

Dashboard information changes according to the user's Django Groups.

#### Administrator

* Total sales
* Outstanding invoices
* Payments received
* Expenses
* Estimated profit
* Customer count
* Recent invoices

#### Sales

* Quotations
* Pending approvals
* Converted Proformas
* Draft quotations

Sales Representatives only see their own quotations.

#### Finance

* Outstanding invoices
* Recent payments
* Supplier payments
* Statements generated

#### Operations

* Active shipments
* BL numbers
* Ports
* Transporters

---

### `core`

Shared infrastructure used across the ERP.

Includes:

* `AuditModel`
* `DocumentSequence`
* Current-user middleware
* PDF rendering
* Shared business infrastructure

`AuditModel` provides:

```text
created_by
updated_by
created_at
updated_at
```

---

# Document Numbering

Documents use atomic per-year sequences.

```text
Quotation       QT-2026-0001
Proforma        PI-2026-0001
Invoice         INV-2026-0001
Receipt         RCPT-2026-0001
Expense         EXP-2026-0001
```

`DocumentSequence` uses database row locking with `select_for_update()` inside a transaction to prevent duplicate numbers when multiple users create documents concurrently.

---

# Approval and Locking

Business documents use controlled state transitions.

```text
Draft
 │
 ▼
Submitted
 │
 ├────────► Rejected
 │
 ▼
Approved
 │
 ▼
Converted / Locked
```

Status cannot simply be changed by assigning a value to the model field.

Instead, explicit model methods enforce transitions:

```python
submit()
approve()
reject()
revert_to_draft()
mark_converted()
```

Invalid transitions raise `ValidationError`.

---

# Audit Trail

The system contains two complementary audit mechanisms.

## User Activity Log

Records business and authentication events such as:

* Login
* Logout
* Submit
* Approve
* Reject
* Convert
* Lock
* Payment
* Print

Other applications can record business events using:

```python
UserActivityLog.log(...)
```

## Master Data History

`django-simple-history` tracks changes to master data.

Each change can include:

```text
Who changed it
When it changed
What changed
Why it changed
```

Updates display field-level differences such as:

```text
Exchange Rate:
1.000000 → 1.050000

Reason:
Adjusted after monthly FX review
```

---

# Reference Documents

Supporting files can be uploaded and linked to quotations.

Examples:

* Client Purchase Orders
* Customs documents
* Correspondence
* Supporting commercial documents

The relationship follows the document chain:

```text
Reference Document
       │
       ▼
   Quotation
       │
       ▼
Proforma Invoice
       │
       ▼
    Invoice
```

A dedicated Usage page allows users to see the entire document chain associated with a reference file.

---

# Item Management

Items represent billable services such as:

* Freight
* Transport
* Handling
* Storage
* Customs
* Insurance

Each item supports:

```text
Code
Name
Description
Category
Currency
Cost Price
Selling Price
VAT Applicable
VAT Percentage
```

Example:

```text
FRT-AIR-001 — Air Freight Cost (Freight)
```

Selecting an item on a quotation automatically fills:

* Code
* Description
* Unit Price
* VAT %

The populated values remain editable on the quotation.

Changes made to a quotation do not modify the master Item.

---

# Searchable Dropdowns

All site-wide `<select>` fields are enhanced with Choices.js.

This applies to:

* Clients
* Suppliers
* Items
* Ports
* Currency
* Payment Terms
* Payment methods
* Status filters
* Other selectable master data

Dynamically created quotation line items are also initialized automatically.

---

# PDF System

All business documents share:

```text
templates/documents/base_document.html
```

Supported documents:

* Quotation
* Proforma Invoice
* Invoice
* Receipt
* Statement of Account

The PDF layout is based on the Texmon Logistics letterhead and supports:

* Company logo
* Company name
* Tagline
* Document type
* Shipment type
* Document number
* Date
* Attention To
* Items table
* Totals
* Payment status
* Signature lines
* Company address
* Telephone
* Email
* Website
* Tax ID
* Page numbers

PDF status banners include:

```text
DRAFT
PENDING APPROVAL
REJECTED
BALANCE DUE
PAID IN FULL
```

Invoice PDFs dynamically display the current payment state.

---

# PDF Engine

The project currently uses **xhtml2pdf** for PDF generation.

The PDF engine was changed from WeasyPrint because WeasyPrint requires system-level GTK/Pango/Cairo libraries, which caused deployment and Windows compatibility issues.

The PDF system uses a centralized helper:

```text
core/pdf.py
```

All document PDF views use the same rendering layer.

The templates intentionally avoid unsupported CSS such as:

* Flexbox
* CSS Grid
* CSS gradients

and instead use table-based layouts for reliable xhtml2pdf rendering.

---

# Database

The application uses PostgreSQL in production.

Current Render PostgreSQL configuration:

```text
Database: texmon
User:     texmon_user
Port:     5432
Host:     dpg-da5evbjncjis738n6vv0-a
```

The database password should **never be committed to Git**.

On Render, store it as:

```text
DATABASE_PASSWORD
```

and retrieve it through:

```python
PASSWORD = os.environ.get("DATABASE_PASSWORD")
```

---

# Static Files

Current Django configuration:

```python
STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"
```

The project-level `static/` directory should exist alongside `manage.py`.

```text
project/
├── manage.py
├── static/
├── staticfiles/
├── requirements.txt
└── project/
    └── settings.py
```

`staticfiles/` is generated by `collectstatic` and should not be committed.

---

# Deployment

The application is designed to run on Render.

Recommended build command:

```bash
pip install -r requirements.txt && python -m playwright install --with-deps chromium && python manage.py collectstatic --noinput && python manage.py migrate
```

If Playwright is no longer required by the current PDF implementation, the Playwright installation step can be removed and the build command simplified to:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
```

The project should only install the PDF engine actually used by `core/pdf.py`.

---

# Installation

Clone the repository and install dependencies:

```bash
pip install -r requirements.txt
```

Run migrations:

```bash
python manage.py migrate
```

Create/update the default Django Groups:

```bash
python manage.py setup_groups
```

Seed default expense categories:

```bash
python manage.py setup_expense_categories
```

Create an administrator:

```bash
python manage.py createsuperuser
```

Start development server:

```bash
python manage.py runserver
```

---

# Permissions

The application uses Django's native permission system and Groups.

Configured roles include:

```text
Administrator
Sales Manager
Sales Representative
Operations Officer
Finance Officer
Accountant
Management Viewer
```

Permissions are assigned using:

```text
app_label.codename
```

The `setup_groups` command is safe to run repeatedly and automatically picks up permissions added by later phases.

---

# Testing

The project uses automated Django tests covering:

* User authentication
* Groups and permissions
* Customer-code generation
* Client autofill
* VAT validation
* Quotation workflow
* Quotation visibility
* Quotation totals
* PDF generation
* Proforma creation
* Data independence
* Invoice creation
* Payment validation
* Overpayment protection
* Receipt generation
* Expense workflows
* Supplier payments
* Ledger posting
* Statements
* Master CRUD
* Change history
* Reference document workflow
* Dashboard
* Item autofill
* Shipment type
* PDF rendering

Current status:

```text
85/85 tests passing
```

Major workflows have also been verified through real HTTP requests and PDF rendering rather than relying solely on unit tests.

---

# Development Principles

The project follows several architectural principles:

### 1. Business rules belong in models/services

Critical transitions and financial validations are enforced server-side rather than relying on templates or JavaScript.

### 2. Database transactions protect financial operations

Operations involving balances and document numbering use transactions and row locking where required.

### 3. Converted documents are independent

Quotation → Proforma → Invoice conversion copies data into independent records.

Editing a downstream document therefore cannot silently modify its source document.

### 4. Immutable financial history

Accounting entries are generated from actual business events and the ledger is append-only.

### 5. Centralized shared infrastructure

Cross-cutting functionality lives in `core` rather than being duplicated across business applications.

### 6. Automated verification

Major functionality is covered by automated tests and important workflows are verified end-to-end.

---

# Development Phases

```text
Phase 1   Project foundation & authentication       ✓
Phase 2   Master data                               ✓
Phase 3   Quotations                                ✓
Phase 4   Proforma Invoices                         ✓
Phase 5   Invoices, Payments & Receipts             ✓
Phase 6   Expenses                                  ✓
Phase 7   Accounting & Statements                   ✓
Phase 8   Dashboard & Master Data UI                ✓
Phase 9   PDF polish & reference documents          ✓
          Item codes & live autofill                ✓
          Company letterhead                        ✓
          UI/search improvements                    ✓
```

---

# Planned Enhancements

Future development can build on the existing foundation with areas such as:

* Advanced reporting
* Financial reports
* Shipment tracking
* More detailed operations workflows
* Email document delivery
* Notifications
* Document versioning
* User activity reporting
* Advanced dashboard analytics
* API integrations
* eTIMS integration
* Additional deployment hardening

---

# Project Identity

**Texmon Logistics ERP**

A centralized logistics, sales, invoicing, expense, and accounting platform designed around a complete document lifecycle:

```text
Master Data
     │
     ▼
Quotation
     │
     ▼
Proforma Invoice
     │
     ▼
Invoice
     │
     ├──────► Payments
     │           │
     │           ▼
     │        Receipts
     │
     ▼
Accounting Ledger
     │
     ▼
Statement of Account
```

The system is built to maintain traceability, enforce financial controls, preserve audit history, and provide a consistent workflow across the entire logistics operation.
