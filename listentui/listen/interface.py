from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from time import time
from typing import Any, ClassVar, Literal, NewType, Optional, Self, Type, Union

from markdownify import markdownify  # type: ignore

AlbumID = NewType("AlbumID", int)
ArtistID = NewType("ArtistID", int)
CharacterID = NewType("CharacterID", int)
SongID = NewType("SongID", int)
SourceID = NewType("SourceID", int)


class Base:
    romaji_first: ClassVar[bool] = False


@dataclass
class Socials(Base):
    name: str
    url: str

    @classmethod
    def from_data(cls: Type[Self], social: dict[str, Any]) -> Self:
        return cls(name=social["name"], url=social["url"])


@dataclass
class Image(Base):
    name: str
    url: str

    @classmethod
    def from_source(
        cls: Type[Self], source: Literal["albums", "artists", "sources"], value: Optional[str] = None
    ) -> Self | None:
        if not value:
            return None

        cdn = "https://cdn.listen.moe"
        match source:
            case "albums":
                url = f"{cdn}/covers/{value}"
            case "artists":
                url = f"{cdn}/artists/{value}"
            case "sources":
                url = f"{cdn}/source/{value}"

        return cls(name=value, url=url)


@dataclass
class User(Base):
    uuid: str
    username: str
    display_name: str
    bio: str | None
    favorites: int
    uploads: int
    requests: int
    feeds: list[SystemFeed]
    link: str = field(init=False)

    def __post_init__(self):
        self.link = f"https://listen.moe/u/{self.username}"

    @classmethod
    def from_data(cls: Type[Self], user: dict[str, Any]) -> Self:
        return cls(
            uuid=user["uuid"],
            username=user["username"],
            display_name=user["displayName"],
            bio=User.convert_to_markdown(user["bio"]) if user["bio"] else None,
            favorites=user["favorites"]["count"],
            uploads=user["uploads"]["count"],
            requests=user["requests"]["count"],
            feeds=[SystemFeed.from_data(feed) for feed in user["systemFeed"]],
        )

    @staticmethod
    def convert_to_markdown(string: str) -> str:
        return markdownify(string)  # type: ignore


@dataclass
class CurrentUser(User):
    token: str
    password: str

    @classmethod
    def from_data_with_password(cls: Type[Self], user: dict[str, Any], token: str, password: str) -> Self:
        return cls(
            uuid=user["uuid"],
            username=user["username"],
            display_name=user["displayName"],
            bio=CurrentUser.convert_to_markdown(user["bio"]) if user["bio"] else None,
            favorites=user["favorites"]["count"],
            uploads=user["uploads"]["count"],
            requests=user["requests"]["count"],
            feeds=[SystemFeed.from_data(feed) for feed in user["systemFeed"]],
            token=token,
            password=password,
        )


@dataclass
class Album(Base):
    id: AlbumID
    name: str | None
    name_romaji: str | None
    image: Image | None
    songs: list[Song] | None = None
    artists: list[Artist] | None = None
    socials: list[Socials] | None = None
    link: str = field(init=False)

    def __post_init__(self):
        self.link = f"https://listen.moe/albums/{self.id}"

    @classmethod
    def from_data(cls: Type[Self], album: dict[str, Any]) -> Self:
        return cls(
            id=album["id"],
            name=album.get("name"),
            name_romaji=album.get("nameRomaji"),
            image=Image.from_source("albums", album["image"]) if album.get("image") else None,
            songs=[Song.from_data(song) for song in album["songs"]] if album.get("songs") else None,
            artists=[Artist.from_data(artist) for artist in album["artists"]] if album.get("artists") else None,
            socials=[Socials.from_data(social) for social in album["links"]] if album.get("links") else None,
        )

    def format_name(self) -> str | None:
        return (self.name_romaji or self.name) if self.romaji_first else (self.name or self.name_romaji)

    def format_socials(self, *, sep: str = ", ") -> str | None:
        if not self.socials:
            return None
        return f"{sep}".join([f"[link={social.url}]{social.name}[/link]" for social in self.socials])


@dataclass
class Artist(Base):
    id: ArtistID
    name: str | None
    name_romaji: str | None
    image: Image | None
    characters: list[Character] | None
    socials: list[Socials] | None = None
    song_count: int | None = None
    albums: list[Album] | None = None
    songs_without_album: list[Song] | None = None
    album_count: int | None = None
    link: str = field(init=False)

    def __post_init__(self):
        self.link = f"https://listen.moe/artists/{self.id}"
        total = 0
        if self.albums:
            for album in self.albums:
                if album.songs:
                    total += len(album.songs)
        if self.songs_without_album:
            total += len(self.songs_without_album)
        self.song_count = total

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, Artist):
            raise Exception("Not supported")
        return self.id == value.id

    def __hash__(self) -> int:
        return hash(f"{self.id}+{self.name}+{self.name_romaji}")

    @classmethod
    def from_data(cls: Type[Self], artist: dict[str, Any]) -> Self:
        return cls(
            id=artist["id"],
            name=artist.get("name"),
            name_romaji=artist.get("nameRomaji"),
            image=Image.from_source("artists", artist["image"]),
            characters=[Character.from_data(character) for character in artist["characters"]]
            if artist.get("characters") and len(artist["characters"]) != 0
            else None,
            socials=[Socials.from_data(social) for social in artist["links"]] if artist.get("links") else None,
            album_count=len(artist["albums"]) if artist.get("albums") else None,
            albums=[Album.from_data(album) for album in artist["albums"]]
            if artist.get("albums") and len(artist["albums"]) != 0
            else None,
            songs_without_album=[Song.from_data(song) for song in artist["songsWithoutAlbum"]]
            if artist.get("songsWithoutAlbum") and len(artist["songsWithoutAlbum"]) != 0
            else None,
        )

    def format_name(self) -> str | None:
        return (self.name_romaji or self.name) if self.romaji_first else (self.name or self.name_romaji)

    def format_socials(self, *, sep: str = ", ", use_app: bool = False) -> str | None:
        if not self.socials:
            return None
        if use_app:
            return f"{sep}".join(
                [f"[@click=app.handle_url('{social.url}')]{social.name}[/]" for social in self.socials]
            )
        return f"{sep}".join([f"[link={social.url}]{social.name}[/link]" for social in self.socials])


@dataclass
class Character(Base):
    id: CharacterID
    name: Optional[str] = None
    name_romaji: Optional[str] = None
    link: str = field(init=False)

    def __post_init__(self):
        self.link = f"https://listen.moe/characters/{self.id}"

    @classmethod
    def from_data(cls: Type[Self], character: dict[str, Any]) -> Self:
        return cls(id=character["id"], name=character.get("name"), name_romaji=character.get("nameRomaji"))


@dataclass
class Source(Base):
    id: SourceID
    name: str | None
    name_romaji: str | None
    image: Image | None
    description: str | None = None
    socials: list[Socials] | None = None
    songs: list[Song] | None = None
    songs_without_album: list[Song] | None = None
    link: str = field(init=False)

    def __post_init__(self):
        self.link = f"https://listen.moe/sources/{self.id}"

    @classmethod
    def from_data(cls: Type[Self], source: dict[str, Any]) -> Self:
        return cls(
            id=source["id"],
            name=source.get("name"),
            name_romaji=source.get("nameRomaji"),
            image=Image.from_source("sources", source["image"]),
            description=source.get("description"),
            socials=[Socials.from_data(social) for social in source["links"]] if source.get("links") else None,
            songs=[Song.from_data(song) for song in source["songs"]] if source.get("songs") else None,
            songs_without_album=[Song.from_data(song) for song in source["songsWithoutAlbum"]]
            if source.get("songsWithoutAlbum") and len(source["songsWithoutAlbum"]) != 0
            else None,
        )

    def format_name(self) -> str | None:
        return (self.name_romaji or self.name) if self.romaji_first else (self.name or self.name_romaji)

    def format_socials(self, *, sep: str = ", ", use_app: bool = False) -> str | None:
        if not self.socials:
            return None
        if use_app:
            return f"{sep}".join(
                [f"[@click=app.handle_url('{social.url}')]{social.name}[/]" for social in self.socials]
            )
        return f"{sep}".join([f"[link={social.url}]{social.name}[/link]" for social in self.socials])

    def description_to_markdown(self) -> str | None:
        return markdownify(self.description)  # type: ignore


@dataclass
class Requester(Base):
    uuid: str
    username: str
    display_name: str
    link: str = field(init=False)

    @classmethod
    def from_data(cls: Type[Self], data: dict[str, Any] | None) -> Self | None:
        if not data:
            return None
        return cls(uuid=data["uuid"], username=data["username"], display_name=data["displayName"])

    def __post_init__(self):
        self.link = f"https://listen.moe/u/{self.username}"


@dataclass
class Uploader(Requester):
    pass


@dataclass
class Event(Base):
    id: str
    name: str
    slug: str
    image: str
    presence: Optional[str] = None

    @classmethod
    def from_data(cls: Type[Self], data: dict[str, Any] | None) -> Self | None:
        if not data:
            return None
        return cls(id=data["id"], name=data["name"], slug=data["slug"], image=data["image"], presence=data["presence"])


@dataclass
class Song(Base):
    @classmethod
    def from_data(cls: Type[Self], data: dict[str, Any]) -> Self:
        return cls(
            id=data["id"],
            title=data["title"],
            title_romaji=data.get("titleRomaji"),
            source=Source.from_data(data["sources"][0]) if data.get("sources") else None,
            artists=[Artist.from_data(artist) for artist in data["artists"]] if data.get("artists") else None,
            album=Album.from_data(data["albums"][0]) if data.get("albums") else None,
            characters=[Character.from_data(chara) for chara in data["characters"]] if data.get("characters") else None,
            duration=data.get("duration"),
            time_end=round(time() + data["duration"]) if data.get("duration") else round(time()),
            snippet=data.get("snippet"),
            played=data.get("played"),
            last_played=datetime.fromtimestamp(int(date) / 1000) if (date := data.get("lastPlayed")) else None,
            uploader=Uploader.from_data(data["uploader"]) if data.get("uploader") else None,
        )

    def _artist_list(
        self,
        count: Optional[int] = None,
        *,
        show_character: bool = False,
        embed_link: bool = False,
    ) -> list[str] | None:
        if not self.artists:
            return None

        artists: list[str] = []
        for idx, artist in enumerate(self.artists):
            if count and idx + 1 > count:
                return artists

            character_map: dict[int, Character] = {}
            if show_character and self.characters and artist.characters:
                character_map: dict[int, Character] = {character.id: character for character in artist.characters}

            name = (artist.name_romaji or artist.name) if self.romaji_first else (artist.name or artist.name_romaji)
            character = None
            character_name = None

            if self.characters:
                character = character_map.get(self.characters[0].id)
                if character:
                    character_name = (
                        (character.name_romaji or character.name)
                        if self.romaji_first
                        else (character.name or character.name_romaji)
                    )

            if show_character:
                if name and character and character_name:
                    if embed_link:
                        j = f"[link={character.link}]{character}[/link]"
                        k = f"(CV: [link={artist.link}]{name}[/link])"
                        artists.append(f"{j} {k}")
                    else:
                        artists.append(f"{character_name} (CV: {name})")
                elif name:
                    if embed_link:
                        artists.append(f"[link={artist.link}]{name}[/link]")
                    else:
                        artists.append(name)
            elif name and embed_link:
                artists.append(f"[link={artist.link}]{name}[/link]")
            elif name:
                artists.append(name)

        return artists

    def format_artists_list(self, show_character: bool = True) -> list[str] | None:
        return self._artist_list(show_character=show_character)

    def format_artists(
        self,
        count: Optional[int] = None,
        *,
        show_character: bool = True,
        embed_link: bool = False,
    ) -> str | None:
        formatted_artist = self._artist_list(count=count, show_character=show_character, embed_link=embed_link)
        if not formatted_artist:
            return None
        return ", ".join(formatted_artist)

    def artist_image(self) -> str | None:
        if not self.artists:
            return None
        if self.artists[0].image:
            return self.artists[0].image.url
        return None

    def _format(self, albs: Union[Album, Source], embed_link: bool = False) -> str | None:
        name = (albs.name_romaji or albs.name) if self.romaji_first else (albs.name or albs.name_romaji)
        if not name:
            return None
        if embed_link:
            return f"[link={albs.link}]{name}[/link]"
        return name

    def format_album(self, *, embed_link: bool = False) -> str | None:
        if not self.album:
            return None
        return self._format(self.album, embed_link)

    def format_source(self, *, embed_link: bool = False) -> str | None:
        if not self.source:
            return None
        return self._format(self.source, embed_link)

    def format_title(self) -> str | None:
        title = (self.title_romaji or self.title) if self.romaji_first else (self.title or self.title_romaji)
        return title or None

    def album_image(self):
        if not self.album:
            return None
        if not self.album.image:
            return None
        return self.album.image.url

    def source_image(self):
        if not self.source:
            return None
        if not self.source.image:
            return None
        return self.source.image.url

    id: SongID
    title: str | None
    source: Source | None
    artists: list[Artist] | None
    characters: list[Character] | None
    album: Album | None
    duration: int | None
    time_end: int
    uploader: Uploader | None = None
    snippet: str | None = None
    played: int | None = None
    title_romaji: str | None = None
    last_played: datetime | None = None


@dataclass
class SystemFeed(Base):
    type: ActivityType
    created_at: datetime
    song: Song | None
    activity: str = field(init=False)

    class ActivityType(Enum):
        # Someone commented on the user's feed.
        COMMENTED = 1
        # The user favorited a song
        FAVORITED = 2
        # The user uploaded a song
        UPLOADED = 3
        # The user approved an upload (only admins)
        APPROVEDUPLOAD = 4

    @classmethod
    def from_data(cls: Type[Self], data: dict[str, Any]) -> Self:
        song = data["song"]
        return cls(
            type=cls.ActivityType.FAVORITED if int(data["type"]) == 2 else cls.ActivityType.UPLOADED,  # noqa: PLR2004
            created_at=datetime.fromtimestamp(round(int(data["createdAt"]) / 1000)),
            song=Song.from_data(song) if song else None,
        )

    def __post_init__(self) -> None:
        match self.type:
            case self.ActivityType.FAVORITED:
                self.activity = "Favorited"
            case self.ActivityType.UPLOADED:
                self.activity = "Uploaded"
            case _:
                self.activity = "User did something"


@dataclass
class PlayStatistics(Base):
    created_at: datetime
    song: Song
    requester: Requester | None

    @classmethod
    def from_data(cls: Type[Self], data: dict[str, Any]) -> Self:
        return cls(
            created_at=datetime.fromtimestamp(round(int(data["createdAt"]) / 1000)),
            song=Song.from_data(data["song"]),
            requester=Requester.from_data(data["requester"]) if data["requester"] else None,
        )


@dataclass
class ListenWsData:
    @classmethod
    def from_data(cls: Type[Self], data: dict[str, Any]) -> Self:
        """
        A dataclass representation of LISTEN.moe websocket data

        Args:
            data `dict`: The websocket data
        Return:
            Self `ListenWsData`
        """
        return cls(
            _op=data["op"],
            _t=data["t"],
            start_time=datetime.fromisoformat(data["d"]["startTime"]),
            listener=data["d"]["listeners"],
            requester=Requester.from_data(data["d"].get("requester")),
            event=Event.from_data(data["d"].get("event")),
            song=Song.from_data(data["d"]["song"]),
            last_played=[Song.from_data(song) for song in data["d"]["lastPlayed"]],
        )

    _op: int
    _t: str
    song: Song
    requester: Requester | None
    start_time: datetime
    last_played: list[Song]
    listener: int
    event: Optional[Event] = None
