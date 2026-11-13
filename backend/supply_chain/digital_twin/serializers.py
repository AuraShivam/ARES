from rest_framework import serializers

from supply_chain.geospatial import MAX_ROUTE_GEOMETRY_POSITIONS, normalize_geojson_geometry


class RecoveryOptionSerializer(serializers.Serializer):
    STRATEGY_TYPES = ("inventory_redistribution", "emergency_procurement", "route_alternative")
    strategy_type = serializers.ChoiceField(choices=STRATEGY_TYPES)
    material_id = serializers.UUIDField(required=False)
    source_warehouse_id = serializers.UUIDField(required=False)
    destination_warehouse_id = serializers.UUIDField(required=False)
    supplier_id = serializers.UUIDField(required=False)
    shipment_id = serializers.UUIDField(required=False)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    transfer_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    lead_time_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    transit_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    estimated_unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    estimated_transfer_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    currency = serializers.RegexField(r"^[A-Z]{3}$", max_length=3, required=False)
    source_reference = serializers.CharField(max_length=160, trim_whitespace=True, required=False, allow_blank=False)
    combination_name = serializers.CharField(max_length=80, trim_whitespace=True, required=False, allow_blank=False)
    release_reorder_buffer = serializers.BooleanField(default=False)
    route_geometry = serializers.JSONField(required=False)

    def validate(self, attrs):
        required_by_type = {
            "inventory_redistribution": ("material_id", "source_warehouse_id", "destination_warehouse_id", "quantity", "transfer_days", "source_reference"),
            "emergency_procurement": ("material_id", "supplier_id", "quantity", "lead_time_days", "source_reference"),
            "route_alternative": ("shipment_id", "route_geometry", "transit_days", "source_reference"),
        }
        missing = [field for field in required_by_type[attrs["strategy_type"]] if field not in attrs]
        if missing:
            raise serializers.ValidationError({field: "This field is required for the selected recovery strategy." for field in missing})
        if "quantity" in attrs and attrs["quantity"] <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
        if attrs["strategy_type"] == "inventory_redistribution":
            if attrs["source_warehouse_id"] == attrs["destination_warehouse_id"]:
                raise serializers.ValidationError({"destination_warehouse_id": "Choose a different destination warehouse."})
            if "estimated_transfer_cost" in attrs and "currency" not in attrs:
                raise serializers.ValidationError({"currency": "Provide a currency when entering a transfer cost."})
        elif attrs["strategy_type"] == "emergency_procurement":
            if "estimated_unit_cost" in attrs and "currency" not in attrs:
                raise serializers.ValidationError({"currency": "Provide a currency when entering a procurement unit cost."})
        else:
            if "estimated_transfer_cost" in attrs and "currency" not in attrs:
                raise serializers.ValidationError({"currency": "Provide a currency when entering route cost."})
            try:
                attrs["route_geometry"] = normalize_geojson_geometry(
                    attrs["route_geometry"], allowed_types={"LineString", "MultiLineString"},
                    max_positions=MAX_ROUTE_GEOMETRY_POSITIONS,
                )
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError({"route_geometry": str(exc)}) from exc
        return attrs

class SimulationRequestSerializer(serializers.Serializer):
    SCENARIOS = (
        "supplier_failure", "warehouse_failure", "shipment_delay",
        "route_disruption", "material_shortage", "demand_surge",
    )
    scenario_type = serializers.ChoiceField(choices=SCENARIOS)
    entity_id = serializers.UUIDField()
    horizon_days = serializers.IntegerField(min_value=1, max_value=365, default=30)
    delay_days = serializers.IntegerField(min_value=1, max_value=365, default=7)
    shortage_quantity = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, default=0)
    demand_increase_percent = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=0, max_value=1000, default=20)
    recovery_options = serializers.ListField(child=RecoveryOptionSerializer(), required=False, max_length=10)
    ranking_weights = serializers.DictField(
        child=serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100),
        required=False,
    )

    def validate(self, attrs):
        weights = attrs.get("ranking_weights")
        if weights is not None:
            allowed = {"recovery_time", "cost", "service_level", "supplier_risk"}
            if set(weights) != allowed:
                raise serializers.ValidationError({"ranking_weights": f"Provide exactly these keys: {', '.join(sorted(allowed))}."})
            if sum(weights.values()) != 100:
                raise serializers.ValidationError({"ranking_weights": "Weights must add up to 100."})
        return attrs
