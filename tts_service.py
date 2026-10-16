import asyncio
import os
import tempfile
import subprocess
import time
import traceback
from pathlib import Path

import edge_tts

TTS_MAX_ATTEMPTS = int(os.getenv("TTS_MAX_ATTEMPTS", "3"))
TTS_RETRY_DELAY_SECONDS = float(os.getenv("TTS_RETRY_DELAY_SECONDS", "3"))
# am-ET-AmehaNeural (male, default) or am-ET-MekdesNeural (female)
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "am-ET-AmehaNeural")
EDGE_TTS_TIMEOUT_SECONDS = int(os.getenv("EDGE_TTS_TIMEOUT_SECONDS", "120"))
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.15"))  # ffmpeg atempo accepts 0.5 to 100
_tts_alert_sent = False


def _synthesize_edge(text, out_path):
    async def _run():
        communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE)
        await asyncio.wait_for(communicate.save(str(out_path)), timeout=EDGE_TTS_TIMEOUT_SECONDS)

    asyncio.run(_run())
    if not Path(out_path).exists() or Path(out_path).stat().st_size == 0:
        raise RuntimeError("edge-tts produced an empty audio file")


def _synthesize_speech(text, out_path):
    """
    Synthesize with edge-tts only (no gTTS fallback), retrying on failure.
    Returns the engine name used, or None if every attempt failed.
    """
    for engine, synth in (("edge-tts", _synthesize_edge),):
        for attempt in range(1, TTS_MAX_ATTEMPTS + 1):
            try:
                synth(text, out_path)
                return engine
            except Exception as tts_exc:
                Path(out_path).unlink(missing_ok=True)
                if attempt >= TTS_MAX_ATTEMPTS:
                    _alert_tts_failure(f"{engine} (after {attempt} attempts)", tts_exc)
                    break
                print(f"{engine} attempt {attempt}/{TTS_MAX_ATTEMPTS} failed: {tts_exc!r}")
                time.sleep(TTS_RETRY_DELAY_SECONDS * attempt)
    return None


SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920
SHORT_MAX_SECONDS = 175  # YouTube Shorts must be under 3 minutes


def media_duration(path):
    """Duration in seconds of an audio/video file, via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return float(result.stdout.strip())


def render_news_short(audio_path, video_path, image_path):
    """
    Vertical 1080x1920 H.264/AAC video for YouTube Shorts: the image sits
    centred over a blurred, enlarged copy of itself so there are no black bars.
    """
    filter_complex = (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={SHORT_WIDTH}:{SHORT_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={SHORT_WIDTH}:{SHORT_HEIGHT},boxblur=25:5[b];"
        f"[fg]scale={SHORT_WIDTH}:{SHORT_HEIGHT}:force_original_aspect_ratio=decrease[f];"
        "[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", str(image_path),
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
        "-r", str(VIDEO_FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
        str(video_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=VIDEO_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg short render failed: {(exc.stderr or '').strip()[-500:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg short render timed out after {VIDEO_TIMEOUT_SECONDS}s") from exc
    if not Path(video_path).exists() or Path(video_path).stat().st_size == 0:
        raise RuntimeError("ffmpeg produced an empty short file")
    return Path(video_path)


def concat_videos(video_paths, output_path):
    """
    Join clips rendered by render_news_video (identical codec, size and fps)
    into one file without re-encoding.
    """
    list_file = Path(output_path).with_suffix(".txt")
    list_file.write_text(
        "".join(f"file '{Path(p).resolve().as_posix()}'\n" for p in video_paths),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=VIDEO_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg concat failed: {(exc.stderr or '').strip()[-500:]}") from exc
    finally:
        list_file.unlink(missing_ok=True)
    return Path(output_path)


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

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 10
VIDEO_TIMEOUT_SECONDS = int(os.getenv("VIDEO_TIMEOUT_SECONDS", "300"))


def render_news_video(audio_path, video_path, image_path=None):
    """
    Build an H.264/AAC mp4 from a still image plus the narration audio.

    The image is scaled to fit inside 1920x1080 and padded, so the output
    dimensions are always even. libx264 with yuv420p refuses odd sizes, which
    is what made video generation fail for many news images. When there is no
    image, a plain black frame is used so a video is still produced.
    Raises RuntimeError with ffmpeg's own error output if encoding fails.
    """
    if image_path:
        video_input = ["-loop", "1", "-framerate", str(VIDEO_FPS), "-i", str(image_path)]
    else:
        video_input = [
            "-f", "lavfi",
            "-i", f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={VIDEO_FPS}",
        ]

    video_filter = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *video_input,
        "-i", str(audio_path),
        "-vf", video_filter,
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
        "-r", str(VIDEO_FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
        str(video_path),
    ]
    try:
        subprocess.run(
            cmd, check=True, capture_output=True, text=True,
            timeout=VIDEO_TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "").strip()[-500:]
        raise RuntimeError(f"ffmpeg video render failed: {stderr_tail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg video render timed out after {VIDEO_TIMEOUT_SECONDS}s") from exc

    if not Path(video_path).exists() or Path(video_path).stat().st_size == 0:
        raise RuntimeError("ffmpeg produced an empty video file")
    return Path(video_path)


def synthesize_news_audio(title, story, signature=True):
    """
    Converts Amharic news text to audio, appends a signature (unless
    signature=False), and speeds up the output using ffmpeg.
    """
    suffix = " ይህ ዜና የቀረበላችሁ በካታንጋ ቻናል ነው" if signature else ""
    full_text = f"{title}. {story}{suffix}"
    
    # Temporary files for processing
    temp_dir = Path(tempfile.gettempdir())
    raw_audio = temp_dir / f"tts_raw_{os.urandom(4).hex()}.mp3"
    fast_audio = temp_dir / f"tts_fast_{os.urandom(4).hex()}.mp3"
    
    try:
        # 1. Synthesize text to speech (edge-tts only)
        engine = _synthesize_speech(full_text, raw_audio)
        if not engine:
            return None
        print(f"TTS engine used: {engine}")

        # 2. Speed up using ffmpeg (TTS_SPEED, default 1.15x)
        # atempo speeds up audio without changing pitch
        cmd = [
            "ffmpeg", "-y", "-i", str(raw_audio),
            "-filter:a", f"atempo={TTS_SPEED}",
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
