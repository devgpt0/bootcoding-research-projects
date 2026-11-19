from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import engine, Base, get_db
from pydantic import BaseModel
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import models
import os
import re
import json

# Load environment variables
load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
whatsapp_content_sid = os.getenv("TWILIO_WHATSAPP_CONTENT_SID")

if not account_sid or not auth_token:
    raise ValueError("Twilio credentials are missing from .env")

client = Client(account_sid, auth_token)

app = FastAPI()

Base.metadata.create_all(bind=engine)


class CandidateCreate(BaseModel):
    name: str
    phone_number: str


class WhatsAppMessage(BaseModel):
    to: str
    message: str


class WhatsAppTemplateMessage(BaseModel):
    to: str
    candidate_name: str


def format_whatsapp_number(phone_number: str) -> str:
    number = phone_number.strip()
    if number.lower().startswith("whatsapp:"):
        number = number[len("whatsapp:"):].strip()

    if not re.fullmatch(r"\+[1-9]\d{7,14}", number):
        raise HTTPException(
            status_code=422,
            detail="Phone numbers must use international format, for example +14155552671."
        )

    return f"whatsapp:{number}"


@app.get("/")
def home():
    return {"message": "WhatsApp Integration Backend is running!"}


@app.get("/candidates")
def get_candidates(db: Session = Depends(get_db)):
    candidates = db.query(models.Candidate).all()
    return candidates


@app.post("/candidates")
def create_candidate(candidate: CandidateCreate, db: Session = Depends(get_db)):
    new_candidate = models.Candidate(
        name=candidate.name,
        phone_number=candidate.phone_number
    )

    db.add(new_candidate)
    db.commit()
    db.refresh(new_candidate)

    return new_candidate


@app.post("/send-whatsapp")
def send_whatsapp(data: WhatsAppMessage):
    if not whatsapp_number:
        raise HTTPException(
            status_code=503,
            detail="TWILIO_WHATSAPP_NUMBER is missing from .env."
        )

    try:
        from_number = format_whatsapp_number(whatsapp_number)
    except HTTPException as e:
        raise HTTPException(
            status_code=503,
            detail="TWILIO_WHATSAPP_NUMBER must be in international format, "
                   "for example whatsapp:+14155238886."
        ) from e

    to_number = format_whatsapp_number(data.to)

    if not data.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    try:
        message = client.messages.create(
            from_=from_number,
            to=to_number,
            body=data.message.strip(),
        )
        return {
            "status": "Message accepted by Twilio",
            "message_sid": message.sid,
            "message_status": message.status,
        }
    except TwilioRestException as e:
        detail = {
            "error_code": e.code,
            "error_message": e.msg,
            "http_status": e.status,
        }
        if e.code == 21608:
            detail["guidance"] = (
                "Trial accounts can message only verified recipient numbers; "
                "verify this recipient in Twilio Console."
            )
        elif e.code == 63015:
            detail["guidance"] = (
                "The recipient may not have joined this WhatsApp Sandbox. "
                "Send the Sandbox join code from that WhatsApp number first."
            )
        elif e.code == 63016:
            detail["guidance"] = (
                "WhatsApp free-form messages require an open 24-hour customer "
                "service window; use an approved template outside that window."
            )
        raise HTTPException(status_code=e.status, detail=detail) from e


@app.post("/send-whatsapp-template")
def send_whatsapp_template(data: WhatsAppTemplateMessage):
    if not whatsapp_number:
        raise HTTPException(
            status_code=503,
            detail="TWILIO_WHATSAPP_NUMBER is missing from .env."
        )

    if not whatsapp_content_sid:
        raise HTTPException(
            status_code=503,
            detail="TWILIO_WHATSAPP_CONTENT_SID is missing from .env. "
                   "Set it to the approved Twilio Content SID."
        )

    if not re.fullmatch(r"HX[0-9a-fA-F]{32}", whatsapp_content_sid):
        raise HTTPException(
            status_code=503,
            detail="TWILIO_WHATSAPP_CONTENT_SID must be a Twilio Content SID "
                   "(HX followed by 32 hexadecimal characters)."
        )

    try:
        from_number = format_whatsapp_number(whatsapp_number)
    except HTTPException as e:
        raise HTTPException(
            status_code=503,
            detail="TWILIO_WHATSAPP_NUMBER must be in international format."
        ) from e

    to_number = format_whatsapp_number(data.to)
    candidate_name = data.candidate_name.strip()
    if not candidate_name:
        raise HTTPException(status_code=422, detail="candidate_name cannot be empty.")

    try:
        message = client.messages.create(
            from_=from_number,
            to=to_number,
            content_sid=whatsapp_content_sid,
            content_variables=json.dumps({"1": candidate_name}),
        )
        return {
            "status": "Template message accepted by Twilio",
            "message_sid": message.sid,
            "message_status": message.status,
        }
    except TwilioRestException as e:
        detail = f"Twilio rejected the template message: {e.msg}"
        if e.code is not None:
            detail = f"Twilio rejected the template message (code {e.code}): {e.msg}"
        if e.code == 20003:
            detail += (
                " Check Twilio account authentication and Content API access. "
                "Your earlier template-creation request reported that Content "
                "API creation is unavailable on the Trial plan; use "
                "/send-whatsapp for ordinary Sandbox text testing."
            )
        raise HTTPException(status_code=502, detail=detail) from e


@app.get("/messages/{message_sid}/status")
def get_twilio_message_status(message_sid: str):
    if not re.fullmatch(r"SM[0-9a-fA-F]{32}", message_sid):
        raise HTTPException(status_code=422, detail="Invalid Twilio message SID.")

    try:
        message = client.messages(message_sid).fetch()
        return {
            "message_sid": message.sid,
            "status": message.status,
            "error_code": message.error_code,
            "error_message": message.error_message,
        }
    except TwilioRestException as e:
        detail = f"Twilio status lookup failed: {e.msg}"
        if e.code is not None:
            detail = f"Twilio status lookup failed (code {e.code}): {e.msg}"
        raise HTTPException(status_code=502, detail=detail) from e
