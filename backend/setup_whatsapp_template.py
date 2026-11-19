import os
from pathlib import Path

from dotenv import load_dotenv, set_key
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client
from twilio.rest.content.v1 import ContentList


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
CONTENT_SID_KEY = "TWILIO_WHATSAPP_CONTENT_SID"
TEMPLATE_NAME = "bootcoding_candidate_notification"
TEMPLATE_BODY = (
    "Hello {{1}}, thank you for contacting Bootcoding. "
    "Our HR team will get back to you soon."
)


def main() -> None:
    load_dotenv(ENV_PATH)
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        raise SystemExit("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env.")

    if os.getenv(CONTENT_SID_KEY):
        raise SystemExit(
            f"{CONTENT_SID_KEY} is already set. Refusing to create a duplicate template."
        )

    client = Client(account_sid, auth_token)

    try:
        content = client.content.v1.contents.create(
            content_create_request=ContentList.ContentCreateRequest(
                {
                    "friendly_name": TEMPLATE_NAME,
                    "language": "en",
                    "variables": {"1": "Candidate Name"},
                    "types": {
                        "twilio/text": {
                            "body": TEMPLATE_BODY,
                        }
                    },
                }
            )
        )
    except TwilioRestException as error:
        detail = f"Twilio could not create the template: {error.msg}"
        if error.code is not None:
            detail = f"Twilio could not create the template (code {error.code}): {error.msg}"
        raise SystemExit(detail) from error

    if not content.sid:
        raise SystemExit("Twilio created the template but returned no Content SID.")

    set_key(str(ENV_PATH), CONTENT_SID_KEY, content.sid)
    print(f"Template created. Content SID saved to {CONTENT_SID_KEY} in .env.")

    content_resource = client.content.v1.contents(content.sid)
    approval_request = content_resource.approval_create.ContentApprovalRequest(
        {
            "name": TEMPLATE_NAME,
            "category": "UTILITY",
        }
    )

    try:
        approval = content_resource.approval_create.create(approval_request)
    except TwilioRestException as error:
        detail = f"Template created, but approval submission failed: {error.msg}"
        if error.code is not None:
            detail = (
                f"Template created, but approval submission failed "
                f"(code {error.code}): {error.msg}"
            )
        raise SystemExit(detail) from error

    print(f"WhatsApp approval request submitted. Current status: {approval.status or 'unknown'}.")
    print("Wait for WhatsApp review before sending messages with this template.")


if __name__ == "__main__":
    main()
