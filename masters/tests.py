from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Client, Commodity, Currency, Item, PaymentTerm, Port, Supplier

User = get_user_model()


class MasterDataModelTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms_30 = PaymentTerm.objects.create(name="30 Days", days=30)
        self.rep = User.objects.create_user(username="jane", password="x")

    def test_client_customer_code_auto_generated(self):
        c1 = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms_30,
        )
        c2 = Client.objects.create(
            company_name="Beta Ltd", currency=self.usd, payment_terms=self.terms_30,
        )
        self.assertTrue(c1.customer_code.startswith("CUS"))
        self.assertNotEqual(c1.customer_code, c2.customer_code)

    def test_client_autofill_payload(self):
        client = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms_30,
            sales_representative=self.rep, billing_address="PO Box 1, Nairobi",
        )
        payload = client.autofill_payload()
        self.assertEqual(payload["currency_code"], "USD")
        self.assertEqual(payload["payment_terms_name"], "30 Days")
        self.assertEqual(payload["sales_representative_id"], self.rep.id)
        self.assertEqual(payload["billing_address"], "PO Box 1, Nairobi")

    def test_item_vat_not_applicable_requires_zero_percentage(self):
        item = Item(
            name="Air Freight", item_type=Item.ItemType.FREIGHT, currency=self.usd,
            cost_price=Decimal("100"), selling_price=Decimal("120"),
            vat_applicable=False, vat_percentage=Decimal("16"),
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_item_margin_property(self):
        item = Item.objects.create(
            name="Handling", item_type=Item.ItemType.HANDLING, currency=self.usd,
            cost_price=Decimal("100"), selling_price=Decimal("150"),
            vat_applicable=True, vat_percentage=Decimal("16"),
        )
        self.assertEqual(item.margin, Decimal("50"))

    def test_port_unique_together(self):
        Port.objects.create(name="Mombasa", country="Kenya", port_type=Port.PortType.SEA)
        with self.assertRaises(Exception):
            Port.objects.create(name="Mombasa", country="Kenya", port_type=Port.PortType.SEA)


class ClientAutofillApiTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms_30 = PaymentTerm.objects.create(name="30 Days", days=30)
        self.user = User.objects.create_user(username="staff", password="x")
        self.client_obj = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms_30,
        )

    def test_requires_login(self):
        resp = self.client.get(f"/masters/api/clients/{self.client_obj.id}/autofill/")
        self.assertEqual(resp.status_code, 302)  # redirected to login

    def test_returns_autofill_payload(self):
        self.client.force_login(self.user)
        resp = self.client.get(f"/masters/api/clients/{self.client_obj.id}/autofill/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["currency_code"], "USD")


class MasterCrudUITests(TestCase):
    """Covers the custom master-data CRUD UI (not the Django admin):
    create, update, delete-with-protection, and change history with reason."""

    def setUp(self):
        perms = Permission.objects.filter(content_type__app_label="masters")
        self.admin_group = Group.objects.create(name="Administrator")
        self.admin_group.permissions.add(*perms)
        self.admin_user = User.objects.create_user(username="admin1", password="pass1234")
        self.admin_user.groups.add(self.admin_group)

    def test_list_requires_login(self):
        resp = self.client.get(reverse("masters:list", args=["currencies"]))
        self.assertEqual(resp.status_code, 302)

    def test_create_currency_via_custom_template(self):
        self.client.login(username="admin1", password="pass1234")
        resp = self.client.post(reverse("masters:create", args=["currencies"]), {
            "name": "Kenyan Shilling", "code": "KES", "symbol": "KSh", "exchange_rate": "130.5", "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Currency.objects.filter(code="KES").exists())

    def test_update_records_change_reason_in_history(self):
        self.client.login(username="admin1", password="pass1234")
        currency = Currency.objects.create(name="Euro", code="EUR", symbol="€", exchange_rate=1)
        resp = self.client.post(reverse("masters:update", args=["currencies", currency.pk]), {
            "name": "Euro", "code": "EUR", "symbol": "€", "exchange_rate": "0.92", "is_active": "on",
            "change_reason": "Daily FX rate sync",
        })
        self.assertEqual(resp.status_code, 302)
        currency.refresh_from_db()
        self.assertEqual(str(currency.exchange_rate), "0.920000")
        latest_history = currency.history.first()
        self.assertEqual(latest_history.history_change_reason, "Daily FX rate sync")

    def test_delete_unreferenced_record_succeeds(self):
        self.client.login(username="admin1", password="pass1234")
        currency = Currency.objects.create(name="Temp", code="TMP", symbol="T", exchange_rate=1)
        resp = self.client.post(reverse("masters:delete", args=["currencies", currency.pk]), {
            "change_reason": "Duplicate entry",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Currency.objects.filter(pk=currency.pk).exists())

    def test_delete_referenced_record_is_blocked_gracefully(self):
        self.client.login(username="admin1", password="pass1234")
        usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        terms = PaymentTerm.objects.create(name="30 Days", days=30)
        Client.objects.create(company_name="Acme Ltd", currency=usd, payment_terms=terms)
        resp = self.client.post(reverse("masters:delete", args=["currencies", usd.pk]))
        self.assertEqual(resp.status_code, 302)  # graceful redirect, not a 500
        self.assertTrue(Currency.objects.filter(pk=usd.pk).exists())  # still there

    def test_history_view_shows_created_and_updated_entries(self):
        self.client.login(username="admin1", password="pass1234")
        currency = Currency.objects.create(name="Pound", code="GBP", symbol="£", exchange_rate=1)
        currency.exchange_rate = 1.25
        currency._change_reason = "Rate update"
        currency.save()
        resp = self.client.get(reverse("masters:history", args=["currencies", currency.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["rows"]), 2)

    def test_hub_view_lists_accessible_master_types(self):
        self.client.login(username="admin1", password="pass1234")
        resp = self.client.get(reverse("masters:hub"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(len(resp.context["items"]) > 0)

    def test_non_privileged_user_cannot_create(self):
        plain_user = User.objects.create_user(username="plain1", password="pass1234")
        self.client.login(username="plain1", password="pass1234")
        resp = self.client.get(reverse("masters:create", args=["currencies"]))
        self.assertEqual(resp.status_code, 403)




class ReferenceDocumentTests(TestCase):
    def setUp(self):
        perms = Permission.objects.filter(content_type__app_label__in=["masters", "quotations"])
        self.admin_group = Group.objects.create(name="Administrator")
        self.admin_group.permissions.add(*perms)
        self.admin_user = User.objects.create_user(username="admin1", password="pass1234")
        self.admin_user.groups.add(self.admin_group)

        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.client_obj = Client.objects.create(company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms)

    def test_upload_reference_document_via_custom_ui(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="admin1", password="pass1234")
        upload = SimpleUploadedFile("po.txt", b"purchase order contents")
        resp = self.client.post(reverse("masters:create", args=["reference-documents"]), {
            "name": "Client PO #1", "description": "Test PO", "file": upload, "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)
        from .models import ReferenceDocument
        self.assertTrue(ReferenceDocument.objects.filter(name="Client PO #1").exists())

    def test_quotation_can_link_a_reference_document(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import ReferenceDocument
        from quotations.models import Quotation, QuotationItem

        doc = ReferenceDocument.objects.create(
            name="Client PO #1", file=SimpleUploadedFile("po.txt", b"contents"),
        )
        q = Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms, reference_document=doc,
        )
        QuotationItem.objects.create(quotation=q, description="Freight", quantity=1, unit_price=Decimal("100"))
        self.assertEqual(q.reference_document, doc)
        self.assertIn(q, doc.quotations.all())

    def test_usage_view_shows_linked_quotation_chain(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import ReferenceDocument
        from quotations.models import Quotation, QuotationItem

        doc = ReferenceDocument.objects.create(
            name="Client PO #1", file=SimpleUploadedFile("po.txt", b"contents"),
        )
        q = Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms, reference_document=doc,
        )
        QuotationItem.objects.create(quotation=q, description="Freight", quantity=1, unit_price=Decimal("100"))

        self.client.login(username="admin1", password="pass1234")
        resp = self.client.get(reverse("masters:reference_document_usage", args=[doc.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["chains"]), 1)
        self.assertEqual(resp.context["chains"][0]["quotation"], q)
        self.assertIsNone(resp.context["chains"][0]["proforma"])


class ItemCodeAutofillTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.user = User.objects.create_user(username="staff1", password="pass1234")
        self.item = Item.objects.create(
            code="FRT-AIR-001", name="Air Freight Cost",
            description="Airfreight charge per shipment, Dubai to Mombasa route",
            item_type=Item.ItemType.FREIGHT, currency=self.usd,
            cost_price=Decimal("2000.00"), selling_price=Decimal("2500.00"),
            vat_applicable=True, vat_percentage=Decimal("13.00"),
        )

    def test_item_str_includes_code(self):
        self.assertIn("FRT-AIR-001", str(self.item))
        self.assertIn("Air Freight Cost", str(self.item))

    def test_item_without_code_falls_back_to_name_only(self):
        plain_item = Item.objects.create(
            name="Storage", item_type=Item.ItemType.STORAGE, currency=self.usd,
            cost_price=Decimal("10"), selling_price=Decimal("20"),
        )
        self.assertNotIn("—", str(plain_item).split("(")[0])

    def test_item_autofill_api_requires_login(self):
        resp = self.client.get(reverse("masters:item_autofill", args=[self.item.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_item_autofill_api_returns_code_description_price_vat(self):
        self.client.login(username="staff1", password="pass1234")
        resp = self.client.get(reverse("masters:item_autofill", args=[self.item.pk]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], "FRT-AIR-001")
        self.assertEqual(data["description"], "Airfreight charge per shipment, Dubai to Mombasa route")
        self.assertEqual(data["unit_price"], "2500.00")
        self.assertEqual(data["vat_percentage"], "13.00")

    def test_item_autofill_falls_back_to_name_when_no_description(self):
        item = Item.objects.create(
            code="STG-001", name="Storage Fee", item_type=Item.ItemType.STORAGE,
            currency=self.usd, cost_price=Decimal("5"), selling_price=Decimal("10"),
        )
        self.client.login(username="staff1", password="pass1234")
        resp = self.client.get(reverse("masters:item_autofill", args=[item.pk]))
        self.assertEqual(resp.json()["description"], "Storage Fee")

    def test_item_autofill_zero_vat_when_not_vat_applicable(self):
        item = Item.objects.create(
            code="AIR-000", name="Zero-rated Air Freight", item_type=Item.ItemType.FREIGHT,
            currency=self.usd, cost_price=Decimal("100"), selling_price=Decimal("150"),
            vat_applicable=False, vat_percentage=Decimal("0"),
        )
        self.client.login(username="staff1", password="pass1234")
        resp = self.client.get(reverse("masters:item_autofill", args=[item.pk]))
        self.assertEqual(resp.json()["vat_percentage"], "0.00")


class QuotationItemPopulateFromItemTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.client_obj = Client.objects.create(company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms)
        self.item = Item.objects.create(
            code="CLR-002", name="Clearance fee", description="Customs clearance handling fee per unit",
            item_type=Item.ItemType.CUSTOMS_CLEARANCE, currency=self.usd,
            cost_price=Decimal("800"), selling_price=Decimal("1000"),
            vat_applicable=True, vat_percentage=Decimal("13.00"),
        )

    def test_server_side_populate_uses_item_description(self):
        from quotations.models import Quotation, QuotationItem
        q = Quotation.objects.create(client=self.client_obj, currency=self.usd, payment_terms=self.terms)
        line = QuotationItem.objects.create(quotation=q, item=self.item, quantity=2, unit_price=Decimal("0"))
        self.assertEqual(line.description, "Customs clearance handling fee per unit")
        self.assertEqual(line.unit_price, Decimal("1000.00"))
        self.assertEqual(line.vat_percentage, Decimal("13.00"))
