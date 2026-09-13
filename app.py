
from flask import Flask, request, Response, render_template, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
from dotenv import load_dotenv
import os
import time


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

app = Flask(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

NGROK_URL = os.getenv("NGROK_URL")
CUSTOMER_PHONE_NUMBER = os.getenv("CUSTOMER_PHONE_NUMBER")


# ============================================================
# VALIDATE CONFIGURATION
# ============================================================

required_variables = {
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_PHONE_NUMBER": TWILIO_PHONE_NUMBER,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "NGROK_URL": NGROK_URL,
    "CUSTOMER_PHONE_NUMBER": CUSTOMER_PHONE_NUMBER,
}

missing_variables = [
    key for key, value in required_variables.items()
    if not value
]

if missing_variables:
    raise RuntimeError(
        "Missing environment variables: "
        + ", ".join(missing_variables)
    )


# Remove trailing slash from NGROK_URL
NGROK_URL = NGROK_URL.rstrip("/")


# ============================================================
# OPENAI CLIENT
# ============================================================

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# TWILIO CLIENT
# ============================================================

twilio_client = Client(
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN
)


# ============================================================
# CONVERSATION DATA
# ============================================================

conversation_data = {
    "status": "Ready",
    "transcript": "",
    "response": "",
    "recording": "",
    "duration": "",
    "call_sid": ""
}


# ============================================================
# DEBUG CONFIGURATION
# ============================================================

print("=" * 60)
print("APPLICATION CONFIGURATION")
print("=" * 60)

print(
    "TWILIO_ACCOUNT_SID:",
    TWILIO_ACCOUNT_SID
)

print(
    "TWILIO_PHONE_NUMBER:",
    TWILIO_PHONE_NUMBER
)

print(
    "CUSTOMER_PHONE_NUMBER:",
    CUSTOMER_PHONE_NUMBER
)

print(
    "NGROK_URL:",
    NGROK_URL
)

print("=" * 60)


# ============================================================
# OPENAI - SPEECH TO TEXT
# ============================================================

def transcribe(audio_file):

    print("Starting transcription...")

    with open(audio_file, "rb") as f:

        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )

    text = transcript.text

    print("USER:", text)

    return text


# ============================================================
# OPENAI - CHAT
# ============================================================

def chat(user_text):

    print("Sending message to OpenAI...")

    response = openai_client.responses.create(
        model="gpt-5.1",
        input=[
            {
                "role": "system",
                "content": (
                    "You are RIA, a helpful and friendly AI "
                    "voice assistant. Keep responses concise "
                    "and natural for a phone conversation."
                )
            },
            {
                "role": "user",
                "content": user_text
            }
        ]
    )

    answer = response.output_text

    print("RIA:", answer)

    return answer


# ============================================================
# OPENAI - TEXT TO SPEECH
# ============================================================

def generate_speech(text):

    output_file = "static/reply.mp3"

    print("Generating speech...")

    os.makedirs("static", exist_ok=True)

    with openai_client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice="alloy",
        input=text
    ) as response:

        response.stream_to_file(output_file)

    print(
        "Speech generated:",
        output_file
    )

    return output_file


# ============================================================
# NGROK HEADER
# ============================================================

@app.after_request
def add_ngrok_skip_header(response):

    response.headers[
        "ngrok-skip-browser-warning"
    ] = "true"

    return response


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# STATUS API
# ============================================================

@app.route("/status")
def status():

    return jsonify(conversation_data)


# ============================================================
# TEST ENDPOINT
# ============================================================

@app.route("/test")
def test():

    return jsonify({
        "success": True,
        "message": "RIA server is running",
        "ngrok_url": NGROK_URL
    })


# ============================================================
# TWILIO VOICE WEBHOOK
# ============================================================

@app.route("/voice", methods=["GET", "POST"])
def voice():

    print("=" * 60)
    print("TWILIO /voice CALLED")
    print("Method:", request.method)
    print("From:", request.form.get("From"))
    print("To:", request.form.get("To"))
    print("Call SID:", request.form.get("CallSid"))
    print("=" * 60)

    conversation_data["status"] = "Connected"

    conversation_data["call_sid"] = (
        request.form.get("CallSid") or ""
    )

    response = VoiceResponse()

    response.say(
        "Hello. This is your Assistant RIA. "
        "How can I help you?",
        voice="alice"
    )

    response.record(
        max_length=300,
        timeout=5,
        play_beep=True,
        trim="trim-silence",

        # Called when recording finishes
        action=NGROK_URL + "/recording_complete",

        # Called when recording is actually available
        recording_status_callback=(
            NGROK_URL +
            "/recording_status"
        ),

        recording_status_callback_method="POST",

        recording_status_callback_event="completed",

        method="POST"
    )

    return Response(
        str(response),
        mimetype="text/xml"
    )


# ============================================================
# RECORDING COMPLETE
#
# This endpoint controls what happens next in the call.
# Processing itself happens in /recording_status.
# ============================================================

@app.route(
    "/recording_complete",
    methods=["POST"]
)
def recording_complete():

    recording_url = request.form.get(
        "RecordingUrl"
    )

    duration = request.form.get(
        "RecordingDuration"
    )

    print("=" * 60)
    print("RECORDING COMPLETE CALLBACK")
    print("Recording URL:", recording_url)
    print("Duration:", duration)
    print("=" * 60)

    conversation_data["status"] = (
        "Processing recording..."
    )

    if duration:
        conversation_data["duration"] = duration

    # Do NOT process the audio here.
    #
    # Twilio documentation says the RecordingUrl
    # may not be accessible yet at this point.
    #
    # Processing is done by /recording_status.

    response = VoiceResponse()

    response.say(
        "Please wait while I process your request."
    )

    response.pause(length=1)

    # Keep call alive while recording is processed.
    response.say(
        "Thank you."
    )

    response.hangup()

    return Response(
        str(response),
        mimetype="text/xml"
    )


# ============================================================
# RECORDING STATUS CALLBACK
# ============================================================

@app.route(
    "/recording_status",
    methods=["POST"]
)
def recording_status():

    recording_url = request.form.get(
        "RecordingUrl"
    )

    recording_sid = request.form.get(
        "RecordingSid"
    )

    recording_status = request.form.get(
        "RecordingStatus"
    )

    duration = request.form.get(
        "RecordingDuration"
    )

    call_sid = request.form.get(
        "CallSid"
    )

    print("=" * 60)
    print("RECORDING STATUS CALLBACK")
    print("Recording SID:", recording_sid)
    print("Recording Status:", recording_status)
    print("Recording URL:", recording_url)
    print("Duration:", duration)
    print("Call SID:", call_sid)
    print("=" * 60)

    if recording_status != "completed":

        print(
            "Recording is not completed yet."
        )

        return ("", 200)


    conversation_data["status"] = (
        "Downloading recording..."
    )

    conversation_data["duration"] = (
        duration or ""
    )

    conversation_data["recording"] = (
        recording_url or ""
    )


    try:

        # ====================================================
        # DOWNLOAD RECORDING
        # ====================================================

        audio_url = recording_url + ".mp3"

        print(
            "Downloading:",
            audio_url
        )

        audio_response = requests.get(
            audio_url,
            auth=HTTPBasicAuth(
                TWILIO_ACCOUNT_SID,
                TWILIO_AUTH_TOKEN
            ),
            timeout=60
        )

        audio_response.raise_for_status()

        audio_file = (
            "call_recording_"
            + str(int(time.time()))
            + ".mp3"
        )

        with open(
            audio_file,
            "wb"
        ) as f:

            f.write(
                audio_response.content
            )

        print(
            "Audio downloaded:",
            audio_file
        )


        # ====================================================
        # SPEECH TO TEXT
        # ====================================================

        conversation_data["status"] = (
            "Transcribing..."
        )

        text = transcribe(
            audio_file
        )

        conversation_data["transcript"] = text


        # ====================================================
        # GPT
        # ====================================================

        conversation_data["status"] = (
            "Generating response..."
        )

        answer = chat(
            text
        )

        conversation_data["response"] = answer


        # ====================================================
        # TEXT TO SPEECH
        # ====================================================

        conversation_data["status"] = (
            "Generating voice..."
        )

        generate_speech(
            answer
        )


        conversation_data["status"] = (
            "Completed"
        )


        # ====================================================
        # CLEANUP
        # ====================================================

        try:

            os.remove(
                audio_file
            )

        except Exception:

            pass


        print("=" * 60)
        print("AI PROCESSING COMPLETED")
        print("=" * 60)

    except Exception as e:

        print("=" * 60)
        print("RECORDING PROCESSING ERROR")
        print("ERROR:", str(e))
        print("=" * 60)

        conversation_data["status"] = (
            "Error"
        )

        conversation_data["response"] = (
            str(e)
        )

    return ("", 200)


# ============================================================
# CALL STATUS CALLBACK
# ============================================================

@app.route(
    "/call_status",
    methods=["POST"]
)
def call_status():

    call_sid = request.form.get(
        "CallSid"
    )

    call_status_value = request.form.get(
        "CallStatus"
    )

    call_duration = request.form.get(
        "CallDuration"
    )

    print("=" * 60)
    print("CALL STATUS")
    print("Call SID:", call_sid)
    print("Status:", call_status_value)
    print("Duration:", call_duration)
    print("=" * 60)

    conversation_data["call_sid"] = (
        call_sid or ""
    )

    return ("", 200)


# ============================================================
# MAKE OUTBOUND CALL
# ============================================================

@app.route("/make_call")
def make_call():

    print("=" * 60)
    print("STARTING OUTBOUND CALL")
    print("To:", CUSTOMER_PHONE_NUMBER)
    print("From:", TWILIO_PHONE_NUMBER)
    print("Webhook:", NGROK_URL + "/voice")
    print("=" * 60)

    try:

        conversation_data["status"] = (
            "Calling..."
        )

        call = twilio_client.calls.create(

            to=CUSTOMER_PHONE_NUMBER,

            from_=TWILIO_PHONE_NUMBER,

            url=NGROK_URL + "/voice",

            method="POST",

            status_callback=(
                NGROK_URL +
                "/call_status"
            ),

            status_callback_method="POST",

            status_callback_event=[
                "initiated",
                "ringing",
                "answered",
                "completed"
            ]
        )

        print("=" * 60)
        print("CALL INITIATED")
        print("Call SID:", call.sid)
        print("Call Status:", call.status)
        print("=" * 60)

        conversation_data["status"] = (
            "Calling"
        )

        conversation_data["call_sid"] = (
            call.sid
        )

        return jsonify({
            "success": True,
            "message": "Call Initiated",
            "call_sid": call.sid,
            "status": call.status
        })

    except Exception as e:

        print("=" * 60)
        print("CALL ERROR")
        print(str(e))
        print("=" * 60)

        conversation_data["status"] = (
            "Call Failed"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# RESET
# ============================================================

@app.route("/reset")
def reset():

    conversation_data["status"] = "Ready"
    conversation_data["transcript"] = ""
    conversation_data["response"] = ""
    conversation_data["recording"] = ""
    conversation_data["duration"] = ""
    conversation_data["call_sid"] = ""

    return jsonify({
        "success": True
    })


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
