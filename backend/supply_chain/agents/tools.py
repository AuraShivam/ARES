"""Bounded read-only tools available to configured ARES model providers."""

import json
import uuid
from dataclasses import dataclass

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import F, Sum
from rest_framework import serializers

from ..agentic_data_readiness import build_agent_data_readiness
from ..models import (
    Disruption,
    Inventory,
    Material,
    PurchaseOrder,
    RiskAssessmentSnapshot,
    Shipment,
    Supplier,
)


class AgentToolFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class ReferenceArguments(serializers.Serializer):
    reference = serializers.CharField(max_length=80, allow_blank=False, trim_whitespace=True)


class NoArguments(serializers.Serializer):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[serializers.Serializer]
    handler: object

    def schema(self):
        if self.arguments is NoArguments:
            parameters = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        else:
            parameters = {
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "description": self.description.split(". ")[0]},
                },
                "required": ["reference"],
                "additionalProperties": False,
            }
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
            "strict": True,
        }


def _json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _evidence(entity_type, record):
    return {
        "reference_type": entity_type,
        "reference_id": str(record.pk),
        "source_name": getattr(record, "source_name", "") or "ARES operational record",
        "observed_at": record.updated_at.isoformat() if hasattr(record, "updated_at") else None,
    }


def _get_by_reference(model, reference, natural_key=None):
    try:
        return model.objects.get(pk=uuid.UUID(reference))
    except (ValueError, TypeError, model.DoesNotExist):
        if natural_key:
            try:
                return model.objects.get(**{natural_key: reference})
            except model.DoesNotExist:
                pass
    raise AgentToolFailure("record_not_found", "No matching ARES record was found for that reference.")


def _supplier(args, user):
    supplier = _get_by_reference(Supplier, args["reference"], "code")
    verified_shipments = Shipment.objects.filter(
        purchase_order__supplier=supplier,
        delivery_outcome_verified=True,
        actual_delivery_date__isnull=False,
        eta__isnull=False,
        status="delivered",
    )
    data = {
        "id": str(supplier.pk), "code": supplier.code, "name": supplier.name,
        "country": supplier.country, "region": supplier.region, "status": supplier.status,
        "risk_score": supplier.risk_score, "lead_time_days": supplier.lead_time_days,
        "verified_delivery_count": verified_shipments.count(),
        "verified_late_delivery_count": verified_shipments.filter(actual_delivery_date__gt=F("eta")).count(),
    }
    return {"data": data, "evidence_references": [_evidence("supplier", supplier)]}


def _material(args, user):
    material = _get_by_reference(Material, args["reference"], "sku")
    data = {
        "id": str(material.pk), "sku": material.sku, "name": material.name,
        "category": material.category, "unit": material.unit, "criticality": material.criticality,
        "preferred_supplier": ({
            "id": str(material.preferred_supplier_id),
            "code": material.preferred_supplier.code,
            "name": material.preferred_supplier.name,
        } if material.preferred_supplier_id else None),
    }
    return {"data": data, "evidence_references": [_evidence("material", material)]}


def _inventory(args, user):
    material = _get_by_reference(Material, args["reference"], "sku")
    rows = list(
        Inventory.objects.filter(material=material)
        .select_related("warehouse")
        .order_by("warehouse__name", "location")[:100]
    )
    total_quantity = Inventory.objects.filter(material=material).aggregate(total=Sum("quantity"))["total"] or 0
    data = {
        "material": {"id": str(material.pk), "sku": material.sku, "name": material.name, "unit": material.unit},
        "total_on_hand": str(total_quantity),
        "record_count": Inventory.objects.filter(material=material).count(),
        "records": [{
            "id": str(row.pk),
            "location": row.location,
            "warehouse": row.warehouse.name if row.warehouse_id else None,
            "quantity": str(row.quantity),
            "reorder_point": str(row.reorder_point),
            "unit_cost": str(row.unit_cost),
            "below_reorder_point": row.below_reorder_point,
        } for row in rows],
    }
    evidence = [_evidence("material", material), *[_evidence("inventory", row) for row in rows]]
    return {"data": data, "evidence_references": evidence}


def _shipment(args, user):
    shipment = _get_by_reference(Shipment, args["reference"], "reference")
    order = shipment.purchase_order
    data = {
        "id": str(shipment.pk), "reference": shipment.reference,
        "status": shipment.status, "carrier": shipment.carrier,
        "origin": shipment.origin, "destination": shipment.destination,
        "eta": shipment.eta.isoformat() if shipment.eta else None,
        "actual_delivery_date": shipment.actual_delivery_date.isoformat() if shipment.actual_delivery_date else None,
        "delivery_outcome_verified": shipment.delivery_outcome_verified,
        "risk_score": shipment.risk_score,
        "purchase_order": order.number,
        "supplier": {"id": str(order.supplier_id), "code": order.supplier.code, "name": order.supplier.name},
    }
    return {"data": data, "evidence_references": [
        _evidence("shipment", shipment), _evidence("purchase_order", order), _evidence("supplier", order.supplier),
    ]}


def _purchase_order(args, user):
    order = _get_by_reference(PurchaseOrder, args["reference"], "number")
    lines = list(order.lines.select_related("material").order_by("line_number")[:100])
    data = {
        "id": str(order.pk), "number": order.number, "status": order.status,
        "supplier": {"id": str(order.supplier_id), "code": order.supplier.code, "name": order.supplier.name},
        "ordered_at": order.ordered_at.isoformat() if order.ordered_at else None,
        "expected_date": order.expected_date.isoformat() if order.expected_date else None,
        "currency": order.currency,
        "lines": [{
            "id": str(line.pk), "line_number": line.line_number,
            "material_sku": line.material.sku, "material_name": line.material.name,
            "quantity": str(line.quantity), "received_quantity": str(line.received_quantity),
            "unit_price": str(line.unit_price),
        } for line in lines],
    }
    evidence = [_evidence("purchase_order", order), _evidence("supplier", order.supplier)]
    evidence.extend(_evidence("purchase_order_line", line) for line in lines)
    evidence.extend(_evidence("material", line.material) for line in lines)
    return {"data": data, "evidence_references": evidence}


def _disruption(args, user):
    disruption = _get_by_reference(Disruption, args["reference"])
    data = {
        "id": str(disruption.pk), "title": disruption.title,
        "disruption_type": disruption.disruption_type, "severity": disruption.severity,
        "status": disruption.status, "confidence": disruption.confidence,
        "affected_region": disruption.affected_region,
        "source_name": disruption.source_name, "source_key": disruption.source_key,
        "affected_supplier_id": str(disruption.affected_supplier_id) if disruption.affected_supplier_id else None,
        "affected_shipment_id": str(disruption.affected_shipment_id) if disruption.affected_shipment_id else None,
    }
    evidence = [_evidence("disruption", disruption)]
    if disruption.affected_supplier_id:
        evidence.append(_evidence("supplier", disruption.affected_supplier))
    if disruption.affected_shipment_id:
        evidence.append(_evidence("shipment", disruption.affected_shipment))
    return {"data": data, "evidence_references": evidence}


def _risk_assessment(args, user):
    disruption = _get_by_reference(Disruption, args["reference"])
    assessment = RiskAssessmentSnapshot.objects.filter(disruption=disruption).order_by("-created_at").first()
    if not assessment:
        raise AgentToolFailure("assessment_not_found", "No stored risk assessment exists for that disruption.")
    data = {
        "id": str(assessment.pk), "disruption_id": str(disruption.pk),
        "risk_score": assessment.risk_score, "risk_band": assessment.risk_band,
        "confidence": assessment.confidence, "model_version": assessment.model_version,
        "factors": assessment.factors, "evidence": assessment.evidence,
        "recommendation": assessment.recommendation, "created_at": assessment.created_at.isoformat(),
    }
    return {"data": data, "evidence_references": [
        _evidence("risk_assessment", assessment), _evidence("disruption", disruption),
    ]}


def _risk_assessment_snapshot(args, user):
    try:
        assessment = RiskAssessmentSnapshot.objects.select_related("disruption").get(pk=uuid.UUID(args["reference"]))
    except (ValueError, TypeError, RiskAssessmentSnapshot.DoesNotExist):
        raise AgentToolFailure("assessment_not_found", "No risk-assessment snapshot matches that exact UUID.") from None
    data = {
        "id": str(assessment.pk), "disruption_id": str(assessment.disruption_id),
        "risk_score": assessment.risk_score, "risk_band": assessment.risk_band,
        "confidence": assessment.confidence, "model_version": assessment.model_version,
        "trigger": assessment.trigger, "factors": assessment.factors,
        "evidence": assessment.evidence, "recommendation": assessment.recommendation,
        "created_at": assessment.created_at.isoformat(),
    }
    return {"data": data, "evidence_references": [
        _evidence("risk_assessment", assessment), _evidence("disruption", assessment.disruption),
    ]}


def _readiness(args, user):
    report = build_agent_data_readiness()
    evidence = [{
        "reference_type": "readiness_capability",
        "reference_id": capability,
        "source_name": "ARES data readiness report",
        "observed_at": report["generated_at"].isoformat(),
    } for capability in report["capabilities"]]
    return {"data": report, "evidence_references": evidence}


TOOLS = {
    "get_data_readiness": Tool(
        "get_data_readiness",
        "Read current ARES data coverage, model readiness, feed freshness, and documented data gaps.",
        NoArguments,
        _readiness,
    ),
    "get_supplier": Tool(
        "get_supplier",
        "Read one supplier by its exact ARES code or UUID, including recorded verified-delivery counts.",
        ReferenceArguments,
        _supplier,
    ),
    "get_material": Tool(
        "get_material",
        "Read one material by its exact SKU or UUID and its recorded preferred supplier.",
        ReferenceArguments,
        _material,
    ),
    "get_inventory": Tool(
        "get_inventory",
        "Read current inventory balances by material SKU or UUID; this does not include an inferred forecast.",
        ReferenceArguments,
        _inventory,
    ),
    "get_shipment": Tool(
        "get_shipment",
        "Read one shipment by its exact reference or UUID and its related order and supplier.",
        ReferenceArguments,
        _shipment,
    ),
    "get_purchase_order": Tool(
        "get_purchase_order",
        "Read one purchase order by its exact number or UUID and its recorded line items.",
        ReferenceArguments,
        _purchase_order,
    ),
    "get_disruption": Tool(
        "get_disruption",
        "Read one disruption by its UUID and any explicitly linked supplier or shipment.",
        ReferenceArguments,
        _disruption,
    ),
    "get_latest_risk_assessment": Tool(
        "get_latest_risk_assessment",
        "Read the latest stored deterministic risk assessment for a disruption UUID; this tool does not trigger a new assessment.",
        ReferenceArguments,
        _risk_assessment,
    ),
    "get_risk_assessment_snapshot": Tool(
        "get_risk_assessment_snapshot",
        "Read one exact stored risk-assessment snapshot by its UUID; this does not trigger a new assessment.",
        ReferenceArguments,
        _risk_assessment_snapshot,
    ),
}


def list_tools():
    return [{
        "name": tool.name,
        "description": tool.description,
        "access": "read_only",
        "requires_arguments": tool.arguments is not NoArguments,
    } for tool in TOOLS.values()]


def provider_tool_definitions(allowed_tools=None):
    allowed = set(allowed_tools) if allowed_tools is not None else set(TOOLS)
    return [tool.schema() for tool in TOOLS.values() if tool.name in allowed]


def execute_read_tool(name, arguments, user, allowed_tools=None):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise AgentToolFailure("unauthorized", "An active authenticated ARES user is required.")
    tool = TOOLS.get(name)
    if not tool or (allowed_tools is not None and name not in allowed_tools):
        raise AgentToolFailure("tool_not_allowed", "That tool is not available to the agent runtime.")
    serializer = tool.arguments(data=arguments)
    if not serializer.is_valid():
        raise AgentToolFailure("invalid_tool_arguments", "The requested tool arguments were invalid.")
    result = tool.handler(serializer.validated_data, user)
    return _json_safe(result)
