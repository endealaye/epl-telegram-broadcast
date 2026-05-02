from flask import Flask, redirect, render_template_string, request, url_for
from werkzeug.exceptions import HTTPException

from news_pipeline import fetch_news_items, mark_review_item
from news_store import delete_news_item, get_news_item, list_news_queue

app = Flask(__name__)

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
    .thumb { width: 100%; max-height: 280px; object-fit: cover; border-radius: 12px; margin: 0 0 14px; background: #e7e2d4; }
    .card-grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 18px; align-items: start; }
    .meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-bottom: 10px; }
    .pill { background: var(--accent-soft); color: var(--accent); padding: 4px 10px; border-radius: 999px; font-size: 12px; }
    .title { font-size: 22px; margin: 0 0 8px; }
    .card a.title-link { color: inherit; text-decoration: none; }
    .actions { margin-top: 14px; display: flex; gap: 10px; flex-wrap: wrap; }
    .actions a { text-decoration: none; color: var(--accent); font-weight: 600; }
    .story { white-space: pre-wrap; line-height: 1.5; max-height: 320px; overflow: auto; padding-right: 6px; }
    .source-box, .editor-box { border: 1px solid var(--border); border-radius: 14px; padding: 14px; background: rgba(255,255,255,0.65); }
    .source-box h3, .editor-box h3 { margin: 0 0 10px; font-size: 16px; }
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
          {% for tag in (item.topic_tags or []) %}
          <span class="pill">{{ tag }}</span>
          {% endfor %}
        </div>
        <h2 class="title">{{ item.title }}</h2>
        <div class="card-grid">
          <div class="source-box">
            <h3>Source Copy</h3>
            <div><strong>Summary:</strong> {{ item.summary }}</div>
            {% if item.story %}
            <div class="story">{{ item.story }}</div>
            {% endif %}
            <div class="mini-links">
              <a href="{{ item.article_url }}" target="_blank" rel="noreferrer">Open source</a>
              <a href="{{ url_for('news_detail', item_id=item.id) }}">Full view</a>
            </div>
          </div>
          <div class="editor-box">
            <h3>Amharic Draft</h3>
            <form method="post" action="{{ url_for('update_item', item_id=item.id) }}">
              <input type="hidden" name="next" value="{{ request.full_path if request.query_string else request.path }}">
              <label for="translated_title_am_{{ item.id }}">Amharic Title</label>
              <input id="translated_title_am_{{ item.id }}" type="text" name="translated_title_am" value="{{ item.translated_title_am or '' }}">
              <label for="translated_story_am_{{ item.id }}">Amharic Story</label>
              <textarea id="translated_story_am_{{ item.id }}" name="translated_story_am">{{ item.translated_story_am or '' }}</textarea>
              <label for="image_url_{{ item.id }}">Image URL Override</label>
              <input id="image_url_{{ item.id }}" type="url" name="image_url" value="{{ item.image_url or '' }}" placeholder="https://...">
              <label for="notes_{{ item.id }}">Notes</label>
              <input id="notes_{{ item.id }}" type="text" name="notes" value="{{ item.notes or '' }}">
              <div class="actions">
                <button class="save" type="submit" name="status" value="translated">Save Draft</button>
                <button class="publish" type="submit" name="status" value="published">Publish</button>
              </div>
            </form>
            <form method="post" action="{{ url_for('delete_item', item_id=item.id) }}" onsubmit="return confirm('Delete this news item?');">
              <input type="hidden" name="next" value="{{ request.full_path if request.query_string else request.path }}">
              <div class="actions">
                <button class="danger" type="submit">Delete</button>
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
        {% for tag in (item.topic_tags or []) %}
        <span>{{ tag }}</span>
        {% endfor %}
      </div>
      <h1>{{ item.title }}</h1>
      <p>{{ item.summary }}</p>
      {% if item.story %}
      <div style="white-space: pre-wrap;">{{ item.story }}</div>
      {% endif %}
      <p><a href="{{ item.article_url }}" target="_blank" rel="noreferrer">Open original article</a></p>

      <form method="post" action="{{ url_for('update_item', item_id=item.id) }}">
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
      <form method="post" action="{{ url_for('delete_item', item_id=item.id) }}" onsubmit="return confirm('Delete this news item?');">
        <div class="actions">
          <button type="submit">Delete</button>
        </div>
      </form>
    </div>
  </div>
</body>
</html>
"""


DEFAULT_STATUSES = {
    "review": ["filtered", "translated"],
    "filtered": ["filtered"],
    "translated": ["translated"],
    "published": ["published"],
    "all_active": ["filtered", "translated", "published"],
}


@app.get("/")
def news_list():
    selected_status = request.args.get("status", "review")
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(100, limit))
    statuses = DEFAULT_STATUSES.get(selected_status, DEFAULT_STATUSES["review"])
    try:
        items = list_news_queue(statuses=statuses, limit=limit)
    except Exception as exc:
        return (f"Failed to load news queue: {exc}", 502)
    return render_template_string(
        LIST_TEMPLATE,
        items=items,
        selected_status=selected_status,
        status_options=list(DEFAULT_STATUSES.keys()),
        limit=limit,
    )


@app.post("/fetch")
def fetch_news():
    try:
        fetch_news_items()
    except Exception as exc:
        return (f"News fetch failed: {exc}", 502)
    return redirect(url_for("news_list"))


@app.get("/items/<int:item_id>")
def news_detail(item_id):
    try:
        item = get_news_item(item_id)
    except Exception as exc:
        return (f"Failed to load news item: {exc}", 502)
    if not item:
        return ("Not found", 404)
    return render_template_string(DETAIL_TEMPLATE, item=item)


@app.post("/items/<int:item_id>")
def update_item(item_id):
    status = request.form.get("status", "translated")
    translated_title_am = request.form.get("translated_title_am") or None
    translated_story_am = request.form.get("translated_story_am") or None
    image_url = request.form.get("image_url")
    image_url = image_url.strip() if image_url is not None else None
    notes = request.form.get("notes") or None
    try:
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
