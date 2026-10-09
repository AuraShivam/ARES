from datetime import date, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from supply_chain.models import Disruption, Inventory, Material, PurchaseOrder, Shipment, Supplier


class Command(BaseCommand):
    help = "Create a small, repeatable ARES demo supply chain."

    def handle(self, *args, **options):
        north, _ = Supplier.objects.update_or_create(code="SUP-001", defaults={
            "name": "Northstar Components", "country": "Germany", "region": "Europe", "risk_score": 24, "lead_time_days": 12, "status": "active"})
        pacific, _ = Supplier.objects.update_or_create(code="SUP-002", defaults={
            "name": "Pacific Materials Co.", "country": "Taiwan", "region": "East Asia", "risk_score": 68, "lead_time_days": 28, "status": "watch"})
        motor, _ = Material.objects.update_or_create(sku="MTR-440", defaults={
            "name": "Industrial drive motor", "category": "Critical components", "unit": "EA", "criticality": "high", "preferred_supplier": north})
        resin, _ = Material.objects.update_or_create(sku="RES-210", defaults={
            "name": "Engineering resin pellets", "category": "Raw materials", "unit": "KG", "criticality": "medium", "preferred_supplier": pacific})
        Inventory.objects.update_or_create(material=motor, location="Berlin DC", defaults={"quantity": Decimal("48"), "reorder_point": Decimal("30"), "unit_cost": Decimal("420")})
        Inventory.objects.update_or_create(material=resin, location="Singapore Hub", defaults={"quantity": Decimal("120"), "reorder_point": Decimal("160"), "unit_cost": Decimal("8.75")})
        po1, _ = PurchaseOrder.objects.update_or_create(number="PO-2026-1042", defaults={
            "supplier": north, "material": motor, "quantity": Decimal("80"), "expected_date": date.today() + timedelta(days=8), "status": "in_transit", "currency": "EUR", "unit_price": Decimal("420")})
        po2, _ = PurchaseOrder.objects.update_or_create(number="PO-2026-1043", defaults={
            "supplier": pacific, "material": resin, "quantity": Decimal("400"), "expected_date": date.today() + timedelta(days=19), "status": "delayed", "currency": "USD", "unit_price": Decimal("8.75")})
        ship, _ = Shipment.objects.update_or_create(reference="SHP-7781", defaults={
            "purchase_order": po2, "origin": "Kaohsiung", "destination": "Singapore Hub", "carrier": "OceanBridge", "eta": date.today() + timedelta(days=19), "status": "delayed", "risk_score": 74})
        Disruption.objects.update_or_create(title="Port congestion in East Asia", defaults={
            "disruption_type": "logistics", "description": "Port congestion is extending transit times on the Pacific route.", "affected_region": "East Asia", "severity": "high", "status": "open", "confidence": 82, "affected_supplier": pacific, "affected_shipment": ship})
        self.stdout.write(self.style.SUCCESS("Demo supply-chain data is ready."))
