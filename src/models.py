from decimal import Decimal
from typing import List

from pydantic import BaseModel


# extraction schema for invoice items
class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    subtotal: float | None = None


# extracted invoice items + vendor name
class ExtractedInvoice(BaseModel):
    vendor: str | None = None
    line_items: List[LineItem]


# tax category shape
class TaxCategory(BaseModel):
    id: str
    name: str
    rate: Decimal


# agent input shape for classified line items
class ClassifiedLineItemInput(LineItem):
    tax_category: str
    tax_rate: float
    tax_amount: float


# stored shape in dynamo for classified line items
class ClassifiedLineItem(LineItem):
    tax_category: str
    tax_rate: Decimal
    tax_amount: Decimal
    excluded: bool = False


# agent result after save_invoice_result tool call
class SaveResult(BaseModel):
    saved: bool
    invoice_id: str
    status: str


# one correction from the critic agent
class CorrectionInput(BaseModel):
    line_item_index: int
    tax_category: str
    note: str | None = None


# number of critic corrections + final status
class CorrectionResult(BaseModel):
    corrected: int
    status: str


# final shape written to dynamo
class InvoiceResult(BaseModel):
    vendor: str | None = None
    line_items: List[ClassifiedLineItem]
    subtotal: Decimal
    total_tax: Decimal
    total: Decimal
