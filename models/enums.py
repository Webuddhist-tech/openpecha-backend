from __future__ import annotations

from enum import StrEnum


class ContributorRole(StrEnum):
    TRANSLATOR = "translator"
    REVISER = "reviser"
    AUTHOR = "author"
    SCHOLAR = "scholar"
    NARRATOR = "narrator"


class AudioFormat(StrEnum):
    MP3 = "mp3"
    WAV = "wav"
    M4A = "m4a"
    OGG = "ogg"
    FLAC = "flac"

    @classmethod
    def from_content_type(cls, content_type: str | None) -> AudioFormat | None:
        """Map an upload's content type to a format, ignoring any parameters such as codecs."""
        if not content_type:
            return None
        return _FORMAT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower())

    @property
    def content_type(self) -> str:
        """The canonical content type to store the audio under."""
        return _CONTENT_TYPES[self][0]


# Accepted content types per format, canonical one first.
_CONTENT_TYPES: dict[AudioFormat, tuple[str, ...]] = {
    AudioFormat.MP3: ("audio/mpeg", "audio/mp3"),
    AudioFormat.WAV: ("audio/wav", "audio/wave", "audio/x-wav"),
    AudioFormat.M4A: ("audio/mp4", "audio/m4a", "audio/x-m4a"),
    AudioFormat.OGG: ("audio/ogg", "audio/vorbis"),
    AudioFormat.FLAC: ("audio/flac", "audio/x-flac"),
}

_FORMAT_BY_CONTENT_TYPE: dict[str, AudioFormat] = {
    content_type: audio_format for audio_format, types in _CONTENT_TYPES.items() for content_type in types
}


class EditionType(StrEnum):
    DIPLOMATIC = "diplomatic"
    CRITICAL = "critical"
    COLLATED = "collated"


class LicenseType(StrEnum):
    # based on https://creativecommons.org/licenses/
    CC0 = "cc0"
    PUBLIC_DOMAIN_MARK = "public"
    CC_BY = "cc-by"
    CC_BY_SA = "cc-by-sa"
    CC_BY_ND = "cc-by-nd"
    CC_BY_NC = "cc-by-nc"
    CC_BY_NC_SA = "cc-by-nc-sa"
    CC_BY_NC_ND = "cc-by-nc-nd"
    UNDER_COPYRIGHT = "copyrighted"
    UNKNOWN = "unknown"


class NoteType(StrEnum):
    DURCHEN = "durchen"


class MarkType(StrEnum):
    YIGCHUNG = "yigchung"


class BibliographyType(StrEnum):
    COLOPHON = "colophon"
    INCIPIT = "incipit"
    ALT_INCIPIT = "alt_incipit"
    ALT_TITLE = "alt_title"
    PERSON = "person"
    TITLE = "title"
    AUTHOR = "author"


class AttributeType(StrEnum):
    OCR_CONFIDENCE = "ocr_confidence"


class SegmentType(StrEnum):
    PARAGRAPH = "paragraph"
    VERSE = "verse"
    TITLE = "title"
    BACK_MATTER = "back_matter"
    FRONT_MATTER = "front_matter"
    TOP_SEGMENT = "top_segment"
