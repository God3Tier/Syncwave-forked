"""Error types shared by the Search Service."""


class PermanentError(Exception):
    """A failure that will not succeed by retrying (bad payload, missing song)."""


class TransientError(Exception):
    """A failure that may succeed on retry (Catalogue down, database hiccup)."""
