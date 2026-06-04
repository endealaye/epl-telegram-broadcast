from flask import Flask, redirect, render_template_string, request, url_for
from werkzeug.exceptions import HTTPException

from news_store import (
    create_follow_up_request,
    delete_news_item,
    get_news_item,
    list_follow_up_requests,
    list_news_queue_preview,
    update_follow_up_request,
)
from telegram_limits import TELEGRAM_NEWS_CAPTION_TARGET, TELEGRAM_NEWS_MAX_LINES, telegram_limit_status

app = Flask(__name__)


def build_amharic_preview_text(title, story):
    parts = []
    if title:
        parts.append(title)
    if story:
        if parts:
            parts.append("")
        parts.append(story)
    return "\n".join(parts)


def attach_limit_status(item):
    preview = build_amharic_preview_text(
        item.get("translated_title_am") or "",
        item.get("translated_story_am") or "",
    )
    has_image = bool(item.get("image_url"))
    item["telegram_limit"] = telegram_limit_status(
        preview,
        has_image=has_image,
        target=TELEGRAM_NEWS_CAPTION_TARGET if has_image else None,
        max_lines=TELEGRAM_NEWS_MAX_LINES,
    )
    return item

LIST_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Football News Desk</title>
  <style>
    :root {
      --bg: #f3efe4;
      --panel: #fffaf1;
      --ink: #1f2a1f;
      --muted: #6a7267;
      --accent: #14532d;
      --accent-soft: #d1fae5;
      --border: #d6d3c7;
    }
    body { margin: 0; font-family: Georgia, serif; background: var(--bg); color: var(--ink); }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
    .topbar, .card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; }
    .topbar { padding: 18px 20px; display: flex; justify-content: space-between; align-items: center; gap: 16px; }
    h1 { margin: 0; font-size: 30px; }
    .muted { color: var(--muted); }
    .controls { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
    .controls input, .controls select, .controls button, .controls a {
      font: inherit; border-radius: 999px; border: 1px solid var(--border); padding: 10px 14px; background: white; color: var(--ink);
      text-decoration: none;
    }
    .controls button { background: var(--accent); color: white; border-color: var(--accent); cursor: pointer; }
    .grid { display: grid; gap: 14px; margin-top: 20px; }
    .card { padding: 18px; }
    .followups { margin-top: 18px; }
    .followup-list { display: grid; gap: 10px; }
    .followup-item { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: rgba(255,255,255,0.72); }
    .followup-item h3 { margin: 0 0 6px; font-size: 17px; }
    .followup-meta { display: flex; gap: 8px; flex-wrap: wrap; color: var(--muted); font-size: 12px; margin-bottom: 8px; }
    .thumb { width: 100%; max-height: 280px; object-fit: cover; border-radius: 12px; margin: 0 0 14px; background: #e7e2d4; }
    .card-grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 18px; align-items: start; }
    .meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-bottom: 10px; }
    .pill { background: var(--accent-soft); color: var(--accent); padding: 4px 10px; border-radius: 999px; font-size: 12px; }
    .limit-pill { padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .limit-safe { background: #dcfce7; color: #166534; }
    .limit-warning { background: #fef3c7; color: #92400e; }
    .limit-bad { background: #fee2e2; color: #991b1b; }
    .limit-box { border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; margin: 10px 0; background: rgba(255,255,255,0.7); font-size: 13px; }
    .limit-box strong { display: block; margin-bottom: 4px; }
    .title { font-size: 22px; margin: 0 0 8px; }
    .card a.title-link { color: inherit; text-decoration: none; }
    .actions { margin-top: 14px; display: flex; gap: 10px; flex-wrap: wrap; }
    .actions a { text-decoration: none; color: var(--accent); font-weight: 600; }
    .story { white-space: pre-wrap; line-height: 1.5; max-height: 320px; overflow: auto; padding-right: 6px; }
    .source-box, .editor-box { border: 1px solid var(--border); border-radius: 14px; padding: 14px; background: rgba(255,255,255,0.65); }
    .source-box h3, .editor-box h3 { margin: 0 0 10px; font-size: 16px; }
    .detected-box { border: 1px solid var(--border); border-radius: 14px; padding: 14px; background: rgba(20,83,45,0.06); margin: 0 0 14px; }
    .detected-box h3 { margin: 0 0 10px; font-size: 16px; }
    .detected-box p { margin: 6px 0; line-height: 1.45; }
    .editor-box label { display: block; margin: 12px 0 6px; font-weight: 600; }
    .editor-box textarea, .editor-box input[type=text] {
      width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); font: inherit; background: white;
    }
    .editor-box input[type=url] {
      width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); font: inherit; background: white;
    }
    .editor-box textarea { min-height: 180px; resize: vertical; }
    .danger { color: #7f1d1d; border-color: #b91c1c; }
    .publish { background: var(--accent); color: white; border-color: var(--accent); }
    .save { background: white; }
    .mini-links { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
    .mini-links a { text-decoration: none; color: var(--accent); font-weight: 600; }
    @media (max-width: 860px) {
      .card-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <h1>Football News Desk</h1>
        <div class="muted">Review English football stories, translate to Amharic, then publish.</div>
      </div>
      <div class="controls">
        <form method="post" action="{{ url_for('fetch_news') }}">
          <button type="submit">Fetch News</button>
        </form>
        <form method="get" action="{{ url_for('news_list') }}">
          <select name="status">
            {% for option in status_options %}
            <option value="{{ option }}" {% if option == selected_status %}selected{% endif %}>{{ option }}</option>
            {% endfor %}
          </select>
          <input type="number" min="1" max="100" name="limit" value="{{ limit }}">
          <button type="submit">Apply</button>
        </form>
      </div>
    </div>

    <div class="card followups">
      <div class="source-box">
        <h2 class="title">Follow-up Requests</h2>
        <div class="muted">Track stories that need a later update, such as injuries, transfer developments, or ongoing match angles.</div>
        <div class="followup-list" style="margin-top:14px;">
          {% for followup in followups %}
          <div class="followup-item">
            <div class="followup-meta">
              <span class="pill">{{ followup.status }}</span>
              <span class="pill">{{ followup.request_type }}</span>
              {% if followup.target_name %}<span>{{ followup.target_name }}</span>{% endif %}
              {% if followup.created_at %}<span>{{ followup.created_at }}</span>{% endif %}
            </div>
            <h3>{{ followup.subject }}</h3>
            {% if followup.details %}<div>{{ followup.details }}</div>{% endif %}
            <div class="actions">
              {% if followup.status == 'active' %}
              <form method="post" action="{{ url_for('update_followup', request_id=followup.id) }}">
                <input type="hidden" name="status" value="resolved">
                <button type="submit">Mark Resolved</button>
              </form>
              {% else %}
              <form method="post" action="{{ url_for('update_followup', request_id=followup.id) }}">
                <input type="hidden" name="status" value="active">
                <button type="submit">Reopen</button>
              </form>
              {% endif %}
              <form method="post" action="{{ url_for('delete_followup', request_id=followup.id) }}" onsubmit="return confirm('Delete this follow-up request?');">
                <button class="danger" type="submit">Delete</button>
              </form>
            </div>
          </div>
          {% else %}
          <div class="followup-item">No follow-up requests yet.</div>
          {% endfor %}
        </div>
      </div>
    </div>

    <div class="grid">
      {% for item in items %}
      <div class="card">
        {% if item.image_url %}
        <img class="thumb" src="{{ item.image_url }}" alt="">
        {% endif %}
        <div class="meta">
          <span>{{ item.source_name }}</span>
          <span>{{ item.published_at or 'No timestamp' }}</span>
          <span class="pill">{{ item.review_status }}</span>
          <span class="pill">score {{ item.relevance_score }}</span>
          {% set limit = item.telegram_limit or {} %}
          <span class="limit-pill {% if limit.status == 'safe' %}limit-safe{% elif limit.status == 'warning' %}limit-warning{% else %}limit-bad{% endif %}">
            Telegram {{ limit.chars or 0 }}/{{ limit.hard_limit_chars or 1024 }} · {{ limit.lines or 0 }}/{{ limit.max_lines or '∞' }} lines · {{ limit.status or 'unknown' }}
          </span>
          {% if ((item.raw_payload or {}).get('follow_up_matches')) %}
          <span class="pill">follow-up match</span>
          {% endif %}
          {% for tag in (item.topic_tags or []) %}
          <span class="pill">{{ tag }}</span>
          {% endfor %}
        </div>
        <h2 class="title">{{ item.title }}</h2>
        <div class="card-grid">
          <div class="source-box">
            <h3>Source Copy</h3>
            <div><strong>Summary:</strong> {{ item.summary }}</div>
            <div class="mini-links">
              <a href="{{ item.article_url }}" target="_blank" rel="noreferrer">Open source</a>
              <a href="{{ url_for('news_detail', item_id=item.id) }}">Full view</a>
            </div>
          </div>
          <div class="editor-box">
            <h3>Amharic Draft</h3>
            {% if item.translated_title_am %}
            <div><strong>Saved title:</strong> {{ item.translated_title_am }}</div>
            {% endif %}
            {% if item.notes %}
            <div style="margin-top:10px;"><strong>Notes:</strong> {{ item.notes }}</div>
            {% endif %}
            <div class="mini-links">
              <a href="{{ url_for('news_detail', item_id=item.id) }}">Open editor</a>
            </div>
            <form method="post" action="{{ url_for('delete_item', item_id=item.id) }}" onsubmit="return confirm('Hide this news item and prevent it from returning?');">
              <input type="hidden" name="next" value="{{ request.full_path if request.query_string else request.path }}">
              <div class="actions">
                <button class="danger" type="submit">Hide</button>
              </div>
            </form>
          </div>
        </div>
      </div>
      {% else %}
      <div class="card">No items in this view.</div>
      {% endfor %}
    </div>
  </div>
</body>
</html>
"""

DETAIL_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ item.title }}</title>
  <style>
    :root {
      --bg: #f3efe4; --panel: #fffaf1; --ink: #1f2a1f; --muted: #6a7267; --accent: #14532d; --border: #d6d3c7;
    }
    body { margin: 0; font-family: Georgia, serif; background: var(--bg); color: var(--ink); }
    .wrap { max-width: 980px; margin: 0 auto; padding: 24px; }
    .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 22px; }
    .hero { width: 100%; max-height: 420px; object-fit: cover; border-radius: 14px; margin-bottom: 16px; background: #e7e2d4; }
    a { color: var(--accent); }
    .meta { color: var(--muted); display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
    .detected-box { border: 1px solid var(--border); border-radius: 14px; padding: 14px; background: rgba(20,83,45,0.06); margin: 14px 0; }
    .detected-box h3 { margin: 0 0 10px; font-size: 16px; }
    .detected-box p { margin: 6px 0; line-height: 1.45; }
    textarea, input[type=text] {
      width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); font: inherit; background: white;
    }
    input[type=url] {
      width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); font: inherit; background: white;
    }
    textarea { min-height: 180px; resize: vertical; }
    .row { margin-top: 18px; }
    .actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 18px; }
    button { font: inherit; border-radius: 999px; border: 1px solid var(--border); padding: 10px 16px; background: white; cursor: pointer; }
    button.primary { background: var(--accent); color: white; border-color: var(--accent); }
    select {
      width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); font: inherit; background: white;
    }
    .limit-pill { padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .limit-safe { background: #dcfce7; color: #166534; }
    .limit-warning { background: #fef3c7; color: #92400e; }
    .limit-bad { background: #fee2e2; color: #991b1b; }
    .limit-box { border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; margin: 10px 0; background: rgba(255,255,255,0.7); font-size: 13px; }
    .limit-box strong { display: block; margin-bottom: 4px; }
  </style>
</head>
<body>
  <div class="wrap">
    <p><a href="{{ url_for('news_list') }}">← Back to queue</a></p>
    <div class="panel">
      {% if item.image_url %}
      <img class="hero" src="{{ item.image_url }}" alt="">
      {% endif %}
      <div class="meta">
        <span>{{ item.source_name }}</span>
        <span>{{ item.published_at or 'No timestamp' }}</span>
        <span>{{ item.review_status }}</span>
        <span>score {{ item.relevance_score }}</span>
        {% set limit = item.telegram_limit or {} %}
        <span id="telegram_limit_pill" class="limit-pill {% if limit.status == 'safe' %}limit-safe{% elif limit.status == 'warning' %}limit-warning{% else %}limit-bad{% endif %}">
          Telegram {{ limit.chars or 0 }}/{{ limit.hard_limit_chars or 1024 }} · {{ limit.lines or 0 }}/{{ limit.max_lines or '∞' }} lines · {{ limit.status or 'unknown' }}
        </span>
        {% if ((item.raw_payload or {}).get('follow_up_matches')) %}
        <span>follow-up match</span>
        {% endif %}
        {% for tag in (item.topic_tags or []) %}
        <span>{{ tag }}</span>
        {% endfor %}
      </div>
      <h1>{{ item.title }}</h1>
      <p>{{ item.summary }}</p>
      {% set match_meta = ((item.raw_payload or {}).get('match_metadata') or {}) %}
      {% if match_meta and match_meta.get('match_type') and match_meta.get('match_type') != 'other' %}
      <div class="detected-box">
        <h3>Detected Match Structure</h3>
        <p><strong>Type:</strong> {{ match_meta.get('match_type') }}</p>
        {% if match_meta.get('prediction') %}
        <p><strong>Prediction:</strong> {{ match_meta.get('prediction') }}</p>
        {% endif %}
        {% if match_meta.get('has_lineup_image') %}
        <p><strong>Lineup Image:</strong> yes</p>
        {% endif %}
        {% if match_meta.get('final_score') %}
        <p><strong>Final Score:</strong> {{ match_meta.get('final_score').get('home') }} {{ match_meta.get('final_score').get('home_score') }} - {{ match_meta.get('final_score').get('away_score') }} {{ match_meta.get('final_score').get('away') }}</p>
        {% endif %}
        {% if match_meta.get('scorers') %}
        <p><strong>Scorers:</strong>
          {% for scorer in match_meta.get('scorers') %}
            {{ scorer.get('player') }} ({{ scorer.get('minute') }}){% if not loop.last %}, {% endif %}
          {% endfor %}
        </p>
        {% endif %}
        {% if match_meta.get('injury_update') %}
        <p><strong>Injury:</strong> {{ match_meta.get('injury_update') }}</p>
        {% endif %}
      </div>
      {% endif %}
      {% if item.story %}
      <div style="white-space: pre-wrap;">{{ item.story }}</div>
      {% endif %}
      {% if ((item.raw_payload or {}).get('follow_up_matches')) %}
      <div class="detected-box">
        <h3>Matched Follow-up Requests</h3>
        {% for followup in ((item.raw_payload or {}).get('follow_up_matches') or []) %}
        <p><strong>{{ followup.get('subject') or followup.get('request_type') }}</strong>{% if followup.get('target_name') %} · {{ followup.get('target_name') }}{% endif %}</p>
        {% endfor %}
      </div>
      {% endif %}
      <p><a href="{{ item.article_url }}" target="_blank" rel="noreferrer">Open original article</a></p>

      <form method="post" action="{{ url_for('update_item', item_id=item.id) }}">
        <div class="limit-box">
          <strong>Telegram Limit Tracker</strong>
          <div id="telegram_limit_text">
            {{ limit.chars or 0 }}/{{ limit.hard_limit_chars or 1024 }} chars ·
            {{ limit.lines or 0 }}/{{ limit.max_lines or '∞' }} lines ·
            target {{ limit.target_chars or 900 }} chars ·
            {{ 'image caption' if item.image_url else 'text message' }}
          </div>
        </div>
        <div class="row">
          <label for="translated_title_am">Amharic Title</label>
          <input id="translated_title_am" type="text" name="translated_title_am" value="{{ item.translated_title_am or '' }}">
        </div>
        <div class="row">
          <label for="translated_story_am">Amharic Story</label>
          <textarea id="translated_story_am" name="translated_story_am">{{ item.translated_story_am or '' }}</textarea>
        </div>
        <div class="row">
          <label for="image_url">Image URL Override</label>
          <input id="image_url" type="url" name="image_url" value="{{ item.image_url or '' }}" placeholder="https://...">
        </div>
        <div class="row">
          <label for="notes">Notes</label>
          <input id="notes" type="text" name="notes" value="{{ item.notes or '' }}">
        </div>
        <div class="actions">
          <button class="primary" type="submit" name="status" value="translated">Save Draft</button>
          <button class="primary" type="submit" name="status" value="published">Publish</button>
        </div>
      </form>
      <form method="post" action="{{ url_for('delete_item', item_id=item.id) }}" onsubmit="return confirm('Hide this news item and prevent it from returning?');">
        <div class="actions">
          <button type="submit">Hide</button>
        </div>
      </form>
      <div class="detected-box">
        <h3>Create Follow-up Request</h3>
        <form method="post" action="{{ url_for('create_followup') }}">
          <input type="hidden" name="linked_item_id" value="{{ item.id }}">
          <input type="hidden" name="subject" value="{{ item.title }}">
          <div class="row">
            <label for="followup_target_name">Target</label>
            <input id="followup_target_name" type="text" name="target_name" placeholder="Player, team, or issue">
          </div>
          <div class="row">
            <label for="followup_request_type">Type</label>
            <select id="followup_request_type" name="request_type">
              <option value="injury_follow_up">Injury Follow-up</option>
              <option value="transfer_follow_up">Transfer Follow-up</option>
              <option value="match_follow_up">Match Follow-up</option>
              <option value="manager_follow_up">Manager Follow-up</option>
              <option value="general_follow_up">General Follow-up</option>
            </select>
          </div>
          <div class="row">
            <label for="followup_details">Notes</label>
            <textarea id="followup_details" name="details" placeholder="Describe the follow-up you want from this story."></textarea>
          </div>
          <div class="actions">
            <button class="primary" type="submit">Create Follow-up</button>
          </div>
        </form>
      </div>
    </div>
  </div>
  <script>
    const titleInput = document.getElementById("translated_title_am");
    const storyInput = document.getElementById("translated_story_am");
    const imageInput = document.getElementById("image_url");
    const limitText = document.getElementById("telegram_limit_text");
    const limitPill = document.getElementById("telegram_limit_pill");
    const newsCaptionTarget = {{ news_caption_target }};
    const newsMaxLines = {{ news_max_lines }};

    function lineCount(value) {
      if (!value) return 0;
      return value.split(/\r\n|\r|\n/).length;
    }

    function previewText() {
      const title = titleInput.value.trim();
      const story = storyInput.value.trim();
      if (title && story) return title + "\\n\\n" + story;
      return title || story;
    }

    function statusClass(status) {
      if (status === "safe") return "limit-pill limit-safe";
      if (status === "warning") return "limit-pill limit-warning";
      return "limit-pill limit-bad";
    }

    function updateLimitTracker() {
      const text = previewText();
      const hasImage = Boolean(imageInput.value.trim());
      const hardLimit = hasImage ? 1024 : 4096;
      const target = hasImage ? newsCaptionTarget : hardLimit;
      const lines = lineCount(text);
      const chars = text.length;
      let status = "safe";
      if (chars > hardLimit) status = "too_long";
      else if (lines > newsMaxLines) status = "too_many_lines";
      else if (chars > target) status = "warning";
      limitText.textContent = `${chars}/${hardLimit} chars · ${lines}/${newsMaxLines} lines · target ${target} chars · ${hasImage ? "image caption" : "text message"} · ${status}`;
      limitPill.textContent = `Telegram ${chars}/${hardLimit} · ${lines}/${newsMaxLines} lines · ${status}`;
      limitPill.className = statusClass(status);
    }

    [titleInput, storyInput, imageInput].forEach((field) => field.addEventListener("input", updateLimitTracker));
    updateLimitTracker();
  </script>
</body>
</html>
"""


DEFAULT_STATUSES = {
    "review": ["filtered", "approved", "translated"],
    "filtered": ["filtered"],
    "approved": ["approved"],
    "translated": ["translated"],
    "all_active": ["filtered", "approved", "translated"],
}


@app.get("/")
def news_list():
    selected_status = request.args.get("status", "review")
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    statuses = DEFAULT_STATUSES.get(selected_status, DEFAULT_STATUSES["review"])
    try:
        items = list_news_queue_preview(statuses=statuses, limit=limit)
        items = [attach_limit_status(item) for item in items]
        followups = list_follow_up_requests()
    except Exception as exc:
        return (f"Failed to load news queue: {exc}", 502)
    return render_template_string(
        LIST_TEMPLATE,
        items=items,
        followups=followups,
        selected_status=selected_status,
        status_options=list(DEFAULT_STATUSES.keys()),
        limit=limit,
    )


@app.get("/healthz")
def healthcheck():
    return {"ok": True}, 200


@app.post("/fetch")
def fetch_news():
    try:
        from news_pipeline import fetch_news_items
        fetch_news_items()
    except Exception as exc:
        return (f"News fetch failed: {exc}", 502)
    return redirect(url_for("news_list"))


@app.post("/followups")
def create_followup():
    subject = request.form.get("subject") or ""
    target_name = request.form.get("target_name") or None
    request_type = request.form.get("request_type") or "general_follow_up"
    details = request.form.get("details") or None
    linked_item_id = request.form.get("linked_item_id") or None
    try:
        create_follow_up_request(
            subject=subject,
            target_name=target_name,
            request_type=request_type,
            details=details,
            linked_item_id=linked_item_id,
        )
    except ValueError as exc:
        return (str(exc), 400)
    except Exception as exc:
        return (f"Follow-up creation failed: {exc}", 502)
    return redirect(url_for("news_list"))


@app.post("/followups/<request_id>")
def update_followup(request_id):
    status = request.form.get("status") or "active"
    try:
        updated = update_follow_up_request(request_id, status=status)
    except Exception as exc:
        return (f"Follow-up update failed: {exc}", 502)
    if not updated:
        return ("Follow-up request not found.", 404)
    return redirect(url_for("news_list"))


@app.post("/followups/<request_id>/delete")
def delete_followup(request_id):
    try:
        deleted = update_follow_up_request(request_id, delete=True)
    except Exception as exc:
        return (f"Follow-up delete failed: {exc}", 502)
    if not deleted:
        return ("Follow-up request not found.", 404)
    return redirect(url_for("news_list"))


@app.get("/items/<int:item_id>")
def news_detail(item_id):
    try:
        item = get_news_item(item_id)
    except Exception as exc:
        return (f"Failed to load news item: {exc}", 502)
    if not item:
        return ("Not found", 404)
    item = attach_limit_status(item)
    return render_template_string(
        DETAIL_TEMPLATE,
        item=item,
        news_caption_target=TELEGRAM_NEWS_CAPTION_TARGET,
        news_max_lines=TELEGRAM_NEWS_MAX_LINES,
    )


@app.post("/items/<int:item_id>")
def update_item(item_id):
    status = request.form.get("status", "translated")
    translated_title_am = request.form.get("translated_title_am") or None
    translated_story_am = request.form.get("translated_story_am") or None
    image_url = request.form.get("image_url")
    image_url = image_url.strip() if image_url is not None else None
    notes = request.form.get("notes") or None
    existing_item = None
    if status == "published":
        try:
            existing_item = get_news_item(item_id)
        except Exception as exc:
            return (f"Failed to load news item for limit check: {exc}", 502)
        effective_image_url = image_url if image_url else ((existing_item or {}).get("image_url") or "")
        effective_title = translated_title_am if translated_title_am is not None else ((existing_item or {}).get("translated_title_am") or "")
        effective_story = translated_story_am if translated_story_am is not None else ((existing_item or {}).get("translated_story_am") or "")
        preview = build_amharic_preview_text(effective_title, effective_story)
        limit = telegram_limit_status(
            preview,
            has_image=bool(effective_image_url),
            target=TELEGRAM_NEWS_CAPTION_TARGET if effective_image_url else None,
            max_lines=TELEGRAM_NEWS_MAX_LINES,
        )
        if limit["status"] in {"too_long", "too_many_lines"}:
            return (
                "Telegram limit failed: "
                f"{limit['chars']}/{limit['hard_limit_chars']} chars, "
                f"{limit['lines']}/{limit['max_lines']} lines, status={limit['status']}.",
                400,
            )
    try:
        from news_pipeline import mark_review_item
        mark_review_item(
            item_id=item_id,
            status=status,
            translated_title_am=translated_title_am,
            translated_story_am=translated_story_am,
            notes=notes,
            image_url=image_url if image_url else None,
        )
    except ValueError as exc:
        return (str(exc), 400)
    except RuntimeError as exc:
        return (str(exc), 502)
    except Exception as exc:
        return (f"Unexpected update error: {exc}", 502)
    if status == "published":
        next_url = url_for("news_list")
    else:
        next_url = request.form.get("next") or url_for("news_detail", item_id=item_id)
    return redirect(next_url)


@app.post("/items/<int:item_id>/delete")
def delete_item(item_id):
    try:
        deleted = delete_news_item(item_id)
    except Exception as exc:
        return (f"Delete failed: {exc}", 502)
    if not deleted:
        return ("Delete failed: item not found or database unavailable.", 502)
    next_url = request.form.get("next") or url_for("news_list")
    return redirect(next_url)


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    if isinstance(exc, HTTPException):
        return exc
    return (f"Dashboard internal error: {exc}", 500)


if __name__ == "__main__":
    app.run(debug=False, port=5050)
