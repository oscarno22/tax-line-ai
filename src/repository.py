import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

import boto3
from boto3.dynamodb.conditions import Key

from models import (
    ClassifiedLineItemInput,
    CorrectionInput,
    CorrectionResult,
    SaveResult,
    TaxCategory,
)

TABLE_NAME = os.environ["TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")


# boto3 requires Decimal for all numeric types
def _to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    return obj


# converts Decimal back to float before json serialization
def to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, list):
        return [to_float(i) for i in obj]
    if isinstance(obj, dict):
        return {k: to_float(v) for k, v in obj.items()}
    return obj


# excluded items are excluded from totals for further review
def _is_excluded(item: ClassifiedLineItemInput) -> bool:
    return (
        item.tax_category == "unclassified"
        or item.quantity is None
        or item.unit_price is None
        or item.subtotal is None
    )


class InvoiceRepository:
    def __init__(self, table):
        self._table = table

    @staticmethod
    def _pk(invoice_id: str) -> str:
        return f"INVOICE#{invoice_id}"

    def get_tax_categories(self) -> List[TaxCategory]:
        # query all items where pk = "TAXCAT"
        resp = self._table.query(KeyConditionExpression=Key("pk").eq("TAXCAT"))
        return [
            TaxCategory(
                # sk format is "CAT#{id}"
                id=item["sk"].removeprefix("CAT#"),
                name=item["name"],
                rate=item["rate"],
            )
            for item in resp.get("Items", [])
        ]

    def create_invoice(
        self,
        invoice_id: str,
        s3_key: str,
        content_type: str,
        vendor: str | None,
        now: str,
    ) -> None:
        # writes METADATA sk — status starts as "pending"
        item = {
            "pk": self._pk(invoice_id),
            "sk": "METADATA",
            "status": "pending",
            "s3_key": s3_key,
            "content_type": content_type,
            "created_at": now,
            "updated_at": now,
        }
        if vendor:
            item["vendor"] = vendor
        self._table.put_item(Item=item)

    def delete_invoice(self, invoice_id: str) -> None:
        self._table.delete_item(Key={"pk": self._pk(invoice_id), "sk": "METADATA"})

    def get_metadata(self, invoice_id: str) -> dict | None:
        return self._table.get_item(
            Key={"pk": self._pk(invoice_id), "sk": "METADATA"}
        ).get("Item")

    def get_result(self, invoice_id: str) -> dict:
        # returns {} if RESULT sk doesn't exist yet (invoice still pending)
        return self._table.get_item(
            Key={"pk": self._pk(invoice_id), "sk": "RESULT"}
        ).get("Item", {})

    def set_failed(self, invoice_id: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._table.update_item(
            Key={"pk": self._pk(invoice_id), "sk": "METADATA"},
            UpdateExpression="SET #s = :s, #e = :e, updated_at = :t",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":s": "failed", ":e": error, ":t": now},
        )

    def save_invoice_result(
        self,
        invoice_id: str,
        line_items: List[ClassifiedLineItemInput],
    ) -> SaveResult:
        pk = self._pk(invoice_id)
        now = datetime.now(timezone.utc).isoformat()

        # annotate line with with excluded flag
        items_with_flag = [
            {**item.model_dump(), "excluded": _is_excluded(item)} for item in line_items
        ]

        # compute tax totals - excluded line items don't contribute
        valid = [item for item in line_items if not _is_excluded(item)]
        subtotal = sum(item.subtotal for item in valid)
        total_tax = sum(item.tax_amount for item in valid)
        total = subtotal + total_tax

        # write RESULT sk
        self._table.put_item(
            Item={
                "pk": pk,
                "sk": "RESULT",
                "line_items": _to_decimal(items_with_flag),
                "subtotal": Decimal(str(subtotal)),
                "total_tax": Decimal(str(total_tax)),
                "total": Decimal(str(total)),
            }
        )

        # partial if any items were excluded - otherwise complete
        status = "partial" if len(valid) < len(line_items) else "complete"

        # update METADATA sk with new status
        self._table.update_item(
            Key={"pk": pk, "sk": "METADATA"},
            UpdateExpression="SET #s = :s, updated_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status, ":t": now},
        )

        return SaveResult(saved=True, invoice_id=invoice_id, status=status)

    def apply_corrections(
        self,
        invoice_id: str,
        corrections: List[CorrectionInput],
    ) -> CorrectionResult:
        # if no corrections were needed
        if not corrections:
            meta = self.get_metadata(invoice_id) or {}
            return CorrectionResult(corrected=0, status=meta.get("status", "complete"))

        pk = self._pk(invoice_id)
        now = datetime.now(timezone.utc).isoformat()

        # load current RESULT from dynamo
        result_item = self._table.get_item(Key={"pk": pk, "sk": "RESULT"}).get(
            "Item", {}
        )
        line_items = list(result_item.get("line_items", []))
        # build lookup to validate critic-supplied category ids
        categories = {cat.id: cat for cat in self.get_tax_categories()}

        correction_records = []
        corrected_count = 0
        # process each correction from critic
        for c in corrections:
            idx = c.line_item_index
            # correct index is invalid
            if not (0 <= idx < len(line_items)):
                continue
            cat = categories.get(c.tax_category)
            if not cat:
                continue

            rate = float(cat.rate)
            subtotal = float(line_items[idx].get("subtotal") or 0)
            # record correction transition for audit trail
            correction_records.append(
                {
                    "line_item_index": idx,
                    "original_category": line_items[idx].get(
                        "tax_category", "unclassified"
                    ),
                    "corrected_category": c.tax_category,
                    "note": c.note,
                }
            )
            # patch the line item — rate and tax_amount recomputed server-side
            line_items[idx] = {
                **line_items[idx],
                "tax_category": c.tax_category,
                "tax_rate": Decimal(str(rate)),
                "tax_amount": Decimal(str(subtotal * rate)),
                "excluded": False,
            }
            corrected_count += 1

        # no corrections were (successfully) applied
        if not corrected_count:
            meta = self.get_metadata(invoice_id) or {}
            return CorrectionResult(corrected=0, status=meta.get("status", "complete"))

        # write audit records to dynamo
        self._table.put_item(
            Item={
                "pk": pk,
                "sk": "CORRECTIONS",
                "corrections": _to_decimal(correction_records),
                "corrected_at": now,
            }
        )

        # recompute totals from patched line_items
        valid = [item for item in line_items if not item.get("excluded", False)]
        subtotal = sum(float(item.get("subtotal") or 0) for item in valid)
        total_tax = sum(float(item.get("tax_amount") or 0) for item in valid)

        # overwrite RESULT with corrected line items + new totals
        self._table.put_item(
            Item={
                "pk": pk,
                "sk": "RESULT",
                "line_items": line_items,
                "subtotal": Decimal(str(subtotal)),
                "total_tax": Decimal(str(total_tax)),
                "total": Decimal(str(subtotal + total_tax)),
            }
        )

        # upgrade partial if all line items are now valid
        status = "complete" if len(valid) == len(line_items) else "partial"
        self._table.update_item(
            Key={"pk": pk, "sk": "METADATA"},
            UpdateExpression="SET #s = :s, updated_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status, ":t": now},
        )

        return CorrectionResult(corrected=corrected_count, status=status)


repo = InvoiceRepository(dynamodb.Table(TABLE_NAME))
