"""Business-rule failures. The API turns each into the shared error shape
(contracts/README.md) with the status code listed in api/main.py."""


class PlaylistError(Exception):
    """A request the service refuses, with a machine-readable code."""

    code = "PLAYLIST_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PlaylistNotFound(PlaylistError):
    code = "PLAYLIST_NOT_FOUND"


class SongNotInPlaylist(PlaylistError):
    code = "SONG_NOT_IN_PLAYLIST"


class SongAlreadyInPlaylist(PlaylistError):
    code = "SONG_ALREADY_IN_PLAYLIST"


class InvalidRequest(PlaylistError):
    code = "INVALID_REQUEST"


class SongNotFound(PlaylistError):
    """The Catalogue says the song does not exist, so it is not added."""

    code = "SONG_NOT_FOUND"


class CatalogueUnavailable(PlaylistError):
    """The Catalogue could not say whether the song exists. The add is refused
    rather than risking a song that cannot be played."""

    code = "CATALOGUE_UNAVAILABLE"
