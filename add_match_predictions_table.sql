CREATE TABLE IF NOT EXISTS match_predictions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matchnumber BIGINT NOT NULL REFERENCES fixtures(matchnumber) ON DELETE CASCADE,
    language TEXT NOT NULL DEFAULT 'am',
    predicted_home_score INTEGER NOT NULL CHECK (predicted_home_score >= 0),
    predicted_away_score INTEGER NOT NULL CHECK (predicted_away_score >= 0),
    prediction_text TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('low', 'medium', 'high')),
    source_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (review_status IN ('draft', 'published', 'rejected')),
    published_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (matchnumber, language)
);

CREATE INDEX IF NOT EXISTS match_predictions_matchnumber_idx
    ON match_predictions (matchnumber);

CREATE INDEX IF NOT EXISTS match_predictions_review_status_idx
    ON match_predictions (review_status);
