ALTER TABLE news_items
    ADD COLUMN IF NOT EXISTS story TEXT,
    ADD COLUMN IF NOT EXISTS translated_title_am TEXT,
    ADD COLUMN IF NOT EXISTS translated_story_am TEXT;
