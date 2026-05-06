import base64
import io
import json
import logging
import os
from typing import List

from agents import Agent, Runner, function_tool
from openai import OpenAI

from models import (
    ClassifiedLineItemInput,
    CorrectionInput,
    CorrectionResult,
    ExtractedInvoice,
    SaveResult,
    TaxCategory,
)
from repository import repo, to_float

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

_EXTRACT_SYSTEM = """
Determine whether this document is an invoice or purchase order containing line items.
Set is_invoice to true only if the document clearly contains purchasable line items with prices.
Set is_invoice to false for anything else (photos, contracts, receipts without line items, random text, etc).
If is_invoice is true, extract the vendor name and every line item with description, quantity, unit price, and subtotal.
If is_invoice is false, return empty line_items.
"""  # noqa: E501

_CLASSIFY_SYSTEM = """
You are a tax classification agent for RetailCo.
Call get_tax_categories to see available categories, classify each line item,
compute tax amounts (tax_amount = subtotal * tax_rate),
then call save_invoice_result with all line items.
If a line item does not clearly fit any available category, use the 'unclassified' category.
If a line item's quantity, unit_price, or subtotal could not be read, set those fields to null.
"""  # noqa: E501

_CRITIC_SYSTEM = """
You are a tax classification critic for RetailCo.
Review the classifier agent's output and correct clear errors before the result is finalised.

Steps:
1. Call get_tax_categories to fetch all valid categories and their rates.
2. Review each line item (0-indexed) for:
   - Category plausibility: does the description match the assigned category?
     Example of a clear error: dog food classified as electronics.
   - Rate sanity: verify tax_rate matches the rate for the assigned category.
   - Excluded item recovery: if tax_category is 'unclassified', attempt to assign the best matching category.
   - Numeric consistency: does quantity x unit_price ≈ subtotal? Note issues but but do not correct numeric fields.
3. If corrections are needed, call correct_invoice_result once with all corrections.
   If everything looks correct, do not call correct_invoice_result.

Only correct obvious errors. Do not second-guess borderline or plausible classifications.
"""  # noqa: E501


@function_tool
def get_tax_categories() -> List[TaxCategory]:
    """Fetch all available tax categories and their rates from the database."""
    return repo.get_tax_categories()


def _extract(file_bytes: bytes, content_type: str) -> ExtractedInvoice:
    file_id = None

    if content_type.startswith("image/"):
        # encode image as base64 data url for vision input
        b64 = base64.b64encode(file_bytes).decode()
        user_content = [
            {
                "type": "input_image",
                "image_url": f"data:{content_type};base64,{b64}",
            }
        ]
    elif content_type == "application/pdf":
        # responses api handles pdfs directly
        uploaded = client.files.create(
            file=("invoice.pdf", io.BytesIO(file_bytes), "application/pdf"),
            purpose="user_data",
        )
        file_id = uploaded.id
        user_content = [{"type": "input_file", "file_id": file_id}]
    else:
        # csv / json — decode as plain text
        user_content = [
            {"type": "input_text", "text": file_bytes.decode("utf-8", errors="replace")}
        ]

    try:
        # extract line items, costs, and/or vendor from file
        response = client.responses.parse(
            model="gpt-5",
            instructions=_EXTRACT_SYSTEM,
            input=[{"role": "user", "content": user_content}],
            text_format=ExtractedInvoice,
        )
        result = response.output_parsed
        logger.info(
            "extraction complete vendor=%s items=%d",
            result.vendor,
            len(result.line_items),
        )
        return result
    finally:
        # always delete uploaded file — openai charges for storage
        if file_id:
            client.files.delete(file_id)


def run(invoice_id: str, file_bytes: bytes, content_type: str) -> None:
    logger.info(
        "invoice_id=%s extraction starting content_type=%s", invoice_id, content_type
    )
    extracted = _extract(file_bytes, content_type)

    if not extracted.is_invoice:
        raise ValueError("uploaded file does not appear to be an invoice")

    logger.info(
        "invoice_id=%s classifier starting items=%d",
        invoice_id,
        len(extracted.line_items),
    )

    # avoids passing invoice_id to the agent
    @function_tool
    def save_invoice_result(line_items: List[ClassifiedLineItemInput]) -> SaveResult:
        """Save the fully classified invoice result. Call once every line item is classified."""  # noqa: E501
        return repo.save_invoice_result(
            invoice_id=invoice_id,
            line_items=line_items,
        )

    agent = Agent(
        name="tax-classifier",
        model="gpt-5",
        instructions=_CLASSIFY_SYSTEM,
        tools=[get_tax_categories, save_invoice_result],
    )

    # run agent until all line items are classified
    Runner.run_sync(
        agent,
        f"Invoice ID: {invoice_id}\n\nExtracted line items:\n{extracted.model_dump_json(indent=2)}",  # noqa: E501
    )
    logger.info("invoice_id=%s classifier complete", invoice_id)


def run_critic(invoice_id: str) -> None:
    result = repo.get_result(invoice_id)
    if not result or not result.get("line_items"):
        return

    logger.info(
        "invoice_id=%s critic starting items=%d", invoice_id, len(result["line_items"])
    )

    # closure captures invoice_id — same pattern as save_invoice_result above
    @function_tool
    def correct_invoice_result(corrections: List[CorrectionInput]) -> CorrectionResult:
        """Correct misclassified line items. Recomputes totals server-side. Call at most once."""  # noqa: E501
        return repo.apply_corrections(invoice_id, corrections)

    critic = Agent(
        name="tax-critic",
        model="gpt-5",
        instructions=_CRITIC_SYSTEM,
        tools=[get_tax_categories, correct_invoice_result],
    )

    # get line items as JSON for readability in critic prompt
    line_items_json = json.dumps(to_float(result.get("line_items", [])), indent=2)
    Runner.run_sync(
        critic,
        f"Invoice ID: {invoice_id}\n\nClassified line items:\n{line_items_json}",
    )
    logger.info("invoice_id=%s critic complete", invoice_id)
