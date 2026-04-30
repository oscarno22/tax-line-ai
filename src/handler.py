import json
import requests


def lambda_handler(event, context):
    route = event.get("routeKey", "")

    if route == "GET /health":
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "ok"}),
        }

    if route == "GET /joke":
        return {
            "statusCode": 200,
            "body": json.dumps({"requests_version": requests.__version__}),
        }

    return {"statusCode": 404, "body": json.dumps({"error": "Not found"})}
