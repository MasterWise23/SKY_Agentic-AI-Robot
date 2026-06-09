"""
sky_tablet.py — SKY server (lite, audio-only variant)

This is a simplified version of sky_server.py without computer vision.
It runs a Flask REST API that accepts audio from the tablet client (Termux),
transcribes it with Vosk, queries the local Ollama LLM, and returns a response.

Use this variant when:
  - The camera is not available or not needed
  - Running on a lower-spec machine where YOLO/DeepFace are too slow
  - Testing the voice interaction pipeline in isolation

For the full version with YOLOv8, DeepFace, and emotion-aware responses,
see sky_server.py.

Requirements: flask, flask-cors, vosk, requests
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import vosk
import wave
import json
import requests as req
import os
import tempfile

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from the tablet client

# ── Configuration ──────────────────────────────────────────────────────────────
# Update VOSK_MODEL_PATH to match your local installation.
# See config.example.py for all configurable variables.
VOSK_MODEL_PATH = r"C:\Users\stf12\PycharmProjects\pythonProject\vosk-model-small-en-us-0.15"
vosk_model = vosk.Model(VOSK_MODEL_PATH)

# ── Conversation history ───────────────────────────────────────────────────────
# Rolling list of messages sent to Ollama for context-aware responses.
# The system prompt defines SKY's personality and response constraints.
conversation_history = [
    {
        "role": "system",
        "content": (
            "You are Sky, a medical assistant robot. "
            "Reply in ONE short sentence only. Max 15 words. "
            "Be warm and helpful."
        )
    }
]

# Words that immediately trigger an emergency response, bypassing the LLM.
EMERGENCY_KEYWORDS = ["help", "emergency", "pain", "falling", "bleeding", "chest", "unconscious"]


# ── Helper functions ───────────────────────────────────────────────────────────

def transcribe_audio(audio_path):
    """
    Transcribe a WAV audio file to text using Vosk (offline STT).
    Reads the file in 4000-frame chunks to handle recordings of any length.
    Returns the full transcribed string, or an empty string if nothing was heard.
    """
    wf = wave.open(audio_path, "rb")
    recognizer = vosk.KaldiRecognizer(vosk_model, wf.getframerate())

    result_text = ""
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            result_text += result.get("text", "")

    # Flush any remaining partial result
    final = json.loads(recognizer.FinalResult())
    result_text += final.get("text", "")

    return result_text.strip()


def check_emergency(text):
    """
    Return True if the transcribed text contains any emergency keyword.
    Checked before querying the LLM so the response is immediate.
    """
    return any(kw in text.lower() for kw in EMERGENCY_KEYWORDS)


def get_response(user_input):
    """
    Send the patient's message to the local Ollama LLM and return the reply.
    Maintains a rolling conversation history (max 8 messages) for context.
    Falls back to a static safe message if Ollama is unreachable.
    """
    conversation_history.append({
        "role": "user",
        "content": user_input
    })

    try:
        response = req.post("http://localhost:11434/api/chat", json={
            "model": "llama3.2:1b",
            "messages": conversation_history,
            "stream": False,
            "options": {
                "num_predict": 50,
                "temperature": 0.5,
                "num_ctx": 512,
            }
        }, timeout=60)

        answer = response.json()["message"]["content"]
        conversation_history.append({"role": "assistant", "content": answer})

        # Keep history bounded — drop oldest user/assistant pairs after the system prompt
        while len(conversation_history) > 8:
            conversation_history.pop(1)

        return answer

    except Exception as e:
        print("Ollama error:", e)
        return "I am having a technical issue. Please call a nurse."


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.route('/talk', methods=['POST'])
def talk():
    """
    Primary voice interaction endpoint.
    Accepts a WAV file uploaded as 'audio' in a multipart form.
    Transcribes speech → checks for emergency → queries LLM.
    Returns: transcribed text, SKY's response, emergency flag.
    """
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_file = request.files['audio']

    # Save to a temporary file — Vosk requires a seekable file, not a stream
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        text = transcribe_audio(tmp_path)
        print(f"Tablet: {text}")

        if not text:
            return jsonify({"response": "I did not understand. Please try again."})

        if check_emergency(text):
            response = "Emergency detected! Call emergency services (911) immediately!"
            print("[EMERGENCY DETECTED]")
        else:
            response = get_response(text)

        print(f"Sky: {response}")

        return jsonify({
            "text": text,
            "response": response,
            "emergency": check_emergency(text)
        })

    finally:
        os.unlink(tmp_path)  # Always clean up the temporary audio file


@app.route('/emergency', methods=['POST'])
def emergency():
    """
    Manual emergency alert endpoint.
    Called when the user taps an emergency button on the tablet or phone app.
    Logs the alert server-side. Can be extended to notify external services.
    """
    data = request.get_json() or {}
    message = data.get("message", "Emergency alert from tablet")
    print(f"[EMERGENCY ALERT] {message}")
    return jsonify({
        "status": "alert_sent",
        "message": "Emergency alert received"
    })


@app.route('/status', methods=['GET'])
def status():
    """Health check endpoint. Used by the tablet to verify server connectivity."""
    return jsonify({"status": "Sky is running"})


# ── Server startup ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket

    # Auto-detect local IP so the tablet knows where to connect
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        local_ip = s.getsockname()[0]
    except:
        local_ip = '0.0.0.0'
    finally:
        s.close()

    print(f"Sky server running on http://{local_ip}:5000")
    print(f"Tablet should connect to: http://{local_ip}:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
