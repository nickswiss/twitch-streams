import json

def handle_disconnect(event, context):
    print("Received event: " + json.dumps(event, indent=2))
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Disconnected!"
        }),
    }