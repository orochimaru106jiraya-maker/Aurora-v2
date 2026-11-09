# Cosmic ki baddie V2 — Project Nova

**Cosmic ki baddie V2** (internally **Project Nova**) is a modular, production-ready Discord server management, ticket, moderation, RBAC, Join-to-Create voice, music, activity/reaction role, and automation bot built from scratch with **Python 3.11+**, **discord.py 2.x**, and **SQLite (`aiosqlite`)**.

## Key Architecture Highlights

1. **Dual Command Architecture (Prefix + Slash / Hybrid Commands)**
   - Every core command works via both traditional configurable server prefixes (`!help`, `!ping`, `!ban`, `!kick`, `!timeout`, `!purge`) and native Discord Application Slash Commands (`/help`, `/ping`, `/ban`, `/kick`, `/timeout`, `/purge`, `/setup`).
   - Each server can customize its own command prefix via `/setup` or `!setprefix`, stored in SQLite and cached in memory.
   - `ProjectNovaBot.on_message` guarantees that non-blocking listeners (such as Auto-Responders) never prevent `await bot.process_commands(message)`.
2. **Centralized Role-Based Access Control (RBAC)**
   - Single `PermissionService` shared across all 14 Cogs.
   - Supports 7 hierarchical tiers (`owner` > `administrator` > `management` > `moderator` > `support` > `custom` > `everyone`), per-command and per-category overrides, role overrides, user-specific allow/deny exceptions, and strict Discord role hierarchy validation.
3. **Centralized Async SQLite Database & Versioned Migrations**
   - Managed exclusively through `DatabaseManager` (`bot/database/manager.py`) and strongly-typed repositories (`bot/database/repositories.py`).
   - Enforces `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`, parameterized SQL queries, atomic write transactions, and 6 versioned schema migrations (`bot/database/migrations.py`).
4. **Persistent Discord UI Views**
   - Ticket creation panels, in-ticket control bars (`Claim`, `Transcript`, `Close`), Join-to-Create room controls, Button/Select self-role panels, Poll/Giveaway buttons, and the `/setup` Configuration Wizard use persistent `discord.ui.View(timeout=None)` instances with deterministic `custom_id`s so interactive components survive bot restarts.

## Project Directory Structure

```text
cosmic-ki-baddie/
├── main.py
├── requirements.txt
├── railway.json
├── nixpacks.toml
├── .python-version
├── .env.example
├── README.md
├── bot/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── bot.py
│   │   ├── config.py
│   │   ├── command_registry.py
│   │   ├── command_sync.py
│   │   ├── error_handler.py
│   │   ├── loader.py
│   │   └── health.py
│   ├── cogs/
│   │   ├── __init__.py
│   │   ├── help.py
│   │   ├── utility.py
│   │   ├── moderation.py
│   │   ├── tickets.py
│   │   ├── setup_wizard.py
│   │   ├── permissions.py
│   │   ├── jtc.py
│   │   ├── activity_roles.py
│   │   ├── reaction_roles.py
│   │   ├── music.py
│   │   ├── ai_assistant.py
│   │   ├── automation.py
│   │   ├── embeds.py
│   │   └── administration.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── sqlite_compat.py
│   │   ├── manager.py
│   │   ├── migrations.py
│   │   └── repositories.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── permission_service.py
│   ├── ui/
│   │   └── __init__.py
│   └── utils/
│       ├── __init__.py
│       └── formatting.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── discord_shim.py
│   ├── test_cog_loading.py
│   ├── test_prefix_commands.py
│   ├── test_slash_commands.py
│   ├── test_permissions.py
│   └── test_database.py
└── data/
```

## Required Discord Developer Portal Intent Settings

Before starting the bot, enable the three Privileged Gateway Intents in the [Discord Developer Portal](https://discord.com/developers/applications):

1. Open your Application → **Bot** tab.
2. Scroll down to **Privileged Gateway Intents** and toggle **ON**:
   - **PRESENCE INTENT** (required for Activity Roles detection: Games, Spotify, Streaming).
   - **SERVER MEMBERS INTENT** (required for Welcome/Goodbye messages, Auto-Role on join, and RBAC member lookups).
   - **MESSAGE CONTENT INTENT** (required for Prefix commands like `!help`, `!ping`, AutoMod content filtering, and Keyword Auto-Responders).
3. Click **Save Changes**.

## Local Installation & Startup

```bash
# 1. Create and activate a Python 3.11+ virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install pinned dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env and set DISCORD_TOKEN=your_bot_token

# 4. Run pre-flight self-test (verifies DB migrations and loads all 14 Cogs)
python main.py --self-test

# 5. Run the automated test suite
pytest -v

# 6. Start the bot
python main.py
```

## Complete Command Reference

All commands below are registered and active in both **Prefix** (`!`) and **Slash** (`/`) formats:

| Category | Commands (Prefix & Slash) | Default RBAC Tier | Description |
| :--- | :--- | :--- | :--- |
| **Configuration** | `/setup` (`!setup`) | Administrator | Interactive configuration wizard with embeds, selects, modals, pagination, and reset confirmation |
| **Configuration** | `/permissions` (`!permissions` / `!rbac`) | Administrator | Manage RBAC staff roles (`addrole`, `removerole`), command/category tiers (`setcommand`, `setcategory`), user exceptions (`allowuser`, `denyuser`), role overrides (`allowrole`), and inspect access (`check`) |
| **Moderation** | `/ban`, `/unban`, `/kick`, `/timeout`, `/untimeout` | Moderator | Member moderation with role hierarchy validation, owner protection, and audit logging |
| **Moderation** | `/warn`, `/warnings`, `/clearwarnings` | Moderator / Support | Persistent SQLite member warnings and DM notifications |
| **Moderation** | `/purge`, `/slowmode`, `/lock`, `/unlock`, `/snipe`, `/modlogs` | Moderator | Channel management, safe message purge (max 100), 5-min privacy-respecting snipe, and audit logs |
| **Moderation** | `/automod` (`status`, `toggle`, `addword`, `removeword`) | Management | Configure automatic moderation for bad words, invite links, external links, mass mentions, and spam |
| **Tickets** | `/ticket` (`panel`, `addcategory`, `removecategory`, `config`, `claim`, `close`) | Management / Support | Multi-category support ticket panels (General Help, File Complaint, Staff Application, Winning Prize), claiming, transcripts, and DM notifications |
| **Voice Channels** | `/jtc setup`, `/vc` (`panel`, `rename`, `limit`, `lock`, `unlock`, `hide`, `unhide`, `transfer`, `allow`, `deny`) | Management / Room Owner | Join-to-Create temporary voice rooms with persistent control panel and restart recovery |
| **Activity Roles** | `/activityrole` (`list`, `add`, `remove`) | Management | Automatic Rich Presence roles for Games, Spotify, Streaming, and all activities |
| **Reaction Roles** | `/reactionrole` (`list`, `create`, `additem`, `delete`) | Management | Persistent Button, Select-Menu, and Reaction role panels (multi-select & exclusive groups) |
| **Automation** | `/autoresponder` (`list`, `add`, `remove`, `toggle`), `/welcome`, `/goodbye`, `/autorole`, `/schedule` | Management | Keyword autoresponders (exact/partial/case-sensitive/cooldowns), welcome/goodbye embeds, join auto-roles, and scheduled announcements |
| **Music** | `/play`, `/pause`, `/resume`, `/skip`, `/stop`, `/queue`, `/nowplaying`, `/volume`, `/loop`, `/shuffle`, `/leave` | Everyone | Multi-server FFmpeg voice music playback, queue controls, volume, loop modes, and idle disconnect |
| **AI Assistant** | `/ask`, `/ai` (`status`, `setup`, `toggle`, `addchannel`) | Everyone / Administrator | Optional modular AI assistant supporting local endpoints (Ollama/vLLM) or OpenAI-compatible APIs |
| **Administration** | `/setprefix`, `/setlang`, `/logging`, `/announce`, `/poll`, `/giveaway`, `/temprole`, `/backup` (`export`, `restore`) | Administrator / Management | Server prefix/language, audit log channels, announcements, persistent polls & giveaways, temporary roles, and JSON config backups |
| **Utility** | `/help` (`!help`, `!commands`), `/ping`, `/serverinfo`, `/userinfo`, `/avatar`, `/roleinfo`, `/channelinfo`, `/botinfo`, `/inviteinfo`, `/embed` (`builder`, `templates`, `load`, `publish`) | Everyone / Management | Interactive help system, latency telemetry, server/member inspection, and modal-driven custom embed builder |

## Railway Deployment Guide

### 1. Deploying the Bot Service on Railway
1. Push the `cosmic-ki-baddie/` repository to GitHub and create a **New Project → Deploy from GitHub repo** in [Railway](https://railway.app/).
2. Railway automatically detects:
   - `railway.json` and `nixpacks.toml` (which install Python 3.11, `ffmpeg`, and `libopus`, and set the start command to `python main.py` with `ON_FAILURE` restart policy).
   - `.python-version` (`3.11`) and `requirements.txt`.
3. Attach a **Persistent Volume** so your SQLite database survives container redeployments:
   - Right-click your Railway service → **Attach Volume** → Set Mount Path to `/app/data`.
4. Configure **Variables** in the Railway service dashboard:
   - `DISCORD_TOKEN`: Your Discord bot token.
   - `DATABASE_PATH`: `/app/data/nova.db`
   - `DEFAULT_PREFIX`: `!`
   - `SYNC_COMMANDS_ON_STARTUP`: `true`
   - `LOG_LEVEL`: `INFO`

### 2. Multi-Service Architecture (Bot vs. Website / Frontend)
If your repository or organization also includes a separate website or web dashboard:
- **Run the Discord Bot and the Website as two separate Railway services** inside the same Railway Project—never overwrite the website's build configuration with the bot's worker process.
- Why separate services are recommended:
  1. **Lifecycle Isolation:** The Discord bot (`python main.py`) maintains a persistent stateful WebSocket gateway connection and voice UDP sockets, whereas a frontend/website scales horizontally on stateless HTTP requests.
  2. **Zero Downtime:** Redeploying frontend UI updates will not disconnect active voice channels or reset the bot's gateway session.
  3. **Independent Resource & Volume Allocation:** The SQLite persistent volume (`/app/data`) can be mounted exclusively to the bot service without lock contention.
