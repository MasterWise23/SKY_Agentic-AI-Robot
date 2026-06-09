# SKY — Agentic AI Healthcare Robot

> Final-year Bachelor Project | Robotics Engineering (English) | UTCN Cluj-Napoca

SKY is an agentic AI system designed for non-invasive patient monitoring and assistance in medical environments. It combines local LLM inference, real-time computer vision, speech interaction, and mobile robot control into a single integrated system.

---

## Demo

> 📹 *Demo video coming soon*

---

## System Architecture

> 🖼️ *Architecture diagram coming soon — see `docs/architecture.svg`*

The system is composed of four interconnected layers:

**Personal phone (.NET MAUI)** — the operator interface. Sends motor and servo control commands to the robot via Bluetooth.

**Tablet on robot (Termux)** — the robot's voice and vision interface. Records patient speech and streams it to the server, plays back TTS responses, and streams its camera feed to the server for computer vision processing.

**Windows server (Flask REST API)** — the AI brain. Receives audio and video from the tablet, runs speech recognition, queries the LLM, performs object detection, emotion analysis, and fall detection, then sends responses and emotion data back.

**Robot hardware** — the physical layer. An Arduino Mega controls motors and servos via Bluetooth. Two ESP32 modules drive animated eye displays that react in real time to patient emotions detected by the server.

### Communication

| Link | Protocol | Direction |
|------|----------|-----------|
| Tablet ↔ Server | HTTP / WiFi | Audio + video stream in, text response + emotion data out |
| Server → ESP32 eyes | WiFi | Emotion-driven animation commands |
| Phone → Arduino | Bluetooth (HC-05) | Motor and servo commands |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| LLM | Llama 3.2 via Ollama (local inference) |
| Speech recognition | Vosk STT (offline) |
| Object detection | YOLOv8 |
| Emotion analysis | DeepFace + OpenCV |
| Fall detection | Planned — camera-based |
| Backend | Python Flask REST API |
| Mobile control app | .NET MAUI (C#), Android |
| Voice client | Termux + Termux:API |
| Microcontroller | Arduino Mega |
| Eye displays | ESP32 × 2 (WiFi) |
| Bluetooth | HC-05 module |
| Wheels | Mecanum (omnidirectional) |

---

## Repository Structure

```
SKY_Agentic-AI-Robot/
├── src/
│   ├── sky_server.py        # Flask API — LLM, STT, YOLOv8, DeepFace
│   ├── sky_tablet.py        # Termux client — audio recording and TTS
│   └── sky_test.py          # Development / testing script
├── arduino/
│   ├── CONTROL_BAZA/        # Arduino Mega — motor and servo control
│   ├── COD_OCHI_ESP32/      # ESP32 — animated eye displays
│   ├── HC-05_servo/         # Bluetooth servo control
│   └── motoare_baza_viteza_max/  # Motor speed calibration
├── docs/
│   └── README_TABLET.md     # Tablet setup and connection guide
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com/) with Llama 3.2 pulled: `ollama pull llama3.2`
- Arduino IDE for flashing `.ino` files
- Android tablet with Termux + Termux:API installed
- Android phone with the .NET MAUI control app

### Server (Windows)

```bash
git clone https://github.com/MasterWise23/SKY_Agentic-AI-Robot.git
cd SKY_Agentic-AI-Robot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Download the Vosk model:
```bash
# Download vosk-model-small-en-us-0.15 from https://alphacephei.com/vosk/models
# Extract to project root
```

Start the server:
```bash
python src/sky_server.py
```

### Tablet (Termux)

See [`docs/README_TABLET.md`](docs/README_TABLET.md) for full setup instructions.

### Arduino

Flash each `.ino` file in the `arduino/` folder to the corresponding board using Arduino IDE:
- `CONTROL_BAZA.ino` → Arduino Mega
- `COD_OCHI_ESP32.ino` → ESP32 × 2

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Health check |
| `/talk` | POST | Send audio, receive LLM response |
| `/emergency` | POST | Trigger emergency alert |

---

## Author

**Ștefania-Alexandra Tanasă**
Robotics Engineering (English profile) — UTCN Cluj-Napoca
[GitHub](https://github.com/MasterWise23)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
