from django.contrib import admin
from .models import (AuditEvent, Disruption, ExternalFeed, ExternalFeedEvent, Inventory,
                     InventoryMovement, Material, PurchaseOrder, PurchaseOrderLine,
                     NotificationDelivery, ResponseActionExecution, RiskAlert,
                     PredictiveEvaluationRun, RiskAssessmentSnapshot, RiskOutcome,
                     ResponsePlanEffectivenessReview, ShipmentRiskPredictionSnapshot,
                     Shipment, Supplier, Warehouse)

for model in (Supplier, Material, Warehouse, Inventory, InventoryMovement,
              PurchaseOrder, PurchaseOrderLine, Shipment, Disruption, AuditEvent,
              ExternalFeed, ExternalFeedEvent, RiskAssessmentSnapshot, RiskAlert, RiskOutcome,
              ResponsePlanEffectivenessReview, ShipmentRiskPredictionSnapshot,
              NotificationDelivery, ResponseActionExecution, PredictiveEvaluationRun):
    admin.site.register(model)
