"""Versioned SQLite database migrations for Project Nova (Cosmic ki baddie V2)."""

from __future__ import annotations

import logging
from typing import List, Tuple

logger = logging.getLogger("project_nova.database.migrations")

# Each migration is (version_number, description, sql_script)
MIGRATIONS: List[Tuple[int, str, str]] = [
    (
        1,
        "Initial core guild configuration and schema_migrations tables",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS guild_configs (
            guild_id INTEGER PRIMARY KEY,
            prefix TEXT NOT NULL DEFAULT '!',
            language TEXT NOT NULL DEFAULT 'en',
            welcome_enabled INTEGER NOT NULL DEFAULT 0,
            welcome_channel_id INTEGER,
            welcome_message TEXT NOT NULL DEFAULT 'Welcome {user} to **{server}**!',
            goodbye_enabled INTEGER NOT NULL DEFAULT 0,
            goodbye_channel_id INTEGER,
            goodbye_message TEXT NOT NULL DEFAULT 'Goodbye **{user_name}**, we will miss you!',
            auto_role_id INTEGER,
            log_channel_id INTEGER,
            mod_log_channel_id INTEGER,
            automod_enabled INTEGER NOT NULL DEFAULT 0,
            automod_max_mentions INTEGER NOT NULL DEFAULT 5,
            automod_anti_invite INTEGER NOT NULL DEFAULT 0,
            automod_anti_links INTEGER NOT NULL DEFAULT 0,
            automod_bad_words TEXT NOT NULL DEFAULT '[]',
            automod_spam_threshold INTEGER NOT NULL DEFAULT 6,
            automod_spam_window_sec INTEGER NOT NULL DEFAULT 5,
            ticket_category_id INTEGER,
            ticket_log_channel_id INTEGER,
            ticket_naming_format TEXT NOT NULL DEFAULT 'ticket-{category}-{username}',
            ticket_limit_per_member INTEGER NOT NULL DEFAULT 1,
            ticket_transcripts_enabled INTEGER NOT NULL DEFAULT 1,
            jtc_trigger_channel_id INTEGER,
            jtc_category_id INTEGER,
            jtc_default_name TEXT NOT NULL DEFAULT '{username}''s Room',
            jtc_default_limit INTEGER NOT NULL DEFAULT 0,
            ai_enabled INTEGER NOT NULL DEFAULT 0,
            ai_provider TEXT NOT NULL DEFAULT 'none',
            ai_endpoint TEXT NOT NULL DEFAULT 'http://127.0.0.1:11434/api/generate',
            ai_model TEXT NOT NULL DEFAULT 'llama3',
            ai_api_key TEXT,
            ai_channels TEXT NOT NULL DEFAULT '[]',
            ai_cooldown_sec INTEGER NOT NULL DEFAULT 10,
            ai_max_context_chars INTEGER NOT NULL DEFAULT 2000,
            music_default_volume INTEGER NOT NULL DEFAULT 80,
            music_idle_timeout_sec INTEGER NOT NULL DEFAULT 180,
            music_dj_role_id INTEGER,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        2,
        "Centralized RBAC roles, command permissions, and user exceptions",
        """
        CREATE TABLE IF NOT EXISTS rbac_staff_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            tier TEXT NOT NULL CHECK (tier IN ('administrator', 'management', 'moderator', 'support', 'custom')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(guild_id, role_id, tier),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS rbac_command_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            target_type TEXT NOT NULL CHECK (target_type IN ('command', 'category')),
            target_name TEXT NOT NULL,
            required_tier TEXT NOT NULL DEFAULT 'everyone',
            allowed_role_ids TEXT NOT NULL DEFAULT '[]',
            denied_role_ids TEXT NOT NULL DEFAULT '[]',
            allowed_user_ids TEXT NOT NULL DEFAULT '[]',
            denied_user_ids TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(guild_id, target_type, target_name),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );
        """,
    ),
    (
        3,
        "Ticket categories, panels, and active/closed ticket records",
        """
        CREATE TABLE IF NOT EXISTS ticket_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            slug TEXT NOT NULL,
            name TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '🎫',
            description TEXT NOT NULL DEFAULT 'Click to open a support ticket.',
            staff_role_ids TEXT NOT NULL DEFAULT '[]',
            is_default INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, slug),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS ticket_panels (
            panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL UNIQUE,
            creator_id INTEGER NOT NULL,
            category_slug TEXT NOT NULL,
            category_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'claimed', 'closed')),
            claimed_by INTEGER,
            closed_by INTEGER,
            close_reason TEXT,
            transcript TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            closed_at TEXT,
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );
        """,
    ),
    (
        4,
        "Moderation warnings, audit logs, temporary roles, polls, and giveaways",
        """
        CREATE TABLE IF NOT EXISTS warnings (
            warn_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS mod_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS temp_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            reason TEXT,
            UNIQUE(guild_id, user_id, role_id),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS polls (
            poll_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options_json TEXT NOT NULL,
            votes_json TEXT NOT NULL DEFAULT '{}',
            is_open INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS giveaways (
            giveaway_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            winners_count INTEGER NOT NULL DEFAULT 1,
            entrants_json TEXT NOT NULL DEFAULT '[]',
            ends_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );
        """,
    ),
    (
        5,
        "Join-to-Create temporary voice channels and Activity Roles",
        """
        CREATE TABLE IF NOT EXISTS jtc_channels (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            user_limit INTEGER NOT NULL DEFAULT 0,
            is_locked INTEGER NOT NULL DEFAULT 0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            allowed_user_ids TEXT NOT NULL DEFAULT '[]',
            denied_user_ids TEXT NOT NULL DEFAULT '[]',
            control_message_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS activity_role_rules (
            rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL CHECK (activity_type IN ('all', 'playing', 'spotify', 'streaming', 'listening', 'watching', 'competing')),
            activity_match TEXT,
            role_id INTEGER NOT NULL,
            remove_on_stop INTEGER NOT NULL DEFAULT 1,
            temp_duration_sec INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS activity_role_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            rule_id INTEGER NOT NULL,
            granted_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT,
            UNIQUE(guild_id, user_id, role_id),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );
        """,
    ),
    (
        6,
        "Reaction roles, button/select role panels, autoresponders, Announcements, and Embed templates",
        """
        CREATE TABLE IF NOT EXISTS reaction_role_panels (
            panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('button', 'select', 'reaction')),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            exclusive INTEGER NOT NULL DEFAULT 0,
            max_Select INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reaction_role_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '⭐',
            description TEXT,
            style TEXT NOT NULL DEFAULT 'primary',
            UNIQUE(panel_id, role_id),
            FOREIGN KEY (panel_id) REFERENCES reaction_role_panels(panel_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS autoresponders (
            responder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            trigger_text TEXT NOT NULL,
            match_mode TEXT NOT NULL DEFAULT 'exact' CHECK (match_mode IN ('exact', 'partial')),
            case_sensitive INTEGER NOT NULL DEFAULT 0,
            response_text TEXT NOT NULL,
            allowed_channel_ids TEXT NOT NULL DEFAULT '[]',
            allowed_role_ids TEXT NOT NULL DEFAULT '[]',
            cooldown_sec INTEGER NOT NULL DEFAULT 5,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(guild_id, trigger_text),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS scheduled_announcements (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            interval_minutes INTEGER NOT NULL DEFAULT 60,
            last_run_at TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS embed_templates (
            template_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            embed_json TEXT NOT NULL,
            author_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(guild_id, name),
            FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE
        );
        """,
    ),
]
