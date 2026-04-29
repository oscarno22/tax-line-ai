import json


def lambda_handler(event, context):
    route = event.get("routeKey", "")

    if route == "GET /health":
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "ok"}),
        }

    return {"statusCode": 404, "body": json.dumps({"error": "Not found"})}
