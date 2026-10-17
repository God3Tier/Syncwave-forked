"""Validates and parses timestamped lyrics in LRC format.

    [ti:Song title]           ID tags: ignored, except [offset:]
    [offset:+250]             show every line 250 ms earlier (negative: later)
    [00:12.34]First line      time tag [mm:ss], [mm:ss.x], [mm:ss.xx] or [mm:ss.xxx]
    [00:15.00][01:30.00]Hook  several time tags can share one line of text
    [00:20.00]                no text: an instrumental break

Word-level <mm:ss.xx> tags (enhanced LRC) are removed from the text. Lines
without a time tag are ignored. Every failure is permanent: the same file
would fail again on retry.
"""

import re
from dataclasses import dataclass

from lyrics_service.shared.errors import PermanentError

_TAG = re.compile(r"\s*\[([^\[\]]*)\]")
_TIME = re.compile(r"(\d+):(\d+)(?:[.:](\d{1,3}))?")
_LOOKS_LIKE_TIME = re.compile(r"\d+:.*")
_ID_TAG = re.compile(r"([A-Za-z#]+):(.*)")
_OFFSET = re.compile(r"[+-]?\d+")
_WORD_TIME = re.compile(r"<\d+:\d+(?:[.:]\d{1,3})?>")


@dataclass(frozen=True, slots=True)
class LyricLine:
    time_ms: int
    text: str

    def as_dict(self) -> dict[str, int | str]:
        return {"time_ms": self.time_ms, "text": self.text}


def parse(raw: bytes) -> list[LyricLine]:
    """Returns the lyric lines sorted by time (stable for equal times)."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PermanentError(
            "LYRICS_INVALID_ENCODING", f"the lyrics file is not valid UTF-8: {exc}"
        ) from exc

    offset_ms = 0
    lines: list[LyricLine] = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        times: list[int] = []
        position = 0
        while match := _TAG.match(line, position):
            content = match.group(1).strip()
            if time := _TIME.fullmatch(content):
                times.append(_to_ms(time, number, content))
            elif _LOOKS_LIKE_TIME.fullmatch(content):
                raise PermanentError(
                    "LYRICS_INVALID", f"line {number}: invalid time tag [{content}]"
                )
            elif not times and (tag := _ID_TAG.fullmatch(content)):
                if tag.group(1).lower() == "offset":
                    offset_ms = _to_offset(tag.group(2).strip(), number)
                break
            else:
                break  # text that starts with brackets, e.g. "[Chorus]"
            position = match.end()
        if times:
            lyric = _WORD_TIME.sub("", line[position:]).strip()
            lines.extend(LyricLine(time_ms, lyric) for time_ms in times)

    if not lines:
        raise PermanentError(
            "LYRICS_NOT_TIMESTAMPED", "the lyrics file has no [mm:ss.xx] time tags"
        )
    shifted = (LyricLine(max(0, line.time_ms - offset_ms), line.text) for line in lines)
    return sorted(shifted, key=lambda line: line.time_ms)


def _to_ms(match: re.Match[str], number: int, content: str) -> int:
    minutes, seconds, fraction = match.groups()
    if int(seconds) >= 60:
        raise PermanentError(
            "LYRICS_INVALID",
            f"line {number}: invalid time tag [{content}] (seconds must be below 60)",
        )
    # "5" is 500 ms, "34" is 340 ms, "345" is 345 ms
    milliseconds = int((fraction or "0").ljust(3, "0"))
    return (int(minutes) * 60 + int(seconds)) * 1000 + milliseconds


def _to_offset(value: str, number: int) -> int:
    if not _OFFSET.fullmatch(value):
        raise PermanentError(
            "LYRICS_INVALID", f"line {number}: [offset:{value}] is not a whole number of ms"
        )
    return int(value)
