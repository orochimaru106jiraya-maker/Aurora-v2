"""Voice Music System (`bot/cogs/music.py`) for Project Nova.

Commands (Slash & Prefix via Hybrid Commands):
- `/play` (`!play`)
- `/pause` (`!pause`)
- `/resume` (`!resume`)
- `/skip` (`!skip`)
- `/stop` (`!stop`)
- `/queue` (`!queue`)
- `/nowplaying` (`!nowplaying`)
- `/volume` (`!volume`)
- `/loop` (`!loop`)
- `/shuffle` (`!shuffle`)
- `/leave` (`!leave`)

Uses FFmpeg (`discord.FFmpegPCMAudio` + `discord.PCMVolumeTransformer`), supports multiple
servers independently, enforces honest audio extraction (never fabricates playback when
extraction fails), and automatically disconnects when idle.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
import random
import shutil
import time
from typing import Deque, Dict, List, Optional
from urllib.parse import urlparse
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.utils.formatting import make_embed

logger = logging.getLogger("project_nova.cogs.music")

DIRECT_AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".m3u8")


@dataclass
class AudioTrack:
    """Represents a validated playable audio track."""

    title: str
    stream_url: str
    webpage_url: str
    requester_id: int
    duration_sec: int = 0
    is_local: bool = False


class GuildMusicState:
    """Per-guild voice playback state, queue, loop mode, and idle timer."""

    def __init__(self, guild_id: int, default_volume: int = 80) -> None:
        self.guild_id = guild_id
        self.queue: Deque[AudioTrack] = deque()
        self.current: Optional[AudioTrack] = None
        self.volume: float = max(0.01, min(2.0, default_volume / 100.0))
        self.loop_mode: str = "off"  # 'off', 'track', 'queue'
        self.last_active_monotonic: float = time.monotonic()


class MusicCog(commands.Cog, name="MusicCog"):
    """Multi-Server Voice Music Player with FFmpeg & Queue Controls."""

    CATEGORY = "Music"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._states: Dict[int, GuildMusicState] = {}

    async def cog_load(self) -> None:
        self.idle_check_loop.start()

    async def cog_unload(self) -> None:
        self.idle_check_loop.cancel()
        for guild in self.bot.guilds:
            if guild.voice_client:
                try:
                    await guild.voice_client.disconnect(force=True)
                except Exception:
                    pass

    async def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self._states:
            cfg = await self.bot.guild_config_repo.ensure_guild(guild_id)
            vol = int(cfg.get("music_default_volume") or 80)
            self._states[guild_id] = GuildMusicState(guild_id, default_volume=vol)
        return self._states[guild_id]

    def _check_ffmpeg_available(self) -> Optional[str]:
        exe = self.bot.config.ffmpeg_executable
        if Path(exe).is_file() or shutil.which(exe):
            return exe
        return None

    async def resolve_audio_track(
        self, query: str, requester_id: int
    ) -> AudioTrack:
        """Resolve `query` into a playable `AudioTrack` or raise ValueError if extraction fails.

        Never fabricates successful playback when audio extraction fails.
        """
        clean = query.strip()
        if not clean:
            raise ValueError("Empty audio query provided.")

        # 1. Check if it is an existing local audio file path (for server-side sounds/tests)
        local_path = Path(clean)
        if local_path.is_file() and local_path.suffix.lower() in DIRECT_AUDIO_EXTENSIONS:
            return AudioTrack(
                title=local_path.stem,
                stream_url=str(local_path.resolve()),
                webpage_url=f"file://{local_path.name}",
                requester_id=requester_id,
                is_local=True,
            )

        # 2. Check if it is a direct HTTP(S) stream URL
        parsed = urlparse(clean)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in DIRECT_AUDIO_EXTENSIONS) or "stream" in path_lower:
                title = Path(parsed.path).stem or parsed.netloc
                return AudioTrack(
                    title=title,
                    stream_url=clean,
                    webpage_url=clean,
                    requester_id=requester_id,
                    is_local=False,
                )

        # 3. Attempt extraction via yt_dlp only if installed in environment
        try:
            import yt_dlp  # type: ignore

            ydl_opts = {
                "format": "bestaudio/best",
                "noplaylist": True,
                "quiet": True,
                "default_search": "ytsearch1",
            }
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(clean, download=False),
            )
            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                if not entries:
                    raise ValueError(f"No playable audio stream found for `{clean}`.")
                info = entries[0]
            stream_url = info.get("url")
            if not stream_url:
                raise ValueError(f"Extractor returned no stream URL for `{clean}`.")
            return AudioTrack(
                title=str(info.get("title") or clean),
                stream_url=str(stream_url),
                webpage_url=str(info.get("webpage_url") or clean),
                requester_id=requester_id,
                duration_sec=int(info.get("duration") or 0),
            )
        except ModuleNotFoundError:
            raise ValueError(
                f"Cannot extract audio for `{clean}`: Direct audio URLs ({', '.join(DIRECT_AUDIO_EXTENSIONS)}) "
                "and local audio files are supported natively; external search/stream extraction requires `yt-dlp`."
            )
        except Exception as exc:
            raise ValueError(f"Audio extraction failed for `{clean}`: {exc}")

    def _start_next_track(self, guild: discord.Guild, state: GuildMusicState) -> None:
        """Play the next track in the guild's queue and clean up after playback."""
        vc = guild.voice_client
        if vc is None or not vc.is_connected():
            state.current = None
            return

        if state.loop_mode == "track" and state.current is not None:
            next_track = state.current
        elif state.queue:
            if state.loop_mode == "queue" and state.current is not None:
                state.queue.append(state.current)
            next_track = state.queue.popleft()
        else:
            state.current = None
            state.last_active_monotonic = time.monotonic()
            return

        ffmpeg_exe = self._check_ffmpeg_available() or "ffmpeg"
        before_opts = None if next_track.is_local else "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        raw_source = discord.FFmpegPCMAudio(
            next_track.stream_url,
            executable=ffmpeg_exe,
            before_options=before_opts,
            options="-vn",
        )
        volume_source = discord.PCMVolumeTransformer(raw_source, volume=state.volume)
        state.current = next_track
        state.last_active_monotonic = time.monotonic()

        def _after_playback(error: Optional[Exception]) -> None:
            try:
                volume_source.cleanup()
            except Exception:
                pass
            if error:
                logger.error("Playback error in guild %d: %s", guild.id, error)
            self._start_next_track(guild, state)

        vc.play(volume_source, after=_after_playback)

    @tasks.loop(seconds=30)
    async def idle_check_loop(self) -> None:
        """Automatically disconnect from voice channels that are idle or empty."""
        if not self.bot.db.is_connected:
            return
        now = time.monotonic()
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                continue
            state = await self.get_state(guild.id)
            cfg = await self.bot.guild_config_repo.ensure_guild(guild.id)
            timeout_sec = int(cfg.get("music_idle_timeout_sec") or 180)

            human_listeners = [m for m in vc.channel.members if not m.bot] if vc.channel else []
            if not human_listeners:
                state.queue.clear()
                state.current = None
                await vc.disconnect()
                continue

            if not vc.is_playing() and not vc.is_paused():
                if (now - state.last_active_monotonic) >= timeout_sec:
                    state.queue.clear()
                    state.current = None
                    await vc.disconnect()

    @commands.hybrid_command(
        name="play",
        aliases=["p"],
        description="Play a direct audio stream/file or add it to the server music queue.",
    )
    @app_commands.describe(query="Direct audio URL (.mp3/.ogg/.wav/.m3u8) or supported stream query")
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Connect to the caller's voice channel and play or queue an audio track."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        if not ctx.author.voice or not isinstance(ctx.author.voice.channel, discord.VoiceChannel):
            raise commands.BadArgument("You must join a voice channel before using `/play`.")

        if not self._check_ffmpeg_available():
            raise commands.CommandError("FFmpeg is not installed or accessible on the host system.")

        try:
            track = await self.resolve_audio_track(query, ctx.author.id)
        except ValueError as exc:
            emb = make_embed(
                "⚠️ Audio Extraction Failed",
                str(exc),
                color=discord.Color.red(),
            )
            await ctx.send(embed=emb, ephemeral=True)
            return

        target_vc = ctx.author.voice.channel
        vc = ctx.guild.voice_client
        if vc is None or not vc.is_connected():
            vc = await target_vc.connect()
        elif vc.channel.id != target_vc.id:
            await vc.move_to(target_vc)

        state = await self.get_state(ctx.guild.id)
        state.queue.append(track)

        if not vc.is_playing() and not vc.is_paused():
            self._start_next_track(ctx.guild, state)
            emb = make_embed(
                "🎵 Now Playing",
                f"**[{track.title}]({track.webpage_url})**\n• **Requested By:** {ctx.author.mention}\n• **Volume:** `{int(state.volume * 100)}%`",
                color=discord.Color.green(),
            )
        else:
            emb = make_embed(
                "➕ Added to Queue",
                f"**[{track.title}]({track.webpage_url})**\n• **Position in Queue:** `#{len(state.queue)}`\n• **Requested By:** {ctx.author.mention}",
                color=discord.Color.blurple(),
            )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="pause",
        description="Pause the currently playing audio track.",
    )
    @commands.guild_only()
    async def pause(self, ctx: commands.Context) -> None:
        """Pause active voice playback."""
        assert ctx.guild is not None
        vc = ctx.guild.voice_client
        if vc is None or not vc.is_playing():
            raise commands.BadArgument("Nothing is currently playing.")
        vc.pause()
        await ctx.send(
            embed=make_embed("⏸️ Playback Paused", "Audio playback has been paused.", color=discord.Color.orange())
        )

    @commands.hybrid_command(
        name="resume",
        description="Resume a paused audio track.",
    )
    @commands.guild_only()
    async def resume(self, ctx: commands.Context) -> None:
        """Resume paused voice playback."""
        assert ctx.guild is not None
        vc = ctx.guild.voice_client
        if vc is None or not vc.is_paused():
            raise commands.BadArgument("Playback is not currently paused.")
        vc.resume()
        await ctx.send(
            embed=make_embed("▶️ Playback Resumed", "Resumed audio playback.", color=discord.Color.green())
        )

    @commands.hybrid_command(
        name="skip",
        aliases=["next", "s"],
        description="Skip the current track and play the next item in the queue.",
    )
    @commands.guild_only()
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the currently playing track."""
        assert ctx.guild is not None
        vc = ctx.guild.voice_client
        state = await self.get_state(ctx.guild.id)
        if vc is None or (not vc.is_playing() and not vc.is_paused()):
            raise commands.BadArgument("No track is currently playing.")
        skipped_title = state.current.title if state.current else "Current Track"
        vc.stop()
        self._start_next_track(ctx.guild, state)
        await ctx.send(
            embed=make_embed("⏭️ Track Skipped", f"Skipped **{skipped_title}**.", color=discord.Color.blurple())
        )

    @commands.hybrid_command(
        name="stop",
        description="Stop playback and clear the server music queue.",
    )
    @commands.guild_only()
    async def stop(self, ctx: commands.Context) -> None:
        """Stop playback and empty the queue."""
        assert ctx.guild is not None
        vc = ctx.guild.voice_client
        state = await self.get_state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        state.loop_mode = "off"
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await ctx.send(
            embed=make_embed("⏹️ Playback Stopped", "Stopped playback and cleared the queue.", color=discord.Color.red())
        )

    @commands.hybrid_command(
        name="queue",
        aliases=["q"],
        description="Display the current server music queue.",
    )
    @commands.guild_only()
    async def queue(self, ctx: commands.Context) -> None:
        """Display the active track and upcoming queue."""
        assert ctx.guild is not None
        state = await self.get_state(ctx.guild.id)
        if state.current is None and not state.queue:
            await ctx.send(
                embed=make_embed("🎶 Music Queue Empty", "No tracks are currently playing or queued.", color=discord.Color.blurple())
            )
            return

        desc_lines: List[str] = []
        if state.current:
            desc_lines.append(
                f"**Now Playing:** [{state.current.title}]({state.current.webpage_url}) (Requested by <@{state.current.requester_id}>)\n"
            )
        if state.queue:
            desc_lines.append("**Up Next:**")
            for idx, item in enumerate(list(state.queue)[:15], start=1):
                desc_lines.append(f"`{idx}.` [{item.title}]({item.webpage_url}) — <@{item.requester_id}>")
        emb = make_embed(
            f"🎶 Music Queue — {ctx.guild.name} (Loop: {state.loop_mode.upper()})",
            "\n".join(desc_lines),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="nowplaying",
        aliases=["np"],
        description="Show details about the currently playing track.",
    )
    @commands.guild_only()
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Show the currently playing track."""
        assert ctx.guild is not None
        state = await self.get_state(ctx.guild.id)
        if state.current is None:
            raise commands.BadArgument("No track is currently playing.")
        emb = make_embed(
            "🎧 Now Playing",
            (
                f"**[{state.current.title}]({state.current.webpage_url})**\n"
                f"• **Requested By:** <@{state.current.requester_id}>\n"
                f"• **Volume:** `{int(state.volume * 100)}%` | **Loop Mode:** `{state.loop_mode.upper()}`\n"
                f"• **Queued Tracks Remaining:** `{len(state.queue)}`"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="volume",
        aliases=["vol"],
        description="Adjust the playback volume between 1% and 200%.",
    )
    @app_commands.describe(level="Volume percentage (1 to 200)")
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, level: int) -> None:
        """Set the voice player volume percentage."""
        assert ctx.guild is not None
        if level < 1 or level > 200:
            raise commands.BadArgument("Volume must be between **1** and **200**.")
        state = await self.get_state(ctx.guild.id)
        state.volume = level / 100.0
        vc = ctx.guild.voice_client
        if vc and isinstance(getattr(vc, "source", None), discord.PCMVolumeTransformer):
            vc.source.volume = state.volume
        await ctx.send(
            embed=make_embed("🔊 Volume Updated", f"Playback volume set to **`{level}%`**.", color=discord.Color.green())
        )

    @commands.hybrid_command(
        name="loop",
        description="Set the music loop mode (off, track, queue).",
    )
    @app_commands.describe(mode="Loop mode: off, track, or queue")
    @commands.guild_only()
    async def loop(self, ctx: commands.Context, mode: str = "track") -> None:
        """Configure loop mode for the server player."""
        assert ctx.guild is not None
        clean = mode.lower().strip()
        if clean not in ("off", "track", "queue"):
            raise commands.BadArgument("Loop mode must be `off`, `track`, or `queue`.")
        state = await self.get_state(ctx.guild.id)
        state.loop_mode = clean
        await ctx.send(
            embed=make_embed("🔁 Loop Mode Updated", f"Loop mode is now set to **`{clean.upper()}`**.", color=discord.Color.green())
        )

    @commands.hybrid_command(
        name="shuffle",
        description="Shuffle the upcoming tracks in the server music queue.",
    )
    @commands.guild_only()
    async def shuffle(self, ctx: commands.Context) -> None:
        """Randomly shuffle the tracks in the queue."""
        assert ctx.guild is not None
        state = await self.get_state(ctx.guild.id)
        if len(state.queue) < 2:
            raise commands.BadArgument("Need at least 2 tracks in the queue to shuffle.")
        items = list(state.queue)
        random.shuffle(items)
        state.queue = deque(items)
        await ctx.send(
            embed=make_embed("🔀 Queue Shuffled", f"Shuffled **{len(items)}** upcoming tracks.", color=discord.Color.green())
        )

    @commands.hybrid_command(
        name="leave",
        aliases=["disconnect", "dc"],
        description="Disconnect the bot from the voice channel and clean up playback state.",
    )
    @commands.guild_only()
    async def leave(self, ctx: commands.Context) -> None:
        """Leave the voice channel and clear the queue."""
        assert ctx.guild is not None
        vc = ctx.guild.voice_client
        if vc is None or not vc.is_connected():
            raise commands.BadArgument("I am not connected to any voice channel.")
        state = await self.get_state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        await vc.disconnect()
        await ctx.send(
            embed=make_embed("👋 Disconnected", "Left the voice channel and cleaned up audio resources.", color=discord.Color.blurple())
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
