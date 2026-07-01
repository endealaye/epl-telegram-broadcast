import os
import sys
import subprocess
import requests
import tempfile
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Add path to import from workspace
sys.path.append('/Users/nebiyou.yirga/Downloads/ft_dd')

# Load environmental variables
from dotenv import load_dotenv
load_dotenv('/Users/nebiyou.yirga/Downloads/ft_dd/.env')

from store import supabase

FONT_PATH = "/Users/nebiyou.yirga/Downloads/ft_dd/NotoSansEthiopic-VariableFont_wdth,wght.ttf"

def wrap_text(text, font, max_width, draw):
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        current_line.append(word)
        test_line = " ".join(current_line)
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w > max_width:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
            
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def compose_video(news_id=None):
    # 1. Fetch news item
    print("Fetching news item from Supabase...")
    query = supabase.table('news_items').select('*').eq('review_status', 'published')
    if news_id:
        query = query.eq('id', news_id)
    else:
        query = query.order('published_at', desc=True).limit(1)
        
    res = query.execute()
    if not res.data:
        print("No published news items found.")
        return False
        
    news = res.data[0]
    title = news['translated_title_am']
    story = news['translated_story_am']
    image_url = news['image_url']
    
    print(f"Using News ID: {news['id']}")
    print(f"Title: {title}")
    
    # 2. Download Image
    print(f"Downloading image from {image_url}...")
    img_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    try:
        response = requests.get(image_url, timeout=20)
        response.raise_for_status()
        img_temp.write(response.content)
        img_temp.close()
        original_image_path = img_temp.name
    except Exception as e:
        print(f"Failed to download image: {e}")
        img_temp.close()
        return False

    try:
        # Load images
        orig_img = Image.open(original_image_path).convert("RGBA")
    except Exception as e:
        print(f"Failed to open image: {e}")
        return False

    # Setup directories
    temp_dir = Path("/Users/nebiyou.yirga/Downloads/ft_dd/temp_frames")
    temp_dir.mkdir(exist_ok=True)
    
    # Video details
    width, height = 1080, 1920
    fps = 30
    duration_secs = 10
    total_frames = fps * duration_secs
    
    # Fonts
    title_font = ImageFont.truetype(FONT_PATH, 44)
    story_font = ImageFont.truetype(FONT_PATH, 30)
    
    print("Generating frames...")
    
    # Text calculation
    # We create a dummy image to calculate wrap heights
    dummy_img = Image.new("RGBA", (width, height))
    dummy_draw = ImageDraw.Draw(dummy_img)
    
    # Text card margins and padding
    card_margin_x = 50
    card_width = width - (card_margin_x * 2) # 980
    card_padding = 40
    text_max_width = card_width - (card_padding * 2) # 900
    
    title_lines = wrap_text(title, title_font, text_max_width, dummy_draw)
    story_lines = wrap_text(story, story_font, text_max_width, dummy_draw)
    
    # Calculate box height dynamically
    line_spacing = 15
    title_height = len(title_lines) * (title_font.size + line_spacing)
    story_height = len(story_lines) * (story_font.size + line_spacing)
    
    card_height = title_height + story_height + (card_padding * 2) + 20
    card_y0 = height - card_height - 80 # 80px margin from bottom
    card_y1 = height - 80
    
    # Pre-render card background elements
    card_x0 = card_margin_x
    card_x1 = width - card_margin_x
    
    for i in range(total_frames):
        # Progress
        if i % 30 == 0:
            print(f"Frame {i}/{total_frames}")
            
        # Ken burns zoom calculation (background zoom from 1.0 to 1.12)
        progress = i / total_frames
        zoom = 1.0 + (progress * 0.12)
        
        # 1. Create Background (Blurred & Darkened)
        bg_w = int(width * zoom)
        bg_h = int(height * zoom)
        bg_resized = orig_img.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
        
        # Crop to center
        left = (bg_w - width) // 2
        top = (bg_h - height) // 2
        bg_cropped = bg_resized.crop((left, top, left + width, top + height))
        
        # Blur background
        bg_blurred = bg_cropped.filter(ImageFilter.GaussianBlur(radius=25))
        
        # Darken background
        dark_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 100))
        bg_final = Image.alpha_composite(bg_blurred, dark_overlay)
        
        # 2. Add Sharper Image in Center (Landscape/Horizontal format)
        # Scale original image to width 1080
        aspect_ratio = orig_img.height / orig_img.width
        fg_w = width
        fg_h = int(width * aspect_ratio)
        fg_resized = orig_img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)
        
        # Place in center vertically
        fg_y = (height - fg_h) // 2 - 150 # slightly higher than center
        bg_final.paste(fg_resized, (0, fg_y), fg_resized)
        
        # 3. Create Draw Context
        draw = ImageDraw.Draw(bg_final)
        
        # 4. Draw Semi-transparent Card
        # Draw dark card container
        draw.rounded_rectangle(
            (card_x0, card_y0, card_x1, card_y1),
            radius=30,
            fill=(0, 0, 0, 185),
            outline=(255, 255, 255, 45),
            width=2
        )
        
        # 5. Draw Title (Gold)
        curr_y = card_y0 + card_padding
        for line in title_lines:
            draw.text(
                (card_x0 + card_padding, curr_y),
                line,
                font=title_font,
                fill=(255, 215, 0, 255) # Gold
            )
            curr_y += title_font.size + line_spacing
            
        # Draw separator line
        curr_y += 10
        draw.line(
            (card_x0 + card_padding, curr_y, card_x1 - card_padding, curr_y),
            fill=(255, 255, 255, 50),
            width=1
        )
        curr_y += 20
        
        # 6. Draw Story (White)
        for line in story_lines:
            draw.text(
                (card_x0 + card_padding, curr_y),
                line,
                font=story_font,
                fill=(255, 255, 255, 240) # Off-white
            )
            curr_y += story_font.size + line_spacing
            
        # 7. Save frame
        frame_path = temp_dir / f"frame_{i:04d}.png"
        bg_final.convert("RGB").save(frame_path, format="PNG")
        
    print("Stitching frames with ffmpeg...")
    output_path = "/Users/nebiyou.yirga/Downloads/ft_dd/output_short.mp4"
    
    # Run ffmpeg to compile frames to MP4
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(temp_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level", "4.0",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        output_path
    ]
    
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        print(f"Video successfully created at {output_path}")
        success = True
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed: {e}")
        success = False
        
    # Cleanup temp folders
    print("Cleaning up temporary files...")
    shutil.rmtree(temp_dir)
    os.unlink(original_image_path)
    
    return success

if __name__ == '__main__':
    # You can pass a news ID as an argument to process a specific news item
    news_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    compose_video(news_id)
