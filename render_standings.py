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


def render_match_score_card(home_team, away_team, home_score, away_score, competition_title, status="FULL TIME"):
    width = 700
    padding = 50
    title_height = 90
    score_area_height = 220
    status_height = 70
    total_height = title_height + score_area_height + status_height + padding

    # Improved professional color palette
    bg_color = (250, 250, 252, 255)       # Very light grey/blue
    text_color = (30, 30, 35, 255)       # Dark charcoal
    accent_color = (0, 60, 150, 255)     # Deep professional blue
    score_bg = (240, 240, 245, 255)      # Light contrast for score area
    status_color = (100, 100, 110, 255)  # Muted grey for status

    image = Image.new("RGBA", (width, total_height), bg_color)
    draw = ImageDraw.Draw(image)

    title_font = standings._load_font(36, bold=True)
    team_font = standings._load_font(34, bold=True)
    score_font = standings._load_latin_font(64, bold=True)
    status_font = standings._load_font(28, bold=True)

    # 1. Title
    title_text = competition_title or "Match Result"
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_w) // 2, 25), title_text, font=title_font, fill=accent_color)

    # 2. Score Area
    center_y = title_height + (score_area_height // 2)
    
    # Draw a subtle background for the score area to avoid overlap feel
    draw.rounded_rectangle(
        [padding, title_height + 20, width - padding, title_height + score_area_height - 20], 
        radius=20, fill=score_bg
    )

    home_logo = _resolve_logo_path(home_team)
    away_logo = _resolve_logo_path(away_team)

    home_x = padding + 60
    away_x = width - padding - 60
    
    # Dynamic space for names to prevent overlap with center score
    # Total width 700. Center score takes ~200. 
    # Each side gets ~250.
    max_name_w = 200 

    if home_logo:
        logo = standings._fit_logo(standings._load_logo(home_logo), 80)
        logo_y = int(round(center_y - 40))
        image.alpha_composite(logo, (home_x, logo_y))

    if away_logo:
        logo = standings._fit_logo(standings._load_logo(away_logo), 80)
        logo_y = int(round(center_y - 40))
        image.alpha_composite(logo, (away_x - 80, logo_y))

    home_name = standings.AMHARIC_TEAMS.get(home_team, home_team)
    away_name = standings.AMHARIC_TEAMS.get(away_team, away_team)

    # Truncate names if they are too long to prevent overlap
    def truncate_text(text, font, max_w):
        while len(text) > 0 and (draw.textbbox((0, 0), text, font=font)[2] > max_w):
            text = text[:-1]
        return text + "..." if len(text) < len(home_name) if 'home_name' in locals() else False else text

    # Simplified truncation for Amharic
    def fit_name(name, font, max_w):
        if draw.textbbox((0, 0), name, font=font)[2] > max_w:
            return name[:10] + "..." 
        return name

    home_name = fit_name(home_name, team_font, max_name_w)
    away_name = fit_name(away_name, team_font, max_name_w)

    draw.text((home_x + 90, center_y - 10), home_name, font=team_font, fill=text_color)
    draw.text((away_x - 90, center_y - 10), away_name, font=team_font, fill=text_color, anchor="rt")

    score_text = f"{home_score} - {away_score}"
    score_bbox = draw.textbbox((0, 0), score_text, font=score_font)
    score_w = score_bbox[2] - score_bbox[0]
    draw.text(((width - score_w) // 2, center_y - 40), score_text, font=score_font, fill=accent_color)

    # 3. Status
    status_y = title_height + score_area_height + 20
    status_bbox = draw.textbbox((0, 0), status, font=status_font)
    status_w = status_bbox[2] - status_bbox[0]
    draw.text(((width - status_w) // 2, status_y), status, font=status_font, fill=status_color)

    overlay = standings._build_standings_watermark_overlay(width, total_height)
    image = Image.alpha_composite(image, overlay)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_path = Path(temp_file.name)
    temp_file.close()
    image.convert("RGB").save(temp_path, format="PNG", optimize=True)
    return temp_path
