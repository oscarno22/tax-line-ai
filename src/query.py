import json

from repository import repo, to_float


def handle(event):
    # parse invoice_id from path parameter
    invoice_id = (event.get("pathParameters") or {}).get("id")
    if not invoice_id:
        return {"statusCode": 400, "body": json.dumps({"error": "missing invoice id"})}

    try:
        # read current invoice metadata to determine status
        meta = repo.get_metadata(invoice_id)
    except Exception:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to read invoice"}),
        }

    if not meta:
        return {"statusCode": 404, "body": json.dumps({"error": "invoice not found"})}

    status = meta["status"]

    # pending — metadata doesn't exist yet, return early
    if status == "pending":
        return {
            "statusCode": 200,
            "body": json.dumps({"invoice_id": invoice_id, "status": "pending"}),
        }

    # failed — file processing enountered an error
    if status == "failed":
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "invoice_id": invoice_id,
                    "status": "failed",
                    "error": meta.get("error", "processing failed"),
                }
            ),
        }

    try:
        # retrieve invoice result with classifications + totals
        result = repo.get_result(invoice_id)
    except Exception:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to read invoice result"}),
        }

    # to_float converts Decimal values from dynamo for serialization
    body = {
        "invoice_id": invoice_id,
        "status": status,
        "line_items": to_float(result.get("line_items", [])),
        "subtotal": to_float(result.get("subtotal")),
        "total_tax": to_float(result.get("total_tax")),
        "total": to_float(result.get("total")),
    }

    if meta.get("vendor"):
        body["vendor"] = meta["vendor"]

    return {"statusCode": 200, "body": json.dumps(body)}
