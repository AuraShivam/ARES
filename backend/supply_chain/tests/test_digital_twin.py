from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from supply_chain.digital_twin.graph import build_graph
from supply_chain.digital_twin.impact import analyze_disruption_impact
from supply_chain.digital_twin.simulation import execute_simulation
from supply_chain.models import (
    DigitalTwinChangeEvent, DigitalTwinSimulation, Disruption, ExternalFeed, ExternalFeedEvent, Inventory, InventoryMovement,
    Material, PurchaseOrder, Shipment, Supplier, Warehouse,
)


User = get_user_model()


class DigitalTwinGraphTests(TestCase):
    def make_network(self):
        supplier = Supplier.objects.create(name="North Supplier", code="NORTH", latitude=Decimal("0"), longitude=Decimal("0"))
        first_warehouse = Warehouse.objects.create(name="Plant North", code="PLANT-N", latitude=Decimal("1"), longitude=Decimal("1"))
        second_warehouse = Warehouse.objects.create(name="Plant South", code="PLANT-S", latitude=Decimal("2"), longitude=Decimal("2"))
        material = Material.objects.create(sku="M-1", name="Motor", preferred_supplier=supplier)
        Inventory.objects.create(material=material, location=first_warehouse.name, warehouse=first_warehouse, quantity=10, reorder_point=2)
        Inventory.objects.create(material=material, location=second_warehouse.name, warehouse=second_warehouse, quantity=5, reorder_point=2)
        first_order = PurchaseOrder.objects.create(number="PO-1", supplier=supplier, material=material, quantity=12, status="approved")
        second_order = PurchaseOrder.objects.create(number="PO-2", supplier=supplier, material=material, quantity=8, status="in_transit")
        first_shipment = Shipment.objects.create(reference="SH-1", purchase_order=first_order, origin="North Supplier", destination=first_warehouse.name)
        second_shipment = Shipment.objects.create(reference="SH-2", purchase_order=second_order, origin="North Supplier", destination=second_warehouse.code)
        return supplier, first_warehouse, second_warehouse, material, first_order, second_order, first_shipment, second_shipment

    def test_graph_resolves_multiple_orders_shipments_and_warehouse_stock_links(self):
        supplier, first, second, material, po1, po2, ship1, ship2 = self.make_network()
        graph = build_graph()
        ids = {node["id"] for node in graph["nodes"]}
        self.assertIn(f"supplier:{supplier.pk}", ids)
        self.assertIn(f"material:{material.pk}", ids)
        self.assertEqual(sum(edge["type"] == "stores" and edge["source"] == f"material:{material.pk}" for edge in graph["edges"]), 2)
        self.assertEqual(sum(edge["type"] == "transports" for edge in graph["edges"]), 2)
        self.assertTrue(any(edge["type"] == "destination" and edge["target"] == f"warehouse:{first.pk}" for edge in graph["edges"]))
        self.assertTrue(any(edge["type"] == "destination" and edge["target"] == f"warehouse:{second.pk}" for edge in graph["edges"]))

    def test_missing_coordinates_are_explicit_and_same_region_does_not_expose(self):
        supplier = Supplier.objects.create(name="Far supplier", code="FAR", country="Same Country", region="Same Region", latitude=50, longitude=50)
        unknown = Supplier.objects.create(name="No coordinates", code="UNKNOWN", country="Same Country", region="Same Region")
        disruption = Disruption.objects.create(title="Flood advisory", disruption_type="flood", severity="high", affected_region="Same Country", latitude=0, longitude=0)
        with override_settings(ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM={"default": {"low": 1, "medium": 1, "high": 1, "critical": 1}}):
            result = analyze_disruption_impact(disruption.pk)
        by_id = {item["id"]: item for item in result["entities"]}
        self.assertEqual(by_id[f"supplier:{supplier.pk}"]["classification"], "unaffected")
        self.assertEqual(by_id[f"supplier:{unknown.pk}"]["classification"], "insufficient_information")
        self.assertIn("coordinates", by_id[f"supplier:{unknown.pk}"]["reason"])

    def test_supplier_near_point_disruption_is_exposed_and_orders_are_potentially_impacted(self):
        supplier, _w1, _w2, _material, _order, _other, shipment, _ship2 = self.make_network()
        disruption = Disruption.objects.create(title="Flood watch", disruption_type="flood", severity="high", latitude=0, longitude=0)
        with override_settings(ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM={"default": {"low": 1, "medium": 5, "high": 100, "critical": 200}}):
            result = analyze_disruption_impact(disruption.pk)
        by_id = {item["id"]: item for item in result["entities"]}
        self.assertEqual(by_id[f"supplier:{supplier.pk}"]["classification"], "geographically_exposed")
        self.assertEqual(by_id[f"shipment:{shipment.pk}"]["classification"], "potentially_impacted")
        self.assertIn("dependency path", by_id[f"shipment:{shipment.pk}"]["reason"])

    def test_exposed_warehouse_propagates_to_exactly_linked_shipment(self):
        warehouse = Warehouse.objects.create(name="Harbor depot", code="HARBOR", latitude=0, longitude=0)
        supplier = Supplier.objects.create(name="Remote source", code="REMOTE", latitude=40, longitude=40)
        material = Material.objects.create(sku="M-HARBOR", name="Pump")
        order = PurchaseOrder.objects.create(number="PO-HARBOR", supplier=supplier, material=material,
                                             quantity=5, status="in_transit")
        shipment = Shipment.objects.create(reference="SH-HARBOR", purchase_order=order,
                                           origin="Port", destination=warehouse.code, status="in_transit")
        disruption = Disruption.objects.create(title="Harbor flooding", disruption_type="flood",
                                               severity="high", latitude=0, longitude=0)
        with override_settings(ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM={"default": {"high": 10}}):
            result = analyze_disruption_impact(disruption.pk)
        by_id = {item["id"]: item for item in result["entities"]}
        self.assertEqual(by_id[f"warehouse:{warehouse.pk}"]["classification"], "geographically_exposed")
        self.assertEqual(by_id[f"shipment:{shipment.pk}"]["classification"], "potentially_impacted")
        self.assertIn("dependency path", by_id[f"shipment:{shipment.pk}"]["reason"])

    def test_source_provided_gdacs_polygon_exposes_only_coordinates_inside_boundary(self):
        inside = Supplier.objects.create(name="Inside flood boundary", code="IN", latitude=Decimal("0.5"), longitude=Decimal("0.5"))
        outside = Supplier.objects.create(name="Outside flood boundary", code="OUT", latitude=Decimal("5"), longitude=Decimal("5"))
        feed = ExternalFeed.objects.create(key="gdacs-recent-disasters", name="GDACS", enabled=True, status="ok")
        disruption = Disruption.objects.create(title="Source flood polygon", disruption_type="flood", severity="high", source_name="GDACS", source_key="GDACS:FL:TEST:1")
        ExternalFeedEvent.objects.create(
            feed=feed, source_key="GDACS:FL:TEST:1", title="Source flood polygon", content_hash="test-hash",
            lifecycle="active", payload={"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
            disruption=disruption,
        )
        result = analyze_disruption_impact(disruption.pk)
        by_id = {item["id"]: item for item in result["entities"]}
        self.assertEqual(by_id[f"supplier:{inside.pk}"]["classification"], "geographically_exposed")
        self.assertEqual(by_id[f"supplier:{outside.pk}"]["classification"], "unaffected")
        self.assertTrue(result["method"]["boundary_available"])

    def test_disruption_without_coordinates_marks_unlinked_records_uncertain(self):
        supplier = Supplier.objects.create(name="Unknown location", code="NOGEO")
        disruption = Disruption.objects.create(title="Unlocated event", severity="high")
        result = analyze_disruption_impact(disruption.pk)
        by_id = {item["id"]: item for item in result["entities"]}
        self.assertEqual(by_id[f"supplier:{supplier.pk}"]["classification"], "insufficient_information")
        self.assertIn("unavailable", by_id[f"supplier:{supplier.pk}"]["reason"])

    def test_empty_dataset_has_empty_graph(self):
        graph = build_graph()
        self.assertEqual(graph["nodes"], [])
        self.assertEqual(graph["edges"], [])

    def test_nodes_without_locations_are_never_assigned_coordinates(self):
        supplier = Supplier.objects.create(name="No map data", code="NO-MAP")
        node = next(item for item in build_graph()["nodes"] if item["entity_id"] == str(supplier.pk))
        self.assertIsNone(node["location"])
        self.assertTrue(node["geographic_data_unavailable"])


class DigitalTwinApiAndSimulationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operator", password="test-password-long-enough")
        self.client.force_authenticate(self.user)

    def test_graph_api_requires_authentication_and_returns_pagination(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/digital-twin/graph/").status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.force_authenticate(user=self.user)
        supplier = Supplier.objects.create(name="North Supplier", code="NORTH")
        material = Material.objects.create(sku="M-API", name="API material", preferred_supplier=supplier)
        PurchaseOrder.objects.create(number="PO-API", supplier=supplier, material=material,
                                     quantity=3, status="approved")
        response = self.client.get("/api/digital-twin/graph/?type=supplier&page=1&page_size=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["pagination"]["count"], 1)
        self.assertEqual(response.data["nodes"][0]["type"], "supplier")
        self.assertTrue(any(edge["source"] == f"supplier:{supplier.pk}" for edge in response.data["edges"]))
        edge_response = self.client.get("/api/digital-twin/edges/?type=supplier")
        self.assertTrue(any(edge["source"] == f"supplier:{supplier.pk}" for edge in edge_response.data["results"]))

    def test_coordinate_input_requires_a_complete_pair(self):
        response = self.client.post("/api/suppliers/", {"name": "Partial coordinate", "code": "PART", "latitude": 10}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Supplier.objects.filter(code="PART").exists())

    def test_shipment_delay_saves_simulation_without_mutating_operations(self):
        supplier = Supplier.objects.create(name="Parts source", code="PARTS")
        material = Material.objects.create(sku="M-200", name="Bearing")
        warehouse = Warehouse.objects.create(code="WH-1", name="Assembly warehouse")
        inventory = Inventory.objects.create(material=material, location=warehouse.name, warehouse=warehouse,
                                             quantity=10, reorder_point=2)
        eta = timezone.localdate() + timedelta(days=3)
        order = PurchaseOrder.objects.create(number="PO-200", supplier=supplier, material=material,
                                             quantity=40, status="in_transit", expected_date=eta)
        shipment = Shipment.objects.create(reference="SH-200", purchase_order=order, origin="Supplier",
                                           destination=warehouse.name, eta=eta, status="in_transit")
        before = (inventory.quantity, order.status, shipment.status)
        response = self.client.post("/api/digital-twin/simulations/", {
            "scenario_type": "shipment_delay", "entity_id": str(shipment.pk), "horizon_days": 5, "delay_days": 7,
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        result = response.data["result"]
        projection = result["material_projection"][0]
        self.assertEqual(result["label"], "SIMULATED")
        self.assertEqual(projection["baseline"]["supply_only_available"], "50.00")
        self.assertEqual(projection["simulated"]["supply_only_available"], "10.00")
        self.assertFalse(result["production_records_changed"])
        inventory.refresh_from_db()
        order.refresh_from_db()
        shipment.refresh_from_db()
        self.assertEqual((inventory.quantity, order.status, shipment.status), before)
        self.assertTrue(DigitalTwinSimulation.objects.filter(pk=response.data["id"], requested_by=self.user).exists())
        self.assertEqual(self.client.get(f"/api/digital-twin/simulations/{response.data['id']}/").status_code, status.HTTP_200_OK)

    def test_warehouse_failure_resolves_exact_code_destination(self):
        supplier = Supplier.objects.create(name="Parts source", code="PARTS")
        material = Material.objects.create(sku="M-WH", name="Control unit")
        warehouse = Warehouse.objects.create(code="WH-CODE", name="Code warehouse")
        Inventory.objects.create(material=material, location=warehouse.name, warehouse=warehouse, quantity=50)
        due = timezone.localdate() + timedelta(days=2)
        order = PurchaseOrder.objects.create(number="PO-WH", supplier=supplier, material=material,
                                             quantity=20, status="in_transit", expected_date=due)
        Shipment.objects.create(reference="SH-WH", purchase_order=order, origin="Parts source",
                                destination=warehouse.code, eta=due, status="in_transit")
        result = execute_simulation({"scenario_type": "warehouse_failure", "entity_id": str(warehouse.pk), "horizon_days": 5})
        projection = result["material_projection"][0]
        self.assertEqual(projection["baseline"]["supply_only_available"], "70.00")
        self.assertEqual(projection["simulated"]["supply_only_available"], "0.00")

    def test_demand_surge_does_not_count_multiple_movements_on_one_date_as_history(self):
        material = Material.objects.create(sku="M-HIST", name="History test")
        inventory = Inventory.objects.create(material=material, location="Plant", quantity=100)
        same_day = timezone.localdate() - timedelta(days=70)
        for _ in range(12):
            InventoryMovement.objects.create(inventory=inventory, movement_type="issue",
                                             quantity_delta=-1, occurred_at=same_day)
        result = execute_simulation({"scenario_type": "demand_surge", "entity_id": str(material.pk),
                                     "horizon_days": 30, "demand_increase_percent": "20"})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["material_projection"][0]["demand_history"]["distinct_consumption_days"], 1)
        self.assertIsNone(result["material_projection"][0]["simulated"]["projected_available"])

    def test_change_cursor_returns_ordered_sequence_without_record_payloads(self):
        supplier = Supplier.objects.create(name="Sequence supplier", code="SEQ")
        change = DigitalTwinChangeEvent.objects.filter(resource="supplier", entity_id=str(supplier.pk)).order_by("-sequence").first()
        self.assertIsNotNone(change)
        response = self.client.get(f"/api/digital-twin/changes/?since={change.sequence - 1}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        matching = [event for event in response.data["results"] if event["sequence"] == change.sequence]
        self.assertEqual(len(matching), 1)
        self.assertNotIn("payload", matching[0])

    def test_sync_status_includes_external_feed_health_without_configuration_secrets(self):
        success = timezone.now()
        ExternalFeed.objects.create(key="gdacs-recent-disasters", name="GDACS", enabled=True,
                                    status="ok", last_success_at=success, events_seen=12)
        response = self.client.get("/api/digital-twin/sync/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        source = response.data["sources"][0]
        self.assertEqual(source["key"], "gdacs-recent-disasters")
        self.assertIsNotNone(source["last_success_at"])
        self.assertNotIn("configuration", source)
