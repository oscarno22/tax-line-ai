import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

import boto3
from boto3.dynamodb.conditions import Key

from models import ClassifiedLineItemInput, SaveResult, TaxCategory

TABLE_NAME = os.environ["TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    return obj


def get_tax_categories() -> List[TaxCategory]:
    resp = table.query(KeyConditionExpression=Key("pk").eq("TAXCAT"))
    return [
        TaxCategory(
            id=item["sk"].removeprefix("CAT#"),
            name=item["name"],
            rate=item["rate"],
            description=item.get("description"),
        )
        for item in resp.get("Items", [])
    ]


def save_invoice_result(
    invoice_id: str,
    line_items: List[ClassifiedLineItemInput],
    subtotal: float,
    total_tax: float,
    total: float,
) -> SaveResult:
    pk = f"INVOICE#{invoice_id}"
    now = datetime.now(timezone.utc).isoformat()

    table.put_item(
        Item={
            "pk": pk,
            "sk": "RESULT",
            "line_items": _to_decimal([item.model_dump() for item in line_items]),
            "subtotal": Decimal(str(subtotal)),
            "total_tax": Decimal(str(total_tax)),
            "total": Decimal(str(total)),
        }
    )

    has_unclassified = any(item.tax_category == "unclassified" for item in line_items)
    status = "partial" if has_unclassified else "complete"

    table.update_item(
        Key={"pk": pk, "sk": "METADATA"},
        UpdateExpression="SET #s = :s, updated_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":t": now},
    )

    return SaveResult(saved=True, invoice_id=invoice_id, status=status)
