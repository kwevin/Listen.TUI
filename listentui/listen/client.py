import json
import time
from asyncio import Lock
from base64 import b64decode
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from logging import getLogger
from string import Template
from typing import Any, Callable, Coroutine, Optional, Self, Union, overload

from async_lru import alru_cache
from frozendict import frozendict
from gql import Client, gql
from gql.client import ReconnectingAsyncClientSession
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportQueryError
from graphql import DocumentNode

from listentui.listen.interface import (
    Album,
    AlbumID,
    Artist,
    ArtistID,
    Character,
    CharacterID,
    CurrentUser,
    PlayStatistics,
    Song,
    SongID,
    Source,
    SourceID,
    User,
)


class NotAuthenticatedError(Exception):
    pass


class RequestError(Enum):
    NULL = 0
    FULL = 1
    IN_QUEUE = 2


@dataclass
class Queries:
    login: DocumentNode
    user: DocumentNode
    album: DocumentNode
    artist: DocumentNode
    character: DocumentNode
    favorite_song: DocumentNode
    check_favorite: DocumentNode
    song: DocumentNode
    songs: DocumentNode
    source: DocumentNode
    play_statistic: DocumentNode
    search: DocumentNode
    request_song: DocumentNode
    request_random_song: DocumentNode


def _build_queries():
    base = {
        "user": """
                    uuid
                    username
                    displayName
                    bio
                    favorites {
                        count
                    }
                    uploads {
                        count
                    }
                    requests {
                        count
                    }
                """,
        "song": """
                    id
                    title
                    sources {
                        id
                        name
                        nameRomaji
                        image
                    }
                    artists {
                        id
                        name
                        nameRomaji
                        image
                        characters {
                            id
                            name
                            nameRomaji
                        }
                    }
                    characters {
                        id
                        name
                        nameRomaji
                    }
                    albums {
                        id
                        name
                        nameRomaji
                        image
                    }
                    uploader {
                        uuid
                        displayName
                        username
                    }
                    duration
                    played
                    titleRomaji
                    snippet
                    lastPlayed
                """,
        "generic": """
                    id
                    name
                    nameRomaji
                """,
    }
    login = Template(
        """
        mutation login($$username: String!, $$password: String!, $$systemOffset: Int!, $$systemCount: Int!) {
            login(username: $$username, password: $$password) {
                user {
                    ${user}
                    systemFeed(offset: $$systemOffset, count: $$systemCount) {
                        type
                        createdAt
                        song {
                            ${song}
                        }
                    }
                }
                token
            }
        }
    """
    ).safe_substitute(base)
    user = Template(
        """
        query user($$username: String!, $$systemOffset: Int!, $$systemCount: Int!) {
            user(username: $$username) {
                ${user}
                systemFeed(offset: $$systemOffset, count: $$systemCount) {
                    type
                    createdAt
                    song {
                        ${song}
                    }
                }
            }
        }
    """
    ).safe_substitute(base)
    album = Template(
        """
        query album($$id: Int!) {
            album(id: $$id) {
                ${generic}
                image
                songs {
                    ${song}
                }
                artists {
                    ${generic}
                    image
                    characters {
                        ${generic}
                    }
                }
                links {
                    name
                    url
                }
            }
        }
    """
    ).safe_substitute(base)
    artist = Template(
        """
        query artist($$id: Int!) {
            artist(id: $$id) {
                ${generic}
                image
                characters {
                    ${generic}
                }
                links {
                    name
                    url
                }
                albums {
                    ${generic}
                    image
                    songs {
                        ${song}
                    }
                }
                songsWithoutAlbum {
                    ${song}
                }
            }
        }
    """
    ).safe_substitute(base)
    character = Template(
        """
        query character($$id: Int!) {
            character(id: $$id) {
                ${generic}
            }
        }
    """
    ).safe_substitute(base)
    song = Template(
        """
        query song($$id: Int!) {
            song(id: $$id) {
                ${song}
            }
        }
    """
    ).safe_substitute(base)
    songs = Template(
        """
        query songs($$offset: Int!, $$count: Int!) {
            songs(offset: $$offset, count: $$count) {
                songs {
                    ${song}
                }                    
                count
            }
        }
    """
    ).safe_substitute(base)
    source = Template(
        """
        query source($$id: Int!) {
            source(id: $$id) {
                ${generic}
                image
                description
                links {
                    name
                    url
                }
                songs {
                    ${song}
                }
                songsWithoutAlbum {
                    ${song}
                }
            }
        }
    """
    ).safe_substitute(base)
    check_favorite = """
        query checkFavorite($songs: [Int!]!) {
            checkFavorite(songs: $songs)
        }
    """
    favorite_song = """
        mutation favoriteSong($id: Int!) {
            favoriteSong(id: $id) {
                id
            }
        }
    """
    play_statistic = Template(
        """
        query play_statistic($count: Int!, $offset: Int) {
            playStatistics(count: $count, offset: $offset) {
                songs {
                    createdAt
                    song {
                        ${song}
                    }
                    requester {
                        uuid
                        username
                        displayName
                    }
                }
            }
        }
    """
    ).safe_substitute(base)
    search = Template(
        """
        query search($term: ID!, $favoritesOnly: Boolean) {
            search(query: $term, favoritesOnly: $favoritesOnly) {
                ... on Song {
                    ${song}
                }
            }
        }
    """
    ).safe_substitute(base)
    request = Template(
        """
        mutation requestSong($id: Int!) {
            requestSong(id: $id) {
                ${song}
            }
        }
    """
    ).safe_substitute(base)
    request_random = Template(
        """
        mutation requestRandomFavorite {
            requestRandomFavorite {
                ${song}
            }
        }
    """
    ).safe_substitute(base)

    return Queries(
        login=gql(login),
        user=gql(user),
        album=gql(album),
        artist=gql(artist),
        character=gql(character),
        check_favorite=gql(check_favorite),
        favorite_song=gql(favorite_song),
        song=gql(song),
        songs=gql(songs),
        source=gql(source),
        play_statistic=gql(play_statistic),
        search=gql(search),
        request_song=gql(request),
        request_random_song=gql(request_random),
    )


def requires_auth(func: Callable[..., Coroutine[Any, Any, Any]]) -> Any:
    @wraps(func)
    async def wrapper(self: "ListenClient", *args: Any, **kwargs: Any) -> Any:
        if not self.logged_in:
            raise NotAuthenticatedError("Not logged in")
        return await func(self, *args, **kwargs)

    return wrapper


class ListenClient:
    ENDPOINT = "https://listen.moe/graphql"
    SYSTEM_COUNT = 10
    SYSTEM_OFFSET = 0
    _client_instance: Optional[Self] = None
    _lock = Lock()

    def __init__(self, user: Optional[CurrentUser] = None) -> None:
        self._log = getLogger(__name__)
        self.logged_in = False
        self.connected = False
        self.headers = {
            "Accept": "*/*",
            "content-type": "application/json",
        }
        self._user = user or None
        if user:
            self.logged_in = True
            self.headers["Authorization"] = f"Bearer {user.token}"
        self._queries = _build_queries()
        transport = AIOHTTPTransport(self.ENDPOINT, headers=self.headers)
        self._client = Client(transport=transport, fetch_schema_from_transport=False, execute_timeout=20)
        self._session: ReconnectingAsyncClientSession | None = None
        ListenClient._client_instance = self
        self._execute_cached = alru_cache(maxsize=20)(self._execute_uncached)
        self._last_hit = 0

    @property
    def current_user(self) -> CurrentUser | None:
        return self._user

    @staticmethod
    def validate_token(token: str) -> bool:
        jwt_payload: dict[str, Any] = json.loads(b64decode(token.split(".")[1] + "=="))
        return not time.time() >= jwt_payload["exp"]

    @classmethod
    async def login(cls, username: str, password: str, user_token: Optional[str] = None) -> Self | TransportQueryError:
        """return a new instance of ListenClient with a logged in user else None if the login failed"""
        if user_token and not cls.validate_token(user_token):
            return await cls.login(username, password)

        async with cls._lock:
            headers = {
                "Accept": "*/*",
                "content-type": "application/json",
            }
            headers = headers | {"Authorization": user_token} if user_token else headers
            transport = AIOHTTPTransport(cls.ENDPOINT, headers=headers)
            client = Client(transport=transport, fetch_schema_from_transport=False)
            query = _build_queries()

            if user_token:
                params = {"username": username, "systemOffset": cls.SYSTEM_OFFSET, "systemCount": cls.SYSTEM_COUNT}
                async with client as session:
                    res: dict[str, Any] = await session.execute(document=query.user, variable_values=params)  # pyright: ignore
                user: dict[str, Any] = res["user"]
                token = user_token
            else:
                params = {
                    "username": username,
                    "password": password,
                    "systemOffset": cls.SYSTEM_OFFSET,
                    "systemCount": cls.SYSTEM_COUNT,
                }
                try:
                    async with client as session:
                        res: dict[str, Any] = await session.execute(document=query.login, variable_values=params)  # pyright: ignore
                except TransportQueryError as e:
                    return e
                user: dict[str, Any] = res["login"]["user"]
                token: str = res["login"]["token"]

            await client.close_async()
        return cls(CurrentUser.from_data_with_password(user, token, password))

    @classmethod
    def get_instance(cls) -> Self:
        """return the current instance of ListenClient, will create a new instance if one does not exist"""
        return cls._client_instance or cls()

    async def connect(self) -> None:
        if self._session:
            raise Exception("Client is already connected")
        async with self._lock:
            self._session = await self._client.connect_async(reconnecting=True)  # pyright: ignore
            self.connected = True

    async def close(self) -> None:
        await self._client.close_async()

    async def regenerate_token(self) -> None:
        """regenerate a new token for the current user"""
        if not self.logged_in or self._user is None:
            return
        params = {
            "username": self._user.username,
            "password": self._user.password,
            "systemOffset": self.SYSTEM_OFFSET,
            "systemCount": self.SYSTEM_COUNT,
        }
        try:
            res = await self._execute_uncached(document=self._queries.login, variable_values=params)
        except TransportQueryError as err:
            raise Exception("Failed to generate new token") from err
        await self._client.close_async()
        self.headers["Authorization"] = f"Bearer {res['login']['token']}"
        transport = AIOHTTPTransport(self.ENDPOINT, headers=self.headers)
        self._client = Client(transport=transport, fetch_schema_from_transport=False)
        async with self._lock:
            self._session = await self._client.connect_async(reconnecting=True)  # pyright: ignore

        return

    async def _execute(
        self, document: DocumentNode, variable_values: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        res = await self._execute_cached(document=document, variable_values=frozendict(variable_values))  # type: ignore
        hits = self._execute_cached.cache_info().hits
        if hits > self._last_hit:
            self._log.debug("Using cached result")
            self._last_hit = hits
            self._log.debug(str(res)[0:100] + "...")
        return res

    async def _execute_uncached(
        self, document: DocumentNode, variable_values: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        if not self.connected:
            raise Exception("Client must be connected")
        try:
            return await self._session.execute(document=document, variable_values=variable_values)  # pyright: ignore
        except TransportQueryError as exc:
            if not exc.errors:
                raise exc
            if exc.errors[0]["message"] == "Not logged in." and self._user is not None:
                await self.regenerate_token()
                return await self._session.execute(document=document, variable_values=variable_values)  # pyright: ignore
            raise Exception("Failed to regenerate user token") from exc

    async def update_current_user(self, offset: int = 0, count: int = 5) -> CurrentUser | None:
        """update the current user with the latest data from the api"""
        if not self._user:
            return None
        current_user = self._user
        user = await self.user(current_user.username, offset, count)
        if not user:
            return None
        self._user = CurrentUser(
            user.uuid,
            user.username,
            user.display_name,
            user.bio,
            user.favorites,
            user.uploads,
            user.requests,
            user.feeds,
            current_user.token,
            current_user.password,
        )
        return self._user

    async def album(self, album_id: Union[AlbumID, int]) -> Album | None:
        """return an album from the api"""
        query = self._queries.album
        params = {"id": album_id}
        res = await self._execute(document=query, variable_values=params)
        album = res.get("album", None)
        if not album:
            return None
        return Album.from_data(album)

    async def artist(self, artist_id: Union[ArtistID, int]) -> Artist | None:
        """return an artist from the api"""
        query = self._queries.artist
        params = {"id": artist_id}
        res = await self._execute(document=query, variable_values=params)
        artist = res.get("artist", None)
        if not artist:
            return None
        return Artist.from_data(artist)

    async def character(self, character_id: Union[CharacterID, int]) -> Character | None:
        """return a character from the api"""
        query = self._queries.character
        params = {"id": character_id}
        res = await self._execute(document=query, variable_values=params)
        character = res.get("character", None)
        if not character:
            return None
        return Character.from_data(character)

    async def song(self, song_id: Union[SongID, int]) -> Song | None:
        """return a song from the api"""
        query = self._queries.song
        params = {"id": song_id}
        res = await self._execute(document=query, variable_values=params)
        song = res.get("song", None)
        if not song:
            return None
        return Song.from_data(song)

    async def songs(self, offset: int, count: int) -> list[Song]:
        """return a list of songs from the api"""
        query = self._queries.songs
        params = {"offset": offset, "count": count}
        res = await self._execute(document=query, variable_values=params)
        songs = res["songs"].get("songs", None)
        if not songs:
            return []
        return [Song.from_data(song) for song in songs]

    async def source(self, source_id: Union[SourceID, int]) -> Source | None:
        """return a source from the api"""
        query = self._queries.source
        params = {"id": source_id}
        res = await self._execute(document=query, variable_values=params)
        source = res.get("source", None)
        if not source:
            return None
        return Source.from_data(source)

    async def user(self, username: str, system_offset: int = 0, system_count: int = 5) -> User | None:
        """return a user from the api"""
        query = self._queries.user
        params = {"username": username, "systemOffset": system_offset, "systemCount": system_count}
        res = await self._execute_uncached(document=query, variable_values=params)
        user = res.get("user", None)
        if not user:
            return None
        return User.from_data(user)

    async def history(self, count: Optional[int] = 50, offset: Optional[int] = 0) -> list[PlayStatistics]:
        """return a list of songs history from the api"""
        query = self._queries.play_statistic
        params = {"count": count, "offset": offset}
        res = await self._execute_uncached(document=query, variable_values=params)
        songs = res["playStatistics"]["songs"]
        return [PlayStatistics.from_data(song) for song in songs]

    async def search(self, term: str, count: Optional[int] = None, favorite_only: Optional[bool] = False) -> list[Song]:
        """search for a song from the api"""
        if not self.logged_in and favorite_only:
            raise NotAuthenticatedError("Not logged in")
        query = self._queries.search
        params = {"term": term, "favoritesOnly": favorite_only}
        res = await self._execute(document=query, variable_values=params)
        songs = res["search"]
        songs = songs[:count] if count else songs
        return [Song.from_data(song) for song in songs]

    @overload
    async def check_favorite(self, song_ids: list[Union[SongID, int]]) -> dict[SongID, bool]: ...

    @overload
    async def check_favorite(self, song_id: Union[SongID, int]) -> bool: ...

    @requires_auth
    async def check_favorite(self, song_id: Union[SongID, int] | list[Union[SongID, int]]) -> bool | dict[SongID, bool]:
        """REQUIRED: logged in user\n
        check if a song is favorited by the current user\n
        raises NotAuthenticatedError if not logged in
        """
        query = self._queries.check_favorite
        params = {"songs": song_id}
        res = await self._execute_uncached(document=query, variable_values=params)
        favorite = res["checkFavorite"]
        if isinstance(song_id, list):
            return {SongID(sid): sid in favorite for sid in song_id}
        return song_id in favorite

    # mutations
    @requires_auth
    async def favorite_song(self, song_id: Union[SongID, int]) -> None:
        """REQUIRED: logged in user\n
        favorite a song\n
        raises NotAuthenticatedError if not logged in
        """
        query = self._queries.favorite_song
        params = {"id": song_id}
        await self._execute_uncached(document=query, variable_values=params)

    async def request_song(self, song_id: Union[SongID, int], exception_on_error: bool = True) -> Song | RequestError:
        """REQUIRED: logged in user\n
        request a song\n
        raises NotAuthenticatedError if not logged in,
        return `None` if the request failed and `exception_on_error` is set to `False`
        """
        query = self._queries.request_song
        params = {"id": song_id}
        if not exception_on_error:
            try:
                res = await self._execute_uncached(document=query, variable_values=params)
            except TransportQueryError as err:
                if not err.errors:
                    return RequestError.NULL
                if err.errors[0]["message"] == "All requests used up for today.":
                    return RequestError.FULL
                if err.errors[0]["message"] == "Song already queued.":
                    return RequestError.IN_QUEUE
                return RequestError.NULL
        else:
            res = await self._execute_uncached(document=query, variable_values=params)

        return Song.from_data(res["requestSong"])

    @requires_auth
    async def request_random_favorite(
        self,
        exception_on_error: bool = True,
    ) -> Song | RequestError:
        """REQUIRED: logged in user\n
        request a random user favorited song\n
        raises NotAuthenticatedError if not logged in,
        return `None` if the request failed and `exception_on_error` is set to `False`
        """
        query = self._queries.request_random_song
        if not exception_on_error:
            try:
                res = await self._execute_uncached(document=query)
            except TransportQueryError:
                return RequestError.FULL
        else:
            res = await self._execute_uncached(document=query)

        return Song.from_data(res["requestRandomFavorite"])


# if __name__ == "__main__":
#     import asyncio

#     from rich.pretty import pprint

#     async def main():
#         client = ListenClient.get_instance()
#         song = await client.song(20294)
#         pprint(song)
#         pprint(song.format_artists_list(romaji_first=True))

#     asyncio.run(main())
