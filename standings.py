import os
import re
import tempfile
import unicodedata
from collections import defaultdict
from functools import cmp_to_key
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from bot_config import AMHARIC_TEAMS, TEAM_MAPPING
from commands import send_admin_alert, send_telegram_message, send_telegram_photo_file
from store import supabase

OFFICIAL_STANDINGS_API_BASE = os.getenv(
    "PL_STANDINGS_API_BASE",
    "https://sdp-prem-prod.premier-league-prod.pulselive.com/api",
)
OFFICIAL_COMPETITION_ID = os.getenv("PL_STANDINGS_COMPETITION_ID", "8")
OFFICIAL_SEASON_ID = os.getenv("PL_STANDINGS_SEASON_ID", "2025")
DEFAULT_STANDINGS_FORMAT = os.getenv("PL_STANDINGS_FORMAT", "short").strip().lower()
STANDINGS_IMAGE_ROW_HEIGHT = int(os.getenv("STANDINGS_IMAGE_ROW_HEIGHT", "90"))
STANDINGS_IMAGE_PADDING = int(os.getenv("STANDINGS_IMAGE_PADDING", "24"))
STANDINGS_IMAGE_WIDTH = int(os.getenv("STANDINGS_IMAGE_WIDTH", "700"))
STANDINGS_LOGO_SIZE = int(os.getenv("STANDINGS_LOGO_SIZE", "65"))
STANDINGS_ROW_X_OFFSET = int(os.getenv("STANDINGS_ROW_X_OFFSET", "100"))
LOCAL_ETHIOPIC_FONT = (
    Path(__file__).resolve().parent / "NotoSansEthiopic-VariableFont_wdth,wght.ttf"
)
LOGO_DIR = Path(__file__).resolve().parent / "logo"
_LOGO_CACHE = {}
TEAM_LOGO_FILES = {
    "arsenal": "arsenal.png",
    "aston villa": "Aston Villa.png",
    "bournemouth": "Bournemouth.png",
    "brentford": "Brentford.png",
    "brighton": "Brighton & Hove Albion.png",
    "brighton & hove albion": "Brighton & Hove Albion.png",
    "bayern munchen": "Bayern München.png",
    "bayern munich": "Bayern München.png",
    "burnley": "Burnley.png",
    "chelsea": "Chelsea.png",
    "crystal palace": "Crystal Palace.png",
    "everton": "Everton.png",
    "fulham": "Fulham.png",
    "leeds": "Leeds United F.C..png",
    "leeds united": "Leeds United F.C..png",
    "liverpool": "Liverpool.png",
    "man city": "Manchester City.png",
    "manchester city": "Manchester City.png",
    "man utd": "Manchester United.png",
    "manchester united": "Manchester United.png",
    "newcastle": "Newcastle United.png",
    "newcastle united": "Newcastle United.png",
    "nott'm forest": "Nottingham Forest.png",
    "nottingham forest": "Nottingham Forest.png",
    "paris": "Paris.png",
    "paris saint-germain": "Paris.png",
    "paris saint germain": "Paris.png",
    "spurs": "Tottenham_Hotspur.png",
    "tottenham": "Tottenham_Hotspur.png",
    "tottenham hotspur": "Tottenham_Hotspur.png",
    "sunderland": "Sunderland.png",
    "west ham": "West Ham United.png",
    "west ham united": "West Ham United.png",
    "wolves": "Wolverhampton Wanderers.png",
    "wolverhampton wanderers": "Wolverhampton Wanderers.png",
}


def _sanitize_error_text(text):
    value = str(text or "")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<redacted>", value)


def normalize_team_name(name):
    if not name:
        return ""
    return TEAM_MAPPING.get(name, name)


def parse_score(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_official_standings(
    competition_id=OFFICIAL_COMPETITION_ID,
    season_id=OFFICIAL_SEASON_ID,
    live=False,
):
    url = (
        f"{OFFICIAL_STANDINGS_API_BASE}/v5/competitions/{competition_id}"
        f"/seasons/{season_id}/standings"
    )
    response = requests.get(
        url,
        params={"live": str(bool(live)).lower()},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def parse_official_standings(payload):
    tables = payload.get("tables") or []
    if not tables:
        return []
    entries = tables[0].get("entries") or []
    rows = []
    for entry in entries:
        team_info = entry.get("team") or {}
        overall = entry.get("overall") or {}
        team_short = (team_info.get("shortName") or "").strip()
        team_name = (team_info.get("name") or "").strip() or team_short
        team_key = normalize_team_name(team_short or team_name)
        rows.append(
            {
                "team": team_key or team_name,
                "team_display": team_name,
                "played": int(overall.get("played") or 0),
                "won": int(overall.get("won") or 0),
                "drawn": int(overall.get("drawn") or 0),
                "lost": int(overall.get("lost") or 0),
                "gf": int(overall.get("goalsFor") or 0),
                "ga": int(overall.get("goalsAgainst") or 0),
                "gd": int(overall.get("goalsFor") or 0) - int(overall.get("goalsAgainst") or 0),
                "points": int(overall.get("points") or 0),
                "position": int(overall.get("position") or 0),
            }
        )
    rows.sort(key=lambda row: row["position"])
    return rows


def fetch_completed_fixtures():
    if not supabase:
        return []
    query = supabase.table("fixtures").select(
        "hometeam,awayteam,hometeamscore,awayteamscore,dateeat,matchgroup"
    )
    try:
        season_start_year = int(OFFICIAL_SEASON_ID)
        season_start = f"{season_start_year}-08-01 00:00:00"
        season_end = f"{season_start_year + 1}-08-01 00:00:00"
        query = query.gte("dateeat", season_start).lt("dateeat", season_end)
    except (TypeError, ValueError):
        pass

    res = query.execute()
    completed = []
    for row in res.data or []:
        if (row.get("matchgroup") or "Premier League") != "Premier League":
            continue
        home = normalize_team_name(row.get("hometeam"))
        away = normalize_team_name(row.get("awayteam"))
        home_score = parse_score(row.get("hometeamscore"))
        away_score = parse_score(row.get("awayteamscore"))
        if not home or not away or home_score is None or away_score is None:
            continue
        completed.append(
            {
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
            }
        )
    return completed


def init_row(team):
    return {
        "team": team,
        "played": 0,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "gf": 0,
        "ga": 0,
        "gd": 0,
        "points": 0,
    }


def update_row(row, scored, conceded):
    row["played"] += 1
    row["gf"] += scored
    row["ga"] += conceded
    if scored > conceded:
        row["won"] += 1
        row["points"] += 3
    elif scored == conceded:
        row["drawn"] += 1
        row["points"] += 1
    else:
        row["lost"] += 1


def base_sort_key(row):
    return (-row["points"], -row["gd"], -row["gf"], row["team"])


def h2h_stats(fixtures, tie_group):
    teams = {row["team"] for row in tie_group}
    stats = {team: {"points": 0, "away_goals": 0} for team in teams}
    for match in fixtures:
        home = match["home"]
        away = match["away"]
        if home not in teams or away not in teams:
            continue

        home_score = match["home_score"]
        away_score = match["away_score"]

        if home_score > away_score:
            stats[home]["points"] += 3
        elif home_score < away_score:
            stats[away]["points"] += 3
        else:
            stats[home]["points"] += 1
            stats[away]["points"] += 1

        stats[away]["away_goals"] += away_score
    return stats


def resolve_tie_group(fixtures, tie_group):
    stats = h2h_stats(fixtures, tie_group)

    def compare(a, b):
        a_stats = stats[a["team"]]
        b_stats = stats[b["team"]]
        if a_stats["points"] != b_stats["points"]:
            return -1 if a_stats["points"] > b_stats["points"] else 1
        if a_stats["away_goals"] != b_stats["away_goals"]:
            return -1 if a_stats["away_goals"] > b_stats["away_goals"] else 1
        return -1 if a["team"] < b["team"] else (1 if a["team"] > b["team"] else 0)

    return sorted(tie_group, key=cmp_to_key(compare))


def compute_standings(fixtures):
    table = defaultdict(dict)
    for match in fixtures:
        home = match["home"]
        away = match["away"]
        if home not in table:
            table[home] = init_row(home)
        if away not in table:
            table[away] = init_row(away)

        update_row(table[home], match["home_score"], match["away_score"])
        update_row(table[away], match["away_score"], match["home_score"])

    rows = list(table.values())
    for row in rows:
        row["gd"] = row["gf"] - row["ga"]

    rows.sort(key=base_sort_key)

    resolved = []
    idx = 0
    while idx < len(rows):
        current = rows[idx]
        tie_group = [current]
        next_idx = idx + 1
        while next_idx < len(rows):
            candidate = rows[next_idx]
            if (
                candidate["points"] == current["points"]
                and candidate["gd"] == current["gd"]
                and candidate["gf"] == current["gf"]
            ):
                tie_group.append(candidate)
                next_idx += 1
                continue
            break

        if len(tie_group) > 1:
            resolved.extend(resolve_tie_group(fixtures, tie_group))
        else:
            resolved.extend(tie_group)
        idx = next_idx

    for position, row in enumerate(resolved, start=1):
        row["position"] = position
    return resolved


def format_row(row):
    team_key = row.get("team") or ""
    team_display = row.get("team_display") or team_key
    team_am = AMHARIC_TEAMS.get(team_key, AMHARIC_TEAMS.get(team_display, team_display))
    gd_text = f"+{row['gd']}" if row["gd"] >= 0 else str(row["gd"])
    return (
        f"{row['position']:>2}. {team_am} ({team_display}) "
        f"{row['played']}ጨ {row['points']}ነጥብ "
        f"GD {gd_text} GF {row['gf']}"
    )


def format_short_row(row):
    team_key = row.get("team") or ""
    team_display = row.get("team_display") or team_key
    team_am = AMHARIC_TEAMS.get(team_key, AMHARIC_TEAMS.get(team_display, team_display))
    gd_text = f"+{row['gd']}" if row["gd"] >= 0 else str(row["gd"])
    return (
        f"{row['position']:>2}. {team_am} ({team_display}) "
        f"P {row['played']} W {row['won']} GD {gd_text} Pts {row['points']}"
    )


def format_team_cell(name, width=18):
    label = " ".join((name or "").split())
    if len(label) > width:
        return f"{label[:width - 3]}..."
    return label.ljust(width)


def format_short_table(rows):
    team_width = 18
    header = f"{'Pos':>3}  {'Team':<{team_width}}  {'P':>2} {'W':>2} {'GD':>4} {'Pts':>3}"
    divider = "-" * len(header)
    lines = [header, divider]
    for row in rows:
        team_key = row.get("team") or ""
        team_display = row.get("team_display") or team_key
        team_display = AMHARIC_TEAMS.get(team_key, AMHARIC_TEAMS.get(team_display, team_display))
        gd_text = f"{int(row['gd']):+d}"
        lines.append(
            f"{int(row['position']):>3}  {format_team_cell(team_display, team_width)}  "
            f"{int(row['played']):>2} {int(row['won']):>2} {gd_text:>4} {int(row['points']):>3}"
        )
    return "\n".join(lines)


def _load_font(size, bold=False):
    candidates = []
    if LOCAL_ETHIOPIC_FONT.exists():
        candidates.append(str(LOCAL_ETHIOPIC_FONT))
    candidates.extend(
        [
            "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
            "/usr/share/fonts/truetype/abyssinica/AbyssinicaSIL-Regular.ttf",
            "/System/Library/Fonts/GeezaPro.ttc",
            "/System/Library/Fonts/Supplemental/NotoSansEthiopic-Regular.ttf",
        ]
    )
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size=size)
            except OSError:
                continue
            if "VariableFont" in os.path.basename(path):
                try:
                    target_weight = 800 if bold else 520
                    axes = font.get_variation_axes()
                    if axes:
                        resolved_axes = []
                        for axis in axes:
                            axis_min = axis.get("minimum")
                            axis_max = axis.get("maximum")
                            axis_name = (axis.get("name") or b"").decode("utf-8", errors="ignore").lower()
                            if "weight" in axis_name and axis_min is not None and axis_max is not None:
                                resolved_axes.append(max(axis_min, min(axis_max, target_weight)))
                            elif axis_name and axis_min is not None and axis_max is not None:
                                resolved_axes.append(max(axis_min, min(axis_max, axis.get("default", axis_min))))
                        if resolved_axes:
                            font.set_variation_by_axes(resolved_axes)
                except Exception:
                    pass
            return font
    return ImageFont.load_default()


def _load_latin_font(size, bold=False):
    candidates = []
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _row_accent_color(position):
    if position <= 4:
        return (0, 126, 255)
    if position <= 6:
        return (255, 133, 0)
    if position >= 18:
        return (226, 59, 103)
    return None


def _normalize_team_lookup(name):
    value = unicodedata.normalize("NFKD", (name or "").strip().lower())
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _resolve_logo_path(row):
    candidates = [
        row.get("team"),
        row.get("team_display"),
    ]
    for candidate in candidates:
        key = _normalize_team_lookup(candidate)
        filename = TEAM_LOGO_FILES.get(key)
        if filename:
            path = LOGO_DIR / filename
            if path.exists():
                return path
    return None


def _load_logo(path):
    cache_key = str(path)
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key].copy()
    with Image.open(path) as image:
        logo = image.convert("RGBA")
    _LOGO_CACHE[cache_key] = logo
    return logo.copy()


def _fit_logo(logo, size):
    width, height = logo.size
    if width <= 0 or height <= 0:
        return logo
    scale = min(size / width, size / height)
    target = (max(1, int(width * scale)), max(1, int(height * scale)))
    resized = logo.resize(target, Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    x = (size - target[0]) // 2
    y = (size - target[1]) // 2
    canvas.alpha_composite(resized, (x, y))
    return canvas


def _draw_cell_text(draw, text, x0, x1, y, align, font, fill):
    text = str(text)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    width = right - left
    if align == "right":
        x = x1 - width
    else:
        x = x0
    text_y = y - ((top + bottom) / 2.0)
    draw.text((x, text_y), text, font=font, fill=fill)


def _draw_left_text_center(draw, text, x, y, font, fill, stroke_width=0, stroke_fill=None):
    text = str(text)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_y = y - ((top + bottom) / 2.0)
    draw.text(
        (x, text_y),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill if stroke_fill is not None else fill,
    )


def _build_standings_watermark_overlay(width, height):
    from news_pipeline import build_watermark_overlay

    return build_watermark_overlay(width, height)


def _short_team_name(row):
    team_key = row.get("team") or ""
    team_display = (row.get("team_display") or row.get("team") or "").strip()
    team = AMHARIC_TEAMS.get(team_key, AMHARIC_TEAMS.get(team_display, team_display))
    if len(team) <= 26:
        return team
    return f"{team[:23].rstrip()}..."


def render_short_standings_image(rows, matchweek=None):
    if not rows:
        raise ValueError("No standings rows to render.")

    width = max(STANDINGS_IMAGE_WIDTH, 1120)
    padding = max(16, STANDINGS_IMAGE_PADDING)
    row_height = max(42, STANDINGS_IMAGE_ROW_HEIGHT)
    header_height = 70
    title_height = 140
    content_height = title_height + header_height + (row_height * len(rows)) + padding
    height = content_height + (padding * 2)

    image = Image.new("RGBA", (width, height), (246, 246, 247, 255))
    draw = ImageDraw.Draw(image)

    panel_x0 = padding
    panel_y0 = padding
    panel_x1 = width - padding
    panel_y1 = height - padding
    draw.rectangle((panel_x0, panel_y0, panel_x1, panel_y1), fill=(246, 246, 247, 255))

    title_font = _load_font(48, bold=True)
    subtitle_font = _load_font(34, bold=True)
    head_font = _load_latin_font(30, bold=True)
    row_font = _load_font(34, bold=True)
    row_num_font = _load_latin_font(32, bold=True)
    row_points_font = _load_latin_font(34, bold=True)

    title = "የፕሪሚየር ሊግ ደረጃ ሰንጠረዥ"
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_box[2] - title_box[0]
    title_x = panel_x0 + ((panel_x1 - panel_x0 - title_width) // 2)
    draw.text((title_x, panel_y0 + 8), title, font=title_font, fill=(0, 0, 0))
    season_label = f"{OFFICIAL_SEASON_ID}-{int(OFFICIAL_SEASON_ID) + 1}" if str(OFFICIAL_SEASON_ID).isdigit() else str(OFFICIAL_SEASON_ID)
    if matchweek:
        season_label = f"{season_label} · {matchweek}ኛ ሳምንት"
    subtitle_box = draw.textbbox((0, 0), season_label, font=subtitle_font)
    subtitle_width = subtitle_box[2] - subtitle_box[0]
    subtitle_x = panel_x0 + ((panel_x1 - panel_x0 - subtitle_width) // 2)
    draw.text((subtitle_x, panel_y0 + 70), season_label, font=subtitle_font, fill=(0, 0, 0))

    table_top = panel_y0 + title_height + 18
    # Keep position/team anchored to base axis; apply offset only to stats columns.
    stats_x_offset = STANDINGS_ROW_X_OFFSET
    col_pos = 60
    col_team = col_pos + 76
    logo_x = col_team
    team_text_x = logo_x + STANDINGS_LOGO_SIZE + 12
    stat_cols = ["GP", "W", "GD", "P"]
    stat_step = 121
    col_positions = {
        "GP": 600 + stats_x_offset,
        "W": 600 + stats_x_offset + stat_step,
        "GD": 600 + stats_x_offset + (stat_step * 2),
        "P": 600 + stats_x_offset + (stat_step * 3),
    }

    for key in stat_cols:
        _draw_cell_text(draw, key, col_positions[key] - 52, col_positions[key], table_top + 28, "right", head_font, (0, 0, 0))
    draw.text((col_pos, table_top + 8), "Pos", font=head_font, fill=(0, 0, 0))
    draw.text((logo_x, table_top + 8), "Team Name", font=head_font, fill=(0, 0, 0))

    y = table_top + 56
    for row in rows:
        pos_text = f"{int(row['position']):02d}"
        team_text = _short_team_name(row)
        gd_text = f"{int(row['gd']):+d}"
        color = (0, 0, 0)
        row_center_y = y + (row_height // 2)
        position_value = int(row["position"])

        # Alternate full-row band (odd positions only).
        if position_value % 2 == 1:
            team_band_x0 = panel_x0 + 16
            team_band_x1 = panel_x1 - 16
            draw.rectangle(
                (team_band_x0, y + 8, team_band_x1, y + row_height - 8),
                fill=(234, 234, 236, 255),
            )

        _draw_left_text_center(draw, f"{position_value:02d}", col_pos, row_center_y, row_num_font, (0, 0, 0))
        logo_path = _resolve_logo_path(row)
        if logo_path:
            logo = _fit_logo(_load_logo(logo_path), STANDINGS_LOGO_SIZE)
            logo_y = int(round(row_center_y - (STANDINGS_LOGO_SIZE / 2.0)))
            image.alpha_composite(logo, (logo_x, logo_y))
        _draw_left_text_center(draw, team_text, team_text_x, row_center_y, row_font, (0, 0, 0))

        _draw_cell_text(draw, int(row["played"]), col_positions["GP"] - 52, col_positions["GP"], row_center_y, "right", row_num_font, color)
        _draw_cell_text(draw, int(row["won"]), col_positions["W"] - 52, col_positions["W"], row_center_y, "right", row_num_font, color)
        _draw_cell_text(draw, gd_text, col_positions["GD"] - 64, col_positions["GD"], row_center_y, "right", row_num_font, color)
        _draw_cell_text(draw, int(row["points"]), col_positions["P"] - 52, col_positions["P"], row_center_y, "right", row_points_font, color)
        y += row_height

    overlay = _build_standings_watermark_overlay(*image.size)
    image = Image.alpha_composite(image, overlay)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_path = Path(temp_file.name)
    temp_file.close()
    image.convert("RGB").save(temp_path, format="PNG", optimize=True)
    return temp_path


def resolve_standings_format(format_name):
    value = (format_name or DEFAULT_STANDINGS_FORMAT or "short").strip().lower()
    if value in {"short", "s", "compact"}:
        return "short"
    return "full"


def format_standings_message(rows, source_label=None, matchweek=None, format_name=None):
    style = resolve_standings_format(format_name)
    header = "📊 *የፕሪሚየር ሊግ ደረጃ ሰንጠረዥ*"
    lines = [header, ""]
    if matchweek:
        lines.append(f"Matchweek: {matchweek}")
    if source_label and style != "short":
        lines.append(f"Source: {source_label}")
    if style != "short":
        lines.append(f"Format: {style}")
    if matchweek or (source_label and style != "short"):
        lines.append("")
    if style == "short":
        lines.append("```")
        lines.append(format_short_table(rows))
        lines.append("```")
    else:
        for row in rows:
            lines.append(format_row(row))
    lines.append("")
    lines.append("_Tie-break order: Points, GD, GF, H2H points, H2H away goals._")
    return "\n".join(lines)


def broadcast_standings(format_name=None):
    try:
        standings = []
        source = None
        matchweek = None
        fallback_reason = None

        try:
            official_payload = fetch_official_standings()
            standings = parse_official_standings(official_payload)
            matchweek = official_payload.get("matchweek")
            source = "premierleague.com official API"
        except Exception as official_exc:
            fallback_reason = str(official_exc)

        if not standings:
            fixtures = fetch_completed_fixtures()
            if fixtures:
                standings = compute_standings(fixtures)
                source = "local fixtures fallback"
            else:
                return {
                    "success": False,
                    "skipped": True,
                    "message": "Skip standings: no data from official API or local fixtures.",
                    "data": {
                        "source": "none",
                        "fallback_error": fallback_reason,
                    },
                }

        resolved_format = resolve_standings_format(format_name)
        if resolved_format == "short":
            image_path = render_short_standings_image(standings, matchweek=matchweek)
            try:
                caption = "📊 *Premier League Table*"
                sent = send_telegram_photo_file(image_path, caption)
            finally:
                image_path.unlink(missing_ok=True)
        else:
            message = format_standings_message(
                standings,
                source_label=source,
                matchweek=matchweek,
                format_name=resolved_format,
            )
            sent = send_telegram_message(message)
        if not sent:
            raise RuntimeError("Telegram delivery failed. Check bot configuration.")
        return {
            "success": True,
            "skipped": False,
            "message": f"Standings sent for {len(standings)} teams.",
            "data": {
                "teams": len(standings),
                "source": source,
                "matchweek": matchweek,
                "leader": standings[0]["team"] if standings else None,
                "fallback_error": fallback_reason,
                "format": resolved_format,
            },
        }
    except Exception as exc:
        error_msg = f"Standings broadcast error: {_sanitize_error_text(exc)}"
        print(error_msg)
        try:
            send_admin_alert(error_msg)
        except Exception:
            print("Admin alert failed.")
        return {
            "success": False,
            "skipped": False,
            "message": error_msg,
            "data": {},
        }
