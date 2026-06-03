# SKY — Agentic AI Healthcare Robot

> Final-year Bachelor Project | Robotics Engineering | UTCN Cluj-Napoca

SKY is an agentic AI system for non-invasive patient monitoring and assistance, combining edge AI with mobility and multi-device integration.

## Architecture

- **Python Flask REST API** — LLM inference (Llama 3.2), speech recognition (Vosk), object detection (YOLOv8), emotion analysis (DeepFace)
- **Android App (.NET MAUI / C#)** — robot control via Bluetooth (motors, servos, gripper)
- **Termux Voice Client** — hands-free speech input and TTS output
- **2x ESP32 Wi-Fi Displays** — real-time animated eyes reflecting patient emotions

## Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM | Llama 3.2 via Ollama |
| Computer Vision | YOLOv8, DeepFace, OpenCV |
| Speech | Vosk STT, Termux TTS |
| Backend | Python Flask, REST API |
| Hardware | Arduino Mega, ESP32, Bluetooth |
| AI Tools | Claude (Anthropic), GitHub Copilot |

## Author

Stefania-Alexandra Tanasa
Robotics Engineering @ UTCN Cluj-Napoca
