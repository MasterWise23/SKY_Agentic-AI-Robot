from flask import Flask, request, jsonify
from flask_cors import CORS
import vosk
import wave
import json
import requests as req
import os
import tempfile
import cv2
import numpy as np
from ultralytics import YOLO
from deepface import DeepFace

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from the tablet client

# ── Model paths and configuration ─────────────────────────────────────────────
# Update VOSK_MODEL_PATH to match your local installation.
# See config.example.py for all configurable variables.
VOSK_MODEL_PATH = r"C:\Users\stf12\PycharmProjects\pythonProject\vosk-model-small-en-us-0.15"
vosk_model = vosk.Model(VOSK_MODEL_PATH)

print("Loading YOLO model...")
yolo_model = YOLO("yolov8n.pt")  # Downloaded automatically on first run
print("YOLO ready!")

# Shared state: holds the most recently detected patient emotion.
# Read by the /emotion endpoint so the ESP32 eye displays can poll it.
current_emotion_global = {"emotion": "neutral"}

# ── YOLO object filter ─────────────────────────────────────────────────────────
# Only report objects relevant in a healthcare environment.
# Keys are COCO class IDs, values are human-readable labels.
RELEVANT_OBJECTS = {
    0: "person", 56: "chair", 57: "couch", 59: "bed",
    60: "dining table", 74: "clock", 62: "tv",
    39: "bottle", 41: "cup", 43: "bowl",
    44: "fork", 45: "knife", 46: "spoon",
    47: "apple", 48: "sandwich", 49: "orange",
    50: "broccoli", 51: "carrot", 52: "hot dog",
    53: "pizza", 54: "donut", 55: "cake",
}

# ── Conversation history ───────────────────────────────────────────────────────
# Keeps the last N messages for context-aware LLM responses.
# The system prompt defines SKY's personality and response style.
conversation_history = [
    {
        "role": "system",
        "content": "You are Sky, a medical assistant robot. Reply in ONE short sentence only. Max 15 words. Be warm and helpful."
    }
]

# Words that immediately trigger an emergency alert response,
# bypassing the LLM entirely for faster reaction time.
EMERGENCY_KEYWORDS = ["help", "emergency", "pain", "falling", "bleeding", "chest", "unconscious"]


# ── Helper functions ───────────────────────────────────────────────────────────

def transcribe_audio(audio_path):
    """
    Transcribe a WAV audio file to text using Vosk (offline STT).
    Reads the file in 4000-frame chunks to handle large recordings.
    Returns the full transcribed string, or an empty string on failure.
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
    final = json.loads(recognizer.FinalResult())
    result_text += final.get("text", "")
    return result_text.strip()


def check_emergency(text):
    """
    Check whether the transcribed text contains any emergency keyword.
    Returns True if an emergency keyword is found, False otherwise.
    """
    return any(kw in text.lower() for kw in EMERGENCY_KEYWORDS)


def get_response(user_input, emotion=None, objects=None):
    """
    Send the patient's message to the local Ollama LLM and return the reply.
    Optionally prepends detected emotion and visible objects as context
    so the LLM can give more relevant responses (e.g. "I see you look sad").
    Maintains a rolling conversation history capped at MAX_CONVERSATION_HISTORY
    to avoid context overflow while preserving recent context.
    Falls back to a safe static message if Ollama is unreachable.
    """
    context = ""
    if emotion and emotion != "unknown":
        context += f"Patient seems {emotion}. "
    if objects:
        context += f"Visible objects: {objects}. "

    conversation_history.append({"role": "user", "content": context + user_input})

    try:
        response = req.post("http://localhost:11434/api/chat", json={
            "model": "llama3.2:1b",
            "messages": conversation_history,
            "stream": False,
            "options": {"num_predict": 50, "temperature": 0.5, "num_ctx": 512}
        }, timeout=60)
        answer = response.json()["message"]["content"]
        conversation_history.append({"role": "assistant", "content": answer})

        # Keep history bounded: remove oldest user/assistant pairs after system prompt
        while len(conversation_history) > 8:
            conversation_history.pop(1)

        return answer

    except Exception as e:
        print("Ollama error:", e)
        return "I am having a technical issue. Please call a nurse."


def analyze_image(image_bytes):
    """
    Run YOLOv8 object detection and DeepFace emotion analysis on a JPEG/PNG frame.
    Accepts raw image bytes (as received from the tablet camera stream).
    Returns a tuple: (list of detected object labels, dominant emotion string).
    Updates current_emotion_global so the /emotion polling endpoint stays current.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return [], "unknown"

    # Object detection — filter to healthcare-relevant COCO classes only
    detected_objects = []
    try:
        results = yolo_model(frame, verbose=False, conf=0.4)
        for result in results:
            for box in result.boxes:
                cls = int(box.cls[0])
                if cls in RELEVANT_OBJECTS:
                    detected_objects.append(RELEVANT_OBJECTS[cls])
        detected_objects = list(set(detected_objects))  # Remove duplicates
    except Exception as e:
        print(f"YOLO error: {e}")

    # Emotion analysis — enforce_detection=False avoids crashes on unclear faces
    emotion = "unknown"
    try:
        analysis = DeepFace.analyze(frame, actions=["emotion"], enforce_detection=False, silent=True)
        if analysis:
            emotion = analysis[0]["dominant_emotion"]
            current_emotion_global["emotion"] = emotion  # Update shared state for ESP32
    except Exception as e:
        print(f"DeepFace error: {e}")

    return detected_objects, emotion


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.route("/talk", methods=["POST"])
def talk():
    """
    Audio-only interaction endpoint.
    Accepts a WAV file uploaded as 'audio' in a multipart form.
    Transcribes speech, checks for emergencies, queries the LLM.
    Returns: transcribed text, SKY's response, emergency flag.
    """
    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_file = request.files["audio"]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        text = transcribe_audio(tmp_path)
        print(f"Tablet: {text}")

        if not text:
            return jsonify({"response": "I did not understand. Please try again."})

        if check_emergency(text):
            response = "Emergency detected! Call emergency services immediately!"
        else:
            response = get_response(text)

        print(f"Sky: {response}")
        return jsonify({"text": text, "response": response, "emergency": check_emergency(text)})
    finally:
        os.unlink(tmp_path)  # Always clean up the temporary audio file


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Image-only analysis endpoint.
    Accepts a JPEG/PNG image uploaded as 'image' in a multipart form.
    Runs YOLOv8 + DeepFace and returns detected objects and dominant emotion.
    Useful for periodic polling from the tablet without audio interaction.
    """
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400

    image_bytes = request.files["image"].read()
    objects, emotion = analyze_image(image_bytes)
    print(f"Objects: {objects}, Emotion: {emotion}")
    return jsonify({"objects": objects, "emotion": emotion, "status": "ok"})


@app.route("/talk_with_vision", methods=["POST"])
def talk_with_vision():
    """
    Combined audio + vision endpoint — the primary interaction mode.
    Accepts both 'audio' (WAV) and optionally 'image' (JPEG/PNG) in a multipart form.
    If an image is provided, vision context (emotion + objects) is injected into the LLM prompt.
    Returns: transcribed text, SKY's response, detected emotion, detected objects, emergency flag.
    """
    emotion = "unknown"
    objects = []

    # Vision is optional — process image first if present
    if "image" in request.files:
        image_bytes = request.files["image"].read()
        objects, emotion = analyze_image(image_bytes)
        print(f"Vision - Objects: {objects}, Emotion: {emotion}")

    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_file = request.files["audio"]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        text = transcribe_audio(tmp_path)
        print(f"Tablet: {text}")

        if not text:
            return jsonify({"response": "I did not understand. Please try again."})

        if check_emergency(text):
            response = "Emergency detected! Call emergency services immediately!"
        else:
            objects_str = ", ".join(objects) if objects else None
            response = get_response(text, emotion=emotion, objects=objects_str)

        print(f"Sky: {response}")
        return jsonify({
            "text": text,
            "response": response,
            "emotion": emotion,
            "objects": objects,
            "emergency": check_emergency(text)
        })
    finally:
        os.unlink(tmp_path)


@app.route("/emergency", methods=["POST"])
def emergency():
    """
    Manual emergency alert endpoint.
    Called by the tablet or phone app when the user triggers an emergency button.
    Logs the alert message server-side. Can be extended to notify external services.
    """
    data = request.get_json() or {}
    message = data.get("message", "Emergency alert from tablet")
    print(f"[EMERGENCY ALERT] {message}")
    return jsonify({"status": "alert_sent"})


@app.route("/status", methods=["GET"])
def status():
    """Health check endpoint. Used by the tablet to verify server connectivity."""
    return jsonify({"status": "Sky is running"})


@app.route("/emotion", methods=["GET"])
def get_emotion():
    """
    Returns the most recently detected patient emotion.
    Polled by the ESP32 eye displays (via WiFi) to update their animations
    in real time based on what the camera sees.
    """
    return jsonify(current_emotion_global)


@app.route("/set_emotion", methods=["POST"])
def set_emotion():
    """
    Manually override the current emotion state.
    Useful for testing the ESP32 eye animations without needing a live camera feed.
    Accepts JSON body: {"emotion": "happy"} (or any DeepFace emotion label).
    """
    data = request.get_json() or {}
    emotion = data.get("emotion", "neutral")
    current_emotion_global["emotion"] = emotion
    print(f"Emotion set to: {emotion}")
    return jsonify({"status": "ok", "emotion": emotion})


# ── Server startup ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket

    # Detect the local IP address so the tablet knows where to connect
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        local_ip = s.getsockname()[0]
    except:
        local_ip = "0.0.0.0"
    finally:
        s.close()

    print(f"Sky server running on http://{local_ip}:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
