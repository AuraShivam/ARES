from django.contrib import admin
from .models import Disruption, Inventory, Material, PurchaseOrder, Shipment, Supplier

for model in (Supplier, Material, Inventory, PurchaseOrder, Shipment, Disruption):
    admin.site.register(model)
