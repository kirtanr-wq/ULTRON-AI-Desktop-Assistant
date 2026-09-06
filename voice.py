import os
import tempfile
import time
import threading

import pyttsx3
import scipy.io.wavfile as wav
import sounddevice as sd
import speech_recognition as sr

from config import MIC_INDEX, SAMPLE_RATE, CHANNELS, PHRASE_TIME_LIMIT

recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = False
recognizer.pause_threshold = 0.8
_tts_lock = threading.Lock()


def test_microphone():
    try:
        device = sd.query_devices(MIC_INDEX)
        if device["max_input_channels"] < 1:
            return False, "Selected device has no microphone input."
        return True, f"{device['name']} ({device['max_input_channels']} input channel(s))"
    except Exception as e:
        return False, str(e)


def listen(status_callback=None):
    temp_file = None
    try:
        device = sd.query_devices(MIC_INDEX)
        if device["max_input_channels"] < 1:
            return None

        if status_callback:
            status_callback("Listening")

        recording = sd.rec(
            int(PHRASE_TIME_LIMIT * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=MIC_INDEX,
        )
        sd.wait()

        if status_callback:
            status_callback("Processing voice")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            temp_file = temp.name

        wav.write(temp_file, SAMPLE_RATE, recording)

        with sr.AudioFile(temp_file) as source:
            audio = recognizer.record(source)

        try:
            return recognizer.recognize_google(audio).strip()
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            print(f"Speech recognition error: {e}")
            return None
    except Exception as e:
        print(f"Microphone error: {e}")
        return None
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


def speak(text):
    """Windows SAPI TTS, safe to call from Ultron's worker thread."""
    if not text:
        return False

    with _tts_lock:
        engine = None
        com_initialized = False
        try:
            # SAPI/COM can fail silently when TTS is created on a background thread.
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com_initialized = True
            except Exception:
                pythoncom = None

            engine = pyttsx3.init("sapi5")
            voices = engine.getProperty("voices")
            if voices:
                # Prefer a Microsoft English voice when available.
                selected = voices[0].id
                for voice in voices:
                    name = getattr(voice, "name", "").lower()
                    if "david" in name or "zira" in name:
                        selected = voice.id
                        break
                engine.setProperty("voice", selected)

            engine.setProperty("rate", 165)
            engine.setProperty("volume", 1.0)
            print(f"TTS START> {len(str(text))} chars", flush=True)
            engine.say(str(text))
            engine.runAndWait()
            print("TTS END>", flush=True)
            time.sleep(0.15)
            return True
        except Exception as e:
            print(f"TTS error: {type(e).__name__}: {e}")
            return False
        finally:
            try:
                if engine:
                    engine.stop()
            except Exception:
                pass
            try:
                if com_initialized:
                    pythoncom.CoUninitialize()
            except Exception:
                pass
