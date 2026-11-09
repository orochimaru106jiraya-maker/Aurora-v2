"""Test harness shim for discord.py 2.x when running automated tests in an
offline environment where the external `discord.py` wheel is not installed.

In production (Railway or local virtualenv with `pip install -r requirements.txt`),
the genuine `discord.py 2.x` library is imported directly. This module is ONLY
activated by `tests/conftest.py` if `import discord` raises `ModuleNotFoundError`.
It faithfully implements the `discord`, `discord.app_commands`, and
`discord.ext.commands` / `discord.ext.tasks` APIs used by Project Nova so that
prefix command parsing, slash command tree registration, hybrid commands, Cogs,
cooldowns, permission checks, and persistent UI views/modals/buttons/selects can
be thoroughly tested offline.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
import inspect
import sys
import types
from typing import Any, Callable, Coroutine, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Type, Union


def install_discord_shim_if_needed() -> bool:
    """Install the discord.py 2.x test shim into `sys.modules` if `discord` is missing."""
    try:
        import discord  # noqa: F401
        return False
    except ModuleNotFoundError:
        pass

    discord_mod = types.ModuleType("discord")
    app_commands_mod = types.ModuleType("discord.app_commands")
    ext_mod = types.ModuleType("discord.ext")
    commands_mod = types.ModuleType("discord.ext.commands")
    tasks_mod = types.ModuleType("discord.ext.tasks")
    ui_mod = types.ModuleType("discord.ui")
    utils_mod = types.ModuleType("discord.utils")

    discord_mod.__version__ = "2.4.0-shim"
    discord_mod.version_info = (2, 4, 0, "final", 0)

    # --- Basic types & enums ---
    class DiscordException(Exception):
        pass

    class Forbidden(DiscordException):
        pass

    class NotFound(DiscordException):
        pass

    class HTTPException(DiscordException):
        pass

    class Color:
        def __init__(self, value: int = 0) -> None:
            self.value = int(value) & 0xFFFFFF

        @classmethod
        def blurple(cls) -> "Color":
            return cls(0x5865F2)

        @classmethod
        def green(cls) -> "Color":
            return cls(0x57F287)

        @classmethod
        def red(cls) -> "Color":
            return cls(0xED4245)

        @classmethod
        def gold(cls) -> "Color":
            return cls(0xFEE75C)

        @classmethod
        def orange(cls) -> "Color":
            return cls(0xE67E22)

        @classmethod
        def blue(cls) -> "Color":
            return cls(0x3498DB)

        @classmethod
        def dark_theme(cls) -> "Color":
            return cls(0x2B2D31)

        @classmethod
        def from_str(cls, value: str) -> "Color":
            clean = value.strip().lstrip("#")
            if clean.startswith("0x") or clean.startswith("0X"):
                clean = clean[2:]
            return cls(int(clean, 16))

        def __int__(self) -> int:
            return self.value

        def __eq__(self, other: Any) -> bool:
            return isinstance(other, Color) and self.value == other.value

    Colour = Color

    class ButtonStyle(Enum):
        primary = 1
        blurple = 1
        secondary = 2
        grey = 2
        gray = 2
        success = 3
        green = 3
        danger = 4
        red = 4
        link = 5

    class TextStyle(Enum):
        short = 1
        paragraph = 2
        long = 2

    class ChannelType(Enum):
        text = 0
        private = 1
        voice = 2
        group = 3
        category = 4
        news = 5
        stage_voice = 13
        forum = 15

    class ActivityType(Enum):
        unknown = -1
        playing = 0
        streaming = 1
        listening = 2
        watching = 3
        custom = 4
        competing = 5

    class Status(Enum):
        online = "online"
        offline = "offline"
        idle = "idle"
        dnd = "dnd"

    class Intents:
        def __init__(self, **kwargs: bool) -> None:
            self.guilds = kwargs.get("guilds", True)
            self.members = kwargs.get("members", False)
            self.moderation = kwargs.get("moderation", True)
            self.emojis_and_stickers = kwargs.get("emojis_and_stickers", True)
            self.integrations = kwargs.get("integrations", False)
            self.webhooks = kwargs.get("webhooks", False)
            self.invites = kwargs.get("invites", True)
            self.voice_states = kwargs.get("voice_states", True)
            self.presences = kwargs.get("presences", False)
            self.messages = kwargs.get("messages", True)
            self.guild_messages = kwargs.get("guild_messages", True)
            self.dm_messages = kwargs.get("dm_messages", True)
            self.reactions = kwargs.get("reactions", True)
            self.guild_reactions = kwargs.get("guild_reactions", True)
            self.dm_reactions = kwargs.get("dm_reactions", True)
            self.typing = kwargs.get("typing", False)
            self.message_content = kwargs.get("message_content", False)

        @classmethod
        def default(cls) -> "Intents":
            return cls(
                guilds=True,
                moderation=True,
                emojis_and_stickers=True,
                invites=True,
                voice_states=True,
                messages=True,
                guild_messages=True,
                dm_messages=True,
                reactions=True,
                guild_reactions=True,
                dm_reactions=True,
                message_content=False,
                members=False,
                presences=False,
            )

        @classmethod
        def all(cls) -> "Intents":
            return cls(
                guilds=True,
                members=True,
                moderation=True,
                emojis_and_stickers=True,
                integrations=True,
                webhooks=True,
                invites=True,
                voice_states=True,
                presences=True,
                messages=True,
                guild_messages=True,
                dm_messages=True,
                reactions=True,
                guild_reactions=True,
                dm_reactions=True,
                typing=True,
                message_content=True,
            )

    class Permissions:
        def __init__(self, **kwargs: bool) -> None:
            self._perms: Dict[str, bool] = {
                "administrator": False,
                "manage_guild": False,
                "manage_roles": False,
                "manage_channels": False,
                "manage_messages": False,
                "kick_members": False,
                "ban_members": False,
                "moderate_members": False,
                "send_messages": True,
                "embed_links": True,
                "attach_files": True,
                "read_message_history": True,
                "view_channel": True,
                "connect": True,
                "speak": True,
                "move_members": False,
                "mention_everyone": False,
            }
            self._perms.update(kwargs)

        def __getattr__(self, name: str) -> bool:
            if "_perms" in self.__dict__ and name in self._perms:
                return bool(self._perms[name])
            if name.startswith("_"):
                raise AttributeError(name)
            return False

        def update(self, **kwargs: bool) -> None:
            self._perms.update(kwargs)

        @classmethod
        def all(cls) -> "Permissions":
            p = cls(administrator=True)
            for k in list(p._perms.keys()):
                p._perms[k] = True
            return p

        @classmethod
        def none(cls) -> "Permissions":
            p = cls()
            for k in list(p._perms.keys()):
                p._perms[k] = False
            return p

    class PermissionOverwrite:
        def __init__(self, **kwargs: Optional[bool]) -> None:
            self._values: Dict[str, Optional[bool]] = dict(kwargs)

        def __getattr__(self, name: str) -> Optional[bool]:
            if "_values" in self.__dict__:
                return self._values.get(name)
            raise AttributeError(name)

        def __setattr__(self, name: str, value: Any) -> None:
            if name == "_values":
                super().__setattr__(name, value)
            else:
                self._values[name] = value

        def pair(self) -> Tuple[Permissions, Permissions]:
            return Permissions(), Permissions()

    class Object:
        def __init__(self, id: int) -> None:
            self.id = int(id)

    class Asset:
        def __init__(self, url: str = "https://cdn.discordapp.com/embed/avatars/0.png") -> None:
            self.url = url

        def __str__(self) -> str:
            return self.url

    class File:
        def __init__(self, fp: Any, filename: Optional[str] = None, spoiler: bool = False) -> None:
            self.fp = fp
            self.filename = filename or "file.txt"
            self.spoiler = spoiler

    class _EmbedField:
        def __init__(self, name: str, value: str, inline: bool = True) -> None:
            self.name = str(name)
            self.value = str(value)
            self.inline = bool(inline)

    class _EmbedProxy:
        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

        def __bool__(self) -> bool:
            return any(v is not None for v in self.__dict__.values())

    class Embed:
        def __init__(
            self,
            *,
            title: Optional[str] = None,
            description: Optional[str] = None,
            color: Optional[Union[Color, int]] = None,
            colour: Optional[Union[Color, int]] = None,
            url: Optional[str] = None,
            timestamp: Optional[datetime] = None,
        ) -> None:
            self.title = title
            self.description = description
            c = color if color is not None else colour
            if isinstance(c, int):
                c = Color(c)
            self.color = c or Color.blurple()
            self.colour = self.color
            self.url = url
            self.timestamp = timestamp
            self._fields: List[_EmbedField] = []
            self._footer = _EmbedProxy(text=None, icon_url=None)
            self._author = _EmbedProxy(name=None, url=None, icon_url=None)
            self._thumbnail = _EmbedProxy(url=None)
            self._image = _EmbedProxy(url=None)

        @property
        def fields(self) -> List[_EmbedField]:
            return list(self._fields)

        @property
        def footer(self) -> _EmbedProxy:
            return self._footer

        @property
        def author(self) -> _EmbedProxy:
            return self._author

        @property
        def thumbnail(self) -> _EmbedProxy:
            return self._thumbnail

        @property
        def image(self) -> _EmbedProxy:
            return self._image

        def add_field(self, *, name: str, value: str, inline: bool = True) -> "Embed":
            self._fields.append(_EmbedField(name=name, value=value, inline=inline))
            return self

        def clear_fields(self) -> None:
            self._fields.clear()

        def remove_field(self, index: int) -> None:
            if 0 <= index < len(self._fields):
                self._fields.pop(index)

        def set_footer(self, *, text: Optional[str] = None, icon_url: Optional[str] = None) -> "Embed":
            self._footer = _EmbedProxy(text=text, icon_url=icon_url)
            return self

        def set_author(
            self,
            *,
            name: str,
            url: Optional[str] = None,
            icon_url: Optional[str] = None,
        ) -> "Embed":
            self._author = _EmbedProxy(name=name, url=url, icon_url=icon_url)
            return self

        def set_thumbnail(self, *, url: Optional[str]) -> "Embed":
            self._thumbnail = _EmbedProxy(url=url)
            return self

        def set_image(self, *, url: Optional[str]) -> "Embed":
            self._image = _EmbedProxy(url=url)
            return self

        def to_dict(self) -> Dict[str, Any]:
            data: Dict[str, Any] = {
                "title": self.title,
                "description": self.description,
                "color": int(self.color) if self.color else 0,
                "fields": [
                    {"name": f.name, "value": f.value, "inline": f.inline}
                    for f in self._fields
                ],
            }
            if self._footer.text:
                data["footer"] = {"text": self._footer.text, "icon_url": self._footer.icon_url}
            if self._author.name:
                data["author"] = {
                    "name": self._author.name,
                    "url": self._author.url,
                    "icon_url": self._author.icon_url,
                }
            if self._thumbnail.url:
                data["thumbnail"] = {"url": self._thumbnail.url}
            if self._image.url:
                data["image"] = {"url": self._image.url}
            if self.timestamp:
                data["timestamp"] = self.timestamp.isoformat()
            return data

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "Embed":
            emb = cls(
                title=data.get("title"),
                description=data.get("description"),
                color=data.get("color", 0x5865F2),
            )
            if "footer" in data and data["footer"]:
                emb.set_footer(
                    text=data["footer"].get("text"),
                    icon_url=data["footer"].get("icon_url"),
                )
            if "author" in data and data["author"]:
                emb.set_author(
                    name=data["author"].get("name", ""),
                    url=data["author"].get("url"),
                    icon_url=data["author"].get("icon_url"),
                )
            if "thumbnail" in data and data["thumbnail"]:
                emb.set_thumbnail(url=data["thumbnail"].get("url"))
            if "image" in data and data["image"]:
                emb.set_image(url=data["image"].get("url"))
            for f in data.get("fields", []):
                emb.add_field(
                    name=f.get("name", "\u200b"),
                    value=f.get("value", "\u200b"),
                    inline=bool(f.get("inline", True)),
                )
            return emb

    # --- Activities ---
    class BaseActivity:
        def __init__(self, name: str = "", type: ActivityType = ActivityType.playing) -> None:
            self.name = name
            self.type = type

    class Activity(BaseActivity):
        pass

    class Game(BaseActivity):
        def __init__(self, name: str) -> None:
            super().__init__(name=name, type=ActivityType.playing)

    class Streaming(BaseActivity):
        def __init__(self, *, name: str, url: str) -> None:
            super().__init__(name=name, type=ActivityType.streaming)
            self.url = url

    class Spotify(BaseActivity):
        def __init__(self, *, title: str = "Track", artist: str = "Artist") -> None:
            super().__init__(name="Spotify", type=ActivityType.listening)
            self.title = title
            self.artist = artist

    class CustomActivity(BaseActivity):
        def __init__(self, name: Optional[str] = None) -> None:
            super().__init__(name=name or "", type=ActivityType.custom)

    # --- Entities (Role, User, Member, Channel, Guild, Message, Voice) ---
    class Role:
        def __init__(
            self,
            *,
            id: int,
            name: str,
            position: int = 1,
            permissions: Optional[Permissions] = None,
            color: Optional[Color] = None,
            guild: Any = None,
            hoist: bool = False,
            mentionable: bool = True,
            is_default: bool = False,
        ) -> None:
            self.id = int(id)
            self.name = name
            self.position = int(position)
            self.permissions = permissions or Permissions()
            self.color = color or Color.blurple()
            self.colour = self.color
            self.guild = guild
            self.hoist = hoist
            self.mentionable = mentionable
            self._is_default = is_default
            self.created_at = datetime.now(timezone.utc)
            self.members: List[Any] = []

        @property
        def mention(self) -> str:
            return f"<@&{self.id}>"

        def is_default(self) -> bool:
            return self._is_default

        def __lt__(self, other: "Role") -> bool:
            return (self.position, self.id) < (other.position, other.id)

        def __le__(self, other: "Role") -> bool:
            return (self.position, self.id) <= (other.position, other.id)

        def __gt__(self, other: "Role") -> bool:
            return (self.position, self.id) > (other.position, other.id)

        def __ge__(self, other: "Role") -> bool:
            return (self.position, self.id) >= (other.position, other.id)

        def __eq__(self, other: Any) -> bool:
            return isinstance(other, Role) and self.id == other.id

        def __hash__(self) -> int:
            return hash(self.id)

    class User:
        def __init__(
            self,
            *,
            id: int,
            name: str = "User",
            discriminator: str = "0",
            bot: bool = False,
        ) -> None:
            self.id = int(id)
            self.name = name
            self.discriminator = discriminator
            self.bot = bot
            self.display_name = name
            self.display_avatar = Asset(f"https://cdn.discordapp.com/avatars/{id}/avatar.png")
            self.avatar = self.display_avatar
            self.created_at = datetime.now(timezone.utc) - timedelta(days=365)
            self.dm_messages: List[Any] = []
            self.dm_disabled: bool = False

        @property
        def mention(self) -> str:
            return f"<@{self.id}>"

        def __str__(self) -> str:
            return self.name

        async def send(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            **kwargs: Any,
        ) -> "Message":
            if self.dm_disabled:
                raise Forbidden("Cannot send messages to this user")
            msg = Message(
                id=len(self.dm_messages) + 90000,
                content=content or "",
                author=self,
                channel=None,
                guild=None,
                embed=embed,
                embeds=embeds or ([embed] if embed else []),
                view=view,
                file=file,
            )
            self.dm_messages.append(msg)
            return msg

    class VoiceState:
        def __init__(self, channel: Any = None) -> None:
            self.channel = channel

    class Member(User):
        def __init__(
            self,
            *,
            id: int,
            name: str = "Member",
            guild: Any = None,
            roles: Optional[List[Role]] = None,
            guild_permissions: Optional[Permissions] = None,
            bot: bool = False,
            activities: Optional[Tuple[BaseActivity, ...]] = None,
            voice: Optional[VoiceState] = None,
        ) -> None:
            super().__init__(id=id, name=name, bot=bot)
            self.guild = guild
            self.roles: List[Role] = list(roles or [])
            self._guild_permissions = guild_permissions
            self.joined_at = datetime.now(timezone.utc) - timedelta(days=30)
            self.timed_out_until: Optional[datetime] = None
            self.activities: Tuple[BaseActivity, ...] = activities or ()
            self.voice: Optional[VoiceState] = voice
            self.status = Status.online

        @property
        def top_role(self) -> Role:
            if not self.roles:
                if self.guild and self.guild.default_role:
                    return self.guild.default_role
                return Role(id=0, name="@everyone", position=0, is_default=True)
            return max(self.roles, key=lambda r: r.position)

        @property
        def guild_permissions(self) -> Permissions:
            if self.guild and self.guild.owner_id == self.id:
                return Permissions.all()
            if self._guild_permissions is not None:
                return self._guild_permissions
            perms = Permissions()
            for r in self.roles:
                if r.permissions.administrator:
                    return Permissions.all()
                for k, v in r.permissions._perms.items():
                    if v:
                        perms._perms[k] = True
            return perms

        async def add_roles(self, *roles: Role, reason: Optional[str] = None) -> None:
            for r in roles:
                if r not in self.roles:
                    self.roles.append(r)
                    if self not in r.members:
                        r.members.append(self)

        async def remove_roles(self, *roles: Role, reason: Optional[str] = None) -> None:
            for r in roles:
                if r in self.roles:
                    self.roles.remove(r)
                if self in r.members:
                    r.members.remove(self)

        async def kick(self, *, reason: Optional[str] = None) -> None:
            if self.guild:
                self.guild._kicked.append((self, reason))
                self.guild._members.pop(self.id, None)

        async def ban(self, *, reason: Optional[str] = None, delete_message_days: int = 0, delete_message_seconds: int = 0) -> None:
            if self.guild:
                self.guild._banned[self.id] = (self, reason)
                self.guild._members.pop(self.id, None)

        async def timeout(self, until: Optional[Union[datetime, timedelta]], *, reason: Optional[str] = None) -> None:
            if isinstance(until, timedelta):
                self.timed_out_until = datetime.now(timezone.utc) + until
            elif isinstance(until, datetime):
                self.timed_out_until = until
            else:
                self.timed_out_until = None

        async def move_to(self, channel: Any, *, reason: Optional[str] = None) -> None:
            if self.voice and self.voice.channel and self in self.voice.channel.members:
                self.voice.channel.members.remove(self)
            if channel is None:
                self.voice = None
            else:
                self.voice = VoiceState(channel=channel)
                if self not in channel.members:
                    channel.members.append(self)

    class Message:
        _next_id = 1000

        def __init__(
            self,
            *,
            id: Optional[int] = None,
            content: str = "",
            author: Any = None,
            channel: Any = None,
            guild: Any = None,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            mentions: Optional[List[Any]] = None,
        ) -> None:
            if id is None:
                Message._next_id += 1
                id = Message._next_id
            self.id = int(id)
            self.content = content
            self.author = author
            self.channel = channel
            self.guild = guild or (channel.guild if channel else None)
            self.embeds: List[Embed] = embeds if embeds is not None else ([embed] if embed else [])
            self.view = view
            self.file = file
            self.mentions: List[Any] = mentions or []
            self.created_at = datetime.now(timezone.utc)
            self.reactions: List[str] = []
            self.deleted = False

        @property
        def jump_url(self) -> str:
            gid = self.guild.id if self.guild else "@me"
            cid = self.channel.id if self.channel else 0
            return f"https://discord.com/channels/{gid}/{cid}/{self.id}"

        async def edit(
            self,
            *,
            content: Optional[str] = None,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            **kwargs: Any,
        ) -> "Message":
            if content is not None:
                self.content = content
            if embed is not None:
                self.embeds = [embed]
            if embeds is not None:
                self.embeds = embeds
            if view is not None:
                self.view = view
            return self

        async def delete(self, *, delay: Optional[float] = None) -> None:
            self.deleted = True
            if self.channel and hasattr(self.channel, "messages"):
                if self in self.channel.messages:
                    self.channel.messages.remove(self)

        async def add_reaction(self, emoji: str) -> None:
            self.reactions.append(str(emoji))

        async def reply(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            mention_author: bool = False,
            ephemeral: bool = False,
            **kwargs: Any,
        ) -> "Message":
            if self.channel:
                return await self.channel.send(
                    content, embed=embed, embeds=embeds, view=view, file=file
                )
            return Message(content=content or "", author=self.author, embed=embed, view=view)

    class CategoryChannel:
        def __init__(self, *, id: int, name: str, guild: Any = None, position: int = 0) -> None:
            self.id = int(id)
            self.name = name
            self.guild = guild
            self.position = position
            self.type = ChannelType.category
            self.overwrites: Dict[Any, PermissionOverwrite] = {}
            self.created_at = datetime.now(timezone.utc)

        @property
        def mention(self) -> str:
            return f"<#{self.id}>"

        @property
        def channels(self) -> List[Any]:
            if not self.guild:
                return []
            return [c for c in self.guild.channels if getattr(c, "category", None) == self]

    class TextChannel:
        def __init__(
            self,
            *,
            id: int,
            name: str,
            guild: Any = None,
            category: Optional[CategoryChannel] = None,
            topic: Optional[str] = None,
            overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
            slowmode_delay: int = 0,
        ) -> None:
            self.id = int(id)
            self.name = name
            self.guild = guild
            self.category = category
            self.topic = topic
            self.overwrites: Dict[Any, PermissionOverwrite] = dict(overwrites or {})
            self.slowmode_delay = slowmode_delay
            self.type = ChannelType.text
            self.messages: List[Message] = []
            self.created_at = datetime.now(timezone.utc)
            self.nsfw = False

        @property
        def mention(self) -> str:
            return f"<#{self.id}>"

        def permissions_for(self, obj: Any) -> Permissions:
            if hasattr(obj, "guild_permissions"):
                return obj.guild_permissions
            return Permissions.all()

        def overwrites_for(self, obj: Any) -> PermissionOverwrite:
            return self.overwrites.get(obj, PermissionOverwrite())

        async def set_permissions(
            self,
            target: Any,
            *,
            overwrite: Optional[PermissionOverwrite] = None,
            reason: Optional[str] = None,
            **kwargs: Optional[bool],
        ) -> None:
            if overwrite is None and not kwargs:
                self.overwrites.pop(target, None)
            elif overwrite is not None:
                self.overwrites[target] = overwrite
            else:
                current = self.overwrites.get(target, PermissionOverwrite())
                for k, v in kwargs.items():
                    setattr(current, k, v)
                self.overwrites[target] = current

        async def edit(
            self,
            *,
            name: Optional[str] = None,
            topic: Optional[str] = None,
            slowmode_delay: Optional[int] = None,
            overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
            reason: Optional[str] = None,
            **kwargs: Any,
        ) -> "TextChannel":
            if name is not None:
                self.name = name
            if topic is not None:
                self.topic = topic
            if slowmode_delay is not None:
                self.slowmode_delay = slowmode_delay
            if overwrites is not None:
                self.overwrites = dict(overwrites)
            return self

        async def delete(self, *, reason: Optional[str] = None) -> None:
            if self.guild:
                self.guild._channels.pop(self.id, None)

        async def purge(
            self,
            *,
            limit: Optional[int] = 100,
            check: Optional[Callable[[Message], bool]] = None,
            reason: Optional[str] = None,
        ) -> List[Message]:
            to_delete: List[Message] = []
            for m in reversed(list(self.messages)):
                if limit is not None and len(to_delete) >= limit:
                    break
                if check is None or check(m):
                    to_delete.append(m)
            for m in to_delete:
                if m in self.messages:
                    self.messages.remove(m)
            return to_delete

        async def history(self, *, limit: Optional[int] = 100):
            items = list(self.messages)
            if limit is not None:
                items = items[-limit:]
            for m in items:
                yield m

        async def fetch_message(self, message_id: int) -> Message:
            for m in self.messages:
                if m.id == message_id:
                    return m
            raise NotFound(f"Message {message_id} not found")

        async def send(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            **kwargs: Any,
        ) -> Message:
            msg = Message(
                content=content or "",
                author=self.guild.me if self.guild else None,
                channel=self,
                guild=self.guild,
                embed=embed,
                embeds=embeds,
                view=view,
                file=file,
            )
            self.messages.append(msg)
            return msg

    class VoiceClient:
        def __init__(self, channel: "VoiceChannel") -> None:
            self.channel = channel
            self.guild = channel.guild
            self._connected = True
            self._playing = False
            self._paused = False
            self.source: Any = None

        def is_connected(self) -> bool:
            return self._connected

        def is_playing(self) -> bool:
            return self._playing

        def is_paused(self) -> bool:
            return self._paused

        def play(self, source: Any, *, after: Optional[Callable[[Optional[Exception]], Any]] = None) -> None:
            self.source = source
            self._playing = True
            self._paused = False

        def pause(self) -> None:
            if self._playing:
                self._playing = False
                self._paused = True

        def resume(self) -> None:
            if self._paused:
                self._paused = False
                self._playing = True

        def stop(self) -> None:
            self._playing = False
            self._paused = False

        async def move_to(self, channel: "VoiceChannel") -> None:
            self.channel = channel

        async def disconnect(self, *, force: bool = False) -> None:
            self._connected = False
            self._playing = False
            if self.guild:
                self.guild.voice_client = None

    class VoiceChannel:
        def __init__(
            self,
            *,
            id: int,
            name: str,
            guild: Any = None,
            category: Optional[CategoryChannel] = None,
            user_limit: int = 0,
            overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
        ) -> None:
            self.id = int(id)
            self.name = name
            self.guild = guild
            self.category = category
            self.user_limit = user_limit
            self.overwrites: Dict[Any, PermissionOverwrite] = dict(overwrites or {})
            self.type = ChannelType.voice
            self.members: List[Member] = []
            self.messages: List[Message] = []
            self.created_at = datetime.now(timezone.utc)

        @property
        def mention(self) -> str:
            return f"<#{self.id}>"

        def permissions_for(self, obj: Any) -> Permissions:
            if hasattr(obj, "guild_permissions"):
                return obj.guild_permissions
            return Permissions.all()

        def overwrites_for(self, obj: Any) -> PermissionOverwrite:
            return self.overwrites.get(obj, PermissionOverwrite())

        async def set_permissions(
            self,
            target: Any,
            *,
            overwrite: Optional[PermissionOverwrite] = None,
            reason: Optional[str] = None,
            **kwargs: Optional[bool],
        ) -> None:
            if overwrite is None and not kwargs:
                self.overwrites.pop(target, None)
            elif overwrite is not None:
                self.overwrites[target] = overwrite
            else:
                current = self.overwrites.get(target, PermissionOverwrite())
                for k, v in kwargs.items():
                    setattr(current, k, v)
                self.overwrites[target] = current

        async def edit(
            self,
            *,
            name: Optional[str] = None,
            user_limit: Optional[int] = None,
            overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
            reason: Optional[str] = None,
            **kwargs: Any,
        ) -> "VoiceChannel":
            if name is not None:
                self.name = name
            if user_limit is not None:
                self.user_limit = user_limit
            if overwrites is not None:
                self.overwrites = dict(overwrites)
            return self

        async def delete(self, *, reason: Optional[str] = None) -> None:
            if self.guild:
                self.guild._channels.pop(self.id, None)

        async def connect(self, **kwargs: Any) -> VoiceClient:
            vc = VoiceClient(self)
            if self.guild:
                self.guild.voice_client = vc
            return vc

        async def send(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            **kwargs: Any,
        ) -> Message:
            msg = Message(
                content=content or "",
                author=self.guild.me if self.guild else None,
                channel=self,
                guild=self.guild,
                embed=embed,
                embeds=embeds,
                view=view,
                file=file,
            )
            self.messages.append(msg)
            return msg

    class Guild:
        _next_channel_id = 50000

        def __init__(
            self,
            *,
            id: int,
            name: str = "Test Server",
            owner_id: int = 1,
        ) -> None:
            self.id = int(id)
            self.name = name
            self.owner_id = int(owner_id)
            self.created_at = datetime.now(timezone.utc) - timedelta(days=180)
            self.icon = Asset(f"https://cdn.discordapp.com/icons/{id}/icon.png")
            self.default_role = Role(
                id=self.id,
                name="@everyone",
                position=0,
                guild=self,
                is_default=True,
            )
            self._roles: Dict[int, Role] = {self.default_role.id: self.default_role}
            self._members: Dict[int, Member] = {}
            self._channels: Dict[int, Any] = {}
            self._banned: Dict[int, Tuple[User, Optional[str]]] = {}
            self._kicked: List[Tuple[Member, Optional[str]]] = []
            self.voice_client: Optional[VoiceClient] = None
            self.verification_level = "medium"
            self.premium_tier = 0
            self.premium_subscription_count = 0

        @property
        def owner(self) -> Optional[Member]:
            return self._members.get(self.owner_id)

        @property
        def me(self) -> Member:
            for m in self._members.values():
                if m.bot:
                    return m
            top_role = Role(
                id=self.id + 999,
                name="Cosmic ki baddie V2",
                position=100,
                permissions=Permissions.all(),
                guild=self,
            )
            bot_member = Member(
                id=999999,
                name="Cosmic ki baddie V2",
                guild=self,
                roles=[self.default_role, top_role],
                guild_permissions=Permissions.all(),
                bot=True,
            )
            self._members[bot_member.id] = bot_member
            return bot_member

        @property
        def roles(self) -> List[Role]:
            return sorted(self._roles.values(), key=lambda r: r.position)

        @property
        def members(self) -> List[Member]:
            return list(self._members.values())

        @property
        def member_count(self) -> int:
            return len(self._members)

        @property
        def channels(self) -> List[Any]:
            return list(self._channels.values())

        @property
        def text_channels(self) -> List[TextChannel]:
            return [c for c in self._channels.values() if isinstance(c, TextChannel)]

        @property
        def voice_channels(self) -> List[VoiceChannel]:
            return [c for c in self._channels.values() if isinstance(c, VoiceChannel)]

        @property
        def categories(self) -> List[CategoryChannel]:
            return [c for c in self._channels.values() if isinstance(c, CategoryChannel)]

        def get_role(self, role_id: int) -> Optional[Role]:
            return self._roles.get(int(role_id))

        def get_member(self, user_id: int) -> Optional[Member]:
            return self._members.get(int(user_id))

        def get_channel(self, channel_id: int) -> Optional[Any]:
            return self._channels.get(int(channel_id))

        def add_role(self, role: Role) -> Role:
            role.guild = self
            self._roles[role.id] = role
            return role

        def add_member(self, member: Member) -> Member:
            member.guild = self
            if self.default_role not in member.roles:
                member.roles.insert(0, self.default_role)
            self._members[member.id] = member
            return member

        def add_channel(self, channel: Any) -> Any:
            channel.guild = self
            self._channels[channel.id] = channel
            return channel

        async def create_text_channel(
            self,
            name: str,
            *,
            category: Optional[CategoryChannel] = None,
            overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
            topic: Optional[str] = None,
            reason: Optional[str] = None,
        ) -> TextChannel:
            Guild._next_channel_id += 1
            ch = TextChannel(
                id=Guild._next_channel_id,
                name=name,
                guild=self,
                category=category,
                overwrites=overwrites,
                topic=topic,
            )
            self._channels[ch.id] = ch
            return ch

        async def create_voice_channel(
            self,
            name: str,
            *,
            category: Optional[CategoryChannel] = None,
            user_limit: int = 0,
            overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
            reason: Optional[str] = None,
        ) -> VoiceChannel:
            Guild._next_channel_id += 1
            ch = VoiceChannel(
                id=Guild._next_channel_id,
                name=name,
                guild=self,
                category=category,
                user_limit=user_limit,
                overwrites=overwrites,
            )
            self._channels[ch.id] = ch
            return ch

        async def create_category(
            self,
            name: str,
            *,
            overwrites: Optional[Dict[Any, PermissionOverwrite]] = None,
            reason: Optional[str] = None,
        ) -> CategoryChannel:
            Guild._next_channel_id += 1
            cat = CategoryChannel(id=Guild._next_channel_id, name=name, guild=self)
            if overwrites:
                cat.overwrites = dict(overwrites)
            self._channels[cat.id] = cat
            return cat

        async def unban(self, user: Object, *, reason: Optional[str] = None) -> None:
            uid = int(user.id)
            if uid not in self._banned:
                raise NotFound("Ban entry not found")
            self._banned.pop(uid, None)

        async def invites(self) -> List[Any]:
            return []

    # --- Interactions & UI ---
    class InteractionResponse:
        def __init__(self, interaction: "Interaction") -> None:
            self._interaction = interaction
            self._done = False
            self.last_modal: Any = None

        def is_done(self) -> bool:
            return self._done

        async def defer(self, *, ephemeral: bool = False, thinking: bool = False) -> None:
            self._done = True

        async def send_message(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            ephemeral: bool = False,
            **kwargs: Any,
        ) -> Message:
            self._done = True
            msg = Message(
                content=content or "",
                author=self._interaction.guild.me if self._interaction.guild else None,
                channel=self._interaction.channel,
                guild=self._interaction.guild,
                embed=embed,
                embeds=embeds,
                view=view,
                file=file,
            )
            self._interaction.sent_messages.append(msg)
            if self._interaction.channel and hasattr(self._interaction.channel, "messages"):
                self._interaction.channel.messages.append(msg)
            return msg

        async def edit_message(
            self,
            *,
            content: Optional[str] = None,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            **kwargs: Any,
        ) -> Message:
            self._done = True
            target = self._interaction.message or (
                self._interaction.sent_messages[-1] if self._interaction.sent_messages else None
            )
            if target is not None:
                await target.edit(content=content, embed=embed, embeds=embeds, view=view)
                return target
            return await self.send_message(content, embed=embed, embeds=embeds, view=view)

        async def send_modal(self, modal: Any) -> None:
            self._done = True
            self.last_modal = modal

    class InteractionFollowup:
        def __init__(self, interaction: "Interaction") -> None:
            self._interaction = interaction

        async def send(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            ephemeral: bool = False,
            **kwargs: Any,
        ) -> Message:
            msg = Message(
                content=content or "",
                author=self._interaction.guild.me if self._interaction.guild else None,
                channel=self._interaction.channel,
                guild=self._interaction.guild,
                embed=embed,
                embeds=embeds,
                view=view,
                file=file,
            )
            self._interaction.sent_messages.append(msg)
            if self._interaction.channel and hasattr(self._interaction.channel, "messages"):
                self._interaction.channel.messages.append(msg)
            return msg

    class Interaction:
        def __init__(
            self,
            *,
            client: Any = None,
            guild: Optional[Guild] = None,
            channel: Any = None,
            user: Optional[Union[Member, User]] = None,
            message: Optional[Message] = None,
            data: Optional[Dict[str, Any]] = None,
            command: Any = None,
        ) -> None:
            self.client = client
            self.guild = guild
            self.guild_id = guild.id if guild else None
            self.channel = channel
            self.user = user
            self.message = message
            self.data = data or {}
            self.command = command
            self.sent_messages: List[Message] = []
            self.response = InteractionResponse(self)
            self.followup = InteractionFollowup(self)

        async def original_response(self) -> Message:
            if self.sent_messages:
                return self.sent_messages[0]
            raise NotFound("No original response")

    # --- UI Components ---
    class SelectOption:
        def __init__(
            self,
            *,
            label: str,
            value: Optional[str] = None,
            description: Optional[str] = None,
            emoji: Optional[str] = None,
            default: bool = False,
        ) -> None:
            self.label = label
            self.value = value if value is not None else label
            self.description = description
            self.emoji = emoji
            self.default = default

    class Item:
        def __init__(self) -> None:
            self.view: Any = None
            self.custom_id: Optional[str] = None
            self.row: Optional[int] = None
            self.disabled: bool = False

        async def callback(self, interaction: Interaction) -> Any:
            pass

    class Button(Item):
        def __init__(
            self,
            *,
            style: ButtonStyle = ButtonStyle.secondary,
            label: Optional[str] = None,
            disabled: bool = False,
            custom_id: Optional[str] = None,
            url: Optional[str] = None,
            emoji: Optional[str] = None,
            row: Optional[int] = None,
        ) -> None:
            super().__init__()
            self.style = style
            self.label = label
            self.disabled = disabled
            self.custom_id = custom_id
            self.url = url
            self.emoji = emoji
            self.row = row

    class Select(Item):
        def __init__(
            self,
            *,
            custom_id: Optional[str] = None,
            placeholder: Optional[str] = None,
            min_values: int = 1,
            max_values: int = 1,
            options: Optional[List[SelectOption]] = None,
            disabled: bool = False,
            row: Optional[int] = None,
        ) -> None:
            super().__init__()
            self.custom_id = custom_id
            self.placeholder = placeholder
            self.min_values = min_values
            self.max_values = max_values
            self.options: List[SelectOption] = list(options or [])
            self.disabled = disabled
            self.row = row
            self.values: List[str] = []

    class RoleSelect(Item):
        def __init__(
            self,
            *,
            custom_id: Optional[str] = None,
            placeholder: Optional[str] = None,
            min_values: int = 1,
            max_values: int = 1,
            disabled: bool = False,
            row: Optional[int] = None,
        ) -> None:
            super().__init__()
            self.custom_id = custom_id
            self.placeholder = placeholder
            self.min_values = min_values
            self.max_values = max_values
            self.disabled = disabled
            self.row = row
            self.values: List[Role] = []

    class ChannelSelect(Item):
        def __init__(
            self,
            *,
            custom_id: Optional[str] = None,
            placeholder: Optional[str] = None,
            min_values: int = 1,
            max_values: int = 1,
            channel_types: Optional[List[ChannelType]] = None,
            disabled: bool = False,
            row: Optional[int] = None,
        ) -> None:
            super().__init__()
            self.custom_id = custom_id
            self.placeholder = placeholder
            self.min_values = min_values
            self.max_values = max_values
            self.channel_types = channel_types or []
            self.disabled = disabled
            self.row = row
            self.values: List[Any] = []

    class UserSelect(Item):
        def __init__(
            self,
            *,
            custom_id: Optional[str] = None,
            placeholder: Optional[str] = None,
            min_values: int = 1,
            max_values: int = 1,
            disabled: bool = False,
            row: Optional[int] = None,
        ) -> None:
            super().__init__()
            self.custom_id = custom_id
            self.placeholder = placeholder
            self.min_values = min_values
            self.max_values = max_values
            self.disabled = disabled
            self.row = row
            self.values: List[Member] = []

    class TextInput(Item):
        def __init__(
            self,
            *,
            label: str,
            style: TextStyle = TextStyle.short,
            custom_id: Optional[str] = None,
            placeholder: Optional[str] = None,
            default: Optional[str] = None,
            required: bool = True,
            min_length: Optional[int] = None,
            max_length: Optional[int] = None,
            row: Optional[int] = None,
        ) -> None:
            super().__init__()
            self.label = label
            self.style = style
            self.custom_id = custom_id
            self.placeholder = placeholder
            self.default = default
            self.required = required
            self.min_length = min_length
            self.max_length = max_length
            self.row = row
            self.value: str = default or ""

        def __str__(self) -> str:
            return self.value

    def button(
        *,
        label: Optional[str] = None,
        custom_id: Optional[str] = None,
        disabled: bool = False,
        style: ButtonStyle = ButtonStyle.secondary,
        emoji: Optional[str] = None,
        row: Optional[int] = None,
    ):
        def decorator(func: Callable) -> Callable:
            func.__discord_ui_button__ = {
                "label": label,
                "custom_id": custom_id,
                "disabled": disabled,
                "style": style,
                "emoji": emoji,
                "row": row,
            }
            return func

        return decorator

    def select(
        *,
        cls: Type[Item] = Select,
        placeholder: Optional[str] = None,
        custom_id: Optional[str] = None,
        min_values: int = 1,
        max_values: int = 1,
        options: Optional[List[SelectOption]] = None,
        channel_types: Optional[List[ChannelType]] = None,
        disabled: bool = False,
        row: Optional[int] = None,
    ):
        def decorator(func: Callable) -> Callable:
            func.__discord_ui_select__ = {
                "cls": cls,
                "placeholder": placeholder,
                "custom_id": custom_id,
                "min_values": min_values,
                "max_values": max_values,
                "options": options or [],
                "channel_types": channel_types or [],
                "disabled": disabled,
                "row": row,
            }
            return func

        return decorator

    class View:
        def __init__(self, *, timeout: Optional[float] = 180.0) -> None:
            self.timeout = timeout
            self.children: List[Item] = []
            self._stopped = False

            for name, member in self.__class__.__dict__.items():
                if hasattr(member, "__discord_ui_button__"):
                    meta = member.__discord_ui_button__
                    btn = Button(**meta)
                    bound_method = getattr(self, name)

                    async def _btn_cb(interaction: Interaction, _bm=bound_method, _btn=btn):
                        return await _bm(interaction, _btn)

                    btn.callback = _btn_cb  # type: ignore
                    self.add_item(btn)
                elif hasattr(member, "__discord_ui_select__"):
                    meta = dict(member.__discord_ui_select__)
                    sel_cls = meta.pop("cls", Select)
                    if sel_cls is Select:
                        meta.pop("channel_types", None)
                    else:
                        meta.pop("options", None)
                        if sel_cls is not ChannelSelect:
                            meta.pop("channel_types", None)
                    sel = sel_cls(**meta)
                    bound_method = getattr(self, name)

                    async def _sel_cb(interaction: Interaction, _bm=bound_method, _sel=sel):
                        return await _bm(interaction, _sel)

                    sel.callback = _sel_cb  # type: ignore
                    self.add_item(sel)

        def add_item(self, item: Item) -> "View":
            item.view = self
            self.children.append(item)
            return self

        def remove_item(self, item: Item) -> "View":
            if item in self.children:
                self.children.remove(item)
                item.view = None
            return self

        def clear_items(self) -> "View":
            for item in self.children:
                item.view = None
            self.children.clear()
            return self

        def is_persistent(self) -> bool:
            return self.timeout is None and all(
                getattr(c, "custom_id", None) is not None or getattr(c, "url", None) is not None
                for c in self.children
            )

        def stop(self) -> None:
            self._stopped = True

        async def interaction_check(self, interaction: Interaction) -> bool:
            return True

        async def on_timeout(self) -> None:
            pass

    class Modal(View):
        def __init_subclass__(cls, *, title: str = "Modal", **kwargs: Any) -> None:
            super().__init_subclass__(**kwargs)
            cls.__modal_title__ = title

        def __init__(
            self,
            *,
            title: str = "Modal",
            timeout: Optional[float] = None,
            custom_id: Optional[str] = None,
        ) -> None:
            super().__init__(timeout=timeout)
            self.title = title
            self.custom_id = custom_id
            for name, val in self.__class__.__dict__.items():
                if isinstance(val, TextInput):
                    ti_copy = TextInput(
                        label=val.label,
                        style=val.style,
                        custom_id=val.custom_id,
                        placeholder=val.placeholder,
                        default=val.default,
                        required=val.required,
                        min_length=val.min_length,
                        max_length=val.max_length,
                        row=val.row,
                    )
                    setattr(self, name, ti_copy)
                    self.add_item(ti_copy)

        async def on_submit(self, interaction: Interaction) -> None:
            pass

    # --- Audio ---
    class AudioSource:
        def cleanup(self) -> None:
            pass

    class FFmpegPCMAudio(AudioSource):
        def __init__(
            self,
            source: str,
            *,
            executable: str = "ffmpeg",
            before_options: Optional[str] = None,
            options: Optional[str] = None,
        ) -> None:
            self.source = source
            self.executable = executable
            self.before_options = before_options
            self.options = options

    class PCMVolumeTransformer(AudioSource):
        def __init__(self, original: AudioSource, volume: float = 1.0) -> None:
            self.original = original
            self.volume = float(volume)

        def cleanup(self) -> None:
            self.original.cleanup()

    # --- discord.utils ---
    def get(iterable: Iterable[Any], **attrs: Any) -> Optional[Any]:
        for elem in iterable:
            if all(getattr(elem, k, None) == v for k, v in attrs.items()):
                return elem
        return None

    def find(predicate: Callable[[Any], bool], iterable: Iterable[Any]) -> Optional[Any]:
        for elem in iterable:
            if predicate(elem):
                return elem
        return None

    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def escape_markdown(text: str) -> str:
        return text

    def format_dt(dt: datetime, style: Optional[str] = None) -> str:
        ts = int(dt.timestamp())
        return f"<t:{ts}:{style}>" if style else f"<t:{ts}>"

    # --- app_commands ---
    class AppCommandError(DiscordException):
        pass

    class CheckFailure(AppCommandError):
        pass

    class CommandOnCooldown(AppCommandError):
        def __init__(self, cooldown: Any, retry_after: float) -> None:
            super().__init__(f"Command on cooldown. Retry after {retry_after:.1f}s")
            self.cooldown = cooldown
            self.retry_after = retry_after

    class Choice:
        def __init__(self, *, name: str, value: Any) -> None:
            self.name = name
            self.value = value

    class AppCommand:
        def __init__(
            self,
            *,
            name: str,
            description: str = "...",
            callback: Callable,
            parent: Optional[Any] = None,
        ) -> None:
            self.name = name
            self.description = description
            self.callback = callback
            self.parent = parent
            self.binding: Any = None
            self.checks: List[Callable] = list(getattr(callback, "__app_cmd_checks__", []))
            self._params = getattr(callback, "__app_cmd_describe__", {})

        @property
        def qualified_name(self) -> str:
            if self.parent:
                return f"{self.parent.qualified_name} {self.name}"
            return self.name

        async def _invoke(self, interaction: Interaction, **kwargs: Any) -> Any:
            for chk in self.checks:
                res = chk(interaction)
                if inspect.isawaitable(res):
                    res = await res
                if not res:
                    raise CheckFailure("App command check failed")
            if self.binding is not None:
                return await self.callback(self.binding, interaction, **kwargs)
            return await self.callback(interaction, **kwargs)

    class AppGroup:
        def __init__(self, *, name: str, description: str = "...") -> None:
            self.name = name
            self.description = description
            self.binding: Any = None
            self._commands: Dict[str, AppCommand] = {}

        @property
        def qualified_name(self) -> str:
            return self.name

        @property
        def commands(self) -> List[AppCommand]:
            return list(self._commands.values())

        def command(self, *, name: Optional[str] = None, description: str = "..."):
            def decorator(func: Callable) -> AppCommand:
                cmd = AppCommand(
                    name=name or func.__name__,
                    description=description,
                    callback=func,
                    parent=self,
                )
                self._commands[cmd.name] = cmd
                return cmd

            return decorator

    def app_command_decorator(*, name: Optional[str] = None, description: str = "..."):
        def decorator(func: Callable) -> AppCommand:
            if isinstance(func, AppCommand):
                if name:
                    func.name = name
                if description != "...":
                    func.description = description
                return func
            return AppCommand(
                name=name or func.__name__,
                description=description or (inspect.getdoc(func) or "...").splitlines()[0],
                callback=func,
            )

        return decorator

    def describe(**parameters: str):
        def decorator(func: Any) -> Any:
            target = func.callback if hasattr(func, "callback") else func
            existing = getattr(target, "__app_cmd_describe__", {})
            existing.update(parameters)
            setattr(target, "__app_cmd_describe__", existing)
            return func

        return decorator

    def choices(**parameters: List[Choice]):
        def decorator(func: Any) -> Any:
            target = func.callback if hasattr(func, "callback") else func
            existing = getattr(target, "__app_cmd_choices__", {})
            existing.update(parameters)
            setattr(target, "__app_cmd_choices__", existing)
            return func

        return decorator

    def app_check(predicate: Callable[[Interaction], Any]):
        def decorator(func: Any) -> Any:
            if hasattr(func, "checks"):
                func.checks.append(predicate)
            else:
                chks = getattr(func, "__app_cmd_checks__", [])
                chks.append(predicate)
                setattr(func, "__app_cmd_checks__", chks)
            return func

        return decorator

    class CommandTree:
        def __init__(self, client: Any) -> None:
            self.client = client
            self._global_commands: Dict[str, Union[AppCommand, AppGroup]] = {}
            self._guild_commands: Dict[int, Dict[str, Union[AppCommand, AppGroup]]] = {}
            self._error_handler: Optional[Callable] = None

        def add_command(
            self,
            command: Union[AppCommand, AppGroup],
            *,
            guild: Optional[Object] = None,
            override: bool = False,
        ) -> None:
            if guild is not None:
                bucket = self._guild_commands.setdefault(int(guild.id), {})
            else:
                bucket = self._global_commands
            if command.name in bucket and not override:
                raise DiscordException(f"Command {command.name!r} already registered")
            bucket[command.name] = command

        def remove_command(self, name: str, *, guild: Optional[Object] = None) -> Optional[Any]:
            if guild is not None:
                return self._guild_commands.get(int(guild.id), {}).pop(name, None)
            return self._global_commands.pop(name, None)

        def get_commands(self, *, guild: Optional[Object] = None) -> List[Union[AppCommand, AppGroup]]:
            if guild is not None:
                merged = dict(self._global_commands)
                merged.update(self._guild_commands.get(int(guild.id), {}))
                return list(merged.values())
            return list(self._global_commands.values())

        def get_command(self, name: str, *, guild: Optional[Object] = None) -> Optional[Union[AppCommand, AppGroup]]:
            if guild is not None and name in self._guild_commands.get(int(guild.id), {}):
                return self._guild_commands[int(guild.id)][name]
            return self._global_commands.get(name)

        def copy_global_to(self, *, guild: Object) -> None:
            self._guild_commands[int(guild.id)] = dict(self._global_commands)

        async def sync(self, *, guild: Optional[Object] = None) -> List[Union[AppCommand, AppGroup]]:
            return self.get_commands(guild=guild)

        def error(self, coro: Callable) -> Callable:
            self._error_handler = coro
            return coro

    # --- discord.ext.commands ---
    class CommandError(DiscordException):
        pass

    class CommandNotFound(CommandError):
        pass

    class MissingRequiredArgument(CommandError):
        def __init__(self, param: inspect.Parameter) -> None:
            super().__init__(f"{param.name} is a required argument that is missing.")
            self.param = param

    class BadArgument(CommandError):
        pass

    class CheckFailureError(CommandError):
        pass

    class MissingPermissions(CheckFailureError):
        def __init__(self, missing_permissions: List[str]) -> None:
            super().__init__(f"Missing permissions: {', '.join(missing_permissions)}")
            self.missing_permissions = missing_permissions

    class BotMissingPermissions(CheckFailureError):
        def __init__(self, missing_permissions: List[str]) -> None:
            super().__init__(f"Bot missing permissions: {', '.join(missing_permissions)}")
            self.missing_permissions = missing_permissions

    class NoPrivateMessage(CheckFailureError):
        pass

    class NotOwner(CheckFailureError):
        pass

    class CommandOnCooldownError(CommandError):
        def __init__(self, cooldown: Any, retry_after: float, type: Any = None) -> None:
            super().__init__(f"You are on cooldown. Try again in {retry_after:.1f}s")
            self.cooldown = cooldown
            self.retry_after = retry_after
            self.type = type

    class ExtensionError(DiscordException):
        pass

    class ExtensionAlreadyLoaded(ExtensionError):
        pass

    class ExtensionNotLoaded(ExtensionError):
        pass

    class BucketType(Enum):
        default = 0
        user = 1
        guild = 2
        channel = 3
        member = 4
        category = 5
        role = 6

    class Cooldown:
        def __init__(self, rate: int, per: float) -> None:
            self.rate = int(rate)
            self.per = float(per)

    class Context:
        def __init__(
            self,
            *,
            bot: "Bot",
            message: Message,
            prefix: str = "!",
            command: Optional["Command"] = None,
            invoked_with: Optional[str] = None,
            interaction: Optional[Interaction] = None,
        ) -> None:
            self.bot = bot
            self.message = message
            self.prefix = prefix
            self.command = command
            self.invoked_with = invoked_with
            self.interaction = interaction
            self.author = interaction.user if interaction else message.author
            self.guild = interaction.guild if interaction else message.guild
            self.channel = interaction.channel if interaction else message.channel
            self.me = self.guild.me if self.guild else bot.user
            self.command_failed = False

        @property
        def cog(self) -> Any:
            return self.command.cog if self.command else None

        @property
        def valid(self) -> bool:
            return self.command is not None

        async def defer(self, *, ephemeral: bool = False) -> None:
            if self.interaction and not self.interaction.response.is_done():
                await self.interaction.response.defer(ephemeral=ephemeral)

        async def send(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            ephemeral: bool = False,
            **kwargs: Any,
        ) -> Message:
            if self.interaction:
                if not self.interaction.response.is_done():
                    return await self.interaction.response.send_message(
                        content,
                        embed=embed,
                        embeds=embeds,
                        view=view,
                        file=file,
                        ephemeral=ephemeral,
                    )
                return await self.interaction.followup.send(
                    content,
                    embed=embed,
                    embeds=embeds,
                    view=view,
                    file=file,
                    ephemeral=ephemeral,
                )
            if self.channel:
                return await self.channel.send(
                    content, embed=embed, embeds=embeds, view=view, file=file
                )
            return Message(content=content or "", author=self.author, embed=embed, view=view)

        async def reply(
            self,
            content: Optional[str] = None,
            *,
            embed: Optional[Embed] = None,
            embeds: Optional[List[Embed]] = None,
            view: Any = None,
            file: Optional[File] = None,
            ephemeral: bool = False,
            **kwargs: Any,
        ) -> Message:
            return await self.send(
                content, embed=embed, embeds=embeds, view=view, file=file, ephemeral=ephemeral
            )

    def _convert_arg(raw: Any, annotation: Any, guild: Optional[Guild]) -> Any:
        if not isinstance(raw, str):
            return raw
        if isinstance(annotation, str):
            ann_s = annotation.replace("Optional[", "").rstrip("]").strip()
            mapping = {
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "discord.Member": Member,
                "Member": Member,
                "discord.User": User,
                "User": User,
                "discord.Object": Object,
                "Object": Object,
                "discord.Role": Role,
                "Role": Role,
                "discord.TextChannel": TextChannel,
                "TextChannel": TextChannel,
                "discord.VoiceChannel": VoiceChannel,
                "VoiceChannel": VoiceChannel,
                "discord.CategoryChannel": CategoryChannel,
                "CategoryChannel": CategoryChannel,
            }
            annotation = mapping.get(ann_s, str)
        if annotation in (inspect.Parameter.empty, str, Any):
            return raw
        origin = getattr(annotation, "__origin__", None)
        if origin is Union:
            args = [a for a in annotation.__args__ if a is not type(None)]
            for sub in args:
                try:
                    return _convert_arg(raw, sub, guild)
                except Exception:
                    continue
            return raw
        if annotation is int:
            clean = raw.strip("<@!&#>")
            return int(clean)
        if annotation is float:
            return float(raw)
        if annotation is bool:
            return raw.lower() in ("1", "true", "yes", "on", "enable", "enabled")
        if annotation in (Member, User, Object) and guild is not None:
            clean = raw.strip("<@!>")
            if clean.isdigit():
                uid = int(clean)
                if annotation is Object:
                    return Object(uid)
                m = guild.get_member(uid)
                if m:
                    return m
                if annotation is User:
                    return User(id=uid, name=f"User-{uid}")
            for m in guild.members:
                if m.name.lower() == raw.lower():
                    return m
            raise BadArgument(f"Member/User {raw!r} not found.")
        if annotation is Role and guild is not None:
            clean = raw.strip("<@&>")
            if clean.isdigit():
                r = guild.get_role(int(clean))
                if r:
                    return r
            for r in guild.roles:
                if r.name.lower() == raw.lower():
                    return r
            raise BadArgument(f"Role {raw!r} not found.")
        if annotation in (TextChannel, VoiceChannel, CategoryChannel) and guild is not None:
            clean = raw.strip("<#>")
            if clean.isdigit():
                ch = guild.get_channel(int(clean))
                if ch:
                    return ch
            for ch in guild.channels:
                if ch.name.lower() == raw.lower():
                    return ch
            raise BadArgument(f"Channel {raw!r} not found.")
        return raw

    class Command:
        def __init__(
            self,
            func: Callable,
            *,
            name: Optional[str] = None,
            description: Optional[str] = None,
            help: Optional[str] = None,
            brief: Optional[str] = None,
            aliases: Optional[Sequence[str]] = None,
            hidden: bool = False,
            parent: Optional["Group"] = None,
            with_app_command: bool = False,
        ) -> None:
            self.callback = func
            self.name = name or func.__name__
            doc = inspect.getdoc(func) or ""
            self.description = description or (doc.splitlines()[0] if doc else "No description.")
            self.help = help or doc or self.description
            self.brief = brief or self.description
            self.aliases: List[str] = list(aliases or [])
            self.hidden = hidden
            self.parent = parent
            self.cog: Any = None
            self.checks: List[Callable] = list(getattr(func, "__commands_checks__", []))
            self._cooldown: Optional[Tuple[int, float, BucketType]] = getattr(
                func, "__commands_cooldown__", None
            )
            self._buckets: Dict[Any, List[float]] = {}
            self.with_app_command = with_app_command
            self.app_command: Optional[AppCommand] = None
            if with_app_command and parent is None:
                self.app_command = AppCommand(
                    name=self.name,
                    description=self.description[:100],
                    callback=self._app_bridge_callback,
                )

        @property
        def qualified_name(self) -> str:
            if self.parent:
                return f"{self.parent.qualified_name} {self.name}"
            return self.name

        @property
        def clean_params(self) -> Dict[str, inspect.Parameter]:
            sig = inspect.signature(self.callback)
            params = list(sig.parameters.values())
            # Strip self (if cog method) and ctx
            start = 2 if (self.cog is not None or (params and params[0].name == "self")) else 1
            return {p.name: p for p in params[start:]}

        @property
        def signature(self) -> str:
            parts = []
            for p in self.clean_params.values():
                if p.default is inspect.Parameter.empty:
                    parts.append(f"<{p.name}>")
                else:
                    parts.append(f"[{p.name}]")
            return " ".join(parts)

        async def _app_bridge_callback(self, interaction: Interaction, **kwargs: Any) -> Any:
            ctx = Context(
                bot=interaction.client,
                message=Message(
                    content=f"/{self.qualified_name}",
                    author=interaction.user,
                    channel=interaction.channel,
                    guild=interaction.guild,
                ),
                prefix="/",
                command=self,
                invoked_with=self.name,
                interaction=interaction,
            )
            return await self.invoke_with_kwargs(ctx, **kwargs)

        async def can_run(self, ctx: Context) -> bool:
            if not await ctx.bot._run_global_checks(ctx):
                return False
            if self.cog is not None and hasattr(self.cog, "cog_check"):
                res = self.cog.cog_check(ctx)
                if inspect.isawaitable(res):
                    res = await res
                if not res:
                    return False
            for chk in self.checks:
                res = chk(ctx)
                if inspect.isawaitable(res):
                    res = await res
                if not res:
                    return False
            return True

        def _check_cooldown(self, ctx: Context) -> None:
            if not self._cooldown:
                return
            rate, per, bucket_type = self._cooldown
            now = asyncio.get_event_loop().time() if asyncio._get_running_loop() else 0.0
            if bucket_type == BucketType.user:
                key = getattr(ctx.author, "id", 0)
            elif bucket_type == BucketType.guild:
                key = getattr(ctx.guild, "id", 0)
            else:
                key = (getattr(ctx.guild, "id", 0), getattr(ctx.author, "id", 0))
            history = [t for t in self._buckets.get(key, []) if now - t < per]
            if len(history) >= rate:
                retry_after = per - (now - history[0])
                raise CommandOnCooldownError(Cooldown(rate, per), max(0.1, retry_after), bucket_type)
            history.append(now)
            self._buckets[key] = history

        async def invoke_with_kwargs(self, ctx: Context, **kwargs: Any) -> Any:
            if not await self.can_run(ctx):
                raise CheckFailureError("You do not have permission to execute this command.")
            self._check_cooldown(ctx)
            converted: Dict[str, Any] = {}
            for pname, param in self.clean_params.items():
                if pname in kwargs:
                    converted[pname] = _convert_arg(kwargs[pname], param.annotation, ctx.guild)
                elif param.default is inspect.Parameter.empty:
                    raise MissingRequiredArgument(param)
            if self.cog is not None:
                return await self.callback(self.cog, ctx, **converted)
            return await self.callback(ctx, **converted)

        async def invoke_from_tokens(self, ctx: Context, tokens: List[str]) -> Any:
            if not await self.can_run(ctx):
                raise CheckFailureError("You do not have permission to execute this command.")
            self._check_cooldown(ctx)
            params = list(self.clean_params.values())
            args: List[Any] = []
            kwargs: Dict[str, Any] = {}
            idx = 0
            for i, p in enumerate(params):
                if p.kind == inspect.Parameter.KEYWORD_ONLY:
                    rest = " ".join(tokens[idx:]).strip()
                    if not rest:
                        if p.default is inspect.Parameter.empty:
                            raise MissingRequiredArgument(p)
                        kwargs[p.name] = p.default
                    else:
                        kwargs[p.name] = _convert_arg(rest, p.annotation, ctx.guild)
                    idx = len(tokens)
                    break
                elif p.kind == inspect.Parameter.VAR_POSITIONAL:
                    args.extend(_convert_arg(t, p.annotation, ctx.guild) for t in tokens[idx:])
                    idx = len(tokens)
                    break
                else:
                    if idx < len(tokens):
                        # If this is the last positional parameter and it's str, consume rest only if no more params
                        raw_val = tokens[idx]
                        idx += 1
                        args.append(_convert_arg(raw_val, p.annotation, ctx.guild))
                    else:
                        if p.default is inspect.Parameter.empty:
                            raise MissingRequiredArgument(p)
                        args.append(p.default)
            if self.cog is not None:
                return await self.callback(self.cog, ctx, *args, **kwargs)
            return await self.callback(ctx, *args, **kwargs)

    class Group(Command):
        def __init__(self, func: Callable, **kwargs: Any) -> None:
            self.fallback: Optional[str] = kwargs.pop("fallback", None)
            super().__init__(func, **kwargs)
            self._subcommands: Dict[str, Command] = {}
            self._subcommand_aliases: Dict[str, Command] = {}
            if self.with_app_command:
                self.app_group = AppGroup(name=self.name, description=self.description[:100])
            else:
                self.app_group = None

        @property
        def commands(self) -> List[Command]:
            return list(self._subcommands.values())

        def get_command(self, name: str) -> Optional[Command]:
            return self._subcommands.get(name) or self._subcommand_aliases.get(name)

        def command(self, *args: Any, **kwargs: Any):
            def decorator(func: Callable) -> Command:
                cmd = Command(
                    func,
                    parent=self,
                    with_app_command=self.with_app_command,
                    **kwargs,
                )
                self._subcommands[cmd.name] = cmd
                for alias in cmd.aliases:
                    self._subcommand_aliases[alias] = cmd
                if self.app_group is not None:
                    app_sub = AppCommand(
                        name=cmd.name,
                        description=cmd.description[:100],
                        callback=cmd._app_bridge_callback,
                        parent=self.app_group,
                    )
                    self.app_group._commands[app_sub.name] = app_sub
                return cmd

            return decorator

    class HybridCommand(Command):
        def __init__(self, func: Callable, **kwargs: Any) -> None:
            kwargs["with_app_command"] = True
            super().__init__(func, **kwargs)

    class HybridGroup(Group):
        def __init__(self, func: Callable, **kwargs: Any) -> None:
            kwargs["with_app_command"] = True
            super().__init__(func, **kwargs)

    def command(*, name: Optional[str] = None, aliases: Optional[Sequence[str]] = None, **kwargs: Any):
        def decorator(func: Callable) -> Command:
            return Command(func, name=name, aliases=aliases, **kwargs)

        return decorator

    def group(*, name: Optional[str] = None, aliases: Optional[Sequence[str]] = None, invoke_without_command: bool = True, **kwargs: Any):
        def decorator(func: Callable) -> Group:
            return Group(func, name=name, aliases=aliases, **kwargs)

        return decorator

    def hybrid_command(*, name: Optional[str] = None, aliases: Optional[Sequence[str]] = None, description: Optional[str] = None, **kwargs: Any):
        def decorator(func: Callable) -> HybridCommand:
            return HybridCommand(func, name=name, aliases=aliases, description=description, **kwargs)

        return decorator

    def hybrid_group(*, name: Optional[str] = None, aliases: Optional[Sequence[str]] = None, description: Optional[str] = None, fallback: Optional[str] = None, **kwargs: Any):
        def decorator(func: Callable) -> HybridGroup:
            return HybridGroup(func, name=name, aliases=aliases, description=description, fallback=fallback, **kwargs)

        return decorator

    def check(predicate: Callable[[Context], Any]):
        def decorator(func: Any) -> Any:
            if isinstance(func, Command):
                func.checks.append(predicate)
            else:
                chks = getattr(func, "__commands_checks__", [])
                chks.append(predicate)
                setattr(func, "__commands_checks__", chks)
            return func

        return decorator

    def has_permissions(**perms: bool):
        async def predicate(ctx: Context) -> bool:
            if ctx.guild is None:
                raise NoPrivateMessage("This command cannot be used in DMs.")
            gp = ctx.author.guild_permissions
            if gp.administrator:
                return True
            missing = [k for k, v in perms.items() if v and not getattr(gp, k, False)]
            if missing:
                raise MissingPermissions(missing)
            return True

        return check(predicate)

    def bot_has_permissions(**perms: bool):
        async def predicate(ctx: Context) -> bool:
            if ctx.guild is None:
                return True
            gp = ctx.guild.me.guild_permissions
            if gp.administrator:
                return True
            missing = [k for k, v in perms.items() if v and not getattr(gp, k, False)]
            if missing:
                raise BotMissingPermissions(missing)
            return True

        return check(predicate)

    def guild_only():
        async def predicate(ctx: Context) -> bool:
            if ctx.guild is None:
                raise NoPrivateMessage("This command can only be used in a server.")
            return True

        return check(predicate)

    def is_owner():
        async def predicate(ctx: Context) -> bool:
            if not await ctx.bot.is_owner(ctx.author):
                raise NotOwner("Only the bot owner can run this command.")
            return True

        return check(predicate)

    def cooldown(rate: int, per: float, type: BucketType = BucketType.default):
        def decorator(func: Any) -> Any:
            if isinstance(func, Command):
                func._cooldown = (rate, per, type)
            else:
                setattr(func, "__commands_cooldown__", (rate, per, type))
            return func

        return decorator

    def when_mentioned_or(*prefixes: str):
        def _getter(bot: Any, msg: Message) -> List[str]:
            uid = bot.user.id if bot.user else 999999
            return list(prefixes) + [f"<@{uid}> ", f"<@!{uid}> "]

        return _getter

    class CogMeta(type):
        def __new__(mcls, cls_name: str, bases: Tuple[type, ...], attrs: Dict[str, Any], **kwargs: Any):
            cls = super().__new__(mcls, cls_name, bases, attrs)
            cls.__cog_name__ = kwargs.get("name", cls_name)
            cls.__cog_description__ = inspect.getdoc(cls) or ""
            return cls

    class Cog(metaclass=CogMeta):
        @property
        def qualified_name(self) -> str:
            return getattr(self, "__cog_name__", self.__class__.__name__)

        @property
        def description(self) -> str:
            return getattr(self, "__cog_description__", "")

        def get_commands(self) -> List[Command]:
            cmds: List[Command] = []
            for _, val in inspect.getmembers(self):
                if isinstance(val, Command) and val.parent is None:
                    cmds.append(val)
            return cmds

        def get_app_commands(self) -> List[Union[AppCommand, AppGroup]]:
            acmds: List[Union[AppCommand, AppGroup]] = []
            for _, val in inspect.getmembers(self):
                if isinstance(val, (AppCommand, AppGroup)) and getattr(val, "parent", None) is None:
                    acmds.append(val)
            return acmds

        async def cog_load(self) -> None:
            pass

        async def cog_unload(self) -> None:
            pass

        @classmethod
        def listener(cls, name: Optional[str] = None):
            def decorator(func: Callable) -> Callable:
                setattr(func, "__cog_listener__", name or func.__name__)
                return func

            return decorator

    class Bot:
        def __init__(
            self,
            command_prefix: Any,
            *,
            help_command: Any = None,
            intents: Optional[Intents] = None,
            owner_id: Optional[int] = None,
            owner_ids: Optional[Iterable[int]] = None,
            **kwargs: Any,
        ) -> None:
            self.command_prefix = command_prefix
            self.help_command = help_command
            self.intents = intents or Intents.default()
            self.owner_id = owner_id
            self.owner_ids = set(owner_ids) if owner_ids else set()
            self.user = User(id=999999, name="Cosmic ki baddie V2", bot=True)
            self.latency: float = 0.042
            self.tree = CommandTree(self)
            self._cogs: Dict[str, Cog] = {}
            self._extensions: Dict[str, types.ModuleType] = {}
            self._commands: Dict[str, Command] = {}
            self._aliases: Dict[str, Command] = {}
            self._listeners: Dict[str, List[Callable]] = {}
            self._global_checks: List[Callable] = []
            self._persistent_views: List[View] = []
            self.guilds: List[Guild] = []
            self._closed = False

        @property
        def cogs(self) -> Dict[str, Cog]:
            return dict(self._cogs)

        @property
        def extensions(self) -> Dict[str, types.ModuleType]:
            return dict(self._extensions)

        @property
        def commands(self) -> Set[Command]:
            return set(self._commands.values())

        @property
        def persistent_views(self) -> List[View]:
            return list(self._persistent_views)

        def add_view(self, view: View, *, message_id: Optional[int] = None) -> None:
            if view not in self._persistent_views:
                self._persistent_views.append(view)

        def add_check(self, func: Callable) -> None:
            self._global_checks.append(func)

        async def _run_global_checks(self, ctx: Context) -> bool:
            for chk in self._global_checks:
                res = chk(ctx)
                if inspect.isawaitable(res):
                    res = await res
                if not res:
                    return False
            return True

        async def is_owner(self, user: Union[User, Member]) -> bool:
            if self.owner_id and user.id == self.owner_id:
                return True
            if self.owner_ids and user.id in self.owner_ids:
                return True
            return False

        def get_guild(self, guild_id: int) -> Optional[Guild]:
            for g in self.guilds:
                if g.id == int(guild_id):
                    return g
            return None

        def get_channel(self, channel_id: int) -> Optional[Any]:
            for g in self.guilds:
                ch = g.get_channel(int(channel_id))
                if ch:
                    return ch
            return None

        def get_user(self, user_id: int) -> Optional[User]:
            for g in self.guilds:
                m = g.get_member(int(user_id))
                if m:
                    return m
            return None

        def get_cog(self, name: str) -> Optional[Cog]:
            return self._cogs.get(name)

        def get_command(self, name: str) -> Optional[Command]:
            parts = name.strip().split()
            if not parts:
                return None
            cmd = self._commands.get(parts[0]) or self._aliases.get(parts[0])
            for sub in parts[1:]:
                if isinstance(cmd, Group):
                    cmd = cmd.get_command(sub)
                else:
                    return None
            return cmd

        def add_command(self, command: Command) -> None:
            if command.name in self._commands:
                raise CommandError(f"Command {command.name!r} is already registered.")
            self._commands[command.name] = command
            for alias in command.aliases:
                if alias in self._aliases or alias in self._commands:
                    raise CommandError(f"Alias {alias!r} is already registered.")
                self._aliases[alias] = command
            if isinstance(command, HybridGroup) and command.app_group is not None:
                self.tree.add_command(command.app_group, override=True)
            elif command.app_command is not None:
                self.tree.add_command(command.app_command, override=True)

        def remove_command(self, name: str) -> Optional[Command]:
            cmd = self._commands.pop(name, None)
            if cmd:
                for alias in cmd.aliases:
                    self._aliases.pop(alias, None)
                self.tree.remove_command(cmd.name)
            return cmd

        async def add_cog(self, cog: Cog, *, override: bool = False) -> None:
            cname = cog.qualified_name
            if cname in self._cogs and not override:
                raise CommandError(f"Cog {cname!r} is already loaded.")
            self._cogs[cname] = cog
            for attr_name in dir(cog):
                attr = getattr(cog, attr_name)
                if isinstance(attr, Command) and attr.parent is None:
                    attr.cog = cog
                    attr._buckets.clear()
                    if isinstance(attr, Group):
                        for sub in attr.commands:
                            sub.cog = cog
                    self.add_command(attr)
                elif isinstance(attr, (AppCommand, AppGroup)) and getattr(attr, "parent", None) is None:
                    attr.binding = cog
                    if isinstance(attr, AppGroup):
                        for sub in attr.commands:
                            sub.binding = cog
                    self.tree.add_command(attr, override=True)
                elif hasattr(attr, "__cog_listener__"):
                    ev_name = getattr(attr, "__cog_listener__")
                    self._listeners.setdefault(ev_name, []).append(attr)
            await cog.cog_load()

        async def remove_cog(self, name: str) -> Optional[Cog]:
            cog = self._cogs.pop(name, None)
            if cog:
                for cmd in list(self._commands.values()):
                    if cmd.cog is cog:
                        self.remove_command(cmd.name)
                for ev_list in self._listeners.values():
                    ev_list[:] = [f for f in ev_list if getattr(f, "__self__", None) is not cog]
                await cog.cog_unload()
            return cog

        async def load_extension(self, name: str) -> None:
            if name in self._extensions:
                raise ExtensionAlreadyLoaded(f"Extension {name!r} is already loaded.")
            import importlib

            mod = importlib.import_module(name)
            if not hasattr(mod, "setup"):
                raise ExtensionError(f"Extension {name!r} has no setup function.")
            await mod.setup(self)
            self._extensions[name] = mod

        async def unload_extension(self, name: str) -> None:
            if name not in self._extensions:
                raise ExtensionNotLoaded(f"Extension {name!r} is not loaded.")
            mod = self._extensions.pop(name)
            for cname, cog in list(self._cogs.items()):
                if cog.__class__.__module__ == mod.__name__:
                    await self.remove_cog(cname)

        async def reload_extension(self, name: str) -> None:
            await self.unload_extension(name)
            await self.load_extension(name)

        async def get_prefix(self, message: Message) -> List[str]:
            cp = self.command_prefix
            if callable(cp):
                res = cp(self, message)
                if inspect.isawaitable(res):
                    res = await res
            else:
                res = cp
            if isinstance(res, str):
                return [res]
            return list(res)

        async def get_context(self, message: Message, *, cls: Type[Context] = Context) -> Context:
            prefixes = await self.get_prefix(message)
            content = message.content or ""
            matched_prefix: Optional[str] = None
            for p in sorted(prefixes, key=len, reverse=True):
                if content.startswith(p):
                    matched_prefix = p
                    break
            if matched_prefix is None:
                return cls(bot=self, message=message, prefix=prefixes[0] if prefixes else "!")
            rest = content[len(matched_prefix) :].strip()
            if not rest:
                return cls(bot=self, message=message, prefix=matched_prefix)
            tokens = rest.split()
            invoked = tokens[0]
            cmd = self._commands.get(invoked) or self._aliases.get(invoked)
            ctx = cls(
                bot=self,
                message=message,
                prefix=matched_prefix,
                command=cmd,
                invoked_with=invoked,
            )
            ctx._tokens = tokens[1:]  # type: ignore
            ctx._raw_invoked = invoked  # type: ignore
            return ctx

        async def invoke(self, ctx: Context) -> None:
            raw_invoked = getattr(ctx, "_raw_invoked", None)
            if ctx.command is None:
                if raw_invoked:
                    await self.on_command_error(ctx, CommandNotFound(f"Command {raw_invoked!r} is not found"))
                return
            tokens: List[str] = list(getattr(ctx, "_tokens", []))
            target_cmd = ctx.command
            if isinstance(target_cmd, Group) and tokens:
                sub = target_cmd.get_command(tokens[0])
                if sub is not None:
                    target_cmd = sub
                    ctx.command = sub
                    tokens = tokens[1:]
                elif getattr(target_cmd, "fallback", None) == tokens[0]:
                    tokens = tokens[1:]
            try:
                await target_cmd.invoke_from_tokens(ctx, tokens)
            except CommandError as exc:
                ctx.command_failed = True
                await self.on_command_error(ctx, exc)
            except Exception as exc:
                ctx.command_failed = True
                await self.on_command_error(ctx, CommandError(str(exc)))

        async def process_commands(self, message: Message) -> None:
            if message.author and message.author.bot:
                return
            ctx = await self.get_context(message)
            await self.invoke(ctx)

        async def dispatch_event(self, event_name: str, *args: Any, **kwargs: Any) -> None:
            full_name = event_name if event_name.startswith("on_") else f"on_{event_name}"
            if hasattr(self, full_name):
                method = getattr(self, full_name)
                await method(*args, **kwargs)
            for listener in list(self._listeners.get(full_name, [])):
                await listener(*args, **kwargs)

        async def on_message(self, message: Message) -> None:
            await self.process_commands(message)

        async def on_command_error(self, ctx: Context, error: CommandError) -> None:
            for listener in list(self._listeners.get("on_command_error", [])):
                await listener(ctx, error)

        async def setup_hook(self) -> None:
            pass

        async def change_presence(self, *, activity: Any = None, status: Any = None) -> None:
            self.activity = activity
            self.status = status

        async def wait_until_ready(self) -> None:
            return None

        async def start(self, token: str, *, reconnect: bool = True) -> None:
            await self.setup_hook()

        async def close(self) -> None:
            self._closed = True

    # --- discord.ext.tasks ---
    class Loop:
        def __init__(self, coro: Callable, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
            self.coro = coro
            self.seconds = seconds
            self.minutes = minutes
            self.hours = hours
            self._running = False
            self._before_loop: Optional[Callable] = None

        def start(self, *args: Any, **kwargs: Any) -> None:
            self._running = True

        def cancel(self) -> None:
            self._running = False

        def stop(self) -> None:
            self._running = False

        def is_running(self) -> bool:
            return self._running

        def before_loop(self, coro: Callable) -> Callable:
            self._before_loop = coro
            return coro

    def loop(*, seconds: float = 0, minutes: float = 0, hours: float = 0, count: Optional[int] = None):
        def decorator(coro: Callable) -> Loop:
            return Loop(coro, seconds=seconds, minutes=minutes, hours=hours)

        return decorator

    # Populate modules
    discord_mod.DiscordException = DiscordException
    discord_mod.Forbidden = Forbidden
    discord_mod.NotFound = NotFound
    discord_mod.HTTPException = HTTPException
    discord_mod.Color = Color
    discord_mod.Colour = Colour
    discord_mod.ButtonStyle = ButtonStyle
    discord_mod.TextStyle = TextStyle
    discord_mod.ChannelType = ChannelType
    discord_mod.ActivityType = ActivityType
    discord_mod.Status = Status
    discord_mod.Intents = Intents
    discord_mod.Permissions = Permissions
    discord_mod.PermissionOverwrite = PermissionOverwrite
    discord_mod.Object = Object
    discord_mod.Asset = Asset
    discord_mod.File = File
    discord_mod.Embed = Embed
    discord_mod.BaseActivity = BaseActivity
    discord_mod.Activity = Activity
    discord_mod.Game = Game
    discord_mod.Streaming = Streaming
    discord_mod.Spotify = Spotify
    discord_mod.CustomActivity = CustomActivity
    discord_mod.Role = Role
    discord_mod.User = User
    discord_mod.VoiceState = VoiceState
    discord_mod.Member = Member
    discord_mod.Message = Message
    discord_mod.CategoryChannel = CategoryChannel
    discord_mod.TextChannel = TextChannel
    discord_mod.VoiceChannel = VoiceChannel
    discord_mod.VoiceClient = VoiceClient
    discord_mod.Guild = Guild
    discord_mod.Interaction = Interaction
    discord_mod.SelectOption = SelectOption
    discord_mod.AudioSource = AudioSource
    discord_mod.FFmpegPCMAudio = FFmpegPCMAudio
    discord_mod.PCMVolumeTransformer = PCMVolumeTransformer

    ui_mod.Item = Item
    ui_mod.Button = Button
    ui_mod.Select = Select
    ui_mod.RoleSelect = RoleSelect
    ui_mod.ChannelSelect = ChannelSelect
    ui_mod.UserSelect = UserSelect
    ui_mod.TextInput = TextInput
    ui_mod.View = View
    ui_mod.Modal = Modal
    ui_mod.button = button
    ui_mod.select = select

    utils_mod.get = get
    utils_mod.find = find
    utils_mod.utcnow = utcnow
    utils_mod.escape_markdown = escape_markdown
    utils_mod.format_dt = format_dt

    app_commands_mod.AppCommandError = AppCommandError
    app_commands_mod.CheckFailure = CheckFailure
    app_commands_mod.CommandOnCooldown = CommandOnCooldown
    app_commands_mod.Choice = Choice
    app_commands_mod.Command = AppCommand
    app_commands_mod.Group = AppGroup
    app_commands_mod.CommandTree = CommandTree
    app_commands_mod.command = app_command_decorator
    app_commands_mod.describe = describe
    app_commands_mod.choices = choices
    app_commands_mod.check = app_check

    commands_mod.CommandError = CommandError
    commands_mod.CommandNotFound = CommandNotFound
    commands_mod.MissingRequiredArgument = MissingRequiredArgument
    commands_mod.BadArgument = BadArgument
    commands_mod.CheckFailure = CheckFailureError
    commands_mod.MissingPermissions = MissingPermissions
    commands_mod.BotMissingPermissions = BotMissingPermissions
    commands_mod.NoPrivateMessage = NoPrivateMessage
    commands_mod.NotOwner = NotOwner
    commands_mod.CommandOnCooldown = CommandOnCooldownError
    commands_mod.ExtensionError = ExtensionError
    commands_mod.ExtensionAlreadyLoaded = ExtensionAlreadyLoaded
    commands_mod.ExtensionNotLoaded = ExtensionNotLoaded
    commands_mod.BucketType = BucketType
    commands_mod.Cooldown = Cooldown
    commands_mod.Context = Context
    commands_mod.Command = Command
    commands_mod.Group = Group
    commands_mod.HybridCommand = HybridCommand
    commands_mod.HybridGroup = HybridGroup
    commands_mod.command = command
    commands_mod.group = group
    commands_mod.hybrid_command = hybrid_command
    commands_mod.hybrid_group = hybrid_group
    commands_mod.check = check
    commands_mod.has_permissions = has_permissions
    commands_mod.bot_has_permissions = bot_has_permissions
    commands_mod.guild_only = guild_only
    commands_mod.is_owner = is_owner
    commands_mod.cooldown = cooldown
    commands_mod.when_mentioned_or = when_mentioned_or
    commands_mod.Cog = Cog
    commands_mod.Bot = Bot

    tasks_mod.Loop = Loop
    tasks_mod.loop = loop

    discord_mod.ui = ui_mod
    discord_mod.utils = utils_mod
    discord_mod.app_commands = app_commands_mod
    discord_mod.ext = ext_mod
    ext_mod.commands = commands_mod
    ext_mod.tasks = tasks_mod

    sys.modules["discord"] = discord_mod
    sys.modules["discord.ui"] = ui_mod
    sys.modules["discord.utils"] = utils_mod
    sys.modules["discord.app_commands"] = app_commands_mod
    sys.modules["discord.ext"] = ext_mod
    sys.modules["discord.ext.commands"] = commands_mod
    sys.modules["discord.ext.tasks"] = tasks_mod
    return True
