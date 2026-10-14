import tempfile
from pathlib import Path
from PIL import Image, ImageDraw
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
    def fit_name(name, font, max_w):
        if not name:
            return ""
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
