"""Readable usernames for guests, such as "SunnyOtter27", instead of id prefixes.

The browser picks a name from the same word lists (frontend/src/guestName.ts)
and sends it when it joins, so the sidebar and the Jam show the same name. A
name the browser sends is accepted only in this shape, and only if no one in
the Jam already uses it; otherwise the service picks one itself.
"""

import re
import secrets
from collections.abc import Iterable

ADJECTIVES = (
    "Amber", "Breezy", "Bright", "Calm", "Clever", "Cosmic", "Dreamy", "Electric",
    "Fuzzy", "Gentle", "Golden", "Happy", "Jazzy", "Jolly", "Lucky", "Mellow",
    "Misty", "Neon", "Quiet", "Rapid", "Rosy", "Silver", "Sleepy", "Snappy",
    "Sonic", "Sunny", "Swift", "Velvet", "Witty", "Zesty",
)  # fmt: skip

ANIMALS = (
    "Badger", "Bear", "Beaver", "Crane", "Dolphin", "Falcon", "Ferret", "Finch",
    "Fox", "Gecko", "Heron", "Koala", "Lemur", "Lynx", "Moose", "Narwhal",
    "Octopus", "Otter", "Owl", "Panda", "Puffin", "Quokka", "Raven", "Robin",
    "Seal", "Sparrow", "Tiger", "Turtle", "Walrus", "Wombat",
)  # fmt: skip

GUEST_NAME_PATTERN = r"^[A-Z][a-z]{2,9}[A-Z][a-z]{2,9}[0-9]{2}$"
_GUEST_NAME = re.compile(GUEST_NAME_PATTERN)
_ATTEMPTS = 50


def is_guest_name(value: str) -> bool:
    return bool(_GUEST_NAME.fullmatch(value))


def random_guest_name() -> str:
    return secrets.choice(ADJECTIVES) + secrets.choice(ANIMALS) + f"{secrets.randbelow(100):02d}"


def pick_guest_name(requested: str | None, taken: Iterable[str]) -> str:
    """The requested name if it is valid and free in this Jam, else a free random one."""
    used = {name.casefold() for name in taken}
    if requested and is_guest_name(requested) and requested.casefold() not in used:
        return requested
    for _ in range(_ATTEMPTS):
        name = random_guest_name()
        if name.casefold() not in used:
            return name
    # 90 000 combinations; a Jam this full still gets a name rather than an error.
    return f"{random_guest_name()}{secrets.randbelow(10_000):04d}"
