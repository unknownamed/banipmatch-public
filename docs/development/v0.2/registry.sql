BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS sessions (
 session_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
 push_authorized INTEGER NOT NULL DEFAULT 0, consent_note TEXT, ready INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE TABLE IF NOT EXISTS endpoint_owners (
 fingerprint TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
 recipient_id TEXT NOT NULL
) STRICT;
PRAGMA user_version=1;
COMMIT;
