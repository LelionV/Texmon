<<<<<<< HEAD
# Logistics ERP - Phase 1

Project setup, custom user model, Django Groups/permissions, base layout, and
the document-numbering/audit-trail foundation every later phase builds on.

## What's in Phase 1

- **Apps created:** accounts, masters, quotations, proforma, invoicing,
  expenses, accounting, dashboard, plus a shared `core` app.
- **Custom user model** (`accounts.User`) with phone/department/job_title and
  role membership via Django Groups (not a custom role field, per spec).
- **UserActivityLog** — generic audit log, auto-populated on login/logout via
  signals; other apps call `UserActivityLog.log(...)` for business events
  (submit, approve, convert, lock, payment, print) in later phases.
- **core.AuditModel** — abstract base (`created_by`, `updated_by`,
  `created_at`, `updated_at`) that every transactional model in later phases
  will inherit from.
- **core.DocumentSequence** — atomic per-year running-number generator used
  for QT-YYYY-0001 / PI-YYYY-0001 / INV-YYYY-0001 / RCPT-YYYY-0001.
- **Groups/permissions**: `python manage.py setup_groups` creates the 7 roles
  from the spec and assigns permissions by "app_label.codename" string,
  skipping ones that don't exist yet. Safe to re-run after every phase.
- **Base template** (`templates/base.html`): Bootstrap 5 + Bootstrap Icons +
  HTMX, fixed sidebar with the full planned menu (placeholder links disabled
  until their phase), topbar, message alerts.
- **Base document template** (`templates/documents/base_document.html`):
  shared print/PDF layout for Quotation/PI/Invoice/Receipt/Statement,
  visually modeled on the sample Texmon Logistics quotation PDF you
  provided (header band, ATTENTION TO box, items table, totals block,
  signature lines). WeasyPrint is installed and ready; actual PDF views are
  wired up per-document starting Phase 3.
- **Login/logout/profile/user list** working end-to-end.

## Setup

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_groups
python manage.py createsuperuser
python manage.py runserver
```

## Architecture decisions

- **Custom user model from day one** — required before any migration runs;
  retrofitting later is a major pain, so it's in place even though Phase 1
  has minimal auth requirements.
- **Groups over a `role` field** — matches the explicit spec requirement and
  lets Django's permission system do the enforcement instead of custom
  if/else checks scattered through views.
- **`core` app for shared concerns** — `AuditModel` and `DocumentSequence`
  are used by masters, quotations, proforma, invoicing, expenses and
  accounting alike. Putting them in `core` (rather than duplicating in each
  app, or bolting them onto `accounts`) avoids circular imports since every
  business app will depend on `core`, never the reverse.
- **DocumentSequence uses `select_for_update()`** inside a transaction so two
  concurrent requests creating a Quotation can't ever be issued the same
  number — important once multiple sales reps are creating quotations at
  once.
- **CurrentUserMiddleware + thread-local** — a convenience fallback so
  service-layer code can stamp `created_by`/`updated_by` without every
  function needing an explicit `user` parameter. Views/services should still
  prefer passing `request.user` explicitly where practical.
- **SQLite by default, Postgres via env vars** — `DATABASE_ENGINE=postgres`
  plus the usual `DATABASE_*` vars switches over with no code changes,
  per the spec's "PostgreSQL preferred (SQLite for development)".

## Next: Phase 2

Master data models (Client, Supplier, Currency, Payment Terms, Commodity,
Item, Port, Transporter, Company Info, Document Settings) + admin
configuration, including the client-select-autopopulates-currency/terms/
sales-rep behavior described in the spec.

## Phase 2: Master Data

Added the `masters` app with all reference data models:

- **Currency** (code, symbol, exchange rate)
- **PaymentTerm** (name, days, description)
- **Commodity** (name, description, HS code)
- **Port** (name, code, country, type: Sea/Air/Land)
- **Transporter** (contact details, vehicle types, license info)
- **Supplier** (contact, tax number, currency, payment terms, supplier type)
- **Item** — billable services (Freight/Transport/Handling/Storage/Customs/
  Insurance), each with its own currency, cost/selling price, and
  **per-item VAT** (`vat_applicable` + `vat_percentage`) since items
  originate from different jurisdictions (e.g. Air Freight at 0% vs Handling
  at 16%). `Item.clean()` enforces `vat_percentage == 0` when
  `vat_applicable` is False.
- **Client** — auto-generates a `customer_code` (`CUS0001`, ...) on first
  save; `sales_representative` FK is limited to users in the Sales
  Representative/Sales Manager groups. `Client.autofill_payload()` returns
  exactly the fields the spec says the quotation form should auto-populate
  on client selection (currency, payment terms, sales rep, billing address)
  — exposed at `GET /masters/api/clients/<id>/autofill/` for Phase 3's
  quotation form to call via HTMX/JS.
- **CompanyInfo** / **DocumentSettings** — soft singletons (`get_solo()`,
  `pk` pinned to 1, add/delete blocked once a row exists) holding company
  letterhead details and document numbering prefixes/terms text.

All models inherit `core.AuditModel`. Full Django admin registered for every
model (list filters, search, autocomplete on FK fields). 7 tests cover
customer-code generation, the autofill payload, VAT validation, and the
autofill API's login requirement — all passing.

Re-running `python manage.py setup_groups` now picks up the new masters
permissions automatically (Sales Manager: 5, Sales Representative: 3,
Operations Officer: 3 — as designed in Phase 1).

### Next: Phase 3

Quotation module: header (auto-numbered QT-YYYY-0001, client selection with
autofill, ports, commodity), line items with per-item VAT calculation,
subtotal/VAT/grand total, and the Draft → Submitted → Approved workflow.

## Phase 3: Quotation Module

Added the `quotations` app: `Quotation` (header) + `QuotationItem` (line
items), fully wired with views, templates, admin, and a PDF endpoint.

- **Auto-numbering**: `Quotation.save()` claims `QT-YYYY-0001` from
  `core.DocumentSequence` at creation time, using the prefix configured in
  `masters.DocumentSettings` and the quotation's date year.
- **Client autofill**: `Quotation.populate_from_client()` mirrors the
  Phase 2 `masters` autofill endpoint server-side, so currency/payment terms/
  sales rep populate from the selected client even without JS; the create
  form also loads `masters:client_autofill` via fetch for live UI updates.
- **Shipment fields** (commodity, origin/destination port, FPOD, qty/unit)
  mirror the reference quotation PDF's COMMODITY/POL/POD/QTY/FPOD row, kept
  separate from the billable `QuotationItem` lines per the spec.
- **Per-line VAT**: `QuotationItem.vat_percentage` is copied from the
  selected master `Item` when added (`populate_from_item()`), so later
  changes to an item's VAT rate don't retroactively rewrite old quotations.
  `line_subtotal` / `vat_amount` / `total_amount` are computed properties;
  saving or deleting any line item recalculates the header's
  `subtotal` / `vat_total` / `grand_total` automatically.
- **Verified against your reference PDF**: seeding the same two lines
  (Freight Cost 2,500 + Clearance fee 2×1,000, both at 13% VAT) reproduces
  **Subtotal 4,500.00 / VAT 585.00 / Grand Total 5,085.00** exactly.
- **Workflow**: Draft → Submitted → Approved → Converted, plus Reject and
  Revert-to-Draft, enforced by model methods (`submit/approve/reject/
  revert_to_draft/mark_converted`) that raise `ValidationError` on invalid
  transitions — never by letting a form set `status` directly. Editing is
  blocked once a quotation leaves Draft (`is_editable`); it's permanently
  locked once Converted (`is_locked`), ready for Phase 4 to call
  `mark_converted()` when a Proforma Invoice is generated.
- **Visibility**: a plain Sales Representative only sees their own
  quotations (`sales_representative == request.user`); Administrator, Sales
  Manager, Finance Officer, Accountant and Management Viewer see all —
  enforced once in `QuotationQuerysetMixin`, tested explicitly.
- **PDF**: `GET /quotations/<id>/pdf/` renders `quotation_pdf.html`
  (extending `documents/base_document.html`) through WeasyPrint — confirmed
  producing a valid PDF 1.7 file.
- New custom permissions `quotations.approve_quotation` and
  `quotations.submit_quotation`; re-running `setup_groups` now assigns them
  to Sales Manager/Sales Representative as configured in Phase 1.
- 13 new tests (workflow transitions, VAT/totals math, visibility rules,
  permission enforcement, PDF generation) — all passing, 21/21 total across
  the project.

### Next: Phase 4

Proforma Invoice module: generate from an Approved quotation (copying its
data independently, per the spec's "editing PI should not modify quotation"
rule), plus BL number / container / vessel / ETA / ETD fields and its own
approval gate before Invoice creation.

## Phase 4: Proforma Invoice Module

Added the `proforma` app: `ProformaInvoice` (header) + `ProformaInvoiceItem`
(line items), generated exclusively from an Approved quotation.

- **Single creation path**: `ProformaInvoice.create_from_quotation()` is the
  *only* way a PI comes into existence — there's no blank "New Proforma"
  form. It validates the quotation is Approved and not already converted
  (enforced via a `OneToOneField` to `quotation`, so "PI can only be
  generated from quotation" is structural, not just a UI rule), copies the
  header fields and clones every `QuotationItem` into an independent
  `ProformaInvoiceItem` row, then calls `quotation.mark_converted()` to lock
  the source quotation.
- **Editing PI never touches the quotation** — proven by a dedicated test
  (`test_editing_pi_does_not_modify_quotation`) that edits a PI line and
  confirms the original quotation line is untouched, since they're
  structurally separate rows, not shared references.
- **New shipping fields** per spec: BL Number, Shipment Reference, Container
  Number, Vessel, ETA, ETD — editable only while the PI is Draft.
- **Own approval workflow**: Draft → Submitted → Approved (+ Reject/Revert),
  mirroring the quotation workflow, with `mark_converted()` reserved for
  Phase 5 to call once an Invoice is generated ("PI approval required before
  invoice creation" / "After invoice creation: LOCK ... Proforma Invoice").
- **UI integration**: an Approved quotation's detail page now shows a
  "Convert to Proforma Invoice" button (permission-gated on
  `proforma.add_proformainvoice`); once converted it becomes "View Proforma
  PI-2026-000X" instead, and the quotation's own Edit button disappears
  since it's now locked.
- **Verified end-to-end over real HTTP** (not just Python): seeded a
  quotation matching your reference PDF, then drove submit → approve →
  convert-to-proforma → view PI → download PI PDF entirely through the
  running dev server. All steps returned correct redirects/200s, the PDF
  is a valid PDF 1.7 file, and the quotation page correctly showed
  "Converted to Proforma" afterwards.
- 9 new tests (creation validation, data copying/independence, workflow,
  permission enforcement, PDF) — 30/30 passing project-wide.
- Re-running `setup_groups` now also picks up the new
  `proforma.approve_proformainvoice` / `submit_proformainvoice` permissions
  for Sales Manager, Sales Representative and Operations Officer.

### Next: Phase 5

Invoice module: generate from an Approved Proforma Invoice (`INV-YYYY-0001`),
which locks both the Quotation and Proforma Invoice; Payments (with
balance tracking and an overpayment guard); auto-generated Receipts
(`RCPT-YYYY-0001`) with their own PDF.

## Phase 5: Invoice, Payments, Receipts

Added the `invoicing` app: `Invoice` + `InvoiceItem` (generated from an
Approved Proforma Invoice), `Payment` (with balance enforcement), and
`Receipt` (auto-generated per payment).

- **Single creation path**: `Invoice.create_from_proforma()` — same pattern
  as Phase 4 — validates the PI is Approved and not already invoiced
  (`OneToOneField`), clones line items independently, computes `due_date`
  from `payment_terms.days`, then calls `proforma.mark_converted()`. The
  quotation was already locked when the PI was created, so per the spec's
  "After invoice creation: LOCK Quotation, Proforma Invoice" — both are now
  confirmed locked (tested explicitly).
- **No invoice edit view** — once created, header and line items are fixed;
  the spec gives invoices no approval workflow of its own (approval already
  happened at the PI stage), so the only thing that changes an invoice
  afterwards is recording payments against it.
- **Overpayment guard, belt-and-braces**: `Payment.clean()` blocks it at the
  form/admin layer; `Payment.save()` *independently* re-checks inside a
  `select_for_update()`-locked transaction, so two concurrent payment
  submissions on the same invoice can't jointly exceed the balance — a
  ValidationError in either path leaves `paid_amount` untouched. Tested with
  a single overpay, a sequential-across-two-payments overpay, and a
  double-check that a fully-paid invoice still rejects further payments.
- **Automatic balance/status updates**: every `Payment.save()` recomputes
  `Invoice.paid_amount` / `balance_due` / `status`
  (Unpaid → Partially Paid → Paid) from actual payment rows — never
  incremented ad hoc, so it can't drift.
- **Receipt is inseparable from Payment**: created in the *same* transaction
  as the payment (`RCPT-YYYY-0001` numbering), so a Payment can never exist
  without a matching Receipt — verified with a dedicated test plus a
  two-payments-two-receipts test.
- **Verified live over HTTP, the entire chain in one run**: seeded a
  quotation matching your reference PDF, then drove submit → approve →
  convert to PI → submit → approve → create Invoice → record a full
  $5,085.00 payment → confirmed the invoice flipped to **Paid** with
  $0.00 balance → downloaded both the Invoice PDF and the Receipt PDF
  (both valid PDF 1.7) → attempted a further payment on the now-fully-paid
  invoice and confirmed it was silently rejected (payment/receipt counts
  stayed at exactly 1 each).
- `setup_groups` re-run confirms Finance Officer went from 0 permissions
  (Phase 1, before `invoicing` existed) to 8, and Management Viewer from 0
  to 5 — the self-updating permission design from Phase 1 has now been
  proven across all five phases.
- 14 new tests — **44/44 passing project-wide**.

### Next: Phase 6

Expenses module: expense categories (Operations: Transport/Fuel/Warehouse/
Customs; Administration: Rent/Utilities/Salaries), the Expense model
(supplier, amount, VAT, attachment, approval), and Supplier Payments
tracking money paid out against expenses.

## PDF Engine Fix: WeasyPrint → xhtml2pdf

**Problem**: WeasyPrint depends on system GTK/Pango/Cairo libraries. On
Windows especially, `libgobject-2.0-0` usually isn't present unless GTK is
separately installed, producing:
`OSError: cannot load library 'gobject-2.0-0'`.

**Fix**: swapped to `xhtml2pdf`, a pure-Python PDF renderer with zero system
dependencies — `pip install xhtml2pdf` is enough on any OS, including
Windows, with no extra installs.

- New `core/pdf.py` — a single `render_pdf(html_string) -> bytes` helper
  used by all four PDF views (quotation, proforma, invoice, receipt), so
  there's one place to swap engines again in future if ever needed.
- `templates/documents/base_document.html` was **rewritten from flexbox to
  table-based layout**, since xhtml2pdf only supports a CSS 2.1-ish subset
  (no flexbox/grid). This included fixing a real rendering bug along the
  way: the "Attention To" box was splitting into three separate visual bars
  instead of one continuous box under the new engine — fixed by moving it
  to a table too.
- **Visually verified**, not just "PDF generated without error": rendered
  all four document PDFs to PNG via PyMuPDF and inspected them directly —
  header, attention box, items table, and totals (including the invoice's
  extra Paid/Balance rows) all render cleanly and the numbers match your
  reference document exactly ($4,500 / $585 / $5,085).
- All 44 pre-existing tests still passed unchanged after the swap.

## Phase 6: Expenses Module

Added the `expenses` app: `ExpenseCategory`, `Expense`, `SupplierPayment`.

- **ExpenseCategory** has a `category_type` (Operations/Administration).
  Category names are ordinary rows (not hardcoded choices), so new ones can
  be added from the admin freely; `python manage.py setup_expense_categories`
  idempotently seeds exactly the spec's examples — Transport, Fuel,
  Warehouse, Customs (Operations) and Rent, Utilities, Salaries
  (Administration).
- **Expense** gets the same Draft → Submitted → Approved/Rejected workflow
  used by quotations/proforma (the spec's "Approved by" field implies a
  real approval step), auto-numbered `EXP-YYYY-0001`, with a single VAT
  percentage per expense (one transaction, one supplier invoice — unlike
  quotations' per-line VAT), a file attachment field, and `is_editable`
  gating edits to Draft only.
- **SupplierPayment** requires an Approved expense and reuses the Phase 5
  overpayment-guard pattern (`clean()` + a `select_for_update()`-locked
  `save()`), tested with the same rigor as invoicing payments.
- **Bug found and fixed during live testing**: recording a supplier payment
  against an expense with no supplier assigned (a legitimate case — e.g.
  Salaries) originally caused a raw `IntegrityError` 500, because `save()`
  silently left `supplier` as `None` instead of validating it. Fixed with
  an explicit check in both `clean()` and `save()` that raises a clear
  `ValidationError`, a template-level guard so the payment form doesn't
  even render for supplier-less expenses, a view-level guard so a direct
  POST still redirects gracefully instead of 500ing, and two new dedicated
  tests (model-level and view-level) covering exactly this case.
- **Verified live over HTTP** in both directions: an expense *with* a
  supplier went through create → submit → approve → full supplier payment
  and correctly ended at $0.00 balance; an expense *without* a supplier
  went through the same workflow and the payment attempt correctly bounced
  with zero `SupplierPayment` rows created, no server error.
- 15 new tests — **59/59 passing project-wide**.

### Next: Phase 7

Accounting module: Statement of Account generated from a client's invoices/
payments/receipts, plus a running ledger and PDF statement output built on
the same `base_document.html`.

## Phase 7: Accounting and Statements

Added the `accounting` app: `LedgerEntry` (an append-only running ledger)
and `StatementOfAccount` (a generated, PDF-able customer statement).

- **LedgerEntry auto-posts from real business events**, not manual entry:
  every Invoice creation posts one debit row, every Payment posts one
  credit row. This is wired via signals from `accounting` listening to
  `invoicing`'s models — `invoicing` has zero knowledge that `accounting`
  exists, keeping the dependency one-directional.
- **Bug found and fixed during testing**: a plain `post_save` signal on
  `Invoice` fires the moment `Invoice.save()` is first called inside
  `create_from_proforma()` — which happens *before* line items are copied
  and `recalculate_totals()` runs, so it was posting a worthless $0.00
  debit every time. Fixed by adding a dedicated `invoice_finalized` Django
  signal, sent explicitly once the invoice's totals are final; `Payment`
  posting was unaffected since a payment's amount is already correct before
  its first save. Caught this via a failing test, not by inspection —
  exactly why the tests exist.
- **`running_balance`** is computed inside a `select_for_update()`-locked
  transaction against the client's last entry, same defensive pattern used
  for Payment/SupplierPayment balances in Phases 5–6, so concurrent postings
  for the same client can't race each other.
- **StatementOfAccount** stores only a header (number, client, period,
  opening/closing balance, who/when generated) — line items are re-queried
  live from the immutable ledger via `get_lines()` rather than duplicated
  into a second table that could drift out of sync.
- **Verified against your spec's own worked example** — Invoice 500,000,
  Payment 200,000, Balance 300,000 — reproduced exactly by a dedicated test.
- `setup_groups` extended: added `accounting.add_statementofaccount` to
  Finance Officer and Accountant (the original Phase 1 permission list only
  had `view_statementofaccount`, which would have blocked anyone from ever
  generating one).
- 8 new tests — **67/67 passing project-wide**.

## Quotation Form UX Improvements

**Client field is now a searchable dropdown.** Using Choices.js (a small
dependency-free JS library, no build step needed), the client `<select>` on
the quotation form is progressively enhanced into a type-to-search dropdown
— useful once there are more than a handful of clients. Selecting a client
now also **actually calls** the `masters:client_autofill` endpoint (built
in Phase 2 but never wired into the UI until now) to auto-populate
currency, payment terms, and sales representative — matching the original
spec requirement that was previously only satisfied server-side.

**Commodity is now free text, not a restricted dropdown.** Changed
`commodity` from a `ForeignKey(masters.Commodity)` to a plain `CharField`
across `Quotation`, `ProformaInvoice`, and `Invoice` (all three needed the
same change, since each copies the field from the document before it in the
chain). The field renders as a text input backed by an HTML `<datalist>`
suggesting existing master Commodity names *and* commodity values already
typed on past quotations — so the suggestion list grows with real usage —
but **any text can be typed and saved**, not just suggested values.
`masters.Commodity` itself is untouched and still exists as the suggestion
source. **Items are completely unaffected** — `QuotationItem.item` is still
a `ForeignKey` to `masters.Item`, unchanged, so pricing/VAT/supplier lookup
on line items still works exactly as before.

Verified live: submitted a quotation with `"Frozen Tilapia Fillets (custom
entry)"` as the commodity — a value that does not exist anywhere in the
master Commodity table — and confirmed it saved, displays correctly on the
detail page, and renders correctly in the PDF.

### Next: Phase 8

Dashboard: role-specific KPI widgets for Administrator (total sales,
outstanding invoices, payments received, expenses, profit, customers),
Sales (my quotations, pending approvals, converted proformas), Finance
(outstanding invoices, payments, supplier payments, statements), and
Operations (active shipments, BL numbers, ports, transport assignments).

## Phase 8 + Master Data Custom UI + UI Polish

### Phase 8: Dashboard
Role-aware KPI dashboard (`dashboard/views.py`) — a single `home()` view
builds different context sections depending on the logged-in user's Group
membership, matching the spec's per-role breakdown:
- **Administrator**: total sales, outstanding invoices, payments received,
  expenses, estimated profit, customer count, recent invoices table.
- **Sales** (Sales Manager sees all; Sales Representative sees only their
  own): my quotations, pending approvals, converted proformas, drafts.
- **Finance** (Finance Officer/Accountant): outstanding invoices total,
  payments in the last 30 days, supplier payments in the last 30 days,
  statements generated.
- **Operations**: active shipments, active BL numbers, active ports,
  transporter count.
A user matching no role still gets a safe fallback view instead of a blank
page or an error.

### Master Data: Custom Template CRUD (not admin-only)
All 8 list-based master models (Client, Supplier, Currency, PaymentTerm,
Commodity, Item, Port, Transporter) now have full Create/Read/Update/
**Delete** through the app's own UI, not just the Django admin:
- **Registry-driven**: `masters/registry.py` describes each model once
  (editable fields, list columns, search fields); one set of generic views
  (`masters/views.py`) and templates serves all of them, so adding a new
  master-data type to the UI is a one-entry registry addition, not a new
  app's worth of boilerplate.
- **Delete** uses Django's `ProtectedError` handling: master records
  referenced by `PROTECT` foreign keys (a Client with quotations, a
  Currency in use, etc.) can't be deleted — the attempt is caught and
  turned into a clear message ("still referenced by other records...
  consider marking it inactive instead") rather than a 500. Verified live:
  attached a Client to a Currency, attempted delete via the UI, confirmed
  it was blocked and the record survived.
- CompanyInfo and DocumentSettings (the two singletons from Phase 2) get
  dedicated edit-in-place pages instead of a list/create/delete flow, since
  "add another Company Info row" isn't meaningful.
- A bug was caught and fixed during testing: the generic views initially
  raised `ImproperlyConfigured` because `PermissionRequiredMixin` was
  listed before the mixin providing the dynamic `get_permission_required()`
  override in the class bases — Python's MRO picked the wrong one. Fixed by
  reordering the base classes; caught by the test suite, not by inspection.

### Change History with Reasons
Added `django-simple-history`, with `history = HistoricalRecords()` on
every one of the 10 master data models:
- Every create/update/delete now supports an optional **"Reason for this
  change"** field, stored as `history_change_reason` on the historical
  record — exactly the "fields for reasons" that were requested.
- The History page for any record shows a chronological timeline (Created/
  Updated/Deleted), who made each change, their stated reason, and a
  **field-level diff** (old value → new value) for every update, computed
  via `django-simple-history`'s `diff_against()`.
- Verified live: updated a Currency's exchange rate with the reason
  "Adjusted after monthly FX review", confirmed the reason and the
  `Exchange Rate: 1.000000 → 1.050000` diff both appear correctly on the
  History page.

### Shipment Type (Import / Export / Transit)
Added `shipment_type` (Import/Export/Transit) to Quotation, copied through
to ProformaInvoice and Invoice at each conversion step — matching the
"IMPORT" tag shown on your reference Texmon quotation. Wired into the
quotation create/edit form and into the PDF badge (`doc_tag`) on all three
document types. Fixed an xhtml2pdf-specific rendering quirk along the way:
nested tables default to filling their parent cell's width unless given an
explicit `width` HTML attribute, which was making the badge stretch full-
width instead of appearing as a compact pill like the reference PDF —
confirmed fixed by rendering the PDF to an image and inspecting it.

### UI Polish
Refreshed `base.html`: Inter font, a refined color system (deeper sidebar
gradient, softer card shadows, consistent border-radius), tighter
typography scale for tables/badges/forms, and a `--erp-*` CSS variable
system so future tweaks are centralized. Master data list/form/history
pages and the new dashboard follow the same visual language.

### Testing
14 new tests (masters CRUD/history/permission-enforcement) — **75/75
passing project-wide.** Every major new flow was also verified live over
HTTP against the running dev server: master data create/update/delete/
history, delete-protection, dashboard KPI rendering, and the shipment-type
PDF badge (rendered to PNG and visually inspected, not just checked for a
200 status).

## Phase 9: PDF Polish + File-Linked References + Global Searchable Dropdowns

### PDF Polish
- **Status banners** on every document PDF: Quotation/Proforma show
  DRAFT/PENDING APPROVAL/REJECTED; Invoice shows a live BALANCE DUE amount
  or PAID IN FULL, flipping color (blue → green) the moment a payment
  clears it. Verified visually at every state by rendering PDFs to PNG.
- **Page numbers** (`Page X of Y`) added to every document footer via
  xhtml2pdf's `<pdf:pagenumber />` / `<pdf:pagecount />` tags.
- **Root-caused and fixed a real xhtml2pdf rendering bug**: the Statement
  of Account PDF was showing garbled, overlapping column headers. After
  several failed attempts (explicit CSS widths, `<colgroup>`,
  `table-layout: fixed` — none of which xhtml2pdf actually honors), the
  true cause turned out to be genuinely empty `<td></td>` cells (no text,
  not even whitespace) in the Opening/Closing Balance summary rows —
  xhtml2pdf's column-width algorithm silently corrupts when it encounters
  these, collapsing unrelated columns in *other* rows on top of each other.
  Fixed by using `&nbsp;` placeholders, confirmed with a rendered PNG, and
  documented directly in `base_document.html`'s comments so this doesn't
  get reintroduced in a future document template.

### Files Linked to Quotations (instead of typed reference numbers)
Added `masters.ReferenceDocument` — an uploaded supporting file (client PO,
customs paperwork, correspondence) with its own name/description, full
change history, and searchable-dropdown selection:
- Registered in the master-data registry (`masters/registry.py`), so it
  gets full custom-UI Create/Update/Delete/History for free, exactly like
  every other master model from Phase 8.
- `Quotation.reference_number` (free text) replaced with
  `Quotation.reference_document` (a `ForeignKey` to `ReferenceDocument`),
  propagated through the existing copy-at-conversion pattern to
  `ProformaInvoice.reference_document` and `Invoice.reference_document` —
  the same "copy once at creation, then independent" design used for every
  other field in the Quotation → Proforma → Invoice chain.
- **Upload-first, then select** workflow: the quotation form's Reference
  Document field is a searchable dropdown with an inline "Upload a new one"
  link straight to the reference-document creation page.
- **Full traceability ("see the whole process linked to the file")**: a
  new Usage page (`masters:reference_document_usage`) on every
  ReferenceDocument lists every Quotation it's linked to, and for each one,
  its downstream Proforma Invoice and Invoice (with live status badges) —
  so from one supporting file you can see the entire pipeline it fed into.
  Verified live: uploaded a file, linked it to a new quotation, confirmed
  it appears correctly on the quotation's detail page and PDF (`Ref No:
  Client PO #4021`), and confirmed the Usage page correctly lists that
  quotation with its (currently empty, since not yet converted) downstream
  chain.

### Global Searchable Dropdowns
Every `<select>` on every page is now automatically upgraded to a
type-to-search dropdown (Choices.js), moved from being quotation-form-only
to a site-wide behavior in `base.html` — clients, currencies, items, ports,
payment methods, status filters, all of it. Two details worth noting:
- Choices.js wraps the underlying `<select>` and maintains its own visual
  state; setting `.value` directly (as the client auto-fill script did)
  doesn't update what's displayed. Fixed by storing each Choices instance
  on its element (`el.choicesInstance`) and calling `.setChoiceByValue()`
  instead — the auto-fill behavior from Phase 3/7 still works correctly
  now that every field involved is also a Choices-enhanced dropdown.
- Dynamically-inserted quotation line-item rows (the "Add Line" button)
  didn't exist yet when the page first loaded, so they're now explicitly
  initialized with Choices.js right after insertion instead of relying on
  the page-load-only global init.

### Testing
3 new tests (upload via custom UI, linking to a quotation, usage-view
chain traversal) — **78/78 passing project-wide.** The full new-file
workflow was also verified live end-to-end over HTTP: upload → appears in
dropdown → linked to quotation → shows on detail page and PDF → traceable
via the Usage page.

## Item Codes + Live Autofill, and Company Letterhead

### Item Codes, Descriptions, and Live Line-Item Autofill
Added `code` and `description` fields to `masters.Item`:
- `code` is a short internal SKU-style identifier (e.g. `FRT-AIR-001`),
  shown in the item dropdown (`Item.__str__` now renders as
  `"FRT-AIR-001 — Air Freight Cost (Freight)"`) so it's searchable via the
  site-wide Choices.js dropdowns from the previous round of changes.
- `description` is the longer text that gets copied onto a quotation line
  when the item is selected, falling back to `name` if left blank.
- **New `masters:item_autofill` JSON endpoint** (mirroring the existing
  `client_autofill` pattern): given an item ID, returns its code,
  description, unit price, and VAT percentage.
- **Live client-side autofill**: selecting an item on any quotation line
  (including lines added later via "Add Line") now fills that line's Code
  display, Description, Unit Price, and VAT % automatically via a
  delegated JS listener on the line-items table — delegated rather than
  bound per-row so it keeps working for dynamically inserted rows.
  Critically, **all three filled fields remain ordinary editable inputs
  afterward** — the autofill is a starting point, not a lock; price and
  VAT can still be hand-adjusted per line without touching the master Item
  record, exactly as requested.
- Verified two ways: seeded items via the DB and confirmed the resulting
  quotation/PDF showed the right data, *and* separately called the actual
  `masters:item_autofill` API endpoint the JavaScript calls and confirmed
  it returns the exact code/description/price/VAT payload the UI expects.
- 7 new tests covering the API endpoint, the code-in-`__str__` behavior,
  the description-falls-back-to-name behavior, the zero-VAT-when-not-
  applicable case, and the server-side `populate_from_item()` fallback.

### Company Letterhead (Texmon Logistics branding)
Redesigned `templates/documents/base_document.html`'s header and footer to
match the supplied Texmon Logistics Limited letterhead, while keeping it
fully data-driven off `CompanyInfo` (not hardcoded to one company name) so
it still works correctly for any company's data entered into the system:
- **Header**: company logo (if uploaded) + bold green company name +
  italic blue tagline on the left; document type, shipment-type badge, and
  document number/date on the right — same two-column structure as before,
  restyled to the brand's green/blue palette.
- **Tri-color accent bar** (red/green/blue) directly under the header,
  echoing the letterhead's brand ribbon — built as three colored table
  cells rather than a CSS gradient, since xhtml2pdf doesn't support CSS
  gradients but reliably renders adjacent colored table cells.
- **Three-line contact footer** (address / phone / email | website),
  centered, matching the letterhead's footer structure, plus an optional
  Tax ID line and the existing page-number line.
- Added `CompanyInfo.website` field to support the footer's "email |
  website" line.
- **Two more xhtml2pdf quirks found and fixed** while building this:
  (1) a `border-top` set on a container with multiple sibling `<div>`
  children gets duplicated above *each* child instead of appearing once at
  the top of the container — fixed by using `<span>` + `<br>` for line
  breaks instead of stacked `<div>`s; (2) xhtml2pdf's special
  `<pdf:pagenumber />` / `<pdf:pagecount />` tags silently fail to render
  when nested inside a `<span>` — fixed by keeping the page-number line in
  its own standalone `<div>`. Both were caught by rendering the PDF to a
  PNG and visually inspecting it, not by assuming the markup worked.
- **Verified across all five document types** (Quotation, Proforma
  Invoice, Invoice, Receipt, Statement of Account) by driving a full
  quotation-to-payment chain end-to-end and rendering every resulting PDF
  to an image for visual confirmation — consistent letterhead, single
  footer divider, and correct page numbers on every one.

### Testing
7 new tests — **85/85 passing project-wide.**
=======
# Texmon
>>>>>>> 46fbd2c (Initial commit)
