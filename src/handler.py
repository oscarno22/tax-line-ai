import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from pydantic import BaseModel
from typing import Literal

import presign

load_dotenv()

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


class FactResponse(BaseModel):
    fact: str
    category: str
    confidence: Literal["high", "medium", "low"]


def lambda_handler(event, context):
    route = event.get("routeKey", "")

    if route == "GET /health":
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "ok"}),
        }

    if route == "POST /invoice":
        return presign.handle(event)

    if route == "GET /fact":
        try:
            params = event.get("queryStringParameters") or {}
            topic = params.get("topic", "science")

            completion = client.beta.chat.completions.parse(
                model="gpt-5",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a knowledgeable assistant. Return a single interesting fact "
                            "about the given topic, its category, and your confidence level."
                        ),
                    },
                    {"role": "user", "content": f"Give me a fact about: {topic}"},
                ],
                response_format=FactResponse,
            )

            result = completion.choices[0].message.parsed
            return {
                "statusCode": 200,
                "body": json.dumps(result.model_dump()),
            }
        except Exception as e:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": str(e)}),
            }

    return {"statusCode": 404, "body": json.dumps({"error": "Not found"})}
