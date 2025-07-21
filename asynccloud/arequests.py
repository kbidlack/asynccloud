from __future__ import annotations

import string
from abc import ABC
from dataclasses import asdict, dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    ClassVar,
    Optional,
    Type,
    Union,
)

import requests
from soundcloud.resource.aliases import Like, RepostItem, SearchItem, StreamItem
from soundcloud.resource.base import BaseData
from soundcloud.resource.comment import BasicComment, Comment
from soundcloud.resource.conversation import Conversation
from soundcloud.resource.download import OriginalDownload
from soundcloud.resource.graphql import UserInteraction
from soundcloud.resource.history import HistoryItem
from soundcloud.resource.message import Message
from soundcloud.resource.playlist import AlbumPlaylist, BasicAlbumPlaylist
from soundcloud.resource.response import NoContentResponse
from soundcloud.resource.track import BasicTrack, Track
from soundcloud.resource.user import User, UserEmail
from soundcloud.resource.web_profile import WebProfile

if TYPE_CHECKING:
    from .asoundcloud import AsyncCloud

from typing import get_args, get_origin  # type: ignore[attr-defined]
from urllib.parse import parse_qs, urljoin, urlparse

from typing_extensions import Protocol


def _convert_dict[T: BaseData](d, return_type: Type[T]) -> T:
    union = get_origin(return_type) is Union
    if union:
        for t in get_args(return_type):
            try:
                return t.from_dict(d)
            except Exception:
                pass
    else:
        return return_type.from_dict(d)
    raise ValueError(f"Could not convert {d} to type {return_type}")


@dataclass
class Request[T: BaseData](ABC):
    base = "https://api-v2.soundcloud.com"
    format_url: str
    return_type: Type[T]
    method: str = "GET"

    def _format_url_and_remove_params(self, kwargs: dict) -> str:
        format_args = {
            tup[1]
            for tup in string.Formatter().parse(self.format_url)
            if tup[1] is not None
        }
        args = {}
        for k in list(kwargs.keys()):
            if k in format_args:
                args[k] = kwargs.pop(k)
        return self.base + self.format_url.format(**args)


@dataclass
class SingleRequest[T: BaseData](Request):
    async def __call__(
        self,
        client: AsyncCloud,
        body: Optional[dict] = None,
        **kwargs,
    ) -> Optional[T]:
        """
        Requests the resource at the given url with
        parameters given by kwargs. Converts the resource
        to type T and returns it. If the
        resource does not exist, returns None
        """
        resource_url = self._format_url_and_remove_params(kwargs)
        params = kwargs
        params["client_id"] = client.client_id

        async with client.session.request(
            self.method, resource_url, json=body, params=params, raise_for_status=True
        ) as r:
            if r.status in (400, 404, 500):
                return None

            return _convert_dict(await r.json(), self.return_type)

        if self.return_type == NoContentResponse:
            return NoContentResponse(r.status_code)  # type: ignore[return-value]
        return _convert_dict(r.json(), self.return_type)


@dataclass
class CollectionRequest[T: BaseData](Request):
    """
    Yields resources from the given url with
    parameters given by kwargs. Converts the resources
    to type T before yielding
    """

    async def __call__(
        self,
        client: AsyncCloud,
        _: Optional[dict] = None,  # body ?
        offset: Optional[str] = None,
        limit: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[T, None]:
        resource_url = self._format_url_and_remove_params(kwargs)
        params = kwargs
        params["client_id"] = client.client_id
        if offset is not None:
            params["offset"] = offset
        if limit is not None:
            params["limit"] = limit
        while resource_url:
            async with client.session.get(
                resource_url, params=params, raise_for_status=True
            ) as r:
                if r.status in (400, 404, 500):
                    return

                data = await r.json()

                for resource in data["collection"]:
                    yield _convert_dict(resource, self.return_type)

                resource_url = data.get("next_href", None)
                parsed = urlparse(resource_url)
                params = parse_qs(parsed.query)
                params["client_id"] = [
                    client.client_id
                ]  # next_href doesn't contain client_id
                resource_url = urljoin(resource_url, parsed.path)


@dataclass
class ListRequest[T: BaseData](Request):
    """
    Requests the resource list at the given url with
    parameters given by kwargs. Converts the resources
    to type T and returns them.
    """

    async def __call__(
        self, client: AsyncCloud, body: Optional[dict] = None, **kwargs
    ) -> list[T]:
        resource_url = self._format_url_and_remove_params(kwargs)
        params = kwargs
        params["client_id"] = client.client_id
        headers = client._get_default_headers()
        resources = []

        async with client.session.get(
            resource_url, params=params, headers=headers, raise_for_status=True
        ) as r:
            if r.status in (400, 404, 500):
                return []

            for resource in await r.json():
                resources.append(_convert_dict(resource, self.return_type))

        return resources


class DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]


@dataclass
class GraphQLRequest[Q: DataclassInstance, T: BaseData]:
    base = "https://graph.soundcloud.com/graphql"
    operation_name: str
    query_arg_type: Type[Q]
    return_type: Type[T]
    query_template_str: str

    def __call__(
        self,
        client: AsyncCloud,
        query_args: Q,
    ) -> Optional[T]:
        params = {}
        params["client_id"] = client.client_id
        headers = client._get_default_headers()
        headers["Apollographql-Client-Name"] = "v2"

        data = {
            "operationName": self.operation_name,
            "query": self.query_template_str,
            "variables": asdict(query_args),
        }

        with requests.post(self.base, json=data, params=params, headers=headers) as r:
            if r.status_code in (400, 404, 500):
                return None
            r.raise_for_status()
            return _convert_dict(r.json()["data"], self.return_type)


"""
v2 endpoints
"""


MeRequest = SingleRequest[User]("/me", User)
MeHistoryRequest = CollectionRequest[HistoryItem](
    "/me/play-history/tracks", HistoryItem
)
MeStreamRequest = CollectionRequest[StreamItem](
    "/stream",
    StreamItem,  # type: ignore[arg-type]
)
ResolveRequest = SingleRequest[SearchItem]("/resolve", SearchItem)  # type: ignore[arg-type]
SearchRequest = CollectionRequest[SearchItem](
    "/search",
    SearchItem,  # type: ignore[arg-type]
)
SearchAlbumsRequest = CollectionRequest[AlbumPlaylist](
    "/search/albums", AlbumPlaylist
)  # ?filter.genre_or_tag
SearchPlaylistsRequest = CollectionRequest[AlbumPlaylist](
    "/search/playlists_without_albums", AlbumPlaylist
)
SearchTracksRequest = CollectionRequest[Track](
    "/search/tracks", Track
)  # ?filter.created_at&filter.duration&filter.license
SearchUsersRequest = CollectionRequest[User]("/search/users", User)  # ?filter.place
TagRecentTracksRequest = CollectionRequest[Track]("/recent-tracks/{tag}", Track)
PlaylistRequest = SingleRequest[BasicAlbumPlaylist](
    "/playlists/{playlist_id}", BasicAlbumPlaylist
)
PostPlaylistRequest = SingleRequest[BasicAlbumPlaylist](
    "/playlists", BasicAlbumPlaylist, method="POST"
)
DeletePlaylistRequest = SingleRequest[NoContentResponse](
    "/playlists/{playlist_id}", NoContentResponse, method="DELETE"
)
PlaylistLikersRequest = CollectionRequest[User]("/playlists/{playlist_id}/likers", User)
PlaylistRepostersRequest = CollectionRequest[User](
    "/playlists/{playlist_id}/reposters", User
)
TrackRequest = SingleRequest[BasicTrack]("/tracks/{track_id}", BasicTrack)
TracksRequest = ListRequest[BasicTrack]("/tracks", BasicTrack)
TrackAlbumsRequest = CollectionRequest[BasicAlbumPlaylist](
    "/tracks/{track_id}/albums", BasicAlbumPlaylist
)  # (can be representation=mini)
TrackPlaylistsRequest = CollectionRequest[BasicAlbumPlaylist](
    "/tracks/{track_id}/playlists_without_albums", BasicAlbumPlaylist
)  # (can be representation=mini)
TrackCommentsRequest = CollectionRequest[BasicComment](
    "/tracks/{track_id}/comments", BasicComment
)
TrackLikersRequest = CollectionRequest[User]("/tracks/{track_id}/likers", User)
TrackRelatedRequest = CollectionRequest[BasicTrack](
    "/tracks/{track_id}/related", BasicTrack
)
TrackRepostersRequest = CollectionRequest[User]("/tracks/{track_id}/reposters", User)
TrackOriginalDownloadRequest = SingleRequest[OriginalDownload](
    "/tracks/{track_id}/download", OriginalDownload
)
UserRequest = SingleRequest[User]("/users/{user_id}", User)
UserCommentsRequest = CollectionRequest[Comment]("/users/{user_id}/comments", Comment)
UserConversationMessagesRequest = CollectionRequest[Message](
    "/users/{user_id}/conversations/{conversation_id}/messages", Message
)
UserConversationsRequest = CollectionRequest[Conversation](
    "/users/{user_id}/conversations", Conversation
)
UserConversationsUnreadRequest = CollectionRequest[Conversation](
    "/users/{user_id}/conversations/unread", Conversation
)
UserEmailsRequest = CollectionRequest[UserEmail]("/users/{user_id}/emails", UserEmail)
UserFeaturedProfilesRequest = CollectionRequest[User](
    "/users/{user_id}/featured-profiles", User
)
UserFollowersRequest = CollectionRequest[User]("/users/{user_id}/followers", User)
UserFollowingsRequest = CollectionRequest[User]("/users/{user_id}/followings", User)
UserLikesRequest = CollectionRequest[Like](
    "/users/{user_id}/likes",
    Like,  # type: ignore[arg-type]
)
UserRelatedArtistsRequest = CollectionRequest[User](
    "/users/{user_id}/relatedartists", User
)
UserRepostsRequest = CollectionRequest[RepostItem](
    "/stream/users/{user_id}/reposts",
    RepostItem,  # type: ignore[arg-type]
)
UserStreamRequest = CollectionRequest[StreamItem](
    "/stream/users/{user_id}",
    StreamItem,  # type: ignore[arg-type]
)
UserTracksRequest = CollectionRequest[BasicTrack]("/users/{user_id}/tracks", BasicTrack)
UserToptracksRequest = CollectionRequest[BasicTrack](
    "/users/{user_id}/toptracks", BasicTrack
)
UserAlbumsRequest = CollectionRequest[BasicAlbumPlaylist](
    "/users/{user_id}/albums", BasicAlbumPlaylist
)  # (can be representation=mini)
UserPlaylistsRequest = CollectionRequest[BasicAlbumPlaylist](
    "/users/{user_id}/playlists_without_albums", BasicAlbumPlaylist
)  # (can be representation=mini)
UserWebProfilesRequest = ListRequest[WebProfile](
    "/users/{user_urn}/web-profiles", WebProfile
)


"""
graphql endpoints
"""


@dataclass
class UserInteractionsQueryResult(BaseData):
    user: tuple[UserInteraction, ...]
    creator: tuple[UserInteraction, ...]


@dataclass
class UserInteractionsQueryParams:
    createdByProfileUrn: str
    interactionTypeUrn: str
    parentUrn: str
    targetUrns: list[str]


UserInteractionsRequest = GraphQLRequest[
    UserInteractionsQueryParams, UserInteractionsQueryResult
](
    "UserInteractions",
    UserInteractionsQueryParams,
    UserInteractionsQueryResult,
    (
        "query UserInteractions(\n"
        "   $parentUrn: String!\n"
        "   $interactionTypeUrn: String!\n"
        "   $targetUrns: [String!]!\n"
        "   $createdByProfileUrn: String\n"
        ") {\n"
        "   user: userInteractions(\n"
        "       parentUrn: $parentUrn\n"
        "       interactionTypeUrn: $interactionTypeUrn\n"
        "       targetUrns: $targetUrns\n"
        "   ) {\n"
        "       interactionCounts {\n"
        "           count\n"
        "           interactionTypeValueUrn\n"
        "       }\n"
        "       interactionTypeUrn\n"
        "       targetUrn\n"
        "       userInteraction\n"
        "   }\n"
        "\n"
        "   creator: userInteractions(\n"
        "       parentUrn: $parentUrn\n"
        "       interactionTypeUrn: $interactionTypeUrn\n"
        "       targetUrns: $targetUrns\n"
        "       createdByProfileUrn: $createdByProfileUrn\n"
        "   ) {\n"
        "       interactionCounts {\n"
        "           count\n"
        "           interactionTypeValueUrn\n"
        "       }\n"
        "       interactionTypeUrn\n"
        "       targetUrn\n"
        "       userInteraction\n"
        "   }\n"
        "}"
    ),
)
