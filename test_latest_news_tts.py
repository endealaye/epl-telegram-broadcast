from gtts import gTTS
import os

title = 'ጋሪ ኔቪል፦ "እንግሊዝ የተከላካይ መስመር ቦታውን በማንኳሰሷ አሁን ዋጋ እየከፈለች ነው!"'
story = '\nየእንግሊዝ ብሔራዊ ቡድን በለመደው ስህተት የክንፍ ተከላካይ (Full-back) ቦታን በማንኳሰሱ ምክንያት፣ ረቡዕ እለት ከዲአር ኮንጎ ጋር ለሚያደርገው የዓለም ዋንጫ የ32ቱ ዙር ወሳኝ ፍልሚያ በቀኝ ተከላካይ መስመር ላይ ከፍተኛ ቀውስ ውስጥ መውደቁን ጋሪ ኔቪል ተቸ።\n\nየመጀመሪያ ተመራጩ የቀኝ ተከላካይ ሪስ ጄምስ በጡንቻ መሳብ (Hamstring) ጉዳት ከጨዋታ ውጪ መሆኑ ሲረጋገጥ፣ ተጠባባቂው ቲኖ ሊቭራሜንቶም በተመሳሳይ ጉዳት ገና ውድድሩ ሳይጀምር ከስብስቡ መቀነሱ የቶማስ ቱሄልን ስብስብ ክፉኛ ጎድቶታል። በዚህም ምክንያት ቱሄል በቶተንሃም በግራ ተከላካይነት ሲጫወት የነበረውን ጄድ ስፔንስን፣ አልያም የመሀል ተከላካዮቹን ጃሬል ኳንሳን ወይም ኤዝሪ ኮንሳን በቀኝ መስመር ላይ ለማሰለፍ ለመወሰን ተገዷል። ኔቪል አክሎም፣ ሁለቱ ተጫዋቾች በተደጋጋሚ የሚጎዱ መሆናቸውን እያወቁ ቱሄል ቅድመ-ዝግጅት አለማድረጉ ስህተት መሆኑን ገልጾ፣ ጠንካራዋ ዲአር ኮንጎ ለእንግሊዝ ከባድ ፈተና እንደምትሆን አስጠንቅቋል።'

full_text = f"{title}. {story}"
lang = 'am'
filename = "latest_news_tts.mp3"

print(f"Synthesizing latest news...")
try:
    tts = gTTS(text=full_text, lang=lang)
    tts.save(filename)
    print(f"Successfully saved to {filename}")
    os.system(f"afplay {filename}")
except Exception as e:
    print(f"Error: {e}")
