from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import uuid

from PIL import Image, ImageDraw

from bot_config import AMHARIC_TEAMS, get_eat_now, get_eat_today, parse_eat_datetime
from commands import send_admin_alert, send_telegram_message, send_telegram_photo_file
from news_pipeline import load_watermark_image, resolve_watermark_asset
from standings import (
    _build_standings_watermark_overlay,
    _fit_logo,
    _load_font,
    _load_latin_font,
    _load_logo,
    _resolve_logo_path,
    broadcast_standings,
)
from store import (
    acquire_bot_lock,
    fetch_fixtures_for_dates,
    fixture_competition_name,
    fixtures_in_window,
    get_bot_state_value,
    has_matches_today,
    has_pending_results,
    has_upcoming_matches,
    is_premier_league_fixture,
    mark_match_state,
    release_bot_lock,
    set_bot_state_value,
    supabase,
)

FIXTURE_IMAGE_WIDTH = 1200
FIXTURE_IMAGE_PADDING = 36
FIXTURE_IMAGE_HEADER_HEIGHT = 170
FIXTURE_IMAGE_GROUP_HEADER = 42
FIXTURE_IMAGE_ROW_HEIGHT = 260
FIXTURE_LOGO_SIZE = 118


def _team_badge_label(team_name):
    words = [part for part in (team_name or "").replace("&", " ").replace(".", " ").split() if part]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(word[0].upper() for word in words[:3])


def _draw_badge_fallback(image, draw, x, y, size, team_name):
    fill = (238, 240, 247, 255)
    outline = (185, 190, 205, 255)
    text_fill = (58, 64, 84, 255)
    draw.ellipse((x, y, x + size, y + size), fill=fill, outline=outline, width=3)
    badge_font = _load_latin_font(max(18, int(size * 0.28)), bold=True)
    label = _team_badge_label(team_name)
    box = draw.textbbox((0, 0), label, font=badge_font)
    text_x = x + ((size - (box[2] - box[0])) // 2)
    text_y = y + ((size - (box[3] - box[1])) // 2) - box[1]
    draw.text((text_x, text_y), label, font=badge_font, fill=text_fill)


def _render_match_board(title, subtitle, groups, mode="fixtures"):
    if not groups:
        raise ValueError("No groups to render.")

    width = FIXTURE_IMAGE_WIDTH
    padding = FIXTURE_IMAGE_PADDING
    header_height = 360 if mode == "results" else 220
    chip_height = 60
    chip_gap = 18
    row_height = 160
    card_gap = 18
    total_height = (
        (padding * 2)
        + header_height
        + chip_height
        + 22
        + sum((len(matches) * row_height) + (card_gap * max(0, len(matches) - 1)) for _, matches in groups)
        + 22
    )

    image = Image.new("RGBA", (width, total_height), (246, 246, 250, 255))
    draw = ImageDraw.Draw(image)

    panel = (padding, padding, width - padding, total_height - padding)
    draw.rounded_rectangle(panel, radius=24, fill=(244, 244, 248, 255))

    title_text = title.replace("📅", "").replace("🏁", "").strip()
    title_font = _load_font(56, bold=True)
    small_title_font = _load_latin_font(22, bold=False)
    chip_font = _load_latin_font(26, bold=True)
    team_font = _load_font(34, bold=True)
    time_font = _load_latin_font(22, bold=False)
    score_font = _load_latin_font(70, bold=True)
    hero_label_font = _load_latin_font(20, bold=False)
    text_dark = (40, 40, 46)
    text_muted = (168, 168, 176)
    chip_active = (125, 53, 221)
    chip_idle = (230, 231, 238)
    chip_idle_text = (96, 96, 106)

    inner_x0 = panel[0] + 22
    inner_x1 = panel[2] - 22

    title_box = draw.textbbox((0, 0), title_text, font=title_font)
    title_x = inner_x0 + ((inner_x1 - inner_x0 - (title_box[2] - title_box[0])) // 2)
    draw.text((title_x, panel[1] + 26), title_text, font=title_font, fill=text_dark)

    subtitle_box = draw.textbbox((0, 0), subtitle, font=small_title_font)
    subtitle_x = inner_x0 + ((inner_x1 - inner_x0 - (subtitle_box[2] - subtitle_box[0])) // 2)
    draw.text((subtitle_x, panel[1] + 96), subtitle, font=small_title_font, fill=text_muted)

    hero_competition, hero_matches = groups[0]
    hero_match = hero_matches[0]
    hero_y0 = panel[1] + 138
    hero_y1 = hero_y0 + (150 if mode == "fixtures" else 190)
    draw.rounded_rectangle((inner_x0, hero_y0, inner_x1, hero_y1), radius=34, fill=(255, 255, 255, 255))

    center_x = (inner_x0 + inner_x1) // 2
    hero_logo_size = 140
    hero_left_center = inner_x0 + 150
    hero_right_center = inner_x1 - 150
    hero_logo_y = hero_y0 + 18

    for team_name, team_display, center in (
        (hero_match["home"], hero_match.get("home_display") or hero_match["home"], hero_left_center),
        (hero_match["away"], hero_match.get("away_display") or hero_match["away"], hero_right_center),
    ):
        logo_path = _resolve_logo_path({"team": team_name, "team_display": team_display})
        if logo_path:
            logo = _fit_logo(_load_logo(logo_path), hero_logo_size)
            image.alpha_composite(logo, (int(center - (hero_logo_size / 2)), hero_logo_y))
        else:
            _draw_badge_fallback(
                image,
                draw,
                int(center - (hero_logo_size / 2)),
                hero_logo_y,
                hero_logo_size,
                team_display,
            )

    hero_home = AMHARIC_TEAMS.get(hero_match["home"], hero_match["home"])
    hero_away = AMHARIC_TEAMS.get(hero_match["away"], hero_match["away"])

    if mode == "fixtures":
        hero_text = f"{hero_home} vs. {hero_away}"
        hero_font = _load_font(42, bold=True)
        hero_box = draw.textbbox((0, 0), hero_text, font=hero_font)
        hero_x = center_x - ((hero_box[2] - hero_box[0]) // 2)
        draw.text((hero_x, hero_y0 + 82), hero_text, font=hero_font, fill=text_dark)
        meta_text = hero_match["time"]
        meta_box = draw.textbbox((0, 0), meta_text, font=time_font)
        meta_x = center_x - ((meta_box[2] - meta_box[0]) // 2)
        draw.text((meta_x, hero_y0 + 130), meta_text, font=time_font, fill=text_muted)
    else:
        label = hero_competition
        label_box = draw.textbbox((0, 0), label, font=hero_label_font)
        label_x = center_x - ((label_box[2] - label_box[0]) // 2)
        draw.text((label_x, hero_y0 + 24), label, font=hero_label_font, fill=text_muted)
        score = f"{hero_match['home_score']} : {hero_match['away_score']}"
        score_box = draw.textbbox((0, 0), score, font=score_font)
        score_x = center_x - ((score_box[2] - score_box[0]) // 2)
        draw.text((score_x, hero_y0 + 52), score, font=score_font, fill=text_dark)
        matchup = f"{hero_home} vs. {hero_away}"
        matchup_font = _load_font(28, bold=True)
        matchup_box = draw.textbbox((0, 0), matchup, font=matchup_font)
        matchup_x = center_x - ((matchup_box[2] - matchup_box[0]) // 2)
        draw.text((matchup_x, hero_y0 + 135), matchup, font=matchup_font, fill=text_muted)

    header_label_y = hero_y1 + 28
    section_label = "Today Match" if mode == "fixtures" else "Match Results"
    draw.text((inner_x0, header_label_y), section_label, font=_load_latin_font(24, bold=False), fill=text_dark)

    chips = [competition for competition, _ in groups]
    chip_y0 = header_label_y + 46
    chip_x = inner_x0
    for index, chip in enumerate(chips):
        chip_text = chip.replace("UEFA Champions League", "UEFA").replace("Premier League", "EPL")
        chip_text = chip_text.replace("UEFA Europa League", "UEL").replace("UEFA Conference League", "UECL")
        text_box = draw.textbbox((0, 0), chip_text, font=chip_font)
        chip_w = (text_box[2] - text_box[0]) + 42
        fill = chip_active if index == 0 else chip_idle
        text_fill = (255, 255, 255) if index == 0 else chip_idle_text
        draw.rounded_rectangle((chip_x, chip_y0, chip_x + chip_w, chip_y0 + chip_height), radius=30, fill=fill)
        text_x = chip_x + ((chip_w - (text_box[2] - text_box[0])) // 2)
        draw.text((text_x, chip_y0 + 12), chip_text, font=chip_font, fill=text_fill)
        chip_x += chip_w + chip_gap

    y = chip_y0 + chip_height + 24
    card_logo_size = 98 if mode == "results" else 72
    for competition, matches in groups:
        for match in matches:
            row_top = y
            row_bottom = row_top + row_height
            draw.rounded_rectangle((inner_x0, row_top, inner_x1, row_bottom), radius=30, fill=(255, 255, 255, 255))

            left_logo_x = inner_x0 + 30
            right_logo_x = inner_x1 - 30 - card_logo_size
            logo_y = row_top + ((row_height - card_logo_size) // 2)
            for team_name, team_display, x in (
                (match["home"], match.get("home_display") or match["home"], left_logo_x),
                (match["away"], match.get("away_display") or match["away"], right_logo_x),
            ):
                logo_path = _resolve_logo_path({"team": team_name, "team_display": team_display})
                if logo_path:
                    logo = _fit_logo(_load_logo(logo_path), card_logo_size)
                    image.alpha_composite(logo, (x, logo_y))
                else:
                    _draw_badge_fallback(image, draw, x, logo_y, card_logo_size, team_display)

            home_name = AMHARIC_TEAMS.get(match["home"], match["home"])
            away_name = AMHARIC_TEAMS.get(match["away"], match["away"])
            if mode == "fixtures":
                pair_logo_size = 60
                pair_gap = 16
                matchup_font = _load_font(22, bold=True)
                time_font_compact = _load_font(20, bold=False)
                matchup_text = f"{home_name} vs. {away_name}"
                matchup_box = draw.textbbox((0, 0), matchup_text, font=matchup_font)
                matchup_width = matchup_box[2] - matchup_box[0]
                time_text = match["time"]
                time_box = draw.textbbox((0, 0), time_text, font=time_font_compact)
                time_width = time_box[2] - time_box[0]
                total_center_width = pair_logo_size + pair_gap + matchup_width + 22 + time_width
                content_x = center_x - (total_center_width // 2)
                pair_logo_y = row_top + ((row_height - pair_logo_size) // 2)

                pair_home_logo_x = content_x
                pair_away_logo_x = pair_home_logo_x + pair_logo_size + 8
                for team_name, team_display, x in (
                    (match["home"], match.get("home_display") or match["home"], pair_home_logo_x),
                    (match["away"], match.get("away_display") or match["away"], pair_away_logo_x),
                ):
                    logo_path = _resolve_logo_path({"team": team_name, "team_display": team_display})
                    if logo_path:
                        logo = _fit_logo(_load_logo(logo_path), pair_logo_size)
                        image.alpha_composite(logo, (x, pair_logo_y))
                    else:
                        _draw_badge_fallback(image, draw, x, pair_logo_y, pair_logo_size, team_display)

                text_x = pair_away_logo_x + pair_logo_size + pair_gap
                draw.text((text_x, row_top + 42), matchup_text, font=matchup_font, fill=text_dark)
                draw.text((text_x + matchup_width + 22, row_top + 44), time_text, font=time_font_compact, fill=text_muted)
            else:
                center_text = f"{home_name} {match['home_score']} - {match['away_score']} {away_name}"
                center_font = _load_font(26, bold=True)
                center_box = draw.textbbox((0, 0), center_text, font=center_font)
                center_x_text = center_x - ((center_box[2] - center_box[0]) // 2)
                draw.text((center_x_text, row_top + 44), center_text, font=center_font, fill=text_dark)

                secondary = competition
                secondary_box = draw.textbbox((0, 0), secondary, font=time_font)
                secondary_x = center_x - ((secondary_box[2] - secondary_box[0]) // 2)
                draw.text((secondary_x, row_top + 94), secondary, font=time_font, fill=text_muted)

            y += row_height + card_gap

    overlay = _build_standings_watermark_overlay(*image.size)
    image = Image.alpha_composite(image, overlay)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_path = Path(temp_file.name)
    temp_file.close()
    image.convert("RGB").save(temp_path, format="PNG", optimize=True)
    return temp_path


def _render_results_news_style(title, subtitle, groups):
    if not groups:
        raise ValueError("No groups to render.")

    width = 1000
    outer_pad = 0
    inner_pad = 42
    title_font = _load_font(46, bold=True)
    date_font = _load_latin_font(25, bold=True)
    team_font = _load_font(40, bold=True)
    text_dark = (14, 14, 18)
    outer_fill = (255, 255, 255, 255)
    inner_fill = (255, 255, 255, 255)
    logo_size = 256
    row_gap = 32

    total_matches = sum(len(matches) for _, matches in groups)
    poster_height = 600
    height = (outer_pad * 2) + (poster_height * total_matches) + (row_gap * max(0, total_matches - 1))
    image = Image.new("RGBA", (width, height), outer_fill)
    draw = ImageDraw.Draw(image)

    watermark_asset = resolve_watermark_asset()
    watermark = load_watermark_image(watermark_asset)
    watermark_target_w = 130
    watermark_scale = watermark_target_w / watermark.width
    watermark_h = max(1, int(watermark.height * watermark_scale))
    watermark = watermark.resize((watermark_target_w, watermark_h), Image.LANCZOS)

    competition_logo_path = Path(__file__).resolve().parent / "UEFA_Champions_League.svg"
    competition_logo = None
    if competition_logo_path.exists():
        competition_logo = load_watermark_image(competition_logo_path)
        competition_logo_target_w = 100
        competition_scale = competition_logo_target_w / competition_logo.width
        competition_logo = competition_logo.resize(
            (competition_logo_target_w, max(1, int(competition_logo.height * competition_scale))),
            Image.LANCZOS,
        )

    y = outer_pad
    for competition, matches in groups:
        for match in matches:
            panel = (outer_pad, y, width - outer_pad, y + poster_height)
            draw.rectangle(panel, fill=inner_fill)

            title_text = title.replace("🏁", "").strip()
            title_box = draw.textbbox((0, 0), title_text, font=title_font)
            title_x = (width - (title_box[2] - title_box[0])) // 2
            draw.text((title_x, y + 22), title_text, font=title_font, fill=text_dark)

            date_text = f"({subtitle})"
            date_box = draw.textbbox((0, 0), date_text, font=date_font)
            date_x = (width - (date_box[2] - date_box[0])) // 2
            draw.text((date_x, y + 81), date_text, font=date_font, fill=text_dark)

            if competition_logo:
                image.alpha_composite(competition_logo, (42, y + 30))

            wm_x = width - outer_pad - inner_pad - watermark.width
            wm_y = y + 20
            image.alpha_composite(watermark, (wm_x, wm_y))

            home_am = AMHARIC_TEAMS.get(match["home"], match["home"])
            away_am = AMHARIC_TEAMS.get(match["away"], match["away"])
            left_center_x = 74 + (logo_size // 2)
            right_center_x = 678 + (logo_size // 2)
            names_y = y + 175
            logos_y = y + ((poster_height - logo_size) // 2) + 75

            for team_name, team_display, center_x in (
                (match["home"], match.get("home_display") or match["home"], left_center_x),
                (match["away"], match.get("away_display") or match["away"], right_center_x),
            ):
                logo_path = _resolve_logo_path({"team": team_name, "team_display": team_display})
                logo_x = int(center_x - (logo_size / 2))
                if logo_path:
                    logo = _fit_logo(_load_logo(logo_path), logo_size)
                    image.alpha_composite(logo, (logo_x, logos_y))
                else:
                    _draw_badge_fallback(image, draw, logo_x, logos_y, logo_size, team_display)

            home_box = draw.textbbox((0, 0), home_am, font=team_font)
            home_x = int(left_center_x - ((home_box[2] - home_box[0]) / 2))
            draw.text((home_x, names_y), home_am, font=team_font, fill=text_dark)

            away_box = draw.textbbox((0, 0), away_am, font=team_font)
            away_x = int(right_center_x - ((away_box[2] - away_box[0]) / 2))
            draw.text((away_x, names_y), away_am, font=team_font, fill=text_dark)

            score_text = f"{match['home_score']}-{match['away_score']}"
            score_target_w = 222
            score_target_h = 134
            score_font_size = 120
            score_font = _load_latin_font(score_font_size, bold=True)
            score_box = draw.textbbox((0, 0), score_text, font=score_font)
            score_w = score_box[2] - score_box[0]
            score_h = score_box[3] - score_box[1]
            while score_font_size > 24 and (score_w > score_target_w or score_h > score_target_h):
                score_font_size -= 2
                score_font = _load_latin_font(score_font_size, bold=True)
                score_box = draw.textbbox((0, 0), score_text, font=score_font)
                score_w = score_box[2] - score_box[0]
                score_h = score_box[3] - score_box[1]
            score_x = ((width - score_w) // 2) - score_box[0]
            canvas_center_y = y + (poster_height // 2)
            score_y = int(canvas_center_y - (score_h / 2) - score_box[1]) + 75
            draw.text((score_x, score_y), score_text, font=score_font, fill=text_dark)

            y += poster_height + row_gap

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_path = Path(temp_file.name)
    temp_file.close()
    image.convert("RGB").save(temp_path, format="PNG", optimize=True)
    return temp_path


def _send_match_board(title, subtitle, groups, mode="fixtures", caption=None):
    if mode == "results":
        image_path = _render_results_news_style(title, subtitle, groups)
    else:
        image_path = _render_match_board(title, subtitle, groups, mode=mode)
    try:
        return send_telegram_photo_file(image_path, caption or title)
    finally:
        image_path.unlink(missing_ok=True)


def _ethiopian_clock_label(hour_24):
    if 6 <= hour_24 < 12:
        period = "ጠዋት"
    elif 12 <= hour_24 < 18:
        period = "ከሰዓት"
    elif 18 <= hour_24 < 24:
        period = "ማታ"
    else:
        period = "ሌሊት"

    ethiopian_hour = (hour_24 - 6) % 12
    if ethiopian_hour == 0:
        ethiopian_hour = 12
    return ethiopian_hour, period


def _format_kickoff_time_ethiopian(match):
    dateeat = match.get("dateeat")
    kickoff = parse_eat_datetime(dateeat)
    if kickoff:
        hour, period = _ethiopian_clock_label(kickoff.hour)
        return f"{hour}:{kickoff.strftime('%M')} {period}"

    dateutc = match.get("dateutc")
    if dateutc:
        try:
            dt_utc = datetime.strptime(dateutc, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=timezone.utc)
            kickoff = dt_utc + timedelta(hours=3)
            hour, period = _ethiopian_clock_label(kickoff.hour)
            return f"{hour}:{kickoff.strftime('%M')} {period}"
        except ValueError:
            pass

    if dateeat and " " in dateeat:
        time_part = dateeat.split(" ")[1][:5]
        try:
            hour_24, minute = [int(part) for part in time_part.split(":", 1)]
            hour, period = _ethiopian_clock_label(hour_24)
            return f"{hour}:{minute:02d} {period}"
        except ValueError:
            return time_part
    return "??:??"


def _has_final_score(fixture):
    return fixture.get('hometeamscore') is not None and fixture.get('awayteamscore') is not None


def _build_daily_fixtures_text(today, groups):
    lines = [f"📅 የዛሬ ጨዋታዎች ({today})", ""]
    for competition, matches in groups:
        lines.append(f"🏆 {competition}")
        for match in matches:
            home_am = AMHARIC_TEAMS.get(match["home"], match["home"])
            away_am = AMHARIC_TEAMS.get(match["away"], match["away"])
            lines.append(f"⏰ {match['time']}")
            lines.append(f"• {home_am} vs {away_am}")
        lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _results_date_scope():
    today = get_eat_today()
    yesterday = (get_eat_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return [yesterday, today]


def _should_send_standings_after_results(today_fixtures):
    premier_league_fixtures = [fixture for fixture in today_fixtures if is_premier_league_fixture(fixture)]
    if not premier_league_fixtures:
        return False

    with_kickoff = []
    for fixture in premier_league_fixtures:
        kickoff = parse_eat_datetime(fixture.get('dateeat'))
        if kickoff:
            with_kickoff.append((kickoff, fixture))

    if not with_kickoff:
        return all(_has_final_score(fixture) for fixture in premier_league_fixtures)

    latest_kickoff = max(kickoff for kickoff, _ in with_kickoff)
    latest_matches = [fixture for kickoff, fixture in with_kickoff if kickoff == latest_kickoff]
    return bool(latest_matches) and all(_has_final_score(fixture) for fixture in latest_matches)


def broadcast_daily():
    try:
        if not supabase:
            return
        # Rule: clear unsent final scores before posting today's fixtures list.
        result_scope = _results_date_scope()
        if has_pending_results(date_strings=result_scope):
            broadcast_results(date_strings=result_scope)

        if not has_matches_today():
            print("Skip daily: no fixtures scheduled today.")
            return

        today = get_eat_today()
        matches = [m for m in fetch_fixtures_for_dates([today]) if not m.get('daily_sent')]
        if not matches:
            print("Skip daily: today's fixtures were already broadcast.")
            return

        competition_groups = defaultdict(list)
        match_ids = []
        for match in matches:
            time = _format_kickoff_time_ethiopian(match)
            competition = fixture_competition_name(match)
            competition_groups[competition].append(
                {
                    "time": time,
                    "home": match["hometeam"],
                    "away": match["awayteam"],
                }
            )
            match_ids.append(match['matchnumber'])

        groups = [(competition, competition_groups[competition]) for competition in sorted(competition_groups.keys())]
        send_telegram_message(_build_daily_fixtures_text(today, groups))
        supabase.table('fixtures').update({
            "daily_sent": True,
            "broadcaststatus": 'scheduled',
        }).in_('matchnumber', match_ids).execute()
    except Exception as e:
        error_msg = f"Daily broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)


def broadcast_reminders():
    try:
        if not supabase:
            return
        if not has_upcoming_matches():
            print("Skip reminders: no fixtures in the next 60 minutes.")
            return

        now = get_eat_now().replace(tzinfo=None)
        matches = [
            match for match in fixtures_in_window(now, now + timedelta(minutes=60))
            if not match.get('reminder_sent')
        ]
        if not matches:
            print("Skip reminders: all upcoming fixtures were already reminded.")
            return

        for match in matches:
            time = _format_kickoff_time_ethiopian(match)
            home_am = AMHARIC_TEAMS.get(match['hometeam'], match['hometeam'])
            away_am = AMHARIC_TEAMS.get(match['awayteam'], match['awayteam'])
            competition = fixture_competition_name(match)
            msg = f"🔔 *የጨዋታ ማሳሰቢያ!*\n\n🏆 {competition}\n⏰ {time} | {home_am} vs {away_am}\nተዘጋጁ! ⚽"
            send_telegram_message(msg)
            mark_match_state(match['matchnumber'], reminder_sent=True, broadcaststatus='reminded')
    except Exception as e:
        error_msg = f"Reminder broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)


def broadcast_results(date_strings=None):
    today = get_eat_today()
    if date_strings is None:
        date_strings = _results_date_scope()
    lock_key = f"lock:results:{today}"
    lock_owner = f"results:{uuid.uuid4()}"
    try:
        if not supabase:
            return
        if not acquire_bot_lock(lock_key=lock_key, owner=lock_owner, ttl_seconds=600):
            print("Skip results: another run currently holds the results lock.")
            return
        if not has_pending_results(date_strings=date_strings):
            print("Skip results: no completed fixtures awaiting a results post.")
            return

        results = [
            result for result in fetch_fixtures_for_dates(date_strings)
            if result.get('hometeamscore') is not None
            and result.get('awayteamscore') is not None
            and not result.get('result_sent')
        ]
        if not results:
            return

        results.sort(key=lambda item: item.get("dateeat") or "")
        competition_groups = defaultdict(list)
        sent_ids = []
        for result in results:
            competition = fixture_competition_name(result)
            competition_groups[competition].append(
                {
                    "home": result["hometeam"],
                    "away": result["awayteam"],
                    "home_score": result["hometeamscore"],
                    "away_score": result["awayteamscore"],
                }
            )
            sent_ids.append(result['matchnumber'])

        groups = [(competition, competition_groups[competition]) for competition in sorted(competition_groups.keys())]
        _send_match_board(
            title="🏁 የጨዋታዎች ውጤት",
            subtitle=today,
            groups=groups,
            mode="results",
            caption="🏁 የጨዋታዎች ውጤት",
        )
        supabase.table('fixtures').update({
            "result_sent": True,
            "broadcaststatus": 'result_sent',
        }).in_('matchnumber', sent_ids).execute()

        refreshed_today = fetch_fixtures_for_dates([today])
        standings_sent_key = f"standings:auto:sent:{today}"
        standings_already_sent = bool(get_bot_state_value(standings_sent_key))
        if _should_send_standings_after_results(refreshed_today) and not standings_already_sent:
            standings_result = broadcast_standings(format_name="short")
            if standings_result.get("success"):
                set_bot_state_value(standings_sent_key, get_eat_now().isoformat())
    except Exception as e:
        error_msg = f"Results broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)
    finally:
        if supabase:
            release_bot_lock(lock_key=lock_key, owner=lock_owner)
