import json
import os
from decimal import Decimal

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _floats(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, list):
        return [_floats(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _floats(v) for k, v in obj.items()}
    return obj


def handle(event):
    invoice_id = (event.get("pathParameters") or {}).get("id")
    if not invoice_id:
        return {"statusCode": 400, "body": json.dumps({"error": "missing invoice id"})}

    pk = f"INVOICE#{invoice_id}"

    try:
        meta = table.get_item(Key={"pk": pk, "sk": "METADATA"}).get("Item")
    except Exception:
        return {"statusCode": 500, "body": json.dumps({"error": "failed to read invoice"})}

    if not meta:
        return {"statusCode": 404, "body": json.dumps({"error": "invoice not found"})}

    status = meta["status"]

    if status == "pending":
        return {"statusCode": 200, "body": json.dumps({"invoice_id": invoice_id, "status": "pending"})}

    if status == "failed":
        return {
            "statusCode": 200,
            "body": json.dumps({"invoice_id": invoice_id, "status": "failed", "error": meta.get("error", "processing failed")}),
        }

    try:
        result = table.get_item(Key={"pk": pk, "sk": "RESULT"}).get("Item", {})
    except Exception:
        return {"statusCode": 500, "body": json.dumps({"error": "failed to read invoice result"})}

    body = {
        "invoice_id": invoice_id,
        "status": "complete",
        "line_items": _floats(result.get("line_items", [])),
        "subtotal": _floats(result.get("subtotal")),
        "total_tax": _floats(result.get("total_tax")),
        "total": _floats(result.get("total")),
    }

    if meta.get("vendor"):
        body["vendor"] = meta["vendor"]

    return {"statusCode": 200, "body": json.dumps(body)}
