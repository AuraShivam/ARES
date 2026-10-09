const NAV_GROUPS = [
  {
    title: 'Monitor',
    items: [
      ['overview', 'Overview', '◫'],
      ['disruptions', 'Disruptions', '⌁'],
      ['response-plans', 'Response plans', '✓'],
      ['notifications', 'Notifications', '✉'],
      ['shipments', 'Shipments', '⇢'],
    ],
  },
  {
    title: 'Operations',
    items: [
      ['purchase-orders', 'Purchase orders', '▤'],
      ['inventory', 'Inventory', '▦'],
      ['warehouses', 'Warehouses', '⌂'],
      ['suppliers', 'Suppliers', '♧'],
      ['materials', 'Materials', '◇'],
    ],
  },
  {
    title: 'Records',
    items: [
      ['purchase-order-lines', 'PO line items', '≡'],
      ['inventory-movements', 'Stock movements', '↕'],
      ['audit-events', 'Audit history', '◷'],
    ],
  },
  {
    title: 'Data',
    items: [
      ['imports', 'Data onboarding', '⇧'],
    ],
  },
]

const SECTIONS = {
  overview: { title: 'Network overview', description: 'A supply-chain view refreshed automatically every 30 seconds.' },
  disruptions: { title: 'Disruptions', description: 'Review events, assess exposure, and record a response.' },
  'response-plans': { title: 'Response plans', description: 'Assign, review, approve, and track disruption response work.' },
  notifications: { title: 'Notifications', description: 'Inspect queued and delivered risk and response-plan email.' },
  shipments: { title: 'Shipments', description: 'Track shipment status, routes, and delivery risk.' },
  'purchase-orders': { title: 'Purchase orders', description: 'Review supplier commitments and multi-line order value.' },
  inventory: { title: 'Inventory', description: 'See on-hand stock, reorder thresholds, and warehouse balances.' },
  warehouses: { title: 'Warehouses', description: 'Manage the facilities connected to inventory balances.' },
  suppliers: { title: 'Suppliers', description: 'Review supplier coverage, lead times, and risk profiles.' },
  materials: { title: 'Materials', description: 'Explore material criticality and preferred sourcing.' },
  'purchase-order-lines': { title: 'PO line items', description: 'Inspect the materials and quantities behind each order.' },
  'inventory-movements': { title: 'Stock movements', description: 'Review receipts, issues, and inventory adjustments.' },
  'audit-events': { title: 'Audit history', description: 'See before-and-after snapshots for API changes.' },
  imports: { title: 'Data onboarding', description: 'Preview imports and check external feed freshness.' },
}

const TABLE_COLUMNS = {
  disruptions: [
    ['title', 'Event'], ['disruption_type', 'Type'], ['affected_region', 'Region'],
    ['severity', 'Severity'], ['affected_supplier_name', 'Supplier'], ['status', 'Status'],
    ['created_at', 'Reported'], ['assess', ''],
  ],
  'response-plans': [
    ['title', 'Plan'], ['disruption_title', 'Disruption'], ['owner', 'Owner'],
    ['due_date', 'Due'], ['status', 'Status'], ['action_count', 'Actions'],
    ['reviewed_by', 'Reviewed by'], ['manage_plan', ''],
  ],
  notifications: [
    ['notification_type', 'Event'], ['subject', 'Subject'], ['recipient_email', 'Recipient'],
    ['status', 'Delivery'], ['attempt_count', 'Attempts'], ['sent_at', 'Sent'],
    ['error_code', 'Delivery detail'], ['created_at', 'Queued'],
  ],
  shipments: [
    ['reference', 'Reference'], ['purchase_order_number', 'Purchase order'], ['origin', 'Origin'],
    ['destination', 'Destination'], ['eta', 'ETA'], ['risk_score', 'Risk'], ['status', 'Status'],
  ],
  'purchase-orders': [
    ['number', 'PO number'], ['supplier_name', 'Supplier'], ['line_count', 'Lines'],
    ['expected_date', 'Expected'], ['status', 'Status'], ['total_value', 'Total value'],
  ],
  inventory: [
    ['material_sku', 'SKU'], ['material_name', 'Material'], ['warehouse_name', 'Warehouse'],
    ['location', 'Location'], ['quantity', 'On hand'], ['reorder_point', 'Reorder at'], ['below_reorder_point', 'Signal'],
  ],
  warehouses: [
    ['code', 'Code'], ['name', 'Warehouse'], ['region', 'Region'], ['country', 'Country'],
    ['warehouse_type', 'Type'], ['active', 'Status'],
  ],
  suppliers: [
    ['code', 'Code'], ['name', 'Supplier'], ['region', 'Region'], ['country', 'Country'],
    ['lead_time_days', 'Lead time'], ['risk_score', 'Risk profile'], ['status', 'Status'],
  ],
  materials: [
    ['sku', 'SKU'], ['name', 'Material'], ['category', 'Category'],
    ['criticality', 'Criticality'], ['preferred_supplier_name', 'Preferred supplier'],
  ],
  'purchase-order-lines': [
    ['purchase_order', 'PO reference'], ['line_number', 'Line'], ['material_sku', 'SKU'],
    ['material_name', 'Material'], ['quantity', 'Ordered'], ['received_quantity', 'Received'], ['line_total', 'Line value'],
  ],
  'inventory-movements': [
    ['material_sku', 'SKU'], ['warehouse_name', 'Warehouse'], ['movement_type', 'Movement'],
    ['quantity_delta', 'Change'], ['balance_after', 'Balance after'], ['reference', 'Reference'], ['actor', 'Actor'], ['created_at', 'Recorded'],
  ],
  'audit-events': [
    ['entity_type', 'Record type'], ['action', 'Action'], ['entity_id', 'Record ID'],
    ['actor', 'Actor'], ['created_at', 'Changed'], ['changes', 'Details'],
  ],
  imports: [
    ['source_name', 'Source'], ['entity_type', 'Data type'], ['file_name', 'File'],
    ['status', 'Status'], ['total_rows', 'Rows'], ['created_rows', 'Created'],
    ['updated_rows', 'Updated'], ['skipped_rows', 'Skipped'], ['error_rows', 'Errors'],
    ['created_at', 'Started'],
  ],
}

export { NAV_GROUPS, SECTIONS, TABLE_COLUMNS }
