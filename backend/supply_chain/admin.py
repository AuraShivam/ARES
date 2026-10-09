from django.contrib import admin
from .models import (AuditEvent, Disruption, ExternalFeed, ExternalFeedEvent, Inventory,
                     InventoryMovement, Material, PurchaseOrder, PurchaseOrderLine,
                     NotificationDelivery, ResponseActionExecution, RiskAlert,
                     RiskAssessmentSnapshot, RiskOutcome, Shipment, Supplier, Warehouse)

for model in (Supplier, Material, Warehouse, Inventory, InventoryMovement,
              PurchaseOrder, PurchaseOrderLine, Shipment, Disruption, AuditEvent,
              ExternalFeed, ExternalFeedEvent, RiskAssessmentSnapshot, RiskAlert, RiskOutcome,
              NotificationDelivery, ResponseActionExecution):
    admin.site.register(model)
