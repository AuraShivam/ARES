import csv
import io
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    DataImport, DataImportRow, Disruption, Inventory, InventoryMovement, Material,
    PurchaseOrder, PurchaseOrderLine, Shipment, Supplier, Warehouse,
)


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 2000

IMPORT_SCHEMAS = {
    "supplier": {
        "label": "Suppliers",
        "required": ["code", "name"],
        "optional": ["country", "region", "risk_score", "lead_time_days", "status", "source_key", "source_updated_at"],
        "key": "code",
    },
    "material": {
        "label": "Materials",
        "required": ["sku", "name"],
        "optional": ["category", "unit", "criticality", "preferred_supplier_code", "source_key", "source_updated_at"],
        "key": "sku",
    },
    "warehouse": {
        "label": "Warehouses",
        "required": ["code", "name"],
        "optional": ["region", "country", "warehouse_type", "active", "source_key", "source_updated_at"],
        "key": "code",
    },
    "inventory": {
        "label": "Inventory balances",
        "required": ["material_sku", "warehouse_code", "quantity"],
        "optional": ["reorder_point", "unit_cost", "source_key", "source_updated_at"],
        "key": "material_sku + warehouse_code",
    },
    "purchase_order": {
        "label": "Purchase orders",
        "required": ["number", "supplier_code", "material_sku", "quantity"],
        "optional": ["expected_date", "status", "currency", "unit_price", "source_key", "source_updated_at"],
        "key": "number",
    },
    "shipment": {
        "label": "Shipments",
        "required": ["reference", "purchase_order_number", "origin", "destination"],
        "optional": ["carrier", "eta", "status", "risk_score", "source_key", "source_updated_at"],
        "key": "reference",
    },
    "disruption": {
        "label": "Disruptions",
        "required": ["source_key", "title", "severity"],
        "optional": [
            "disruption_type", "description", "affected_region", "status", "confidence",
            "affected_supplier_code", "shipment_reference", "source_updated_at",
        ],
        "key": "source name + source_key",
    },
}


class ImportFileError(ValueError):
    pass


class ImportCommitError(Exception):
    def __init__(self, message, rows=None):
        super().__init__(message)
        self.rows = rows or []


def template_metadata():
    return {
        "limits": {"max_file_bytes": MAX_FILE_BYTES, "max_rows": MAX_IMPORT_ROWS},
        "entities": [
            {
                "key": key,
                "label": schema["label"],
                "required": schema["required"],
                "columns": schema["required"] + schema["optional"],
                "match_key": schema["key"],
            }
            for key, schema in IMPORT_SCHEMAS.items()
        ],
    }


def _normalize_header(value):
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lstrip("\ufeff").lower()).strip("_")


def parse_csv_upload(upload, entity_type):
    if entity_type not in IMPORT_SCHEMAS:
        raise ImportFileError("Choose a supported import type.")
    if upload is None:
        raise ImportFileError("Choose a CSV file to upload.")
    filename = os.path.basename((upload.name or "upload.csv").replace("\\", "/"))
    if len(filename) > 255:
        raise ImportFileError("The CSV file name must be 255 characters or fewer.")
    if not filename.lower().endswith(".csv"):
        raise ImportFileError("Upload a .csv file.")
    if upload.size > MAX_FILE_BYTES:
        raise ImportFileError("The CSV file exceeds the 5 MB limit.")

    raw_content = upload.read(MAX_FILE_BYTES + 1)
    if len(raw_content) > MAX_FILE_BYTES:
        raise ImportFileError("The CSV file exceeds the 5 MB limit.")
    try:
        content = raw_content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFileError("The CSV file must use UTF-8 encoding.") from exc

    try:
        reader = csv.DictReader(io.StringIO(content, newline=""))
        if not reader.fieldnames:
            raise ImportFileError("The CSV file needs a header row and at least one data row.")
        headers = [_normalize_header(name or "") for name in reader.fieldnames]
        if any(not header for header in headers):
            raise ImportFileError("Every CSV column needs a header.")
        if len(headers) != len(set(headers)):
            raise ImportFileError("The CSV contains duplicate column headers.")

        schema = IMPORT_SCHEMAS[entity_type]
        allowed = set(schema["required"] + schema["optional"])
        missing = sorted(set(schema["required"]) - set(headers))
        unknown = sorted(set(headers) - allowed)
        if missing or unknown:
            details = []
            if missing:
                details.append(f"Missing required columns: {', '.join(missing)}.")
            if unknown:
                details.append(f"Unknown columns: {', '.join(unknown)}.")
            details.append(f"Use the {schema['label']} template for the supported headers.")
            raise ImportFileError(" ".join(details))

        reader.fieldnames = headers
        rows = []
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise ImportFileError(f"Row {row_number} has more values than the header row.")
            row = {header: (raw_row.get(header) or "").strip() for header in headers}
            if not any(row.values()):
                continue
            rows.append((row_number, row))
            if len(rows) > MAX_IMPORT_ROWS:
                raise ImportFileError(f"The CSV exceeds the {MAX_IMPORT_ROWS} row limit.")
    except csv.Error as exc:
        raise ImportFileError(f"The CSV could not be parsed: {exc}") from exc

    if not rows:
        raise ImportFileError("The CSV contains no data rows.")
    return filename, headers, rows


def _field_default(model, field_name):
    return model._meta.get_field(field_name).get_default()


def _parse_integer(value):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("enter a whole number") from exc


def _parse_decimal(value):
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("enter a valid decimal number") from exc
    if not parsed.is_finite():
        raise ValueError("enter a finite decimal number")
    return parsed


def _parse_bool(value):
    normalized = value.casefold()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError("use true/false, yes/no, or 1/0")


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("use YYYY-MM-DD") from exc


def _parse_source_timestamp(value):
    parsed = parse_datetime(value)
    if parsed is None or timezone.is_naive(parsed):
        raise ValueError("use an ISO 8601 timestamp with a timezone, such as 2026-06-30T12:00:00Z")
    return parsed


def _set_value(instance, row, column, field_name, errors, parser=None, required=False, blank_default=None):
    model = type(instance)
    if column not in row:
        return
    elif row[column] == "":
        if required:
            errors.append(f"{column} is required.")
        elif instance.pk:
            return
        value = blank_default if blank_default is not None else _field_default(model, field_name)
    else:
        try:
            value = parser(row[column]) if parser else row[column]
        except ValueError as exc:
            errors.append(f"{column}: {exc}.")
            value = getattr(instance, field_name) if instance.pk else _field_default(model, field_name)
    setattr(instance, field_name, value)


def _set_reference(instance, row, column, field_name, model, lookup_field, errors, required=False):
    if column not in row:
        return
    value = row[column].strip()
    if not value:
        if required:
            errors.append(f"{column} is required.")
        elif not instance.pk:
            setattr(instance, field_name, None)
        return
    match = model.objects.filter(**{f"{lookup_field}__iexact": value}).first()
    if match is None:
        errors.append(f"{column}: no matching {lookup_field.replace('_', ' ')} '{value}'. Import that record first.")
        setattr(instance, field_name, None)
    else:
        setattr(instance, field_name, match)


def _candidate(entity_type, row, existing, source_name, natural_key):
    model = {
        "supplier": Supplier,
        "material": Material,
        "warehouse": Warehouse,
        "inventory": Inventory,
        "purchase_order": PurchaseOrder,
        "shipment": Shipment,
        "disruption": Disruption,
    }[entity_type]
    candidate = model(pk=existing.pk) if existing else model()
    if existing:
        for field in model._meta.concrete_fields:
            if field.primary_key:
                continue
            setattr(candidate, field.attname, getattr(existing, field.attname))

    errors = []
    normalized_code = lambda value: value.strip().upper()

    if entity_type == "supplier":
        _set_value(candidate, row, "code", "code", errors, normalized_code, required=True)
        _set_value(candidate, row, "name", "name", errors, required=True)
        _set_value(candidate, row, "country", "country", errors)
        _set_value(candidate, row, "region", "region", errors)
        _set_value(candidate, row, "risk_score", "risk_score", errors, _parse_integer)
        _set_value(candidate, row, "lead_time_days", "lead_time_days", errors, _parse_integer)
        _set_value(candidate, row, "status", "status", errors, str.casefold)
    elif entity_type == "material":
        _set_value(candidate, row, "sku", "sku", errors, normalized_code, required=True)
        _set_value(candidate, row, "name", "name", errors, required=True)
        _set_value(candidate, row, "category", "category", errors)
        _set_value(candidate, row, "unit", "unit", errors, str.upper)
        _set_value(candidate, row, "criticality", "criticality", errors, str.casefold)
        if "preferred_supplier_code" in row:
            _set_reference(candidate, row, "preferred_supplier_code", "preferred_supplier", Supplier, "code", errors)
    elif entity_type == "warehouse":
        _set_value(candidate, row, "code", "code", errors, normalized_code, required=True)
        _set_value(candidate, row, "name", "name", errors, required=True)
        _set_value(candidate, row, "region", "region", errors)
        _set_value(candidate, row, "country", "country", errors)
        _set_value(candidate, row, "warehouse_type", "warehouse_type", errors, str.casefold)
        _set_value(candidate, row, "active", "active", errors, _parse_bool)
    elif entity_type == "inventory":
        _set_reference(candidate, row, "material_sku", "material", Material, "sku", errors, required=True)
        _set_reference(candidate, row, "warehouse_code", "warehouse", Warehouse, "code", errors, required=True)
        if candidate.warehouse:
            candidate.location = candidate.warehouse.name
        _set_value(candidate, row, "quantity", "quantity", errors, _parse_decimal, required=True)
        _set_value(candidate, row, "reorder_point", "reorder_point", errors, _parse_decimal)
        _set_value(candidate, row, "unit_cost", "unit_cost", errors, _parse_decimal)
        for field_name in ("quantity", "reorder_point", "unit_cost"):
            if getattr(candidate, field_name) is not None and getattr(candidate, field_name) < 0:
                errors.append(f"{field_name} cannot be negative.")
    elif entity_type == "purchase_order":
        _set_value(candidate, row, "number", "number", errors, normalized_code, required=True)
        _set_reference(candidate, row, "supplier_code", "supplier", Supplier, "code", errors, required=True)
        _set_reference(candidate, row, "material_sku", "material", Material, "sku", errors, required=True)
        _set_value(candidate, row, "quantity", "quantity", errors, _parse_decimal, required=True)
        _set_value(candidate, row, "expected_date", "expected_date", errors, _parse_date)
        _set_value(candidate, row, "status", "status", errors, str.casefold)
        _set_value(candidate, row, "currency", "currency", errors, str.upper)
        _set_value(candidate, row, "unit_price", "unit_price", errors, _parse_decimal)
        if candidate.quantity not in (None, "") and candidate.quantity <= 0:
            errors.append("quantity must be greater than zero.")
        if candidate.unit_price not in (None, "") and candidate.unit_price < 0:
            errors.append("unit_price cannot be negative.")
        if existing:
            lines = list(existing.lines.order_by("line_number"))
            if len(lines) > 1:
                errors.append("CSV updates support single-line purchase orders only; this order has multiple lines.")
            elif lines and candidate.quantity is not None and lines[0].received_quantity > candidate.quantity:
                errors.append("quantity cannot be lower than the order's received quantity.")
    elif entity_type == "shipment":
        _set_value(candidate, row, "reference", "reference", errors, normalized_code, required=True)
        _set_reference(candidate, row, "purchase_order_number", "purchase_order", PurchaseOrder, "number", errors, required=True)
        _set_value(candidate, row, "origin", "origin", errors, required=True)
        _set_value(candidate, row, "destination", "destination", errors, required=True)
        _set_value(candidate, row, "carrier", "carrier", errors)
        _set_value(candidate, row, "eta", "eta", errors, _parse_date)
        _set_value(candidate, row, "status", "status", errors, str.casefold)
        _set_value(candidate, row, "risk_score", "risk_score", errors, _parse_integer)
    else:
        _set_value(candidate, row, "title", "title", errors, required=True)
        _set_value(candidate, row, "disruption_type", "disruption_type", errors)
        _set_value(candidate, row, "description", "description", errors)
        _set_value(candidate, row, "affected_region", "affected_region", errors)
        _set_value(candidate, row, "severity", "severity", errors, str.casefold, required=True)
        _set_value(candidate, row, "status", "status", errors, str.casefold)
        _set_value(candidate, row, "confidence", "confidence", errors, _parse_integer)
        _set_reference(candidate, row, "affected_supplier_code", "affected_supplier", Supplier, "code", errors)
        _set_reference(candidate, row, "shipment_reference", "affected_shipment", Shipment, "reference", errors)

    if "source_key" in row and row["source_key"]:
        if len(row["source_key"]) > 160:
            errors.append("source_key must be 160 characters or fewer.")
        else:
            candidate.source_key = row["source_key"].strip()
    elif not existing or not candidate.source_key:
        candidate.source_key = natural_key[:160]
    if entity_type == "disruption" and not candidate.source_key:
        errors.append("source_key is required for repeatable disruption imports.")
    candidate.source_name = source_name
    if "source_updated_at" in row and row["source_updated_at"]:
        try:
            candidate.source_updated_at = _parse_source_timestamp(row["source_updated_at"])
        except ValueError as exc:
            errors.append(f"source_updated_at: {exc}.")
    elif "source_updated_at" in row and not existing:
        candidate.source_updated_at = None

    try:
        candidate.full_clean(validate_unique=False, validate_constraints=True)
    except ValidationError as exc:
        if hasattr(exc, "message_dict"):
            for field, messages in exc.message_dict.items():
                errors.extend(f"{field}: {message}" for message in messages)
        else:
            errors.extend(exc.messages)
    return candidate, list(dict.fromkeys(errors))


def _natural_key(entity_type, row):
    if entity_type == "supplier":
        return row.get("code", "").strip().upper()
    if entity_type == "material":
        return row.get("sku", "").strip().upper()
    if entity_type == "warehouse":
        return row.get("code", "").strip().upper()
    if entity_type == "inventory":
        material = row.get("material_sku", "").strip().upper()
        warehouse = row.get("warehouse_code", "").strip().upper()
        return f"{material}|{warehouse}" if material and warehouse else ""
    if entity_type == "purchase_order":
        return row.get("number", "").strip().upper()
    if entity_type == "shipment":
        return row.get("reference", "").strip().upper()
    return row.get("source_key", "").strip()


def _existing_record(entity_type, row, source_name, lock=False):
    if entity_type == "supplier":
        queryset = Supplier.objects.filter(code__iexact=row.get("code", "").strip())
    elif entity_type == "material":
        queryset = Material.objects.filter(sku__iexact=row.get("sku", "").strip())
    elif entity_type == "warehouse":
        queryset = Warehouse.objects.filter(code__iexact=row.get("code", "").strip())
    elif entity_type == "inventory":
        queryset = Inventory.objects.filter(
            material__sku__iexact=row.get("material_sku", "").strip(),
            warehouse__code__iexact=row.get("warehouse_code", "").strip(),
        )
    elif entity_type == "purchase_order":
        queryset = PurchaseOrder.objects.filter(number__iexact=row.get("number", "").strip())
    elif entity_type == "shipment":
        queryset = Shipment.objects.filter(reference__iexact=row.get("reference", "").strip())
    else:
        queryset = Disruption.objects.filter(
            source_name__iexact=source_name.strip(),
            source_key__iexact=row.get("source_key", "").strip(),
        )
    if lock:
        queryset = queryset.select_for_update()
    matches = list(queryset[:2])
    if len(matches) > 1:
        return None, "The natural key matches multiple existing records; resolve the duplicate keys first."
    return (matches[0] if matches else None), None


def _validated_row(entity_type, row, source_name, duplicate_policy, lock=False):
    key = _natural_key(entity_type, row)
    existing, lookup_error = _existing_record(entity_type, row, source_name, lock=lock) if key else (None, None)
    candidate, errors = _candidate(entity_type, row, existing, source_name, key)
    if lookup_error:
        errors.append(lookup_error)
    if existing and duplicate_policy == "error":
        errors.append("A record with this natural key already exists.")
    action = "error" if errors else "skip" if existing and duplicate_policy == "skip" else "update" if existing else "create"
    return {"natural_key": key, "candidate": candidate, "existing": existing, "action": action, "errors": list(dict.fromkeys(errors))}


@transaction.atomic
def create_preview(entity_type, source_name, duplicate_policy, upload):
    if entity_type not in IMPORT_SCHEMAS:
        raise ImportFileError("Choose a supported import type.")
    source_name = (source_name or "").strip()
    if not source_name:
        raise ImportFileError("Enter a name for the data source.")
    if len(source_name) > 120:
        raise ImportFileError("Data source names must be 120 characters or fewer.")
    if duplicate_policy not in {"skip", "update", "error"}:
        raise ImportFileError("Choose a supported duplicate policy.")

    filename, _headers, rows = parse_csv_upload(upload, entity_type)
    previews = [_validated_row(entity_type, row, source_name, duplicate_policy) for _line, row in rows]
    key_counts = {}
    for preview in previews:
        if preview["natural_key"]:
            folded_key = preview["natural_key"].casefold()
            key_counts[folded_key] = key_counts.get(folded_key, 0) + 1
    for preview in previews:
        if preview["natural_key"] and key_counts.get(preview["natural_key"].casefold(), 0) > 1:
            preview["errors"].append("This natural key appears more than once in the CSV.")
            preview["action"] = "error"

    batch = DataImport.objects.create(
        entity_type=entity_type,
        source_name=source_name,
        file_name=filename,
        duplicate_policy=duplicate_policy,
        total_rows=len(rows),
        created_rows=sum(preview["action"] == "create" for preview in previews),
        updated_rows=sum(preview["action"] == "update" for preview in previews),
        skipped_rows=sum(preview["action"] == "skip" for preview in previews),
        error_rows=sum(preview["action"] == "error" for preview in previews),
    )
    DataImportRow.objects.bulk_create([
        DataImportRow(
            batch=batch,
            row_number=line_number,
            natural_key=preview["natural_key"],
            action=preview["action"],
            errors=preview["errors"],
            raw_data=row,
        )
        for (line_number, row), preview in zip(rows, previews)
    ])
    return batch


def _apply_candidate(entity_type, candidate, existing, batch):
    if entity_type == "inventory":
        previous_quantity = existing.quantity if existing else None
        candidate.save()
        if existing and previous_quantity != candidate.quantity:
            delta = candidate.quantity - previous_quantity
            InventoryMovement.objects.create(
                inventory=candidate,
                movement_type="adjustment",
                quantity_delta=delta,
                balance_after=candidate.quantity,
                reference=f"CSV-{str(batch.pk)[:12]}",
                notes=f"Inventory balance imported from {batch.source_name}.",
                actor="csv-import",
            )
        return candidate

    candidate.save()
    if entity_type == "purchase_order":
        existing_line = existing.lines.order_by("line_number").first() if existing else None
        if existing_line:
            existing_line.material = candidate.material
            existing_line.quantity = candidate.quantity
            existing_line.unit_price = candidate.unit_price
            existing_line.save(update_fields=["material", "quantity", "unit_price", "updated_at"])
        else:
            PurchaseOrderLine.objects.create(
                purchase_order=candidate,
                line_number=1,
                material=candidate.material,
                quantity=candidate.quantity,
                unit_price=candidate.unit_price,
            )
    return candidate


@transaction.atomic
def commit_preview(batch_id):
    try:
        batch = DataImport.objects.select_for_update().get(pk=batch_id)
    except DataImport.DoesNotExist as exc:
        raise ImportCommitError("Import preview was not found.") from exc
    if batch.status != "preview":
        raise ImportCommitError("This import has already been committed.")
    rows = list(batch.rows.select_for_update().order_by("row_number"))
    preview_errors = [row for row in rows if row.action == "error"]
    if preview_errors:
        raise ImportCommitError("Resolve all preview errors before committing this import.", [
            {"row_number": row.row_number, "natural_key": row.natural_key, "errors": row.errors}
            for row in preview_errors
        ])

    prepared = []
    conflicts = []
    for import_row in rows:
        result = _validated_row(batch.entity_type, import_row.raw_data, batch.source_name, batch.duplicate_policy, lock=True)
        if result["errors"]:
            conflicts.append({"row_number": import_row.row_number, "natural_key": result["natural_key"], "errors": result["errors"]})
        else:
            prepared.append((import_row, result))
    if conflicts:
        raise ImportCommitError("The data changed after preview. Review a new preview before committing.", conflicts)

    counts = {"created": 0, "updated": 0, "skipped": 0}
    for import_row, result in prepared:
        action = result["action"]
        if action == "skip":
            import_row.action = "skipped"
            import_row.record_id = result["existing"].pk
            counts["skipped"] += 1
        else:
            record = _apply_candidate(batch.entity_type, result["candidate"], result["existing"], batch)
            import_row.action = "updated" if action == "update" else "created"
            import_row.record_id = record.pk
            counts["updated" if action == "update" else "created"] += 1
        import_row.save(update_fields=["action", "record_id"])

    batch.status = "committed"
    batch.created_rows = counts["created"]
    batch.updated_rows = counts["updated"]
    batch.skipped_rows = counts["skipped"]
    batch.error_rows = 0
    batch.completed_at = timezone.now()
    batch.save(update_fields=[
        "status", "created_rows", "updated_rows", "skipped_rows", "error_rows", "completed_at", "updated_at",
    ])
    return batch


def serialize_import_row(row):
    return {
        "row_number": row.row_number,
        "natural_key": row.natural_key,
        "action": row.action,
        "errors": row.errors,
        "record_id": str(row.record_id) if row.record_id else None,
    }


def serialize_import(batch, include_rows=False):
    payload = {
        "id": str(batch.pk),
        "entity_type": batch.entity_type,
        "source_name": batch.source_name,
        "file_name": batch.file_name,
        "duplicate_policy": batch.duplicate_policy,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "created_rows": batch.created_rows,
        "updated_rows": batch.updated_rows,
        "skipped_rows": batch.skipped_rows,
        "error_rows": batch.error_rows,
        "created_at": batch.created_at,
        "completed_at": batch.completed_at,
    }
    if include_rows:
        payload["rows"] = [serialize_import_row(row) for row in batch.rows.all()]
    return payload
