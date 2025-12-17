CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'created',
    entity_name TEXT,
    faction1_name TEXT,
    faction2_name TEXT,
    faction1_players JSONB DEFAULT '[]'::jsonb,
    faction2_players JSONB DEFAULT '[]'::jsonb,
    map_picked TEXT,
    faction1_vc_id TEXT,
    faction2_vc_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

-- Create index on status for faster queries
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);

-- Create index on updated_at for sorting
CREATE INDEX IF NOT EXISTS idx_matches_updated_at ON matches(updated_at);

