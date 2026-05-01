import json
import os
from decimal import Decimal, InvalidOperation

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def handle(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "invalid request body"}),
        }

    category_id = body.get("id")
    name = body.get("name")
    rate = body.get("rate")

    if not category_id or not name or rate is None:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "id, name, and rate are required"}),
        }

    try:
        rate_decimal = Decimal(str(rate))
    except InvalidOperation:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "rate must be a number"}),
        }

    item = {
        "pk": "TAXCAT",
        "sk": f"CAT#{category_id}",
        "name": name,
        "rate": rate_decimal,
    }

    if body.get("description"):
        item["description"] = body["description"]

    try:
        table.put_item(Item=item)
    except Exception:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to save tax category"}),
        }

    return {"statusCode": 200, "body": json.dumps({"id": category_id, "name": name})}
