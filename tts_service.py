from gtts import gTTS
import os
import tempfile
import subprocess
import time
import traceback
from pathlib import Path

TTS_MAX_ATTEMPTS = int(os.getenv("TTS_MAX_ATTEMPTS", "3"))
TTS_RETRY_DELAY_SECONDS = float(os.getenv("TTS_RETRY_DELAY_SECONDS", "3"))
_tts_alert_sent = False


def _alert_tts_failure(stage, exc):
    """Tell the admin once per process why voice generation failed."""
    global _tts_alert_sent
    print(f"TTS Service Error ({stage}): {exc!r}")
    traceback.print_exc()
    if _tts_alert_sent:
        return
    _tts_alert_sent = True
    try:
        from commands import send_admin_alert

        send_admin_alert(f"Voice generation failed at {stage}: {type(exc).__name__}: {str(exc)[:300]}")
    except Exception as alert_exc:
        print(f"Could not send TTS admin alert: {alert_exc!r}")

def synthesize_news_audio(title, story):
    """
    Converts Amharic news text to audio, appends a signature, 
    and speeds up the output using ffmpeg.
    """
    suffix = " ይህ ዜና የቀረበላችሁ በካታንጋ ቻናል ነው"
    full_text = f"{title}. {story}{suffix}"
    
    # Temporary files for processing
    temp_dir = Path(tempfile.gettempdir())
    raw_audio = temp_dir / f"tts_raw_{os.urandom(4).hex()}.mp3"
    fast_audio = temp_dir / f"tts_fast_{os.urandom(4).hex()}.mp3"
    
    try:
        # 1. Synthesize text to speech
        for attempt in range(1, TTS_MAX_ATTEMPTS + 1):
            try:
                tts = gTTS(text=full_text, lang='am')
                tts.save(str(raw_audio))
                break
            except Exception as tts_exc:
                if attempt >= TTS_MAX_ATTEMPTS:
                    _alert_tts_failure(f"gTTS (after {attempt} attempts)", tts_exc)
                    return None
                print(f"gTTS attempt {attempt}/{TTS_MAX_ATTEMPTS} failed: {tts_exc!r}")
                time.sleep(TTS_RETRY_DELAY_SECONDS * attempt)
        
        # 2. Speed up using ffmpeg (1.5x)
        # -filter:a "atempo=1.5" speeds up audio without changing pitch
        cmd = [
            "ffmpeg", "-y", "-i", str(raw_audio),
            "-filter:a", "atempo=1.5",
            str(fast_audio)
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        
        return fast_audio
    except Exception as e:
        _alert_tts_failure("ffmpeg/other", e)
        return None
    finally:
        # Clean up raw file immediately
        if raw_audio.exists():
            raw_audio.unlink()
