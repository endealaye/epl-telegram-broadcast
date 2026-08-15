import os
import requests
from pathlib import Path
from tts_service import synthesize_news_audio
from commands import send_telegram_video_file

# 1. Data from database
title = 'ጋሪ ኔቪል፦ "እንግሊዝ የተከላካይ መስመር ቦታውን በማንኳሰሷ አሁን ዋጋ እየከፈለች ነው!"'
story = '\r\nየእንግሊዝ ብሔራዊ ቡድን በለመደው ስህተት የክንፍ ተከላካይ (Full-back) ቦታን በማንኳሰሱ ምክንያት፣ ረቡዕ እለት ከዲአር ኮንጎ ጋር ለሚያደርገው የዓለም ዋንጫ የ32ቱ ዙር ወሳኝ ፍልሚያ በቀኝ ተከላካይ መስመር ላይ ከፍተኛ ቀውስ ውስጥ መውደቁን ጋሪ ኔቪል ተቸ።\r\n\r\nየመጀመሪያ ተመራጩ የቀኝ ተከላካይ ሪስ ጄምስ በጡንቻ መሳብ (Hamstring) ጉዳት ከጨዋታ ውጪ መሆኑ ሲረጋገጥ፣ ተጠባባቂው ቲኖ ሊቭራሜንቶም በተመሳሳይ ጉዳት ገና ውድድሩ ሳይጀምር ከስብስቡ መቀነሱ የቶማስ ቱሄልን ስብስብ ክፉኛ ጎድቶታል። በዚህም ምክንያት ቱሄል በቶተንሃም በግራ ተከላካይነት ሲጫወት የነበረውን ጄድ ስፔንስን፣ አልያም የመሀል ተከላካዮቹን ጃሬል ኳንሳን ወይም ኤዝሪ ኮንሳን በቀኝ መስመር ላይ ለማሰለፍ ለመወሰን ተገዷል። ኔቪል አክሎም፣ ሁለቱ ተጫዋቾች በተደጋጋሚ የሚጎዱ መሆናቸውን እያወቁ ቱሄል ቅድመ-ዝግጅት አለማድረጉ ስህተት መሆኑን ገልጾ፣ ጠንካራዋ ዲአር ኮንጎ ለእንግሊዝ ከባድ ፈተና እንደምትሆን አስጠንቅቋል።'
image_url = 'https://e0.365dm.com/26/06/1600x900/skysports-rice-saka-neville_7285790.jpg?20260629150802'

# 2. Generate Audio
print("Generating audio...")
audio_path = synthesize_news_audio(title, story)
if not audio_path:
    print("Failed to generate audio")
    exit(1)

# 3. Download Image
print("Downloading image...")
img_path = Path("temp_news_img.jpg")
img_data = requests.get(image_url).content
img_path.write_bytes(img_data)

# 4. Create MP4 using ffmpeg
# Combines static image + audio into a video
print("Creating MP4...")
video_path = Path("last_news.mp4")
cmd = [
    "ffmpeg", "-y",
    "-loop", "1", "-i", str(img_path),
    "-i", str(audio_path),
    "-c:v", "libx264", "-tune", "stillimage",
    "-c:a", "aac", "-b:a", "128k",
    "-pix_fmt", "yuv420p",
    "-shortest",
    str(video_path)
]
import subprocess
subprocess.run(cmd, check=True, capture_output=True)

# 5. Send to Telegram
print("Sending to Telegram...")
success = send_telegram_video_file(
    video_path=str(video_path),
    caption=f"🔊 {title}"
)

if success:
    print("Successfully sent last news in MP4 format!")
else:
    print("Failed to send video to Telegram.")

# Cleanup
img_path.unlink(missing_ok=True)
audio_path.unlink(missing_ok=True)
video_path.unlink(missing_ok=True)
