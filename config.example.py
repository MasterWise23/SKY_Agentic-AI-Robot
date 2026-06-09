# SKY — Configuration file
# Copy this file to config.py and update the values for your environment.
# config.py is listed in .gitignore and will not be committed.

# ── Vosk speech recognition model ─────────────────────────────────────────────
# Download from: https://alphacephei.com/vosk/models
# Recommended: vosk-model-small-en-us-0.15
VOSK_MODEL_PATH = r"C:\path\to\vosk-model-small-en-us-0.15"

# ── YOLOv8 model ──────────────────────────────────────────────────────────────
# "yolov8n.pt" is downloaded automatically by Ultralytics on first run.
# Use yolov8n.pt (nano) for speed, yolov8s.pt (small) for better accuracy.
YOLO_MODEL_PATH = "yolov8n.pt"

# ── Ollama / LLM settings ─────────────────────────────────────────────────────
# Ollama must be running locally: https://ollama.com/
# Pull the model first: ollama pull llama3.2:1b
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:1b"

# LLM generation parameters
LLM_MAX_TOKENS = 50       # Keep responses short for a medical assistant
LLM_TEMPERATURE = 0.5     # Lower = more predictable, higher = more creative
LLM_CONTEXT_SIZE = 512    # Tokens of context window

# ── Conversation settings ──────────────────────────────────────────────────────
# Maximum number of messages kept in conversation history (older ones are dropped)
MAX_CONVERSATION_HISTORY = 8

# System prompt — defines SKY's personality and behaviour
SYSTEM_PROMPT = (
    "You are Sky, a medical assistant robot. "
    "Reply in ONE short sentence only. Max 15 words. Be warm and helpful."
)

# ── Emergency detection ────────────────────────────────────────────────────────
# Words that trigger an immediate emergency alert response
EMERGENCY_KEYWORDS = ["help", "emergency", "pain", "falling", "bleeding", "chest", "unconscious"]

# ── Computer vision settings ───────────────────────────────────────────────────
# Minimum confidence threshold for YOLO object detection (0.0 – 1.0)
YOLO_CONFIDENCE = 0.4

# ── Flask server settings ──────────────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"   # Listen on all interfaces (required for tablet to connect)
SERVER_PORT = 5000
DEBUG_MODE = False         # Set to True only during development
