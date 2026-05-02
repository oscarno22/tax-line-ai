from decimal import Decimal
from typing import List

from pydantic import BaseModel


# extraction schema
class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    subtotal: float | None = None


class ExtractedInvoice(BaseModel):
    vendor: str | None = None
    line_items: List[LineItem]


class TaxCategory(BaseModel):
    id: str
    name: str
    rate: Decimal
    description: str | None = None


class ClassifiedLineItem(LineItem):
    tax_category: str
    tax_rate: Decimal
    tax_amount: Decimal
    excluded: bool = False


class ClassifiedLineItemInput(LineItem):
    tax_category: str
    tax_rate: float
    tax_amount: float


class SaveResult(BaseModel):
    saved: bool
    invoice_id: str
    status: str


class CorrectionInput(BaseModel):
    line_item_index: int
    tax_category: str
    note: str | None = None


class CorrectionResult(BaseModel):
    corrected: int
    status: str


# FINAL SHAPE WRITTEN TO DYNAMO
class InvoiceResult(BaseModel):
    vendor: str | None = None
    line_items: List[ClassifiedLineItem]
    subtotal: Decimal
    total_tax: Decimal
    total: Decimal
