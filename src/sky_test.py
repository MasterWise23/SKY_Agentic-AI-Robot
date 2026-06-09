"""
sky_test.py — SKY standalone desktop prototype (Windows only)

This is the original all-in-one development version of SKY, designed to run
entirely on a Windows PC with a connected webcam and microphone.
It integrates voice recognition, LLM responses, computer vision, fall detection,
and TTS in a single multithreaded application.

In the production setup this functionality is split across:
  - sky_server.py  (Flask API — runs on the PC)
  - sky_tablet.py  (client — runs on the Android tablet via Termux)

Use this file for local development and testing without the tablet.

Requirements: see requirements.txt
Hardware: webcam, microphone, speakers (Windows SAPI TTS)
"""

import ollama
import pyttsx3
import vosk
import pyaudio
import json
import threading
import time
import cv2
from deepface import DeepFace
from ultralytics import YOLO
from collections import deque
import re
import win32com.client  # Windows SAPI TTS — Windows only
import logging
import os


# ── CONFIGURATION ──────────────────────────────────────────────────────────────
# Paths can be overridden via environment variables for portability.
# Example: set VOSK_MODEL_PATH=D:\models\vosk-model-small-en-us-0.15

VOSK_MODEL_PATH = os.environ.get(
    "VOSK_MODEL_PATH",
    r"C:\Users\stf12\PycharmProjects\pythonProject\vosk-model-small-en-us-0.15"
)

YOLO_MODEL_PATH = os.environ.get(
    "YOLO_MODEL_PATH",
    "yolov8n.pt"  # Downloaded automatically by Ultralytics on first run
)

# COCO class IDs filtered to objects relevant in a healthcare environment.
# Full COCO class list: https://docs.ultralytics.com/datasets/detect/coco/
RELEVANT_OBJECTS = {
    # People and furniture
    0: "person",
    56: "chair",
    57: "couch",
    59: "bed",
    60: "dining table",
    74: "clock",
    62: "tv",
    # Containers and drinks
    39: "bottle",
    41: "cup",
    43: "bowl",
    # Cutlery
    44: "fork",
    45: "knife",
    46: "spoon",
    # Food items
    47: "apple",
    48: "sandwich",
    49: "orange",
    50: "broccoli",
    51: "carrot",
    52: "hot dog",
    53: "pizza",
    54: "donut",
    55: "cake",
}

# Words that immediately trigger an emergency response, bypassing the LLM.
EMERGENCY_KEYWORDS = frozenset([
    'emergency', 'help', 'pain', 'chest', 'bleeding',
    'unconscious', 'poison', 'overdose', 'falling'
])

# ── FALL DETECTION PARAMETERS ─────────────────────────────────────────────────
FALL_HISTORY_LENGTH = 15    # Number of frames kept per tracked person
FALL_MIN_HISTORY = 10       # Minimum frames required before fall detection runs
FALL_DROP_THRESHOLD = 0.15  # Minimum downward shift (as fraction of frame height)
FALL_HEIGHT_REDUCTION = 0.6 # Bounding box height must shrink by this factor
FALL_TIME_ON_GROUND = 1.0   # Seconds a person must remain horizontal to trigger alert

# ── VISION TIMING ─────────────────────────────────────────────────────────────
EMOTION_FRAMES_INTERVAL = 60  # Run DeepFace every N frames (reduces CPU load)
YOLO_COOLDOWN_SECONDS = 0.5   # Minimum seconds between YOLO inference calls

# ── CONVERSATION SETTINGS ─────────────────────────────────────────────────────
CONVERSATION_HISTORY_MAXLEN = 10  # Rolling window of messages kept for LLM context
RESPONSE_CACHE_MAXLEN = 5         # Cached responses used as fallback if Ollama fails

# ── VOICE ACTIVATION ──────────────────────────────────────────────────────────
# Say ACTIVATION_WORD to wake SKY up, DEACTIVATION_WORD to put it to sleep.
ACTIVATION_WORD = "hello"
DEACTIVATION_WORD = "bye"


# ── LOGGING SETUP ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Sky")


# ── MAIN ASSISTANT CLASS ───────────────────────────────────────────────────────

class SkyAssistant:
    """
    Encapsulates all SKY state, models, and logic in a single thread-safe object.

    Three background threads operate concurrently:
      - vision_loop()  — camera, YOLO, DeepFace, fall detection
      - voice_loop()   — microphone, Vosk STT, LLM query, TTS response
      - keyboard_loop() — text input fallback for development

    All shared state is protected by explicit threading.Lock() instances.
    Resources (camera, audio stream) are stored as instance attributes so
    shutdown() can release them cleanly from any thread.
    """

    def __init__(self):
        # ── Thread safety locks ───────────────────────────────────────────────
        self.state_lock = threading.Lock()    # Protects emotion, environment, person_positions
        self.tts_lock = threading.Lock()      # Prevents overlapping speech
        self.history_lock = threading.Lock()  # Protects conversation_history
        self.cache_lock = threading.Lock()    # Protects response_cache

        # ── Runtime state ─────────────────────────────────────────────────────
        self._current_emotion = "neutral"       # Latest DeepFace result
        self._detected_environment = "unknown"  # Latest YOLO scene description
        self._is_speaking = False               # True while SAPI is synthesizing
        self._shutdown_flag = threading.Event() # Set to signal all threads to exit
        self._is_active = True                  # False = sleep mode (ignores voice)

        # Person bounding box history for fall detection.
        # Key: person index from YOLO, Value: deque of position dicts.
        self._person_positions = {}

        # ── Conversation history ──────────────────────────────────────────────
        # Deque with maxlen automatically discards oldest messages.
        # The system prompt at index 0 defines SKY's personality and constraints.
        self._conversation_history = deque([
            {
                "role": "system",
                "content": (
                    "You are Sky, a compassionate medical assistant. "
                    "Provide clear, accurate health information. "
                    "You are also a companionship for patients so be friendly and funny when they are sad.\n\n"
                    "GUIDELINES:\n"
                    "- Give concise, actionable answers (2-3 sentences for any questions)\n"
                    "- Use plain language, avoid jargon\n"
                    "- For emergencies: say 'Call emergency services immediately' first\n"
                    "- Always end with: 'Consult a healthcare professional for personalized advice'\n"
                    "- Structure: brief explanation → practical guidance → when to seek help\n\n"
                    "SCOPE: symptoms, conditions, medications, first aid, wellness, test results, companionship.\n"
                    "NOT FOR: diagnosis, prescriptions, treatment plans."
                )
            }
        ], maxlen=CONVERSATION_HISTORY_MAXLEN)

        # Simple keyword-based cache: if Ollama is unreachable, return a
        # previously cached answer for a similar query rather than failing silently.
        self._response_cache = deque(maxlen=RESPONSE_CACHE_MAXLEN)

        # ── Resource handles (stored for cleanup in shutdown()) ───────────────
        self._camera = None
        self._audio = None
        self._audio_stream = None
        self._vision_window_open = True

        # ── Model initialization ──────────────────────────────────────────────
        logger.info("Initializing Vosk model...")
        self._vosk_model = vosk.Model(VOSK_MODEL_PATH)
        self._recognizer = vosk.KaldiRecognizer(self._vosk_model, 16000)

        logger.info(f"Initializing YOLO model: {YOLO_MODEL_PATH}")
        self._yolo_model = YOLO(YOLO_MODEL_PATH)
        self._object_classes = RELEVANT_OBJECTS
        logger.info(f"Loaded {len(RELEVANT_OBJECTS)} object classes for detection")


    # ── SHUTDOWN ───────────────────────────────────────────────────────────────

    def shutdown(self):
        """
        Graceful shutdown — sets the shutdown flag (signals all threads to exit),
        stops TTS, releases the camera, closes the audio stream, and destroys
        all OpenCV windows. Called from main() after keyboard_loop() returns.
        """
        logger.info("Initiating shutdown...")
        self._shutdown_flag.set()
        self._vision_window_open = False

        # Stop any in-progress TTS
        with self.tts_lock:
            if self._is_speaking:
                try:
                    speaker = win32com.client.Dispatch("SAPI.SpVoice")
                    speaker.Speak("")
                except:
                    pass

        if self._camera is not None:
            self._camera.release()
            self._camera = None

        if self._audio_stream is not None:
            self._audio_stream.stop_stream()
            self._audio_stream.close()
            self._audio_stream = None

        if self._audio is not None:
            self._audio.terminate()
            self._audio = None

        cv2.destroyAllWindows()
        logger.info("Shutdown complete")

    def is_shutting_down(self):
        """Returns True once shutdown() has been called."""
        return self._shutdown_flag.is_set()


    # ── THREAD-SAFE STATE PROPERTIES ──────────────────────────────────────────

    @property
    def current_emotion(self):
        with self.state_lock:
            return self._current_emotion

    @current_emotion.setter
    def current_emotion(self, value):
        with self.state_lock:
            self._current_emotion = value

    @property
    def detected_environment(self):
        with self.state_lock:
            return self._detected_environment

    @detected_environment.setter
    def detected_environment(self, value):
        with self.state_lock:
            self._detected_environment = value

    @property
    def is_speaking(self):
        with self.tts_lock:
            return self._is_speaking

    @is_speaking.setter
    def is_speaking(self, value):
        with self.tts_lock:
            self._is_speaking = value

    @property
    def is_active(self):
        """True if SKY is in listening mode; False if in sleep mode."""
        with self.state_lock:
            return self._is_active

    @is_active.setter
    def is_active(self, value):
        with self.state_lock:
            self._is_active = value

    def handle_activation_command(self, text):
        """
        Check whether the transcribed text is a wake/sleep command.
        Handles activation (ACTIVATION_WORD) and deactivation (DEACTIVATION_WORD).
        Returns True if a command was handled so the caller can skip LLM processing.
        """
        text_lower = text.lower().strip()

        if text_lower == ACTIVATION_WORD or text_lower.startswith(f"{ACTIVATION_WORD} "):
            if not self._is_active:
                self._is_active = True
                logger.info("Assistant activated via voice command")
                self.speak("Hello! I'm listening now.")
            return True

        if text_lower == DEACTIVATION_WORD or text_lower.startswith(f"{DEACTIVATION_WORD} "):
            if self._is_active:
                self._is_active = False
                logger.info("Assistant deactivated via voice command")
                self.speak("Goodbye. Say hello to wake me up.")
            return True

        return False

    def get_person_positions_snapshot(self):
        """Return a thread-safe copy of the person positions dict."""
        with self.state_lock:
            return {k: list(v) for k, v in self._person_positions.items()}

    def update_person_position(self, person_id, position_data):
        """
        Append a new position snapshot for a tracked person.
        Creates a bounded deque for new person IDs automatically.
        """
        with self.state_lock:
            if person_id not in self._person_positions:
                self._person_positions[person_id] = deque(maxlen=FALL_HISTORY_LENGTH)
            self._person_positions[person_id].append(position_data)

    def cleanup_stale_person_data(self, max_age_seconds=5.0):
        """
        Remove position history for people who have not been seen recently.
        Prevents unbounded memory growth when people leave the camera frame.
        """
        current_time = time.time()
        with self.state_lock:
            stale_ids = [
                pid for pid, positions in self._person_positions.items()
                if positions and (current_time - positions[-1].get("time", 0)) > max_age_seconds
            ]
            for pid in stale_ids:
                del self._person_positions[pid]
                logger.debug(f"Cleaned up stale person data for ID {pid}")


    # ── TTS ────────────────────────────────────────────────────────────────────

    def speak(self, text):
        """
        Synthesize speech using Windows SAPI (synchronous, blocking).
        Sets is_speaking=True for the duration so the voice loop pauses recording,
        preventing SKY from hearing its own TTS output.
        """
        with self.tts_lock:
            self._is_speaking = True

        logger.info(f"Speaking: {text}")
        print(f"\nSky: {text}\n")

        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate = 0      # Normal speed
            speaker.Volume = 100
            speaker.Speak(text)
        except Exception as e:
            logger.error(f"TTS error: {e}")
        finally:
            with self.tts_lock:
                self._is_speaking = False


    # ── EMERGENCY DETECTION ────────────────────────────────────────────────────

    @staticmethod
    def check_emergency(user_input):
        """Return True if the input contains any emergency keyword."""
        text_lower = user_input.lower()
        return any(kw in text_lower for kw in EMERGENCY_KEYWORDS)


    # ── LLM RESPONSE ──────────────────────────────────────────────────────────

    def get_response(self, user_input):
        """
        Query the local Ollama LLM (llama3.2:1b) and return its response.

        Emergency inputs bypass the LLM entirely and prepend a fixed alert string.
        The current emotion (from DeepFace) is prepended as context so the LLM
        can adapt its tone (e.g. be more reassuring when the patient looks sad).

        If Ollama is unreachable, falls back to a keyword-matched cached response
        or a static error message.
        """
        is_emergency = self.check_emergency(user_input)
        if is_emergency:
            logger.warning("EMERGENCY DETECTED in user input")
            emergency_response = (
                "This may be an emergency. Call emergency services (911) immediately if this is urgent. "
            )

        # Inject current emotion as context prefix
        emotion = self.current_emotion
        emotion_context = f"User seems {emotion}. " if emotion != "neutral" else ""
        prompt = f"{emotion_context}User: {user_input}\nAssistant (concise, medical):"

        with self.history_lock:
            messages = list(self._conversation_history) + [{"role": "user", "content": prompt}]

        try:
            response = ollama.chat(
                model='llama3.2:1b',
                messages=messages,
                options={
                    "temperature": 0.5,
                    "num_predict": 200,
                    "num_ctx": 512,
                    "top_p": 0.9
                },
                stream=False
            )

            answer = response['message']['content'].strip()

            # Prepend emergency alert only if the LLM didn't already include it
            if is_emergency and "911" not in answer.lower():
                answer = emergency_response + answer

            # Update conversation history and response cache (thread-safe)
            with self.history_lock:
                self._conversation_history.append({"role": "user", "content": user_input})
                self._conversation_history.append({"role": "assistant", "content": answer})

            with self.cache_lock:
                self._response_cache.append((user_input.lower(), answer))

            return answer

        except Exception as e:
            logger.error(f"Ollama error: {e}")
            # Try to return a cached response for a similar query
            with self.cache_lock:
                for cached_input, cached_answer in self._response_cache:
                    if any(word in user_input.lower() for word in cached_input.split() if len(word) > 3):
                        return f"[Cached] {cached_answer}"
            return "I'm having trouble connecting. Please try again."


    # ── FALL DETECTION ─────────────────────────────────────────────────────────

    def check_fall(self, box, frame_height, person_id):
        """
        Detect whether a tracked person has fallen based on their bounding box history.

        A fall is flagged when ALL of the following are true:
          1. The person's bounding box is wider than it is tall (horizontal = lying down).
          2. The bounding box centre has dropped faster than FALL_DROP_THRESHOLD.
          3. The bounding box height has shrunk by more than FALL_HEIGHT_REDUCTION.
          4. The person has been horizontal for at least FALL_TIME_ON_GROUND seconds.

        Returns True if a fall is detected, False otherwise.
        """
        x1, y1, x2, y2 = box
        width = x2 - x1
        height = y2 - y1
        center_y = (y1 + y2) / 2

        self.update_person_position(person_id, {
            "time": time.time(),
            "center_y": center_y,
            "height": height,
            "width": width
        })

        positions = self.get_person_positions_snapshot().get(person_id, [])

        if len(positions) < FALL_MIN_HISTORY:
            return False  # Not enough history yet

        is_horizontal = width > height * 2
        old_center = positions[0]["center_y"]
        new_center = positions[-1]["center_y"]
        dropped_fast = (new_center - old_center) > frame_height * FALL_DROP_THRESHOLD

        old_height = positions[0]["height"]
        new_height = positions[-1]["height"]
        height_reduced = new_height < old_height * FALL_HEIGHT_REDUCTION

        time_on_ground = time.time() - positions[0]["time"]
        staying_down = is_horizontal and time_on_ground > FALL_TIME_ON_GROUND

        return staying_down and (dropped_fast or height_reduced)


# ── VISION THREAD ──────────────────────────────────────────────────────────────

def vision_loop(assistant: SkyAssistant):
    """
    Background thread: reads camera frames, runs YOLO and DeepFace,
    detects falls, and updates shared state on the assistant object.

    YOLO runs on a time-based cooldown (YOLO_COOLDOWN_SECONDS) to limit CPU usage.
    DeepFace runs every EMOTION_FRAMES_INTERVAL frames for the same reason.
    Stale person tracking data is cleaned up every 10 seconds.

    The thread exits cleanly when assistant.is_shutting_down() returns True.
    """
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logger.error("Camera not detected")
        return

    assistant._camera = cap  # Store handle for cleanup in shutdown()
    logger.info("Vision system started")

    yolo_conf_threshold = 0.4
    frame_count = 0
    last_yolo_time = 0
    last_cleanup_time = 0
    cleanup_interval = 10.0

    while not assistant.is_shutting_down():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue

        frame_height = frame.shape[0]
        current_time = time.time()
        detected_objects = []

        # ── YOLO inference (time-gated) ───────────────────────────────────────
        if (current_time - last_yolo_time) > YOLO_COOLDOWN_SECONDS:
            last_yolo_time = current_time
            try:
                results = assistant._yolo_model(frame, verbose=False, conf=yolo_conf_threshold)

                for result in results:
                    if len(result.boxes) == 0:
                        continue
                    for i, box in enumerate(result.boxes):
                        cls = int(box.cls[0])
                        if cls not in assistant._object_classes:
                            continue

                        label = assistant._object_classes[cls]
                        detected_objects.append(label)
                        x1, y1, x2, y2 = map(int, box.xyxy[0])

                        if cls == 0:  # Person — also check for fall
                            color = (0, 255, 0)
                            if assistant.check_fall((x1, y1, x2, y2), frame_height, i):
                                color = (0, 0, 255)
                                cv2.putText(frame, "FALL DETECTED", (x1, y1 - 30),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                        else:
                            color = (255, 165, 0)

                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(frame, label, (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            except Exception as e:
                logger.error(f"YOLO error: {e}")

        # Update shared environment description
        if detected_objects:
            assistant.detected_environment = ", ".join(set(detected_objects))

        # ── DeepFace emotion analysis (frame-gated) ───────────────────────────
        if frame_count % EMOTION_FRAMES_INTERVAL == 0:
            try:
                analysis = DeepFace.analyze(
                    frame, actions=['emotion'],
                    enforce_detection=False, silent=True
                )
                if analysis:
                    assistant.current_emotion = analysis[0]['dominant_emotion']
            except Exception as e:
                logger.debug(f"Emotion analysis error: {e}")

        frame_count += 1

        # ── Stale person data cleanup ─────────────────────────────────────────
        if current_time - last_cleanup_time > cleanup_interval:
            assistant.cleanup_stale_person_data()
            last_cleanup_time = current_time

        # ── Overlay HUD on frame ──────────────────────────────────────────────
        cv2.putText(frame, f"Emotion: {assistant.current_emotion}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Env: {assistant.detected_environment}", (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2)

        cv2.imshow("Sky Vision", frame)
        if cv2.waitKey(1) == ord('q'):
            break


# ── VOICE THREAD ───────────────────────────────────────────────────────────────

def voice_loop(assistant: SkyAssistant):
    """
    Background thread: continuously reads microphone input, transcribes with Vosk,
    checks for activation commands, and queries the LLM when active.

    Pauses automatically while SKY is speaking (is_speaking=True) to prevent
    feedback loops where SKY hears its own TTS output.

    Includes audio stream recovery: if PyAudio raises an OSError (e.g. buffer
    overflow, device disconnected), the stream is closed and re-opened.
    """
    audio = pyaudio.PyAudio()
    assistant._audio = audio

    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=4000
        )
        assistant._audio_stream = stream
    except Exception as e:
        logger.error(f"Failed to initialize audio stream: {e}")
        return

    logger.info("Voice assistant ready")

    while not assistant.is_shutting_down():
        # Pause while SKY is speaking to avoid feedback
        if assistant.is_speaking:
            time.sleep(0.05)
            continue

        try:
            data = stream.read(2000, exception_on_overflow=False)

            if assistant._recognizer.AcceptWaveform(data):
                result = json.loads(assistant._recognizer.Result())
                text = result.get("text", "").strip()

                if text:
                    # Activation/deactivation commands take priority
                    if assistant.handle_activation_command(text):
                        continue

                    if assistant.is_active:
                        logger.info(f"You (voice): {text}")
                        response = assistant.get_response(text)
                        assistant.speak(response)
                    else:
                        logger.debug(f"Ignored (sleep mode): {text}")
            else:
                # Show partial transcription as live feedback
                partial = json.loads(assistant._recognizer.PartialResult())
                partial_text = partial.get("partial", "").strip()
                if partial_text:
                    status = "listening" if assistant.is_active else "SLEEP"
                    print(f"[{status}] [Hearing: {partial_text}...]", end='\r')

        except OSError as e:
            # Stream overflow or device error — attempt recovery
            logger.warning(f"Audio stream error, attempting recovery: {e}")
            time.sleep(0.5)
            try:
                stream.stop_stream()
                stream.close()
                stream = audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=4000
                )
                assistant._audio_stream = stream
            except Exception as reinit_error:
                logger.error(f"Audio stream recovery failed: {reinit_error}")
                break
        except Exception as e:
            logger.error(f"Audio error: {e}")
            time.sleep(0.1)


# ── KEYBOARD THREAD ────────────────────────────────────────────────────────────

def keyboard_loop(assistant: SkyAssistant):
    """
    Runs in the main thread: accepts text input from the keyboard as an alternative
    to voice. Useful during development when a microphone is unavailable.
    Type 'exit', 'quit', or 'stop' to trigger a graceful shutdown.
    """
    logger.info("Keyboard interaction enabled")
    print("\nType 'exit' to close\n")

    while not assistant.is_shutting_down():
        try:
            user_input = input("You (keyboard): ")
        except (EOFError, KeyboardInterrupt):
            print("\nKeyboard interrupt detected")
            break

        if user_input.lower() in ["exit", "quit", "stop"]:
            logger.info("User requested shutdown via keyboard")
            break

        if not user_input.strip():
            continue

        response = assistant.get_response(user_input)
        assistant.speak(response)


# ── ENTRY POINT ────────────────────────────────────────────────────────────────

def main():
    """
    Initialises the assistant, warms up the YOLO model, delivers the greeting,
    starts vision and voice threads as daemons, then hands control to the
    keyboard loop. On exit, calls shutdown() and waits for threads to finish.
    """
    logger.info("Starting Sky Medical Assistant")

    assistant = SkyAssistant()

    # Warm up YOLO with a single frame to avoid latency on first detection
    logger.info("Warming up YOLO model...")
    warmup_cap = cv2.VideoCapture(0)
    ret, warmup_frame = warmup_cap.read()
    warmup_cap.release()
    if ret and warmup_frame is not None:
        assistant._yolo_model.predict(source=warmup_frame, verbose=False)
    logger.info("Models loaded. Starting assistant...")

    assistant.speak("Hello. I am Sky, your medical assistant. How can I help you today?")

    # Daemon threads exit automatically when the main thread exits
    vision_thread = threading.Thread(target=vision_loop, args=(assistant,), daemon=True)
    voice_thread = threading.Thread(target=voice_loop, args=(assistant,), daemon=True)

    vision_thread.start()
    voice_thread.start()

    try:
        keyboard_loop(assistant)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        assistant.shutdown()
        vision_thread.join(timeout=1.0)
        voice_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
