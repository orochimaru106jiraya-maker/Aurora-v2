"""Repository layer for Project Nova (Cosmic ki baddie V2).

Provides strongly-typed async CRUD operations backed by `DatabaseManager` using
parameterized SQL queries.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bot.database.manager import DatabaseManager

DEFAULT_TICKET_CATEGORIES: List[Tuple[str, str, str, str]] = [
    ("general-help", "General Help", "💬", "Ask general questions or get server assistance."),
    ("file-complaint", "File Complaint", "⚠️", "Report a member or file a formal server complaint."),
    ("staff-application", "Staff Application", "📋", "Apply to join the server moderation or support team."),
    ("winning-prize", "Winning Prize", "🏆", "Claim a giveaway, event, or tournament prize."),
]

ALLOWED_CONFIG_COLUMNS = {
    "prefix",
    "language",
    "welcome_enabled",
    "welcome_channel_id",
    "welcome_message",
    "goodbye_enabled",
    "goodbye_channel_id",
    "goodbye_message",
    "auto_role_id",
    "log_channel_id",
    "mod_log_channel_id",
    "automod_enabled",
    "automod_max_mentions",
    "automod_anti_invite",
    "automod_anti_links",
    "automod_bad_words",
    "automod_spam_threshold",
    "automod_spam_window_sec",
    "ticket_category_id",
    "ticket_log_channel_id",
    "ticket_naming_format",
    "ticket_limit_per_member",
    "ticket_transcripts_enabled",
    "jtc_trigger_channel_id",
    "jtc_category_id",
    "jtc_default_name",
    "jtc_default_limit",
    "ai_enabled",
    "ai_provider",
    "ai_endpoint",
    "ai_model",
    "ai_api_key",
    "ai_channels",
    "ai_cooldown_sec",
    "ai_max_context_chars",
    "music_default_volume",
    "music_idle_timeout_sec",
    "music_dj_role_id",
}


class GuildConfigRepository:
    """Manages per-guild settings and caches prefixes for fast lookup."""

    def __init__(self, db: DatabaseManager, default_prefix: str = "!") -> None:
        self.db = db
        self.default_prefix = default_prefix
        self._prefix_cache: Dict[int, str] = {}

    async def ensure_guild(self, guild_id: int) -> Dict[str, Any]:
        """Ensure a guild_configs row and default ticket categories exist for `guild_id`."""
        row = await self.db.fetchone(
            "SELECT * FROM guild_configs WHERE guild_id = ?;", (int(guild_id),)
        )
        if row is None:
            await self.db.execute(
                "INSERT OR IGNORE INTO guild_configs (guild_id, prefix) VALUES (?, ?);",
                (int(guild_id), self.default_prefix),
            )
            row = await self.db.fetchone(
                "SELECT * FROM guild_configs WHERE guild_id = ?;", (int(guild_id),)
            )
        assert row is not None
        self._prefix_cache[int(guild_id)] = str(row["prefix"])
        return row

    async def get_prefix(self, guild_id: Optional[int]) -> str:
        """Return the configured command prefix for a guild (or default prefix in DMs)."""
        if guild_id is None:
            return self.default_prefix
        gid = int(guild_id)
        if gid in self._prefix_cache:
            return self._prefix_cache[gid]
        cfg = await self.ensure_guild(gid)
        return str(cfg["prefix"])

    async def set_prefix(self, guild_id: int, prefix: str) -> None:
        clean = prefix.strip()
        if not clean or len(clean) > 10:
            raise ValueError("Prefix must be between 1 and 10 non-whitespace characters.")
        await self.ensure_guild(guild_id)
        await self.db.execute(
            "UPDATE guild_configs SET prefix = ?, updated_at = datetime('now') WHERE guild_id = ?;",
            (clean, int(guild_id)),
        )
        self._prefix_cache[int(guild_id)] = clean

    async def update_fields(self, guild_id: int, **fields: Any) -> Dict[str, Any]:
        """Update one or more validated configuration columns for `guild_id`."""
        await self.ensure_guild(guild_id)
        invalid = set(fields.keys()) - ALLOWED_CONFIG_COLUMNS
        if invalid:
            raise ValueError(f"Invalid guild config fields: {sorted(invalid)}")
        if not fields:
            return await self.ensure_guild(guild_id)
        assignments = [f"{col} = ?" for col in fields.keys()]
        assignments.append("updated_at = datetime('now')")
        values = list(fields.values()) + [int(guild_id)]
        sql = f"UPDATE guild_configs SET {', '.join(assignments)} WHERE guild_id = ?;"
        await self.db.execute(sql, values)
        if "prefix" in fields:
            self._prefix_cache[int(guild_id)] = str(fields["prefix"])
        return await self.ensure_guild(guild_id)


class RBACRepository:
    """Manages staff role tiers and command/category permission rules."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def add_staff_role(self, guild_id: int, role_id: int, tier: str) -> None:
        await self.guild_repo.ensure_guild(guild_id)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO rbac_staff_roles (guild_id, role_id, tier)
            VALUES (?, ?, ?);
            """,
            (int(guild_id), int(role_id), tier.lower()),
        )

    async def remove_staff_role(self, guild_id: int, role_id: int, tier: Optional[str] = None) -> int:
        if tier:
            return await self.db.execute_rowcount(
                "DELETE FROM rbac_staff_roles WHERE guild_id = ? AND role_id = ? AND tier = ?;",
                (int(guild_id), int(role_id), tier.lower()),
            )
        return await self.db.execute_rowcount(
            "DELETE FROM rbac_staff_roles WHERE guild_id = ? AND role_id = ?;",
            (int(guild_id), int(role_id)),
        )

    async def list_staff_roles(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM rbac_staff_roles WHERE guild_id = ? ORDER BY tier, role_id;",
            (int(guild_id),),
        )

    async def set_permission_rule(
        self,
        guild_id: int,
        target_type: str,
        target_name: str,
        *,
        required_tier: str = "everyone",
        allowed_role_ids: Optional[Sequence[int]] = None,
        denied_role_ids: Optional[Sequence[int]] = None,
        allowed_user_ids: Optional[Sequence[int]] = None,
        denied_user_ids: Optional[Sequence[int]] = None,
    ) -> None:
        await self.guild_repo.ensure_guild(guild_id)
        await self.db.execute(
            """
            INSERT INTO rbac_command_permissions (
                guild_id, target_type, target_name, required_tier,
                allowed_role_ids, denied_role_ids, allowed_user_ids, denied_user_ids, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(guild_id, target_type, target_name) DO UPDATE SET
                required_tier = excluded.required_tier,
                allowed_role_ids = excluded.allowed_role_ids,
                denied_role_ids = excluded.denied_role_ids,
                allowed_user_ids = excluded.allowed_user_ids,
                denied_user_ids = excluded.denied_user_ids,
                updated_at = datetime('now');
            """,
            (
                int(guild_id),
                target_type.lower(),
                target_name.lower(),
                required_tier.lower(),
                json.dumps([int(x) for x in (allowed_role_ids or [])]),
                json.dumps([int(x) for x in (denied_role_ids or [])]),
                json.dumps([int(x) for x in (allowed_user_ids or [])]),
                json.dumps([int(x) for x in (denied_user_ids or [])]),
            ),
        )

    async def get_permission_rule(
        self, guild_id: int, target_type: str, target_name: str
    ) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone(
            """
            SELECT * FROM rbac_command_permissions
            WHERE guild_id = ? AND target_type = ? AND target_name = ?;
            """,
            (int(guild_id), target_type.lower(), target_name.lower()),
        )
        if row is None:
            return None
        row["allowed_role_ids"] = json.loads(row.get("allowed_role_ids") or "[]")
        row["denied_role_ids"] = json.loads(row.get("denied_role_ids") or "[]")
        row["allowed_user_ids"] = json.loads(row.get("allowed_user_ids") or "[]")
        row["denied_user_ids"] = json.loads(row.get("denied_user_ids") or "[]")
        return row

    async def list_permission_rules(self, guild_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM rbac_command_permissions WHERE guild_id = ? ORDER BY target_type, target_name;",
            (int(guild_id),),
        )
        for r in rows:
            r["allowed_role_ids"] = json.loads(r.get("allowed_role_ids") or "[]")
            r["denied_role_ids"] = json.loads(r.get("denied_role_ids") or "[]")
            r["allowed_user_ids"] = json.loads(r.get("allowed_user_ids") or "[]")
            r["denied_user_ids"] = json.loads(r.get("denied_user_ids") or "[]")
        return rows

    async def delete_permission_rule(self, guild_id: int, target_type: str, target_name: str) -> int:
        return await self.db.execute_rowcount(
            """
            DELETE FROM rbac_command_permissions
            WHERE guild_id = ? AND target_type = ? AND target_name = ?;
            """,
            (int(guild_id), target_type.lower(), target_name.lower()),
        )


class TicketRepository:
    """Manages ticket categories, panels, and active/closed tickets."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def ensure_default_categories(self, guild_id: int) -> List[Dict[str, Any]]:
        await self.guild_repo.ensure_guild(guild_id)
        existing = await self.db.fetchall(
            "SELECT * FROM ticket_categories WHERE guild_id = ? ORDER BY id;",
            (int(guild_id),),
        )
        if not existing:
            for slug, name, emoji, desc in DEFAULT_TICKET_CATEGORIES:
                await self.db.execute(
                    """
                    INSERT OR IGNORE INTO ticket_categories
                    (guild_id, slug, name, emoji, description, staff_role_ids, is_default)
                    VALUES (?, ?, ?, ?, ?, '[]', 1);
                    """,
                    (int(guild_id), slug, name, emoji, desc),
                )
            existing = await self.db.fetchall(
                "SELECT * FROM ticket_categories WHERE guild_id = ? ORDER BY id;",
                (int(guild_id),),
            )
        for row in existing:
            row["staff_role_ids"] = json.loads(row.get("staff_role_ids") or "[]")
        return existing

    async def add_category(
        self,
        guild_id: int,
        slug: str,
        name: str,
        emoji: str = "🎫",
        description: str = "Click to open a support ticket.",
        staff_role_ids: Optional[Sequence[int]] = None,
    ) -> None:
        await self.ensure_default_categories(guild_id)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO ticket_categories
            (guild_id, slug, name, emoji, description, staff_role_ids, is_default)
            VALUES (?, ?, ?, ?, ?, ?, 0);
            """,
            (
                int(guild_id),
                slug.lower().strip(),
                name.strip(),
                emoji.strip() or "🎫",
                description.strip(),
                json.dumps([int(r) for r in (staff_role_ids or [])]),
            ),
        )

    async def remove_category(self, guild_id: int, slug: str) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM ticket_categories WHERE guild_id = ? AND slug = ?;",
            (int(guild_id), slug.lower().strip()),
        )

    async def get_category(self, guild_id: int, slug: str) -> Optional[Dict[str, Any]]:
        await self.ensure_default_categories(guild_id)
        row = await self.db.fetchone(
            "SELECT * FROM ticket_categories WHERE guild_id = ? AND slug = ?;",
            (int(guild_id), slug.lower().strip()),
        )
        if row:
            row["staff_role_ids"] = json.loads(row.get("staff_role_ids") or "[]")
        return row

    async def record_panel(
        self, guild_id: int, channel_id: int, message_id: int, title: str, description: str
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO ticket_panels (guild_id, channel_id, message_id, title, description)
            VALUES (?, ?, ?, ?, ?);
            """,
            (int(guild_id), int(channel_id), int(message_id), title, description),
        )

    async def count_open_tickets_for_user(self, guild_id: int, creator_id: int) -> int:
        row = await self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM tickets
            WHERE guild_id = ? AND creator_id = ? AND status IN ('open', 'claimed');
            """,
            (int(guild_id), int(creator_id)),
        )
        return int(row["cnt"]) if row else 0

    async def create_ticket(
        self,
        guild_id: int,
        channel_id: int,
        creator_id: int,
        category_slug: str,
        category_name: str,
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO tickets (guild_id, channel_id, creator_id, category_slug, category_name, status)
            VALUES (?, ?, ?, ?, ?, 'open');
            """,
            (int(guild_id), int(channel_id), int(creator_id), category_slug, category_name),
        )

    async def get_ticket_by_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        return await self.db.fetchone(
            "SELECT * FROM tickets WHERE channel_id = ?;", (int(channel_id),)
        )

    async def claim_ticket(self, channel_id: int, moderator_id: int) -> None:
        await self.db.execute(
            "UPDATE tickets SET status = 'claimed', claimed_by = ? WHERE channel_id = ?;",
            (int(moderator_id), int(channel_id)),
        )

    async def close_ticket(
        self,
        channel_id: int,
        closed_by: int,
        close_reason: str,
        transcript: str,
    ) -> None:
        await self.db.execute(
            """
            UPDATE tickets
            SET status = 'closed',
                closed_by = ?,
                close_reason = ?,
                transcript = ?,
                closed_at = datetime('now')
            WHERE channel_id = ?;
            """,
            (int(closed_by), close_reason, transcript, int(channel_id)),
        )

    async def list_open_tickets(self, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if guild_id is not None:
            return await self.db.fetchall(
                "SELECT * FROM tickets WHERE guild_id = ? AND status IN ('open', 'claimed');",
                (int(guild_id),),
            )
        return await self.db.fetchall(
            "SELECT * FROM tickets WHERE status IN ('open', 'claimed');"
        )


class ModerationRepository:
    """Manages warnings, moderation audit logs, temporary roles, polls, and giveaways."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def add_warning(
        self, guild_id: int, user_id: int, moderator_id: int, reason: str
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO warnings (guild_id, user_id, moderator_id, reason)
            VALUES (?, ?, ?, ?);
            """,
            (int(guild_id), int(user_id), int(moderator_id), reason),
        )

    async def get_warnings(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY warn_id DESC;",
            (int(guild_id), int(user_id)),
        )

    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?;",
            (int(guild_id), int(user_id)),
        )

    async def log_mod_action(
        self,
        guild_id: int,
        action: str,
        target_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
        details: Optional[str] = None,
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO mod_logs (guild_id, action, target_id, moderator_id, reason, details)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (int(guild_id), action, int(target_id), int(moderator_id), reason, details),
        )

    async def get_mod_logs(
        self, guild_id: int, target_id: Optional[int] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        if target_id is not None:
            return await self.db.fetchall(
                "SELECT * FROM mod_logs WHERE guild_id = ? AND target_id = ? ORDER BY log_id DESC LIMIT ?;",
                (int(guild_id), int(target_id), int(limit)),
            )
        return await self.db.fetchall(
            "SELECT * FROM mod_logs WHERE guild_id = ? ORDER BY log_id DESC LIMIT ?;",
            (int(guild_id), int(limit)),
        )

    async def add_temp_role(
        self, guild_id: int, user_id: int, role_id: int, expires_at: str, reason: str = ""
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT OR REPLACE INTO temp_roles (guild_id, user_id, role_id, expires_at, reason)
            VALUES (?, ?, ?, ?, ?);
            """,
            (int(guild_id), int(user_id), int(role_id), expires_at, reason),
        )

    async def get_expired_temp_roles(self, now_iso: str) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM temp_roles WHERE expires_at <= ?;", (now_iso,)
        )

    async def remove_temp_role(self, guild_id: int, user_id: int, role_id: int) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM temp_roles WHERE guild_id = ? AND user_id = ? AND role_id = ?;",
            (int(guild_id), int(user_id), int(role_id)),
        )

    async def create_poll(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        author_id: int,
        question: str,
        options: List[str],
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO polls (guild_id, channel_id, message_id, author_id, question, options_json, votes_json)
            VALUES (?, ?, ?, ?, ?, ?, '{}');
            """,
            (int(guild_id), int(channel_id), int(message_id), int(author_id), question, json.dumps(options)),
        )

    async def get_poll_by_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone(
            "SELECT * FROM polls WHERE message_id = ?;", (int(message_id),)
        )
        if row:
            row["options"] = json.loads(row["options_json"])
            row["votes"] = json.loads(row["votes_json"])
        return row

    async def record_poll_vote(self, poll_id: int, user_id: int, option_idx: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM polls WHERE poll_id = ?;", (int(poll_id),))
        if not row:
            raise ValueError("Poll not found")
        votes = json.loads(row["votes_json"])
        votes[str(user_id)] = int(option_idx)
        await self.db.execute(
            "UPDATE polls SET votes_json = ? WHERE poll_id = ?;",
            (json.dumps(votes), int(poll_id)),
        )
        row["options"] = json.loads(row["options_json"])
        row["votes"] = votes
        return row

    async def create_giveaway(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        host_id: int,
        prize: str,
        winners_count: int,
        ends_at: str,
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, winners_count, ends_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(guild_id),
                int(channel_id),
                int(message_id),
                int(host_id),
                prize,
                int(winners_count),
                ends_at,
            ),
        )

    async def get_giveaway_by_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ?;", (int(message_id),)
        )
        if row:
            row["entrants"] = json.loads(row["entrants_json"])
        return row

    async def toggle_giveaway_entrant(self, giveaway_id: int, user_id: int) -> Tuple[bool, int]:
        row = await self.db.fetchone(
            "SELECT * FROM giveaways WHERE giveaway_id = ?;", (int(giveaway_id),)
        )
        if not row:
            raise ValueError("Giveaway not found")
        entrants: List[int] = [int(x) for x in json.loads(row["entrants_json"])]
        uid = int(user_id)
        if uid in entrants:
            entrants.remove(uid)
            joined = False
        else:
            entrants.append(uid)
            joined = True
        await self.db.execute(
            "UPDATE giveaways SET entrants_json = ? WHERE giveaway_id = ?;",
            (json.dumps(entrants), int(giveaway_id)),
        )
        return joined, len(entrants)

    async def close_giveaway(self, giveaway_id: int) -> None:
        await self.db.execute(
            "UPDATE giveaways SET is_active = 0 WHERE giveaway_id = ?;", (int(giveaway_id),)
        )


class JTCRepository:
    """Manages Join-to-Create temporary voice channel state."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def register_channel(
        self,
        channel_id: int,
        guild_id: int,
        owner_id: int,
        name: str,
        user_limit: int = 0,
        control_message_id: Optional[int] = None,
    ) -> None:
        await self.guild_repo.ensure_guild(guild_id)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO jtc_channels
            (channel_id, guild_id, owner_id, name, user_limit, control_message_id)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                int(channel_id),
                int(guild_id),
                int(owner_id),
                name,
                int(user_limit),
                int(control_message_id) if control_message_id else None,
            ),
        )

    async def get_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone(
            "SELECT * FROM jtc_channels WHERE channel_id = ?;", (int(channel_id),)
        )
        if row:
            row["allowed_user_ids"] = json.loads(row.get("allowed_user_ids") or "[]")
            row["denied_user_ids"] = json.loads(row.get("denied_user_ids") or "[]")
        return row

    async def update_channel(self, channel_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {
            "owner_id",
            "name",
            "user_limit",
            "is_locked",
            "is_hidden",
            "allowed_user_ids",
            "denied_user_ids",
            "control_message_id",
        }
        invalid = set(fields.keys()) - allowed
        if invalid:
            raise ValueError(f"Invalid JTC fields: {invalid}")
        for k in ("allowed_user_ids", "denied_user_ids"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps([int(x) for x in fields[k]])
        sets = ", ".join(f"{k} = ?" for k in fields.keys())
        vals = list(fields.values()) + [int(channel_id)]
        await self.db.execute(f"UPDATE jtc_channels SET {sets} WHERE channel_id = ?;", vals)
        return await self.get_channel(channel_id)

    async def delete_channel(self, channel_id: int) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM jtc_channels WHERE channel_id = ?;", (int(channel_id),)
        )

    async def list_all_channels(self, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if guild_id is not None:
            rows = await self.db.fetchall(
                "SELECT * FROM jtc_channels WHERE guild_id = ?;", (int(guild_id),)
            )
        else:
            rows = await self.db.fetchall("SELECT * FROM jtc_channels;")
        for r in rows:
            r["allowed_user_ids"] = json.loads(r.get("allowed_user_ids") or "[]")
            r["denied_user_ids"] = json.loads(r.get("denied_user_ids") or "[]")
        return rows


class ActivityRoleRepository:
    """Manages activity-based role rules and active temporary role grants."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def add_rule(
        self,
        guild_id: int,
        activity_type: str,
        role_id: int,
        activity_match: Optional[str] = None,
        remove_on_stop: bool = True,
        temp_duration_sec: int = 0,
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO activity_role_rules
            (guild_id, activity_type, activity_match, role_id, remove_on_stop, temp_duration_sec, enabled)
            VALUES (?, ?, ?, ?, ?, ?, 1);
            """,
            (
                int(guild_id),
                activity_type.lower(),
                activity_match.strip() if activity_match else None,
                int(role_id),
                1 if remove_on_stop else 0,
                int(temp_duration_sec),
            ),
        )

    async def remove_rule(self, guild_id: int, rule_id: int) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM activity_role_rules WHERE guild_id = ? AND rule_id = ?;",
            (int(guild_id), int(rule_id)),
        )

    async def list_rules(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM activity_role_rules WHERE guild_id = ? AND enabled = 1 ORDER BY rule_id;",
            (int(guild_id),),
        )

    async def record_grant(
        self,
        guild_id: int,
        user_id: int,
        role_id: int,
        rule_id: int,
        expires_at: Optional[str] = None,
    ) -> None:
        await self.guild_repo.ensure_guild(guild_id)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO activity_role_grants
            (guild_id, user_id, role_id, rule_id, expires_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (int(guild_id), int(user_id), int(role_id), int(rule_id), expires_at),
        )

    async def remove_grant(self, guild_id: int, user_id: int, role_id: int) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM activity_role_grants WHERE guild_id = ? AND user_id = ? AND role_id = ?;",
            (int(guild_id), int(user_id), int(role_id)),
        )

    async def list_user_grants(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM activity_role_grants WHERE guild_id = ? AND user_id = ?;",
            (int(guild_id), int(user_id)),
        )


class ReactionRoleRepository:
    """Manages reaction role, button role, and select-menu role panels."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def create_panel(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        mode: str,
        title: str,
        description: str,
        exclusive: bool = False,
        max_select: int = 5,
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO reaction_role_panels
            (guild_id, channel_id, message_id, mode, title, description, exclusive, max_Select)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(guild_id),
                int(channel_id),
                int(message_id),
                mode.lower(),
                title,
                description,
                1 if exclusive else 0,
                int(max_select),
            ),
        )

    async def add_panel_item(
        self,
        panel_id: int,
        guild_id: int,
        role_id: int,
        label: str,
        emoji: str = "⭐",
        description: Optional[str] = None,
        style: str = "primary",
    ) -> int:
        return await self.db.execute(
            """
            INSERT OR REPLACE INTO reaction_role_items
            (panel_id, guild_id, role_id, label, emoji, description, style)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (int(panel_id), int(guild_id), int(role_id), label, emoji, description, style),
        )

    async def get_panel(self, panel_id: int) -> Optional[Dict[str, Any]]:
        panel = await self.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE panel_id = ?;", (int(panel_id),)
        )
        if panel:
            panel["items"] = await self.db.fetchall(
                "SELECT * FROM reaction_role_items WHERE panel_id = ? ORDER BY item_id;",
                (int(panel_id),),
            )
        return panel

    async def get_panel_by_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        panel = await self.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE message_id = ?;", (int(message_id),)
        )
        if panel:
            panel["items"] = await self.db.fetchall(
                "SELECT * FROM reaction_role_items WHERE panel_id = ? ORDER BY item_id;",
                (int(panel["panel_id"]),),
            )
        return panel

    async def list_panels(self, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if guild_id is not None:
            panels = await self.db.fetchall(
                "SELECT * FROM reaction_role_panels WHERE guild_id = ? ORDER BY panel_id;",
                (int(guild_id),),
            )
        else:
            panels = await self.db.fetchall("SELECT * FROM reaction_role_panels ORDER BY panel_id;")
        for p in panels:
            p["items"] = await self.db.fetchall(
                "SELECT * FROM reaction_role_items WHERE panel_id = ? ORDER BY item_id;",
                (int(p["panel_id"]),),
            )
        return panels

    async def delete_panel(self, guild_id: int, panel_id: int) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM reaction_role_panels WHERE guild_id = ? AND panel_id = ?;",
            (int(guild_id), int(panel_id)),
        )


class AutomationRepository:
    """Manages keyword autoresponders and scheduled announcements."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def upsert_autoresponder(
        self,
        guild_id: int,
        trigger_text: str,
        response_text: str,
        *,
        match_mode: str = "exact",
        case_sensitive: bool = False,
        allowed_channel_ids: Optional[Sequence[int]] = None,
        allowed_role_ids: Optional[Sequence[int]] = None,
        cooldown_sec: int = 5,
        enabled: bool = True,
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO autoresponders (
                guild_id, trigger_text, match_mode, case_sensitive, response_text,
                allowed_channel_ids, allowed_role_ids, cooldown_sec, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, trigger_text) DO UPDATE SET
                match_mode = excluded.match_mode,
                case_sensitive = excluded.case_sensitive,
                response_text = excluded.response_text,
                allowed_channel_ids = excluded.allowed_channel_ids,
                allowed_role_ids = excluded.allowed_role_ids,
                cooldown_sec = excluded.cooldown_sec,
                enabled = excluded.enabled;
            """,
            (
                int(guild_id),
                trigger_text.strip(),
                match_mode.lower(),
                1 if case_sensitive else 0,
                response_text,
                json.dumps([int(c) for c in (allowed_channel_ids or [])]),
                json.dumps([int(r) for r in (allowed_role_ids or [])]),
                int(cooldown_sec),
                1 if enabled else 0,
            ),
        )

    async def list_autoresponders(self, guild_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM autoresponders WHERE guild_id = ? ORDER BY responder_id;",
            (int(guild_id),),
        )
        for r in rows:
            r["allowed_channel_ids"] = json.loads(r.get("allowed_channel_ids") or "[]")
            r["allowed_role_ids"] = json.loads(r.get("allowed_role_ids") or "[]")
        return rows

    async def delete_autoresponder(self, guild_id: int, trigger_text: str) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM autoresponders WHERE guild_id = ? AND trigger_text = ?;",
            (int(guild_id), trigger_text.strip()),
        )

    async def toggle_autoresponder(self, guild_id: int, trigger_text: str, enabled: bool) -> int:
        return await self.db.execute_rowcount(
            "UPDATE autoresponders SET enabled = ? WHERE guild_id = ? AND trigger_text = ?;",
            (1 if enabled else 0, int(guild_id), trigger_text.strip()),
        )

    async def add_scheduled_announcement(
        self,
        guild_id: int,
        channel_id: int,
        message_text: str,
        interval_minutes: int = 60,
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO scheduled_announcements
            (guild_id, channel_id, message_text, interval_minutes, enabled)
            VALUES (?, ?, ?, ?, 1);
            """,
            (int(guild_id), int(channel_id), message_text, max(1, int(interval_minutes))),
        )

    async def list_scheduled_announcements(self, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if guild_id is not None:
            return await self.db.fetchall(
                "SELECT * FROM scheduled_announcements WHERE guild_id = ? ORDER BY schedule_id;",
                (int(guild_id),),
            )
        return await self.db.fetchall(
            "SELECT * FROM scheduled_announcements WHERE enabled = 1 ORDER BY schedule_id;"
        )

    async def delete_scheduled_announcement(self, guild_id: int, schedule_id: int) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM scheduled_announcements WHERE guild_id = ? AND schedule_id = ?;",
            (int(guild_id), int(schedule_id)),
        )


class EmbedTemplateRepository:
    """Manages saved custom Discord embed templates per guild."""

    def __init__(self, db: DatabaseManager, guild_repo: GuildConfigRepository) -> None:
        self.db = db
        self.guild_repo = guild_repo

    async def save_template(
        self, guild_id: int, name: str, embed_dict: Dict[str, Any], author_id: int
    ) -> int:
        await self.guild_repo.ensure_guild(guild_id)
        return await self.db.execute(
            """
            INSERT INTO embed_templates (guild_id, name, embed_json, author_id, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(guild_id, name) DO UPDATE SET
                embed_json = excluded.embed_json,
                author_id = excluded.author_id,
                updated_at = datetime('now');
            """,
            (int(guild_id), name.lower().strip(), json.dumps(embed_dict), int(author_id)),
        )

    async def get_template(self, guild_id: int, name: str) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone(
            "SELECT * FROM embed_templates WHERE guild_id = ? AND name = ?;",
            (int(guild_id), name.lower().strip()),
        )
        if row:
            row["embed_data"] = json.loads(row["embed_json"])
        return row

    async def list_templates(self, guild_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM embed_templates WHERE guild_id = ? ORDER BY name;",
            (int(guild_id),),
        )
        for r in rows:
            r["embed_data"] = json.loads(r["embed_json"])
        return rows

    async def delete_template(self, guild_id: int, name: str) -> int:
        return await self.db.execute_rowcount(
            "DELETE FROM embed_templates WHERE guild_id = ? AND name = ?;",
            (int(guild_id), name.lower().strip()),
        )
