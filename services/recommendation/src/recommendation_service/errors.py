"""Failures the API reports. Each carries its HTTP status and error code
(contracts/api/recommendation.openapi.yaml)."""


class RecommendationError(Exception):
    status_code = 500
    code = "RECOMMENDATION_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidRequest(RecommendationError):
    status_code = 400
    code = "INVALID_REQUEST"


class CatalogueUnavailable(RecommendationError):
    """The Catalogue could not supply songs. There is nothing to recommend, so
    this is the one dependency failure that is an error."""

    status_code = 502
    code = "CATALOGUE_UNAVAILABLE"


class WeatherUnavailable(Exception):
    """The weather could not be fetched. Never shown to the caller: the service
    falls back to recommendations without weather."""
