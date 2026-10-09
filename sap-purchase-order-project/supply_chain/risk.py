"""Deterministic, explainable risk scoring for the ARES demo MVP."""

SEVERITY_POINTS = {"low": 15, "medium": 35, "high": 60, "critical": 80}


def assess(disruption):
    score = SEVERITY_POINTS.get(disruption.severity, 25)
    factors = [f"Base impact for {disruption.severity} severity: {score}/100"]
    if disruption.affected_supplier:
        supplier = disruption.affected_supplier
        supplier_points = round(supplier.risk_score * 0.2)
        score += supplier_points
        factors.append(f"Supplier {supplier.code} risk profile adds {supplier_points} points (profile {supplier.risk_score}/100)")
    if disruption.affected_shipment:
        shipment = disruption.affected_shipment
        shipment_points = round(shipment.risk_score * 0.15)
        score += shipment_points
        factors.append(f"Shipment {shipment.reference} exposure adds {shipment_points} points (shipment {shipment.risk_score}/100)")
        if shipment.status in ("delayed", "at_risk"):
            score += 10
            factors.append("Shipment is delayed or already at risk: +10 points")
    confidence_adjustment = round((100 - disruption.confidence) * 0.1)
    score += confidence_adjustment
    if confidence_adjustment:
        factors.append(f"Evidence confidence is {disruption.confidence}%; uncertainty adds {confidence_adjustment} points")
    score = min(100, max(0, score))
    band = "critical" if score >= 80 else "high" if score >= 60 else "moderate" if score >= 35 else "low"
    if score >= 70:
        recommendation = "Escalate to the supply-chain response owner; review alternate sources and expedite options before approving a change."
    elif score >= 40:
        recommendation = "Review exposed orders and inventory buffers; prepare a contingency option and monitor for changes."
    else:
        recommendation = "Continue monitoring and validate the event against another source before taking operational action."
    return {"disruption_id": str(disruption.id), "risk_score": score, "risk_band": band, "confidence": disruption.confidence,
            "factors": factors, "recommendation": recommendation,
            "governance": "Advisory only. A human must review and approve any operational action.",
            "model": "ARES transparent rules v1"}
