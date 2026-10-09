from django.core.management.base import BaseCommand, CommandError

from supply_chain.risk import score_evidence


SCENARIOS = [
    {
        "name": "Low-impact event with no exposure signals",
        "severity": "low",
        "confidence": 100,
        "evidence": {},
        "expected_band": "low",
    },
    {
        "name": "High-impact event without linked records",
        "severity": "high",
        "confidence": 100,
        "evidence": {},
        "expected_band": "high",
    },
    {
        "name": "Supplier watch with linked order and regional match",
        "severity": "medium",
        "confidence": 82,
        "evidence": {
            "supplier": {"code": "SUP-WATCH", "risk_score": 68, "status": "watch", "lead_time_days": 28},
            "purchase_orders": [{"number": "PO-101", "status": "approved"}],
            "delayed_purchase_orders": 0,
            "materials": [{"sku": "MAT-101", "criticality": "medium", "quantity": 100, "reorder_point": 20, "inventory_records": 1}],
            "stale_sources": [],
            "freshness_unknown": 0,
            "region_anchors": ["supplier region: West"],
            "affected_region": "West",
        },
        "expected_band": "high",
    },
    {
        "name": "Critical event with blocked supplier, overdue shipment, and low stock",
        "severity": "critical",
        "confidence": 60,
        "evidence": {
            "supplier": {"code": "SUP-BLOCKED", "risk_score": 90, "status": "blocked", "lead_time_days": 42},
            "shipment": {"reference": "SHP-101", "risk_score": 80, "status": "delayed", "overdue": True},
            "purchase_orders": [{"number": "PO-102", "status": "delayed"}],
            "delayed_purchase_orders": 1,
            "materials": [{"sku": "MAT-102", "criticality": "high", "quantity": 2, "reorder_point": 10, "inventory_records": 1}],
            "stale_sources": ["Supplier SUP-BLOCKED"],
            "freshness_unknown": 0,
            "region_anchors": ["shipment origin: Port Meridian"],
            "affected_region": "Port Meridian",
        },
        "expected_band": "critical",
    },
    {
        "name": "Low-severity event with critical material below reorder point",
        "severity": "low",
        "confidence": 100,
        "evidence": {
            "purchase_orders": [{"number": "PO-103", "status": "approved"}],
            "delayed_purchase_orders": 0,
            "materials": [{"sku": "MAT-103", "criticality": "high", "quantity": 0, "reorder_point": 5, "inventory_records": 1}],
            "stale_sources": [],
            "freshness_unknown": 0,
            "region_anchors": ["warehouse region: East Asia"],
            "affected_region": "East Asia",
        },
        "expected_band": "moderate",
    },
]


class Command(BaseCommand):
    help = "Evaluate the deterministic risk rules against representative supply-chain scenarios."

    def handle(self, *args, **options):
        mismatches = []
        self.stdout.write("ARES risk scenario evaluation (deterministic rules; not a prediction-quality benchmark)")
        self.stdout.write("Scenario | Score | Actual band | Target band | Result")
        for scenario in SCENARIOS:
            result = score_evidence(
                scenario["severity"],
                scenario["confidence"],
                scenario["evidence"],
            )
            passed = result["risk_band"] == scenario["expected_band"]
            label = "PASS" if passed else "REVIEW"
            self.stdout.write(
                f"{scenario['name']} | {result['risk_score']} | {result['risk_band']} | "
                f"{scenario['expected_band']} | {label}"
            )
            if not passed:
                mismatches.append(scenario["name"])
        self.stdout.write(f"\n{len(SCENARIOS) - len(mismatches)}/{len(SCENARIOS)} target bands matched.")
        if mismatches:
            raise CommandError("Risk scenario targets need review: " + "; ".join(mismatches))
