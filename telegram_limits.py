TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1000
TELEGRAM_NEWS_CAPTION_TARGET = 750
TELEGRAM_ANALYSIS_CAPTION_TARGET = 900
TELEGRAM_NEWS_MAX_LINES = 14
TELEGRAM_ANALYSIS_MAX_LINES = 18


def _truncate_chars(text, limit):
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    marker = "..."
    if limit <= len(marker):
        return text[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def _truncate_lines(text, max_lines):
    lines = (text or "").splitlines()
    if max_lines <= 0 or len(lines) <= max_lines:
        return text or ""
    return "\n".join(lines[:max_lines]).rstrip()


def enforce_telegram_limit(text, *, has_image=False, target=None, max_lines=None):
    hard_limit = TELEGRAM_CAPTION_LIMIT if has_image else TELEGRAM_TEXT_LIMIT
    effective_limit = min(target or hard_limit, hard_limit)
    output = text or ""
    if max_lines:
        output = _truncate_lines(output, max_lines)
    output = _truncate_chars(output, effective_limit)
    return output


def telegram_limit_status(text, *, has_image=False, target=None, max_lines=None):
    hard_limit = TELEGRAM_CAPTION_LIMIT if has_image else TELEGRAM_TEXT_LIMIT
    safe_target = min(target or hard_limit, hard_limit)
    line_count = len((text or "").splitlines())
    char_count = len(text or "")
    if char_count > hard_limit:
        status = "too_long"
    elif max_lines and line_count > max_lines:
        status = "too_many_lines"
    elif char_count > safe_target:
        status = "warning"
    else:
        status = "safe"
    return {
        "status": status,
        "chars": char_count,
        "lines": line_count,
        "target_chars": safe_target,
        "hard_limit_chars": hard_limit,
        "max_lines": max_lines,
    }


def compact_news_caption(text, *, has_image=True):
    return enforce_telegram_limit(
        text,
        has_image=has_image,
        target=TELEGRAM_NEWS_CAPTION_TARGET if has_image else TELEGRAM_TEXT_LIMIT,
        max_lines=TELEGRAM_NEWS_MAX_LINES,
    )


def compact_analysis_text(text, *, has_image=False):
    return enforce_telegram_limit(
        text,
        has_image=has_image,
        target=TELEGRAM_ANALYSIS_CAPTION_TARGET if has_image else TELEGRAM_TEXT_LIMIT,
        max_lines=TELEGRAM_ANALYSIS_MAX_LINES,
    )
