from django.contrib import admin
from .models import (AuditEvent, Disruption, ExternalFeed, ExternalFeedEvent, Inventory,
                     InventoryMovement, Material, PurchaseOrder, PurchaseOrderLine,
                     NotificationDelivery, ResponseActionExecution, RiskAlert,
                     PredictiveEvaluationRun, RiskAssessmentSnapshot, RiskOutcome,
                     ResponsePlanEffectivenessReview, ShipmentRiskPredictionSnapshot,
                     Shipment, Supplier, Warehouse)

for model in (Supplier, Material, Warehouse, Inventory, InventoryMovement,
              PurchaseOrder, PurchaseOrderLine, Shipment, Disruption,
              ExternalFeed, ExternalFeedEvent, RiskAssessmentSnapshot, RiskAlert, RiskOutcome,
              ResponsePlanEffectivenessReview, ShipmentRiskPredictionSnapshot,
              NotificationDelivery, ResponseActionExecution, PredictiveEvaluationRun):
    admin.site.register(model)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "entity_type", "entity_id", "action", "actor")
    list_filter = ("entity_type", "action")
    search_fields = ("entity_id", "actor")
    readonly_fields = ("id", "entity_type", "entity_id", "action", "actor", "changes", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
