-- Tracks which merged video a story went into. Null = not merged yet.
-- Written by youtube_digest.build_and_send_category_videos after a video is sent.
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS video_batch_id text;
CREATE INDEX IF NOT EXISTS news_items_video_batch_id_idx ON news_items (video_batch_id);
