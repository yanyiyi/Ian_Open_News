PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  track TEXT NOT NULL,
  name TEXT NOT NULL,
  source_group TEXT,
  source_type TEXT NOT NULL,
  feed_url TEXT,
  site_url TEXT,
  status TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  track TEXT NOT NULL,
  status TEXT NOT NULL,
  priority TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  source_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  author TEXT,
  published_at TEXT,
  captured_at TEXT,
  summary TEXT,
  tags_json TEXT NOT NULL,
  origin TEXT NOT NULL,
  reference_json TEXT NOT NULL,
  review_json TEXT NOT NULL,
  FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS review_events (
  id TEXT PRIMARY KEY,
  item_id TEXT NOT NULL,
  track TEXT NOT NULL,
  step TEXT NOT NULL,
  status TEXT NOT NULL,
  reviewer TEXT,
  created_at TEXT,
  notes TEXT,
  evidence_json TEXT NOT NULL,
  FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX IF NOT EXISTS idx_items_track_status ON items(track, status);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id);
CREATE INDEX IF NOT EXISTS idx_review_events_item ON review_events(item_id);
