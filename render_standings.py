import os
import tempfile
import unicodedata
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import standings

# Re-using logic from standings.py for consistency
AMHARIC_TEAMS = standings.AMHARIC_TEAMS
TEAM_LOGO_FILES = standings.TEAM_LOGO_FILES
LOGO_DIR = standings.LOGO_DIR

def _resolve_logo_path(team_name):
    key = standings._normalize_team_lookup(team_name)
    filename = TEAM_LOGO_FILES.get(key)
    if filename:
        path = LOGO_DIR / filename
        if path.exists():
            return path
    return None

def render_world_cup_group_card(group_name, rows):
    """
    Renders a group standing card for World Cup groups with 8 columns.
    rows: List of dicts with 'team_name', 'played', 'won', 'drawn', 'lost', 'goal_difference', 'points', 'position'
    """
    width = 850
    padding = 40
    row_height = 90
    header_height = 80
    title_height = 100
    
    total_height = title_height + header_height + (len(rows) * row_height) + padding
    
    # Colors
    bg_color = (255, 255, 255, 255)
    header_bg = (245, 245, 247, 255)
    text_color = (0, 0, 0, 255)
    accent_color = (0, 102, 204, 255) # FIFA Blue
    
    image = Image.new("RGBA", (width, total_height), bg_color)
    draw = ImageDraw.Draw(image)
    
    # Fonts
    title_font = standings._load_font(44, bold=True)
    header_font = standings._load_latin_font(26, bold=True)
    am_header_font = standings._load_font(24, bold=True)
    row_font = standings._load_font(32, bold=True)
    num_font = standings._load_latin_font(32, bold=True)
    points_font = standings._load_latin_font(34, bold=True)
    
    # 1. Draw Title
    title_text = f"የዓለም ዋንጫ - {group_name}"
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_w) // 2, 25), title_text, font=title_font, fill=accent_color)
    
    # 2. Draw Table Header
    header_y = title_height
    draw.rectangle([padding, header_y, width - padding, header_y + header_height], fill=header_bg)
    
    # Column Definitions (X-Positions)
    col_pos = padding + 20
    col_team = padding + 90
    col_p = 480
    col_w = 540
    col_d = 600
    col_l = 660
    col_gd = 720
    col_pts = 790
    
    y_text = header_y + 25
    draw.text((col_pos, y_text), "Pos", font=header_font, fill=text_color)
    draw.text((col_team, y_text), "ሀገር (Country)", font=am_header_font, fill=text_color)
    draw.text((col_p, y_text), "P", font=header_font, fill=text_color)
    draw.text((col_w, y_text), "W", font=header_font, fill=text_color)
    draw.text((col_d, y_text), "D", font=header_font, fill=text_color)
    draw.text((col_l, y_text), "L", font=header_font, fill=text_color)
    draw.text((col_gd, y_text), "GD", font=header_font, fill=text_color)
    draw.text((col_pts, y_text), "Pts", font=header_font, fill=text_color)
    
    # 3. Draw Rows
    y = header_y + header_height
    for i, row in enumerate(rows):
        # Alternating background
        if i % 2 == 1:
            draw.rectangle([padding, y, width - padding, y + row_height], fill=(250, 250, 252, 255))
        
        row_center_y = y + (row_height // 2)
        
        # Rank
        pos = str(row['position']).zfill(2)
        standings._draw_left_text_center(draw, pos, col_pos, row_center_y, num_font, text_color)
        
        # Flag + Team Name
        team_name = row['team_name']
        logo_path = _resolve_logo_path(team_name)
        if logo_path:
            logo = standings._fit_logo(standings._load_logo(logo_path), 60)
            logo_y = int(round(row_center_y - 30))
            image.alpha_composite(logo, (col_team, logo_y))
        
        am_name = AMHARIC_TEAMS.get(team_name, team_name)
        if len(am_name) > 18:
            am_name = f"{am_name[:16]}..."
        standings._draw_left_text_center(draw, am_name, col_team + 75, row_center_y, row_font, text_color)
        
        # Stats
        stats = [
            (col_p, str(row['played']), num_font, text_color),
            (col_w, str(row['won']), num_font, text_color),
            (col_d, str(row['drawn']), num_font, text_color),
            (col_l, str(row['lost']), num_font, text_color),
            (col_gd, f"{int(row['goal_difference']):+d}", num_font, text_color),
            (col_pts, str(row['points']), points_font, accent_color),
        ]
        
        for x, val, font, color in stats:
            # Center align numbers in their columns roughly
            bbox = draw.textbbox((0, 0), val, font=font)
            val_w = bbox[2] - bbox[0]
            draw.text((x + (20 - val_w // 2), row_center_y - (bbox[3]-bbox[1])//2 - 5), val, font=font, fill=color)
        
        y += row_height
        # Separator line
        draw.line([padding, y, width - padding, y], fill=(235, 235, 237, 255), width=1)

    # Watermark
    overlay = standings._build_standings_watermark_overlay(width, total_height)
    image = Image.alpha_composite(image, overlay)
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_path = Path(temp_file.name)
    temp_file.close()
    image.convert("RGB").save(temp_path, format="PNG", optimize=True)
    return temp_path
