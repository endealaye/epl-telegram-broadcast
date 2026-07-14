from gtts import gTTS
import os
import tempfile
import subprocess
from pathlib import Path

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
        tts = gTTS(text=full_text, lang='am')
        tts.save(str(raw_audio))
        
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
        print(f"TTS Service Error: {e}")
        return None
    finally:
        # Clean up raw file immediately
        if raw_audio.exists():
            raw_audio.unlink()
