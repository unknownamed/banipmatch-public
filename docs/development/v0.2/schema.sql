-- Additive migration of a session-private v0.1 database. Published v0.1 untouched.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS condition_revisions (
 revision_id TEXT PRIMARY KEY, before_scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
 after_scenario_id TEXT NOT NULL UNIQUE REFERENCES scenarios(scenario_id),
 confirmation TEXT NOT NULL CHECK(confirmation IN ('confirmed_simulation','assumed')),
 reason TEXT NOT NULL, revision_json TEXT NOT NULL CHECK(json_valid(revision_json)), created_at TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS input_rebases (
 scenario_id TEXT PRIMARY KEY REFERENCES scenarios(scenario_id),
 source_scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
 previous_active_scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
 plan_version INTEGER NOT NULL, created_at TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS invitations (
 invitation_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, vehicle_ids_json TEXT NOT NULL,
 expires_at TEXT NOT NULL, consumed_by TEXT, claim_key_hash TEXT, revoked INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE TABLE IF NOT EXISTS recipients (
 recipient_id TEXT PRIMARY KEY, invitation_id TEXT NOT NULL UNIQUE REFERENCES invitations(invitation_id),
 plan_id TEXT NOT NULL, expires_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS recipient_vehicles (
 plan_id TEXT NOT NULL, vehicle_id TEXT NOT NULL,
 recipient_id TEXT NOT NULL REFERENCES recipients(recipient_id), PRIMARY KEY(plan_id,vehicle_id)
) STRICT;
CREATE TABLE IF NOT EXISTS push_subscriptions (
 recipient_id TEXT PRIMARY KEY REFERENCES recipients(recipient_id),
 encrypted_json TEXT, endpoint_fingerprint TEXT, expires_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('active','revoked','expired')),
 created_at TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS dispatches (
 dispatch_id TEXT PRIMARY KEY, approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
 plan_id TEXT NOT NULL, plan_version INTEGER NOT NULL, scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
 preview_json TEXT NOT NULL CHECK(json_valid(preview_json)), created_at TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS notifications (
 notification_id TEXT PRIMARY KEY, dispatch_id TEXT NOT NULL REFERENCES dispatches(dispatch_id),
 recipient_id TEXT REFERENCES recipients(recipient_id), vehicle_ids_json TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 delivery_status TEXT NOT NULL CHECK(delivery_status IN
 ('pending','sending','accepted','failed','unknown','expired','unsubscribed','unlinked','superseded')),
 error_code TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, accepted_at TEXT,
 opened_at TEXT, retry_not_before TEXT, response TEXT NOT NULL DEFAULT 'none' CHECK(response IN
 ('none','acknowledged','can_perform','cannot_perform')), responded_at TEXT
) STRICT;
CREATE TABLE IF NOT EXISTS notification_attempts (
 attempt_id TEXT PRIMARY KEY, notification_id TEXT NOT NULL REFERENCES notifications(notification_id),
 started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, error_code TEXT
) STRICT;
CREATE TABLE IF NOT EXISTS recipient_responses (
 response_id TEXT PRIMARY KEY, notification_id TEXT NOT NULL REFERENCES notifications(notification_id),
 recipient_id TEXT NOT NULL REFERENCES recipients(recipient_id), response TEXT NOT NULL,
 note TEXT NOT NULL, created_at TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS notifications_by_recipient ON notifications(recipient_id,created_at);
PRAGMA user_version=2;
COMMIT;
CREATE TABLE IF NOT EXISTS recipient_locations (
 recipient_id TEXT PRIMARY KEY REFERENCES recipients(recipient_id),
 latitude REAL NOT NULL, longitude REAL NOT NULL, accuracy_m REAL NOT NULL,
 captured_at TEXT NOT NULL, received_at TEXT NOT NULL
) STRICT;
