import base64
import io
import os
from typing import List

from agents import Agent, Runner, function_tool
from openai import OpenAI

import tools as invoice_tools
from models import ClassifiedLineItemInput, ExtractedInvoice

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

_EXTRACT_SYSTEM = """
Extract all line items from this invoice.
Return the vendor name and every line item with description, quantity, unit price, and subtotal.
"""  # noqa: E501

_CLASSIFY_SYSTEM = """
You are a tax classification agent for RetailCo.
Call get_tax_categories to see available categories, classify each line item,
compute tax amounts (tax_amount = subtotal * tax_rate),
then call save_invoice_result with the complete result.
"""


@function_tool
def get_tax_categories() -> List[dict]:
    """Fetch all available tax categories and their rates from the database."""
    return invoice_tools.get_tax_categories()


def _extract(file_bytes: bytes, content_type: str) -> ExtractedInvoice:
    file_id = None

    if content_type.startswith("image/"):
        b64 = base64.b64encode(file_bytes).decode()
        user_content = [
            {
                "type": "input_image",
                "image_url": f"data:{content_type};base64,{b64}",
            }
        ]
    elif content_type == "application/pdf":
        # responses api handles pdfs natively via file_id
        uploaded = client.files.create(
            file=("invoice.pdf", io.BytesIO(file_bytes), "application/pdf"),
            purpose="user_data",
        )
        file_id = uploaded.id
        user_content = [{"type": "input_file", "file_id": file_id}]
    else:
        user_content = [
            {"type": "input_text", "text": file_bytes.decode("utf-8", errors="replace")}
        ]

    try:
        response = client.responses.parse(
            model="gpt-5",
            instructions=_EXTRACT_SYSTEM,
            input=[{"role": "user", "content": user_content}],
            text_format=ExtractedInvoice,
        )
        return response.output_parsed
    finally:
        if file_id:
            client.files.delete(file_id)


def run(invoice_id: str, file_bytes: bytes, content_type: str) -> None:
    extracted = _extract(file_bytes, content_type)

    @function_tool
    def save_invoice_result(
        line_items: List[ClassifiedLineItemInput],
        subtotal: float,
        total_tax: float,
        total: float,
    ) -> dict:
        """Save the fully classified invoice result. Call once every line item is classified."""  # noqa: E501
        return invoice_tools.save_invoice_result(
            invoice_id=invoice_id,
            line_items=[item.model_dump() for item in line_items],
            subtotal=subtotal,
            total_tax=total_tax,
            total=total,
        )

    agent = Agent(
        name="tax-classifier",
        model="gpt-5",
        instructions=_CLASSIFY_SYSTEM,
        tools=[get_tax_categories, save_invoice_result],
    )

    Runner.run_sync(
        agent,
        f"Invoice ID: {invoice_id}\n\nExtracted line items:\n{extracted.model_dump_json(indent=2)}",  # noqa: E501
    )
