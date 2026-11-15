-- Generated from docs/schema.json (schema_version 1). Run by the migration runner inside a transaction.
-- Foreign keys are enforced per connection (PRAGMA foreign_keys = ON); see docs/DATABASE.md.

CREATE TABLE "users" (
  "id" TEXT PRIMARY KEY NOT NULL,
  "username" TEXT NOT NULL UNIQUE COLLATE NOCASE,
  "password_hash" TEXT,
  "name" TEXT NOT NULL,
  "name_fa" TEXT,
  "initials" TEXT NOT NULL,
  "initials_fa" TEXT,
  "language" TEXT NOT NULL DEFAULT 'en' CHECK (language IN ('en','fa')),
  "density" TEXT NOT NULL DEFAULT 'comfortable' CHECK (density IN ('comfortable','compact')),
  "created_at" TEXT NOT NULL
) STRICT;
CREATE TABLE "sessions" (
  "token_hash" TEXT PRIMARY KEY NOT NULL,
  "user_id" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  "expires_at" TEXT NOT NULL,
  FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE CASCADE
) STRICT;
CREATE INDEX "idx_sessions_user" ON "sessions" ("user_id");
CREATE INDEX "idx_sessions_expires" ON "sessions" ("expires_at");
CREATE TABLE "boards" (
  "id" TEXT PRIMARY KEY NOT NULL,
  "created_at" TEXT NOT NULL
) STRICT;
CREATE TABLE "board_members" (
  "board_id" TEXT NOT NULL,
  "user_id" TEXT NOT NULL,
  "role" TEXT NOT NULL CHECK (role IN ('owner','member')),
  "position" INTEGER NOT NULL CHECK (position >= 1),
  PRIMARY KEY ("board_id", "user_id"),
  FOREIGN KEY ("board_id") REFERENCES "boards" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE CASCADE
) STRICT;
CREATE INDEX "idx_board_members_user" ON "board_members" ("user_id");
CREATE UNIQUE INDEX "uq_board_one_owner" ON "board_members" ("board_id") WHERE role = 'owner';
CREATE UNIQUE INDEX "uq_user_one_owned_board" ON "board_members" ("user_id") WHERE role = 'owner';
CREATE TABLE "columns" (
  "id" TEXT PRIMARY KEY NOT NULL,
  "board_id" TEXT NOT NULL,
  "slug" TEXT NOT NULL,
  "name" TEXT,
  "position" INTEGER NOT NULL CHECK (position >= 1),
  "wip_limit" INTEGER CHECK (wip_limit IS NULL OR wip_limit > 0),
  "collapsed" INTEGER NOT NULL DEFAULT 0 CHECK (collapsed IN (0,1)),
  UNIQUE ("board_id", "slug"),
  UNIQUE ("board_id", "position"),
  FOREIGN KEY ("board_id") REFERENCES "boards" ("id") ON DELETE CASCADE
) STRICT;
CREATE TABLE "labels" (
  "id" TEXT PRIMARY KEY NOT NULL,
  "board_id" TEXT NOT NULL,
  "slug" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "name_fa" TEXT,
  "position" INTEGER NOT NULL CHECK (position >= 1),
  UNIQUE ("board_id", "slug"),
  FOREIGN KEY ("board_id") REFERENCES "boards" ("id") ON DELETE CASCADE
) STRICT;
CREATE TABLE "cards" (
  "id" TEXT PRIMARY KEY NOT NULL,
  "board_id" TEXT NOT NULL,
  "column_id" TEXT NOT NULL,
  "position" INTEGER NOT NULL,
  "seq" INTEGER NOT NULL CHECK (seq >= 1),
  "title" TEXT NOT NULL,
  "title_fa" TEXT,
  "details" TEXT NOT NULL DEFAULT '',
  "details_fa" TEXT,
  "priority" TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high')),
  "due_date" TEXT CHECK (due_date IS NULL OR date(due_date) IS due_date),
  "progress" INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  "created_at" TEXT NOT NULL,
  "deleted_at" TEXT,
  UNIQUE ("board_id", "seq"),
  FOREIGN KEY ("board_id") REFERENCES "boards" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("column_id") REFERENCES "columns" ("id") ON DELETE NO ACTION
) STRICT;
CREATE INDEX "idx_cards_column_order" ON "cards" ("column_id", "position", "seq");
CREATE INDEX "idx_cards_deleted" ON "cards" ("deleted_at") WHERE deleted_at IS NOT NULL;
CREATE TABLE "card_labels" (
  "card_id" TEXT NOT NULL,
  "label_id" TEXT NOT NULL,
  "position" INTEGER NOT NULL CHECK (position >= 1),
  PRIMARY KEY ("card_id", "label_id"),
  FOREIGN KEY ("card_id") REFERENCES "cards" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("label_id") REFERENCES "labels" ("id") ON DELETE CASCADE
) STRICT;
CREATE INDEX "idx_card_labels_label" ON "card_labels" ("label_id");
CREATE TABLE "card_members" (
  "card_id" TEXT NOT NULL,
  "user_id" TEXT NOT NULL,
  "position" INTEGER NOT NULL CHECK (position >= 1),
  PRIMARY KEY ("card_id", "user_id"),
  FOREIGN KEY ("card_id") REFERENCES "cards" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE CASCADE
) STRICT;
CREATE INDEX "idx_card_members_user" ON "card_members" ("user_id");
CREATE TABLE "spaces" (
  "id" TEXT PRIMARY KEY NOT NULL,
  "board_id" TEXT NOT NULL,
  "kind" TEXT NOT NULL CHECK (kind IN ('general','card')),
  "card_id" TEXT UNIQUE,
  "created_at" TEXT NOT NULL,
  FOREIGN KEY ("board_id") REFERENCES "boards" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("card_id") REFERENCES "cards" ("id") ON DELETE CASCADE,
  CHECK ((kind = 'card') = (card_id IS NOT NULL))
) STRICT;
CREATE INDEX "idx_spaces_board" ON "spaces" ("board_id");
CREATE UNIQUE INDEX "uq_spaces_one_general" ON "spaces" ("board_id") WHERE kind = 'general';
CREATE TABLE "messages" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  "space_id" TEXT NOT NULL,
  "author_id" TEXT NOT NULL,
  "kind" TEXT NOT NULL CHECK (kind IN ('message','event','task')),
  "text" TEXT,
  "text_fa" TEXT,
  "event" TEXT CHECK (event IS NULL OR event IN ('progress','added','removed','moved','created','updated')),
  "event_value" INTEGER CHECK (event_value IS NULL OR event_value BETWEEN 0 AND 100),
  "event_member_id" TEXT,
  "event_column_id" TEXT,
  "card_id" TEXT,
  "by_ai" INTEGER NOT NULL DEFAULT 0 CHECK (by_ai IN (0,1)),
  "created_at" TEXT NOT NULL,
  FOREIGN KEY ("space_id") REFERENCES "spaces" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("author_id") REFERENCES "users" ("id") ON DELETE RESTRICT,
  FOREIGN KEY ("event_member_id") REFERENCES "users" ("id") ON DELETE RESTRICT,
  FOREIGN KEY ("event_column_id") REFERENCES "columns" ("id") ON DELETE SET NULL,
  FOREIGN KEY ("card_id") REFERENCES "cards" ("id") ON DELETE CASCADE,
  CHECK ((kind = 'event') = (event IS NOT NULL)),
  CHECK ((kind = 'task') = (card_id IS NOT NULL)),
  CHECK (kind = 'message' OR text IS NULL),
  CHECK ((event IS 'progress') = (event_value IS NOT NULL)),
  CHECK ((event IS NOT NULL AND event IN ('added','removed')) = (event_member_id IS NOT NULL)),
  CHECK (by_ai = 0 OR kind = 'event')
) STRICT;
CREATE INDEX "idx_messages_space" ON "messages" ("space_id", "id");
CREATE INDEX "idx_messages_card" ON "messages" ("card_id") WHERE card_id IS NOT NULL;
CREATE TABLE "images" (
  "id" TEXT PRIMARY KEY NOT NULL,
  "board_id" TEXT NOT NULL,
  "uploader_id" TEXT NOT NULL,
  "message_id" INTEGER UNIQUE,
  "file_name" TEXT NOT NULL,
  "mime_type" TEXT CHECK (mime_type IS NULL OR mime_type IN ('image/jpeg','image/png','image/webp')),
  "size_bytes" INTEGER NOT NULL DEFAULT 0 CHECK (size_bytes BETWEEN 0 AND 2097152),
  "data" BLOB,
  "created_at" TEXT NOT NULL,
  FOREIGN KEY ("board_id") REFERENCES "boards" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("uploader_id") REFERENCES "users" ("id") ON DELETE RESTRICT,
  FOREIGN KEY ("message_id") REFERENCES "messages" ("id") ON DELETE CASCADE,
  CHECK ((data IS NULL) = (mime_type IS NULL)),
  CHECK (size_bytes = COALESCE(length(data), 0))
) STRICT;
CREATE INDEX "idx_images_unattached" ON "images" ("created_at") WHERE message_id IS NULL;
CREATE TABLE "space_reads" (
  "user_id" TEXT NOT NULL,
  "space_id" TEXT NOT NULL,
  "last_read_message_id" INTEGER NOT NULL DEFAULT 0 CHECK (last_read_message_id >= 0),
  PRIMARY KEY ("user_id", "space_id"),
  FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("space_id") REFERENCES "spaces" ("id") ON DELETE CASCADE
) STRICT;
CREATE INDEX "idx_space_reads_space" ON "space_reads" ("space_id");
CREATE TABLE "ai_messages" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  "board_id" TEXT NOT NULL,
  "user_id" TEXT NOT NULL,
  "role" TEXT NOT NULL CHECK (role IN ('user','assistant')),
  "content" TEXT NOT NULL,
  "changes" TEXT CHECK (changes IS NULL OR json_valid(changes)),
  "created_at" TEXT NOT NULL,
  FOREIGN KEY ("board_id") REFERENCES "boards" ("id") ON DELETE CASCADE,
  FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE CASCADE
) STRICT;
CREATE INDEX "idx_ai_messages_thread" ON "ai_messages" ("board_id", "user_id", "id");
