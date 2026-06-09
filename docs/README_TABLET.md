# Sky Medical Assistant - Tablet Connection Guide

## Architecture

```
[Windows PC - Server] <----> [Android Tablet - Termux Client]
   - Runs sky_server.py         - Runs sky_tablet.py
   - Flask API on port 5000     - Connects via HTTP
   - Vosk transcription         - Records audio
   - Ollama AI responses        - Plays TTS
```

## Server Setup (Windows PC)

1. **Start the server:**
   ```powershell
   cd D:\sky_test.py\vosk-model-small-en-us-0.15
   D:\sky_test.py\.venv\Scripts\python.exe sky_server.py
   ```

2. **Note the IP address** displayed:
   ```
   Sky server running on http://192.168.1.XXX:5000
   ```

## Tablet Setup (Termux)

1. **Install required packages:**
   ```bash
   pkg update
   pkg install python ffmpeg
   pip install requests
   ```

2. **Install TermuxAPI:**
   ```bash
   pkg install termux-api
   ```

3. **Grant permissions (on Android):**
   - Open Termux app settings
   - Grant Microphone permission
   - Or run: `termux-setup-storage`

4. **Configure server IP:**
   ```bash
   export SKY_SERVER_URL="http://192.168.1.XXX:5000"
   ```
   Replace `192.168.1.XXX` with the IP from step 2.

5. **Run the tablet client:**
   ```bash
   cd ~/vosk-model-small-en-us-0.15
   python sky_tablet.py
   ```

## Network Requirements

- Both devices must be on the **same WiFi network**
- Windows Firewall must allow incoming connections on port 5000

### Allow Firewall (Windows PowerShell as Admin):
```powershell
New-NetFirewallRule -DisplayName "Sky Server" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow
```

## Troubleshooting

### "Cannot connect to server"
1. Check both devices are on same WiFi
2. Verify server IP hasn't changed
3. Check Windows Firewall

### "Recording failed"
1. Grant microphone permission in Android settings
2. Try: `termux-audio-record -h` to verify command exists

### "TTS error"
1. Ensure Termux-TTS works: `termux-tts-speak "test"`
2. Install a TTS engine on Android if needed

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Check server health |
| `/talk` | POST | Send audio, get response |
| `/emergency` | POST | Direct emergency alert |

## Quick Test

From tablet, test connection:
```bash
curl http://192.168.1.XXX:5000/status
```

Expected: `{"status":"Sky is running"}`
