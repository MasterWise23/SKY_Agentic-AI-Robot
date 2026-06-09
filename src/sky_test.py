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
import win32com.client
import logging
import os

# CONFIGURATION


VOSK_MODEL_PATH = os.environ.get(
    "VOSK_MODEL_PATH",
    r"C:\Users\stf12\PycharmProjects\pythonProject\vosk-model-small-en-us-0.15"
)

# YOLO model

YOLO_MODEL_PATH = os.environ.get(
    "YOLO_MODEL_PATH",
    "yolov8n.pt"  # Default: COCO 80 classes (includes food/cutlery)
)

# COCO classes (YOLOv8n.pt) - Extended with food and cutlery
# Full list: https://docs.ultralytics.com/datasets/detect/coco/
RELEVANT_OBJECTS = {
    # People and furniture
    0: "person",
    56: "chair",
    57: "couch",
    59: "bed",
    60: "dining table",
    74: "clock",
    62: "tv",

    # Containers and drink
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

EMERGENCY_KEYWORDS = frozenset([
    'emergency', 'help', 'pain', 'chest', 'bleeding',
    'unconscious', 'poison', 'overdose', 'falling'
])

# Fall detection thresholds
FALL_HISTORY_LENGTH = 15
FALL_MIN_HISTORY = 10
FALL_DROP_THRESHOLD = 0.15  # Fraction of frame height
FALL_HEIGHT_REDUCTION = 0.6
FALL_TIME_ON_GROUND = 1.0  # seconds

# Vision timing
EMOTION_FRAMES_INTERVAL = 60
YOLO_COOLDOWN_SECONDS = 0.5

# Conversation
CONVERSATION_HISTORY_MAXLEN = 10
RESPONSE_CACHE_MAXLEN = 5

# Voice activation commands
ACTIVATION_WORD = "hello"
DEACTIVATION_WORD = "bye"


# LOGGING SETUP

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Sky")


# SKY ASSISTANT CLASS

class SkyAssistant:
    """Main assistant class encapsulating all state and resources."""

    def __init__(self):
        # Thread safety locks
        self.state_lock = threading.Lock()  # Protects emotion, environment, person_positions
        self.tts_lock = threading.Lock()
        self.history_lock = threading.Lock()
        self.cache_lock = threading.Lock()

        # Runtime state
        self._current_emotion = "neutral"
        self._detected_environment = "unknown"
        self._is_speaking = False
        self._shutdown_flag = threading.Event()
        self._is_active = True  # Voice activation state (starts active)

        # Person tracking for fall detection (with cleanup)
        self._person_positions = {}

        # Conversation management
        self._conversation_history = deque([
            {
                "role": "system",
                "content": """You are Sky, a compassionate medical assistant. Provide clear, accurate health information. You are also a companionship for patients so be friendly and funny when they are sad.

GUIDELINES:
- Give concise, actionable answers (2-3 sentences for any questions)
- Use plain language, avoid jargon
- For emergencies: say "Call emergency services immediately" first
- Always end with: "Consult a healthcare professional for personalized advice"
- Structure: brief explanation → practical guidance → when to seek help

SCOPE: symptoms, conditions, medications, first aid, wellness, test results, companionship.
NOT FOR: diagnosis, prescriptions, treatment plans."""
            }
        ], maxlen=CONVERSATION_HISTORY_MAXLEN)

        self._response_cache = deque(maxlen=RESPONSE_CACHE_MAXLEN)

        # Resource handles (for cleanup)
        self._camera = None
        self._audio = None
        self._audio_stream = None
        self._vision_window_open = True

        # Initialize models
        logger.info("Initializing Vosk model...")
        self._vosk_model = vosk.Model(VOSK_MODEL_PATH)
        self._recognizer = vosk.KaldiRecognizer(self._vosk_model, 16000)

        logger.info(f"Initializing YOLO model: {YOLO_MODEL_PATH}")
        self._yolo_model = YOLO(YOLO_MODEL_PATH)

        # Object classes to detect (from COCO dataset)
        self._object_classes = RELEVANT_OBJECTS
        logger.info(f"Loaded {len(RELEVANT_OBJECTS)} object classes for detection")


    # SHUTDOWN MANAGEMENT

    def shutdown(self):
        """Graceful shutdown - release all resources."""
        logger.info("Initiating shutdown...")
        self._shutdown_flag.set()
        self._vision_window_open = False

        with self.tts_lock:
            if self._is_speaking:
                try:
                    speaker = win32com.client.Dispatch("SAPI.SpVoice")
                    speaker.Speak("")  # Stop current speech
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
        return self._shutdown_flag.is_set()


    # THREAD-SAFE STATE ACCESS

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
        """Check if assistant is actively listening (not in sleep mode)."""
        with self.state_lock:
            return self._is_active

    @is_active.setter
    def is_active(self, value):
        with self.state_lock:
            self._is_active = value

    def handle_activation_command(self, text):
        """
        Check if text is an activation/deactivation command.
        Returns True if command was handled, False otherwise.
        """
        text_lower = text.lower().strip()

        # Check for activation word
        if text_lower == ACTIVATION_WORD or text_lower.startswith(f"{ACTIVATION_WORD} "):
            if not self._is_active:
                self._is_active = True
                logger.info("Assistant activated via voice command")
                self.speak("Hello! I'm listening now.")
            return True

        # Check for deactivation word
        if text_lower == DEACTIVATION_WORD or text_lower.startswith(f"{DEACTIVATION_WORD} "):
            if self._is_active:
                self._is_active = False
                logger.info("Assistant deactivated via voice command")
                self.speak("Goodbye. Say hello to wake me up.")
            return True

        return False

    def get_person_positions_snapshot(self):
        """Get a thread-safe copy of person positions."""
        with self.state_lock:
            return {k: list(v) for k, v in self._person_positions.items()}

    def update_person_position(self, person_id, position_data):
        """Update person position with automatic cleanup of old entries."""
        with self.state_lock:
            if person_id not in self._person_positions:
                self._person_positions[person_id] = deque(maxlen=FALL_HISTORY_LENGTH)
            self._person_positions[person_id].append(position_data)

    def cleanup_stale_person_data(self, max_age_seconds=5.0):
        """Remove person data older than max_age_seconds."""
        current_time = time.time()
        with self.state_lock:
            stale_ids = []
            for person_id, positions in self._person_positions.items():
                if positions and (current_time - positions[-1].get("time", 0)) > max_age_seconds:
                    stale_ids.append(person_id)
            for pid in stale_ids:
                del self._person_positions[pid]
                logger.debug(f"Cleaned up stale person data for ID {pid}")

    # TTS - THREAD-SAFE

    def speak(self, text):
        with self.tts_lock:
            self._is_speaking = True

        logger.info(f"Speaking: {text}")
        print(f"\nSky: {text}\n")

        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate = 0
            speaker.Volume = 100
            speaker.Speak(text)
        except Exception as e:
            logger.error(f"TTS error: {e}")
        finally:
            with self.tts_lock:
                self._is_speaking = False

    # EMERGENCY DETECTION

    @staticmethod
    def check_emergency(user_input):
        """Check if input contains emergency keywords."""
        text_lower = user_input.lower()
        return any(kw in text_lower for kw in EMERGENCY_KEYWORDS)


    # AI RESPONSE - THREAD-SAFE

    def get_response(self, user_input):
        # Emergency detection
        is_emergency = self.check_emergency(user_input)
        if is_emergency:
            logger.warning("EMERGENCY DETECTED in user input")
            emergency_response = (
                "This may be an emergency. Call emergency services (911) immediately if this is urgent. "
            )

        # Build prompt with emotion context
        emotion = self.current_emotion
        emotion_context = f"User seems {emotion}. " if emotion != "neutral" else ""
        prompt = f"{emotion_context}User: {user_input}\nAssistant (concise, medical):"

        # Get thread-safe copy of conversation history
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

            # Add emergency prefix if needed (single check)
            if is_emergency and "911" not in answer.lower():
                answer = emergency_response + answer

            # Store in history (thread-safe)
            with self.history_lock:
                self._conversation_history.append({"role": "user", "content": user_input})
                self._conversation_history.append({"role": "assistant", "content": answer})

            # Cache response (thread-safe)
            with self.cache_lock:
                self._response_cache.append((user_input.lower(), answer))

            return answer

        except Exception as e:
            logger.error(f"Ollama error: {e}")
            # Try cached response
            with self.cache_lock:
                for cached_input, cached_answer in self._response_cache:
                    if any(word in user_input.lower() for word in cached_input.split() if len(word) > 3):
                        return f"[Cached] {cached_answer}"
            return "I'm having trouble connecting. Please try again."

    # FALL DETECTION

    def check_fall(self, box, frame_height, person_id):
        x1, y1, x2, y2 = box
        width = x2 - x1
        height = y2 - y1
        center_y = (y1 + y2) / 2

        # Update position (thread-safe, with automatic trimming)
        self.update_person_position(person_id, {
            "time": time.time(),
            "center_y": center_y,
            "height": height,
            "width": width
        })

        positions = self.get_person_positions_snapshot().get(person_id, [])

        if len(positions) < FALL_MIN_HISTORY:
            return False

        is_horizontal = width > height * 2
        old_center = positions[0]["center_y"]
        new_center = positions[-1]["center_y"]

        dropped_fast = (new_center - old_center) > frame_height * FALL_DROP_THRESHOLD

        old_height = positions[0]["height"]
        new_height = positions[-1]["height"]

        height_reduced = new_height < old_height * FALL_HEIGHT_REDUCTION

        time_on_ground = time.time() - positions[0]["time"]
        staying_down = is_horizontal and time_on_ground > FALL_TIME_ON_GROUND

        if staying_down and (dropped_fast or height_reduced):
            return True

        return False

# VISION THREAD - THREAD-SAFE

def vision_loop(assistant: SkyAssistant):
    """Vision loop with thread-safe state updates and proper cleanup."""

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logger.error("Camera not detected")
        return

    assistant._camera = cap  # Store for cleanup
    logger.info("Vision system started")

    yolo_conf_threshold = 0.4
    frame_count = 0
    last_yolo_time = 0
    last_cleanup_time = 0
    cleanup_interval = 10.0  # Cleanup stale person data every 10 seconds

    while not assistant.is_shutting_down():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue

        frame_height = frame.shape[0]
        current_time = time.time()

        detected_objects = []

        # Run YOLO with time-based cooldown
        if (current_time - last_yolo_time) > YOLO_COOLDOWN_SECONDS:
            last_yolo_time = current_time
            try:
                results = assistant._yolo_model(frame, verbose=False, conf=yolo_conf_threshold)

                for result in results:
                    if len(result.boxes) == 0:
                        continue
                    for i, box in enumerate(result.boxes):
                        cls = int(box.cls[0])
                        conf = float(box.conf[0])

                        if cls in assistant._object_classes:
                            label = assistant._object_classes[cls]
                            detected_objects.append(label)
                            x1, y1, x2, y2 = map(int, box.xyxy[0])

                            if cls == 0:  # person
                                color = (0, 255, 0)
                                if assistant.check_fall((x1, y1, x2, y2), frame_height, i):
                                    color = (0, 0, 255)
                                    cv2.putText(frame, "FALL DETECTED", (x1, y1 - 30),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                            else:
                                color = (255, 165, 0)

                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                            cv2.putText(frame, f"{label}", (x1, y1 - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            except Exception as e:
                logger.error(f"YOLO error: {e}")

        # Update environment (thread-safe)
        if detected_objects:
            assistant.detected_environment = ", ".join(set(detected_objects))

        # Emotion analysis - less frequent
        if frame_count % EMOTION_FRAMES_INTERVAL == 0:
            try:
                analysis = DeepFace.analyze(
                    frame, actions=['emotion'],
                    enforce_detection=False, silent=True
                )
                if analysis and len(analysis) > 0:
                    assistant.current_emotion = analysis[0]['dominant_emotion']
            except Exception as e:
                logger.debug(f"Emotion analysis error: {e}")

        frame_count += 1

        # Periodic cleanup of stale person data
        if current_time - last_cleanup_time > cleanup_interval:
            assistant.cleanup_stale_person_data()
            last_cleanup_time = current_time

        # Overlay info (read thread-safe values)
        emotion = assistant.current_emotion
        env = assistant.detected_environment

        cv2.putText(frame, f"Emotion: {emotion}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Env: {env}", (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2)

        cv2.imshow("Sky Vision", frame)

        if cv2.waitKey(1) == ord('q'):
            break

    # Cleanup handled by assistant.shutdown()

# VOICE THREAD - THREAD-SAFE

def voice_loop(assistant: SkyAssistant):
    """Voice loop with thread-safe state access and stream recovery."""

    audio = pyaudio.PyAudio()
    assistant._audio = audio  # Store for cleanup

    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=4000
        )
        assistant._audio_stream = stream  # Store for cleanup
    except Exception as e:
        logger.error(f"Failed to initialize audio stream: {e}")
        return

    logger.info("Voice assistant ready")

    while not assistant.is_shutting_down():
        if assistant.is_speaking:
            time.sleep(0.05)
            continue

        try:
            data = stream.read(2000, exception_on_overflow=False)

            if assistant._recognizer.AcceptWaveform(data):
                result = json.loads(assistant._recognizer.Result())
                text = result.get("text", "").strip()

                if text:
                    # Check for activation/deactivation commands first
                    if assistant.handle_activation_command(text):
                        continue  # Command handled, skip normal processing

                    # Only process if assistant is active
                    if assistant.is_active:
                        logger.info(f"You (voice): {text}")
                        response = assistant.get_response(text)
                        assistant.speak(response)
                    else:
                        logger.debug(f"Ignored (sleep mode): {text}")
            else:
                partial = json.loads(assistant._recognizer.PartialResult())
                partial_text = partial.get("partial", "").strip()
                if partial_text:
                    status = "listening" if assistant.is_active else "SLEEP"
                    print(f"[{status}] [Hearing: {partial_text}...]", end='\r')

        except OSError as e:
            # Audio stream overflow or device disconnected - try to recover
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


# KEYBOARD THREAD

def keyboard_loop(assistant: SkyAssistant):
    """Keyboard loop with graceful shutdown support."""
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


# MAIN

def main():
    logger.info("Starting Sky Medical Assistant")

    # Create assistant instance (encapsulates all state)
    assistant = SkyAssistant()

    # Warm-up YOLO model
    logger.info("Warming up YOLO model...")
    warmup_cap = cv2.VideoCapture(0)
    ret, warmup_frame = warmup_cap.read()
    warmup_cap.release()
    if ret and warmup_frame is not None:
        assistant._yolo_model.predict(source=warmup_frame, verbose=False)
    logger.info("Models loaded. Starting assistant...")

    # Initial greeting
    assistant.speak("Hello. I am Sky, your medical assistant. How can I help you today?")

    # Create threads with explicit assistant reference
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