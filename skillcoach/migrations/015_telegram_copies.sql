-- Telegram copies for DELIVERY_CHANNEL=both, and bot identity for every Telegram mode.
--
-- Receipts are namespaced by bot: bot_id 0 is the bot whose update IDs were recorded before this
-- migration (TELEGRAM_LEGACY_BOT_ID); any other bot uses its own numeric ID, so a different bot can
-- never collide with or reuse another bot's update IDs, while a regenerated token for the same bot
-- keeps its namespace. access_audit follows the receipt key.
ALTER TABLE access_audit DROP CONSTRAINT access_audit_update_id_fkey;
ALTER TABLE telegram_receipts ADD COLUMN bot_id bigint NOT NULL DEFAULT 0 CHECK (bot_id >= 0);
ALTER TABLE telegram_receipts DROP CONSTRAINT telegram_receipts_pkey;
ALTER TABLE telegram_receipts ADD PRIMARY KEY (bot_id, update_id);
ALTER TABLE access_audit ADD COLUMN bot_id bigint NOT NULL DEFAULT 0;
ALTER TABLE access_audit ADD CONSTRAINT access_audit_receipt_fkey
    FOREIGN KEY (bot_id, update_id) REFERENCES telegram_receipts(bot_id, update_id);

-- The last question the learner was shown in Telegram (displayed_target stays the web/canonical one):
-- typed Telegram replies bind to it, and a late Telegram copy never moves the web conversation back.
ALTER TABLE coach_state ADD COLUMN telegram_target jsonb;

-- People who have messaged this bot. Telegram copies go only to someone who started the current bot;
-- a binding is never inferred from an email address or a name. last_message_at is when Telegram says
-- their newest typed message was sent (NULL until one arrives), so a restoration can tell a fresh owner
-- message from one that waited in Telegram's queue.
CREATE TABLE telegram_starts (
    bot_id bigint NOT NULL CHECK (bot_id >= 0),
    telegram_id bigint NOT NULL CHECK (telegram_id > 0),
    learner_id text NOT NULL REFERENCES learners(id),
    first_inbound_at timestamptz NOT NULL DEFAULT now(),
    last_inbound_at timestamptz NOT NULL DEFAULT now(),
    last_message_at timestamptz,
    PRIMARY KEY (bot_id, telegram_id)
);
CREATE INDEX telegram_starts_learner ON telegram_starts(learner_id);

-- Telegram health, with its history kept. A row with learner_id NULL is the whole bot (credentials
-- rejected, an explicit frozen error, or an operator's restoration gate); otherwise one recipient.
-- 'probation' is an operator-authorized restoration, begun at probation_since, waiting for Telegram to
-- accept the reply to an owner message sent after that moment. Codes come from a fixed vocabulary only.
CREATE TABLE telegram_pauses (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bot_id bigint NOT NULL CHECK (bot_id >= 0),
    learner_id text REFERENCES learners(id),
    code text NOT NULL CHECK (code ~ '^[a-z_]{1,40}$'),
    state text NOT NULL CHECK (state IN ('paused', 'probation', 'cleared')),
    since timestamptz NOT NULL DEFAULT now(),
    probation_since timestamptz,
    cleared_at timestamptz,
    cleared_by text CHECK (cleared_by IN ('inbound', 'operator', 'confirmed')),
    CHECK ((state = 'cleared') = (cleared_at IS NOT NULL)),
    CHECK (state <> 'probation' OR probation_since IS NOT NULL)
);
CREATE UNIQUE INDEX telegram_pauses_open ON telegram_pauses(bot_id, coalesce(learner_id, ''))
    WHERE state <> 'cleared';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'skillcoach_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON telegram_starts, telegram_pauses TO skillcoach_runtime;
    END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES (15);
