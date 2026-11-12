from rest_framework import serializers


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
