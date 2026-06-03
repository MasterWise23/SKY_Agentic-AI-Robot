from flask import Flask, request, jsonify
from flask_cors import CORS
import vosk
import wave
import json
import requests as req
import os
import tempfile

app = Flask(__name__)
CORS(app)  # Allow tablet requests

# Vosk model path
VOSK_MODEL_PATH = r"C:\Users\stf12\PycharmProjects\pythonProject\vosk-model-small-en-us-0.15"
vosk_model = vosk.Model(VOSK_MODEL_PATH)

conversation_history = [
    {
        "role": "system",
        "content": """You are Sky, a medical assistant robot.
        Reply in ONE short sentence only. Max 15 words.
        Be warm and helpful."""
    }
]

# Emergency keywords
EMERGENCY_KEYWORDS = ["help", "emergency", "pain", "falling", "bleeding", "chest", "unconscious"]


# PROCESARE AUDIO

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


# OLLAMA

def check_emergency(text):
    return any(kw in text.lower() for kw in EMERGENCY_KEYWORDS)

def get_response(user_input):
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

        conversation_history.append({
            "role": "assistant",
            "content": answer
        })

        # Keep history bounded
        while len(conversation_history) > 8:
            conversation_history.pop(1)

        return answer

    except Exception as e:
        print("Ollama error:", e)
        return "I am having a technical issue. Please call a nurse."


# ENDPOINTS

@app.route('/talk', methods=['POST'])
def talk():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_file = request.files['audio']

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
        os.unlink(tmp_path)


@app.route('/emergency', methods=['POST'])
def emergency():
    data = request.get_json() or {}
    message = data.get("message", "Emergency alert from tablet")
    print(f"[EMERGENCY ALERT] {message}")
    return jsonify({
        "status": "alert_sent",
        "message": "Emergency alert received"
    })


@app.route('/status', methods=['GET'])
def status():
    return jsonify({"status": "Sky is running"})


# MAIN

if __name__ == "__main__":
    import socket
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