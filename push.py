import json
from pywebpush import webpush, WebPushException

VAPID_PRIVATE_KEY = "YOUR_VAPID_PRIVATE_KEY"
VAPID_PUBLIC_KEY = "YOUR_VAPID_PUBLIC_KEY"

def send_push(subscription, title, body):
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": "mailto:admin@sensus-app.com"},
        )
    except WebPushException as exc:
        print("Web push failed:", exc)
