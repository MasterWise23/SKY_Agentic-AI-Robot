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
CORS(app)

VOSK_MODEL_PATH = r"C:\Users\stf12\PycharmProjects\pythonProject\vosk-model-small-en-us-0.15"
vosk_model = vosk.Model(VOSK_MODEL_PATH)

print("Loading YOLO model...")
yolo_model = YOLO("yolov8n.pt")
print("YOLO ready!")

current_emotion_global = {"emotion": "neutral"}

RELEVANT_OBJECTS = {
    0: "person", 56: "chair", 57: "couch", 59: "bed",
    60: "dining table", 74: "clock", 62: "tv",
    39: "bottle", 41: "cup", 43: "bowl",
    44: "fork", 45: "knife", 46: "spoon",
    47: "apple", 48: "sandwich", 49: "orange",
    50: "broccoli", 51: "carrot", 52: "hot dog",
    53: "pizza", 54: "donut", 55: "cake",
}

conversation_history = [
    {
        "role": "system",
        "content": "You are Sky, a medical assistant robot. Reply in ONE short sentence only. Max 15 words. Be warm and helpful."
    }
]

EMERGENCY_KEYWORDS = ["help", "emergency", "pain", "falling", "bleeding", "chest", "unconscious"]

def transcribe_audio(audio_path):
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
    return any(kw in text.lower() for kw in EMERGENCY_KEYWORDS)

def get_response(user_input, emotion=None, objects=None):
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
        while len(conversation_history) > 8:
            conversation_history.pop(1)
        return answer
    except Exception as e:
        print("Ollama error:", e)
        return "I am having a technical issue. Please call a nurse."

def analyze_image(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return [], "unknown"
    detected_objects = []
    try:
        results = yolo_model(frame, verbose=False, conf=0.4)
        for result in results:
            for box in result.boxes:
                cls = int(box.cls[0])
                if cls in RELEVANT_OBJECTS:
                    detected_objects.append(RELEVANT_OBJECTS[cls])
        detected_objects = list(set(detected_objects))
    except Exception as e:
        print(f"YOLO error: {e}")
    emotion = "unknown"
    try:
        analysis = DeepFace.analyze(frame, actions=["emotion"], enforce_detection=False, silent=True)
        if analysis:
            emotion = analysis[0]["dominant_emotion"]
            current_emotion_global["emotion"] = emotion
    except Exception as e:
        print(f"DeepFace error: {e}")
    return detected_objects, emotion

@app.route("/talk", methods=["POST"])
def talk():
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
        os.unlink(tmp_path)

@app.route("/analyze", methods=["POST"])
def analyze():
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400
    image_bytes = request.files["image"].read()
    objects, emotion = analyze_image(image_bytes)
    print(f"Objects: {objects}, Emotion: {emotion}")
    return jsonify({"objects": objects, "emotion": emotion, "status": "ok"})

@app.route("/talk_with_vision", methods=["POST"])
def talk_with_vision():
    emotion = "unknown"
    objects = []
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
        return jsonify({"text": text, "response": response, "emotion": emotion, "objects": objects, "emergency": check_emergency(text)})
    finally:
        os.unlink(tmp_path)

@app.route("/emergency", methods=["POST"])
def emergency():
    data = request.get_json() or {}
    message = data.get("message", "Emergency alert from tablet")
    print(f"[EMERGENCY ALERT] {message}")
    return jsonify({"status": "alert_sent"})

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "Sky is running"})

@app.route("/emotion", methods=["GET"])
def get_emotion():
    return jsonify(current_emotion_global)

@app.route("/set_emotion", methods=["POST"])
def set_emotion():
    data = request.get_json() or {}
    emotion = data.get("emotion", "neutral")
    current_emotion_global["emotion"] = emotion
    print(f"Emotion set to: {emotion}")
    return jsonify({"status": "ok", "emotion": emotion})

if __name__ == "__main__":
    import socket
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