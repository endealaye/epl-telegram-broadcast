import os
from PIL import Image
from collections import Counter

FLAG_DIR = "logo/flags"
WHITE_THRESHOLD = 200

def get_near_white_colors(image_path):
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            pixels = list(img.getdata())
            
            near_white = [p for p in pixels if p[0] >= WHITE_THRESHOLD and p[1] >= WHITE_THRESHOLD and p[2] >= WHITE_THRESHOLD]
            
            if not near_white:
                return None
                
            counts = Counter(near_white)
            most_common = counts.most_common(3)
            return [f"RGB{c[0]} (count: {c[1]})" for c in most_common]
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    files = [f for f in os.listdir(FLAG_DIR) if f.endswith(".png")]
    for f in sorted(files):
        colors = get_near_white_colors(os.path.join(FLAG_DIR, f))
        if colors:
            print(f"{f}: {', '.join(colors)}")
