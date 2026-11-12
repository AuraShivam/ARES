from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from supply_chain.import_views import import_commit, import_detail, import_preview, import_templates, imports_list
from supply_chain.auth_views import current_user, login, logout
from supply_chain.feed_views import feed_status
from supply_chain.agents.api import data_readiness as agent_data_readiness
from supply_chain.digital_twin import api as digital_twin_api
from supply_chain.views import (
    AuditEventViewSet, DisruptionViewSet, InventoryMovementViewSet, InventoryViewSet,
    MaterialViewSet, NotificationDeliveryViewSet, PurchaseOrderLineViewSet, PurchaseOrderViewSet,
    ResponseActionViewSet,
    ResponsePlanViewSet, RiskAlertViewSet, RiskAssessmentViewSet, ShipmentViewSet,
    SupplierViewSet, WarehouseViewSet, health, overview, risk_assess,
    predictive_risk, inventory_forecast, risk_calibration, risk_outcome_upsert, risk_policy, map_data,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet)
router.register("materials", MaterialViewSet)
router.register("warehouses", WarehouseViewSet)
router.register("inventory", InventoryViewSet)
router.register("inventory-movements", InventoryMovementViewSet)
router.register("purchase-orders", PurchaseOrderViewSet)
router.register("purchase-order-lines", PurchaseOrderLineViewSet)
router.register("response-plans", ResponsePlanViewSet)
router.register("response-actions", ResponseActionViewSet)
router.register("shipments", ShipmentViewSet)
router.register("disruptions", DisruptionViewSet)
router.register("audit-events", AuditEventViewSet)
router.register("risk/assessments", RiskAssessmentViewSet, basename="risk-assessment")
router.register("risk/alerts", RiskAlertViewSet, basename="risk-alert")
router.register("notifications", NotificationDeliveryViewSet, basename="notification-delivery")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/login/", login, name="api-login"),
    path("api/auth/me/", current_user, name="api-current-user"),
    path("api/auth/logout/", logout, name="api-logout"),
    path("api/inventory/forecast/", inventory_forecast, name="inventory-forecast"),
    path("api/ai/data-readiness/", agent_data_readiness, name="ai-data-readiness"),
    path("api/map/data/", map_data, name="map-data"),
    path("api/digital-twin/graph/", digital_twin_api.graph_snapshot, name="digital-twin-graph"),
    path("api/digital-twin/nodes/", digital_twin_api.graph_nodes, name="digital-twin-nodes"),
    path("api/digital-twin/edges/", digital_twin_api.graph_edges, name="digital-twin-edges"),
    path("api/digital-twin/entities/<str:entity_type>/<uuid:entity_id>/", digital_twin_api.entity_detail, name="digital-twin-entity"),
    path("api/digital-twin/geo/", digital_twin_api.geo_data, name="digital-twin-geo"),
    path("api/digital-twin/health/", digital_twin_api.health_overview, name="digital-twin-health"),
    path("api/digital-twin/impacts/<uuid:disruption_id>/", digital_twin_api.disruption_impact, name="digital-twin-impact"),
    path("api/digital-twin/dependencies/<str:entity_type>/<uuid:entity_id>/", digital_twin_api.affected_dependencies, name="digital-twin-dependencies"),
    path("api/digital-twin/sync/status/", digital_twin_api.sync_status, name="digital-twin-sync-status"),
    path("api/digital-twin/changes/", digital_twin_api.changes_since, name="digital-twin-changes"),
    path("api/digital-twin/simulations/", digital_twin_api.simulations, name="digital-twin-simulations"),
    path("api/digital-twin/simulations/<uuid:simulation_id>/", digital_twin_api.simulation_detail, name="digital-twin-simulation-detail"),
    path("api/", include(router.urls)),
    path("api/imports/templates/", import_templates, name="import-templates"),
    path("api/feeds/status/", feed_status, name="feed-status"),
    path("api/imports/preview/", import_preview, name="import-preview"),
    path("api/imports/<uuid:batch_id>/commit/", import_commit, name="import-commit"),
    path("api/imports/<uuid:batch_id>/", import_detail, name="import-detail"),
    path("api/imports/", imports_list, name="imports-list"),
    path("api/overview/", overview, name="overview"),
    path("api/risk/assess/", risk_assess, name="risk-assess"),
    path("api/risk/policy/", risk_policy, name="risk-policy"),
    path("api/risk/outcomes/", risk_outcome_upsert, name="risk-outcome-upsert"),
    path("api/risk/calibration/", risk_calibration, name="risk-calibration"),
    path("api/risk/predictive/", predictive_risk, name="risk-predictive"),
    path("api/health/", health, name="health"),
]

handler404 = "config.api_errors.api_not_found"
handler500 = "config.api_errors.api_server_error"
