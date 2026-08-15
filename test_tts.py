from gtts import gTTS
import os

text = "ሰላም፣ ይህ የዜና ሙከራ ነው"
lang = 'am'
filename = "test_amharic.mp3"

print(f"Synthesizing text: {text}")
try:
    tts = gTTS(text=text, lang=lang)
    tts.save(filename)
    print(f"Successfully saved to {filename}")
    
    # Attempt to play the file on macOS
    os.system(f"afplay {filename}")
except Exception as e:
    print(f"Error: {e}")
