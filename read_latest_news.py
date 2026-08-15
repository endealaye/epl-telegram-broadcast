from tts_service import synthesize_news_audio
from commands import send_telegram_audio_file
import os

title = 'አርሰናል ትሮሳርድን ወደ ቤሺክታስ ለማዘዋወር ከስምምነት ላይ ደርሷል'
story = 'አርሰናል ቤልጄማዊውን የፊት መስመር አጥቂ ሊያንድሮ ትሮሳርድን ለቤስኪታስ ለመሸጥ ከስምምነት ላይ ደርሷል\n\nየ31 አመቱ ወጣት የህክምና ምርመራ ለማድረግ ወደ ኢስታንቡል እንዲሄድ ፍቃድ ተሰጥቶታል። ከመድፈኞቹ ጋር እስከ 2027 ኮንትራት ያለው ትሮሳርድ ክለቡን ከBrighton በ£21m plus add-ons በጥር 2023 ተቀላቅሏል።“ከፕሮፌሽናል እግር ኳስ ተጫዋች ሊያንድሮ ትሮሳርድ እና ክለቡ አርሰናል ጋር ቋሚ ዝውውሩን በሚመለከት ድርድር ተጀምሯል” ሲል የቱርክ ሱፐር ሊግ ቡድን በሰጠው መግለጫ ተናግሯል። በአርሰናል ቤት ባደረጋቸው 174 ጨዋታዎች 36 ጎሎችን አስቆጥሮ 34 ለጎል የሚሆኑ ኳሶችን አስመዝግቧል።ይህም የሚኬል አርቴታ ቡድን ያለፈውን የውድድር አመት የፕሪምየር ሊግ ዋንጫ እንዲያሸንፍ ረድቶታል።'

print("Synthesizing audio...")
audio_path = synthesize_news_audio(title, story)
if audio_path:
    print("Sending to Telegram...")
    success = send_telegram_audio_file(audio_path, caption=f"🔊 {title}")
    if success:
        print("Successfully read the news aloud on Telegram!")
    else:
        print("Failed to send audio.")
    audio_path.unlink(missing_ok=True)
else:
    print("Failed to synthesize audio.")
