CREATE TABLE IF NOT EXISTS news_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_key TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    article_url TEXT NOT NULL,
    image_url TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    story TEXT,
    author TEXT,
    published_at TIMESTAMPTZ,
    language TEXT NOT NULL DEFAULT 'en',
    topic_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_status TEXT NOT NULL DEFAULT 'fetched'
        CHECK (review_status IN ('fetched', 'filtered', 'approved', 'rejected', 'translated', 'published')),
    relevance_score INTEGER NOT NULL DEFAULT 0,
    cluster_key TEXT,
    translated_title_am TEXT,
    translated_story_am TEXT,
    notes TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS news_items_review_status_idx ON news_items (review_status);
CREATE INDEX IF NOT EXISTS news_items_published_at_idx ON news_items (published_at DESC);
CREATE INDEX IF NOT EXISTS news_items_source_key_idx ON news_items (source_key);
