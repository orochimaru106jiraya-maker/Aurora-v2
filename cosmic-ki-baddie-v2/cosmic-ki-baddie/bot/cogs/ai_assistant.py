"""Optional Modular AI Assistant Module (`bot/cogs/ai_assistant.py`).

Features:
- No mandatory paid API.
- Modular provider architecture (`LocalEndpointProvider` for Ollama/LM Studio/vLLM,
  and `OpenAICompatibleProvider` for optional user-supplied API keys).
- Enable/disable controls, configurable allowed channels, per-user cooldowns,
  rate limits, and context limits.
- Never pretends the bot has AI capabilities when no model is connected or enabled;
  displays a clear setup guide instead.
- Never exposes API keys in Discord messages or logs.
"""

from __future__ import annotations

from collections import deque
import json
import logging
import time
from typing import Any, Deque, Dict, List, Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.permission_service import require_tier
from bot.utils.formatting import make_embed

logger = logging.getLogger("project_nova.cogs.ai_assistant")


class AIProviderClient:
    """Modular async HTTP client supporting local endpoints and optional OpenAI-compatible APIs."""

    @staticmethod
    async def generate_response(
        *,
        provider: str,
        endpoint: str,
        model: str,
        prompt: str,
        api_key: Optional[str] = None,
        timeout_sec: float = 20.0,
    ) -> str:
        import httpx

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        prov = provider.lower().strip()
        if prov == "local":
            payload = {"model": model, "prompt": prompt, "stream": False}
        elif prov == "openai_compatible":
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are Cosmic ki baddie V2 (Project Nova), a helpful Discord server assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 500,
            }
        else:
            raise RuntimeError("No AI provider is configured.")

        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "response" in data:
                return str(data["response"]).strip()
            if "choices" in data and data["choices"]:
                msg = data["choices"][0].get("message", {})
                return str(msg.get("content") or data["choices"][0].get("text") or "").strip()
            raise RuntimeError("Unexpected response format from AI endpoint.")


class AIAssistantCog(commands.Cog, name="AIAssistantCog"):
    """Optional Modular AI Assistant with Rate, Context, and Channel Controls."""

    CATEGORY = "AI Assistant"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.provider_client = AIProviderClient()
        # (guild_id, user_id) -> monotonic timestamp
        self._user_cooldowns: Dict[Tuple[int, int], float] = {}
        # guild_id -> deque of request timestamps in last 60s
        self._guild_rate_window: Dict[int, Deque[float]] = {}

    @commands.hybrid_command(
        name="ask",
        aliases=["chat"],
        description="Ask a question to the configured server AI assistant.",
    )
    @app_commands.describe(prompt="Your question or prompt for the AI assistant")
    @commands.guild_only()
    async def ask(self, ctx: commands.Context, *, prompt: str) -> None:
        """Query the server's configured AI model (if enabled and connected)."""
        assert ctx.guild is not None and ctx.channel is not None
        cfg = await self.bot.guild_config_repo.ensure_guild(ctx.guild.id)

        # 1. Check if AI is enabled and configured; never pretend AI is connected if not!
        provider = str(cfg.get("ai_provider") or "none").lower()
        if not cfg.get("ai_enabled") or provider == "none":
            emb = make_embed(
                "🤖 AI Assistant Not Configured",
                (
                    "The optional AI Assistant module is currently **disabled** or has no model connected.\n\n"
                    "**How Administrators Can Configure It:**\n"
                    "• Run `/ai setup provider:local endpoint:http://127.0.0.1:11434/api/generate model:llama3`\n"
                    "• Or configure via `/setup` → **AI Assistant Settings**\n"
                    "• No paid API is required!"
                ),
                color=discord.Color.orange(),
            )
            await ctx.send(embed=emb, ephemeral=True)
            return

        # 2. Check allowed channels restriction
        allowed_channels: List[int] = json.loads(cfg.get("ai_channels") or "[]")
        if allowed_channels and ctx.channel.id not in allowed_channels:
            ch_mentions = ", ".join(f"<#{cid}>" for cid in allowed_channels)
            emb = make_embed(
                "🚫 Channel Restricted",
                f"The AI Assistant is restricted to: {ch_mentions}",
                color=discord.Color.orange(),
            )
            await ctx.send(embed=emb, ephemeral=True)
            return

        # 3. Enforce per-user cooldown
        now = time.monotonic()
        cd_sec = int(cfg.get("ai_cooldown_sec") or 10)
        ukey = (ctx.guild.id, ctx.author.id)
        last_ts = self._user_cooldowns.get(ukey, 0.0)
        if cd_sec > 0 and (now - last_ts) < cd_sec:
            rem = cd_sec - (now - last_ts)
            await ctx.send(
                embed=make_embed(
                    "⏳ AI Cooldown",
                    f"Please wait **{rem:.1f}s** before sending another AI prompt.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        # 4. Enforce per-guild rate limit (max 20 requests / minute)
        g_window = self._guild_rate_window.setdefault(ctx.guild.id, deque())
        while g_window and (now - g_window[0]) > 60.0:
            g_window.popleft()
        if len(g_window) >= 20:
            await ctx.send(
                embed=make_embed(
                    "🚦 Server Rate Limit Reached",
                    "This server has reached the maximum AI request rate (20 requests/min). Please try again shortly.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        # 5. Enforce context length limit
        max_chars = int(cfg.get("ai_max_context_chars") or 2000)
        truncated_prompt = prompt.strip()[:max_chars]

        self._user_cooldowns[ukey] = now
        g_window.append(now)

        try:
            reply_text = await self.provider_client.generate_response(
                provider=provider,
                endpoint=str(cfg.get("ai_endpoint") or ""),
                model=str(cfg.get("ai_model") or "llama3"),
                prompt=truncated_prompt,
                api_key=cfg.get("ai_api_key"),
            )
        except Exception as exc:
            # Never leak API keys in error messages or logs
            safe_err = str(exc)
            if cfg.get("ai_api_key"):
                safe_err = safe_err.replace(str(cfg["ai_api_key"]), "[REDACTED_KEY]")
            logger.warning("AI provider connection error in guild %d: %s", ctx.guild.id, safe_err)
            emb = make_embed(
                "⚠️ AI Endpoint Unreachable",
                f"Could not reach the configured AI model (`{cfg.get('ai_model')}` at `{cfg.get('ai_endpoint')}`).\n"
                f"Details: `{safe_err[:200]}`",
                color=discord.Color.red(),
            )
            await ctx.send(embed=emb, ephemeral=True)
            return

        emb = make_embed(
            f"🤖 AI Response ({cfg.get('ai_model')})",
            reply_text[:4000] or "*Empty response from model.*",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_group(
        name="ai",
        description="Configure the server's optional AI assistant provider, channels, and limits.",
        fallback="status",
    )
    @commands.guild_only()
    @require_tier("administrator")
    async def ai_group(self, ctx: commands.Context) -> None:
        """Display the current AI assistant settings (with API keys masked)."""
        assert ctx.guild is not None
        cfg = await self.bot.guild_config_repo.ensure_guild(ctx.guild.id)
        channels: List[int] = json.loads(cfg.get("ai_channels") or "[]")
        has_key = "Configured (`********`)" if cfg.get("ai_api_key") else "None (Not required for local)"
        ch_str = ", ".join(f"<#{cid}>" for cid in channels) if channels else "All Channels"

        emb = make_embed(
            f"🤖 AI Assistant Configuration — {ctx.guild.name}",
            (
                f"• **Enabled:** `{'Yes' if cfg['ai_enabled'] else 'No'}`\n"
                f"• **Provider:** `{cfg['ai_provider']}`\n"
                f"• **Model:** `{cfg['ai_model']}`\n"
                f"• **Endpoint:** `{cfg['ai_endpoint']}`\n"
                f"• **API Key:** {has_key}\n"
                f"• **Allowed Channels:** {ch_str}\n"
                f"• **Per-User Cooldown:** `{cfg['ai_cooldown_sec']}s` | **Max Context:** `{cfg['ai_max_context_chars']} chars`"
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb, ephemeral=True)

    @ai_group.command(
        name="setup",
        description="Configure the AI provider, endpoint URL, model name, and cooldown.",
    )
    @app_commands.describe(
        provider="Provider type: local, openai_compatible, or none",
        endpoint="HTTP endpoint URL for the model",
        model="Model identifier (e.g. llama3, mistral, gpt-4o-mini)",
        cooldown_sec="Per-user cooldown in seconds",
        max_context_chars="Maximum prompt length in characters",
        api_key="Optional API key (never displayed in chat or logs)",
    )
    @require_tier("administrator")
    async def ai_setup(
        self,
        ctx: commands.Context,
        provider: str,
        endpoint: str,
        model: str = "llama3",
        cooldown_sec: int = 10,
        max_context_chars: int = 2000,
        api_key: Optional[str] = None,
    ) -> None:
        """Configure the AI provider and enable the AI assistant."""
        assert ctx.guild is not None
        prov = provider.lower().strip()
        if prov not in ("local", "openai_compatible", "none"):
            raise commands.BadArgument("Provider must be `local`, `openai_compatible`, or `none`.")

        updates: Dict[str, Any] = {
            "ai_enabled": 0 if prov == "none" else 1,
            "ai_provider": prov,
            "ai_endpoint": endpoint.strip(),
            "ai_model": model.strip(),
            "ai_cooldown_sec": max(1, int(cooldown_sec)),
            "ai_max_context_chars": max(100, min(8000, int(max_context_chars))),
        }
        if api_key is not None:
            updates["ai_api_key"] = api_key.strip()

        await self.bot.guild_config_repo.update_fields(ctx.guild.id, **updates)
        emb = make_embed(
            "✅ AI Assistant Configured",
            (
                f"• **Status:** `{'Enabled' if updates['ai_enabled'] else 'Disabled'}`\n"
                f"• **Provider:** `{prov}` | **Model:** `{model}`\n"
                f"• **Endpoint:** `{endpoint}`\n"
                f"• **API Key:** `{'Updated (Hidden)' if api_key else 'Unchanged'}`"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb, ephemeral=True)

    @ai_group.command(
        name="toggle",
        description="Enable or disable the AI Assistant module.",
    )
    @app_commands.describe(enabled="True to enable, False to disable")
    @require_tier("administrator")
    async def ai_toggle(self, ctx: commands.Context, enabled: bool) -> None:
        """Toggle AI assistant on or off."""
        assert ctx.guild is not None
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id, ai_enabled=1 if enabled else 0
        )
        await ctx.send(
            embed=make_embed(
                "🤖 AI Assistant Toggled",
                f"AI Assistant is now **{'Enabled' if enabled else 'Disabled'}**.",
                color=discord.Color.green() if enabled else discord.Color.orange(),
            )
        )

    @ai_group.command(
        name="addchannel",
        description="Restrict AI assistant usage to specific text channels.",
    )
    @app_commands.describe(channel="Channel to allow AI assistant usage in")
    @require_tier("administrator")
    async def ai_addchannel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Add a channel to the AI assistant allowlist."""
        assert ctx.guild is not None
        cfg = await self.bot.guild_config_repo.ensure_guild(ctx.guild.id)
        channels: List[int] = json.loads(cfg.get("ai_channels") or "[]")
        if channel.id not in channels:
            channels.append(channel.id)
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id, ai_channels=json.dumps(channels)
        )
        await ctx.send(
            embed=make_embed(
                "✅ AI Channel Added",
                f"Added {channel.mention} to allowed AI channels.",
                color=discord.Color.green(),
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIAssistantCog(bot))
