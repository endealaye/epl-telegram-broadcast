"""League/competition logos (Premier League, Champions League, ...) for news images and video cards.

Logos are looked up by keyword in assets/logos, so the exact file name doesn't matter:
"Premier_League.svg", "premier-league-logo.png" and "PremierLeague.png" all match
"premier_league". When no logo is found every caller falls back to what it did before.
"""
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent
# First directory with a match wins. The older logo/ and repo-root files are fallbacks.
LOGO_DIRS = (REPO_ROOT / "assets" / "logos", REPO_ROOT / "logo", REPO_ROOT)
LOGO_EXTENSIONS = (".svg", ".png", ".webp", ".jpg", ".jpeg")

# Matched against the file name with everything but letters and digits removed, lower-cased.
LEAGUE_LOGO_KEYWORDS = {
    "premier_league": ("premierleague", "premier"),
    "champions_league": ("championsleague", "champions"),
    "europa_league": ("europaleague", "europa"),
    "conference_league": ("conferenceleague", "conference"),
    "world_cup": ("worldcup", "fifa"),
    "la_liga": ("laliga",),
    "serie_a": ("seriea",),
    "bundesliga": ("bundesliga",),
}


def _normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_league_logos(category):
    """Logo files for a category, best first (SVG before raster). Empty list if none."""
    keywords = LEAGUE_LOGO_KEYWORDS.get(category)
    if not keywords:
        return []
    for directory in LOGO_DIRS:
        if not directory.is_dir():
            continue
        matches = [
            path for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() in LOGO_EXTENSIONS
            and any(keyword in _normalize(path.stem) for keyword in keywords)
        ]
        if matches:
            return sorted(matches, key=lambda p: (LOGO_EXTENSIONS.index(p.suffix.lower()), p.name))
    return []


@lru_cache(maxsize=64)
def _load_fitted(path_str, max_width, max_height):
    path = Path(path_str)
    if path.suffix.lower() == ".svg":
        import cairosvg  # imported here so a missing cairosvg only disables SVG logos

        png = cairosvg.svg2png(url=str(path), output_width=max_width * 2)
        with Image.open(BytesIO(png)) as image:
            logo = image.convert("RGBA")
    else:
        with Image.open(path) as image:
            logo = image.convert("RGBA")
    scale = min(max_width / logo.width, max_height / logo.height)
    size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    return logo.resize(size, Image.LANCZOS)


def load_league_logo(category, max_width, max_height):
    """The category's logo as an RGBA image that fits inside max_width x max_height
    (aspect ratio kept), or None when there is no usable logo."""
    for path in find_league_logos(category):
        try:
            return _load_fitted(str(path), int(max_width), int(max_height))
        except Exception as exc:
            print(f"League logo {path.name} unusable: {exc!r}")
    return None
