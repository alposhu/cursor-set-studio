"""Data model for Cursor Set Studio.

The role table below is the single source of truth for everything the app
knows about Windows cursor roles: registry value names, matching keywords,
and hotspot defaults.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class Confidence(enum.IntEnum):
    """How much we trust an automatic match."""

    UNASSIGNED = 0
    LOW = 1      # matched, but ambiguous or weak - flag it visually
    HIGH = 2     # clean, unambiguous match
    MANUAL = 3   # the user placed it themselves; never second-guess

    @property
    def label(self) -> str:
        return {
            Confidence.UNASSIGNED: "Unassigned",
            Confidence.LOW: "Uncertain",
            Confidence.HIGH: "Matched",
            Confidence.MANUAL: "Manual",
        }[self]


class HotspotDefault(enum.Enum):
    """Where to put the hotspot when converting an image that carries none."""

    TOP_LEFT = "top_left"
    CENTER = "center"


@dataclass(frozen=True)
class CursorRole:
    """One of the cursor roles Windows knows about."""

    registry_name: str          # REG_SZ value name under Control Panel\\Cursors
    display_name: str           # what Windows Mouse Properties calls it
    keywords: tuple[str, ...]   # matching vocabulary, best-first
    hotspot_default: HotspotDefault = HotspotDefault.CENTER
    prefers_animation: bool = False
    core: bool = True           # False for the Win10/11 best-effort extras
    description: str = ""

    @property
    def key(self) -> str:
        return self.registry_name


# The 15 core roles, in the order Mouse Properties lists them. Each keyword
# tuple leads with the registry name itself, since packs very often name
# their files after it.
CORE_ROLES: tuple[CursorRole, ...] = (
    CursorRole(
        "Arrow", "Normal Select",
        ("arrow", "normal", "default", "pointer", "main", "standard",
         "regular", "normalselect"),
        HotspotDefault.TOP_LEFT,
        description="The everyday pointer.",
    ),
    CursorRole(
        "Help", "Help Select",
        ("help", "question", "qmark", "whatsthis", "helpselect"),
        HotspotDefault.TOP_LEFT,
        description="Pointer with a question mark.",
    ),
    CursorRole(
        "AppStarting", "Working in Background",
        ("appstarting", "working", "workinbg", "bgtask", "loadingsmall",
         "background", "startup", "launch"),
        HotspotDefault.TOP_LEFT,
        prefers_animation=True,
        description="Pointer plus a spinner.",
    ),
    CursorRole(
        "Wait", "Busy",
        ("wait", "busy", "hourglass", "loading", "spinner", "spin", "progress"),
        HotspotDefault.CENTER,
        prefers_animation=True,
        description="The system is busy.",
    ),
    CursorRole(
        "Crosshair", "Precision Select",
        ("crosshair", "cross", "precision", "plus", "target", "cros"),
        HotspotDefault.CENTER,
        description="Precision crosshair.",
    ),
    CursorRole(
        "IBeam", "Text Select",
        ("ibeam", "text", "beam", "ibea", "caret", "edit"),
        HotspotDefault.CENTER,
        description="The text-editing I-beam.",
    ),
    CursorRole(
        "NWPen", "Handwriting",
        ("nwpen", "pen", "handwriting", "write", "ink", "pencil"),
        HotspotDefault.TOP_LEFT,
        description="Pen / handwriting input.",
    ),
    CursorRole(
        "No", "Unavailable",
        ("no", "unavailable", "forbidden", "denied", "block", "banned",
         "unavail", "nodrop", "notallowed"),
        HotspotDefault.CENTER,
        description="Action not allowed.",
    ),
    CursorRole(
        "SizeNS", "Vertical Resize",
        ("sizens", "ns", "vertical", "vert", "resizev", "updown", "northsouth"),
        HotspotDefault.CENTER,
        description="Resize up and down.",
    ),
    CursorRole(
        "SizeWE", "Horizontal Resize",
        ("sizewe", "sizeew", "we", "ew", "horizontal", "horz", "resizeh",
         "leftright", "eastwest"),
        HotspotDefault.CENTER,
        description="Resize left and right.",
    ),
    CursorRole(
        "SizeNWSE", "Diagonal Resize 1",
        ("sizenwse", "nwse", "diagonal1", "diag1"),
        HotspotDefault.CENTER,
        description="Resize along the top-left / bottom-right diagonal.",
    ),
    CursorRole(
        "SizeNESW", "Diagonal Resize 2",
        ("sizenesw", "nesw", "diagonal2", "diag2"),
        HotspotDefault.CENTER,
        description="Resize along the top-right / bottom-left diagonal.",
    ),
    CursorRole(
        "SizeAll", "Move",
        ("sizeall", "move", "drag", "pan", "allsize", "fleur"),
        HotspotDefault.CENTER,
        description="Move or pan in any direction.",
    ),
    CursorRole(
        "UpArrow", "Alternate Select",
        ("uparrow", "alternate", "altselect", "alt", "up"),
        HotspotDefault.TOP_LEFT,
        description="The upward alternate-select arrow.",
    ),
    CursorRole(
        "Hand", "Link Select",
        ("hand", "link", "hyperlink", "click", "pointinghand", "linkselect"),
        HotspotDefault.TOP_LEFT,
        description="The hand shown over links.",
    ),
)

# Windows 10/11 extras. Supported when present, never required.
EXTRA_ROLES: tuple[CursorRole, ...] = (
    CursorRole(
        "Pin", "Location Select",
        ("pin", "location", "gps", "locationselect", "place"),
        HotspotDefault.TOP_LEFT,
        core=False,
        description="Location pin (Windows 10/11).",
    ),
    CursorRole(
        "Person", "Person Select",
        ("person", "user", "contact", "avatar", "personselect"),
        HotspotDefault.TOP_LEFT,
        core=False,
        description="Person select (Windows 10/11).",
    ),
)

ALL_ROLES: tuple[CursorRole, ...] = CORE_ROLES + EXTRA_ROLES
ROLES_BY_KEY: dict[str, CursorRole] = {r.registry_name: r for r in ALL_ROLES}


def role(key: str) -> CursorRole:
    return ROLES_BY_KEY[key]


CURSOR_EXTENSIONS = {".cur", ".ani"}
CONVERTIBLE_EXTENSIONS = {".png", ".ico"}


class FileKind(enum.Enum):
    STATIC = "cur"        # .cur
    ANIMATED = "ani"      # .ani
    CONVERTIBLE = "img"   # .png / .ico - needs an opt-in conversion


@dataclass
class CursorFile:
    """A single scanned file that could fill a role."""

    path: Path
    kind: FileKind
    # Filled in lazily by cursor_io. These stay None if the file turned out
    # to be unreadable, in which case `error` explains why.
    width: Optional[int] = None
    height: Optional[int] = None
    hotspot: Optional[tuple[int, int]] = None
    frame_count: int = 1
    error: Optional[str] = None
    # Set when this entry stands in for a run of numbered frame files.
    sequence_paths: list[Path] = field(default_factory=list)
    # True once the user has opted this convertible image in.
    convert_opted_in: bool = False

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def is_sequence(self) -> bool:
        return len(self.sequence_paths) > 1

    @property
    def is_animated(self) -> bool:
        return self.kind is FileKind.ANIMATED or self.is_sequence

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def display_label(self) -> str:
        if self.is_sequence:
            return f"{self.stem} ({len(self.sequence_paths)} frames)"
        return self.name

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CursorFile) and other.path == self.path


@dataclass
class Assignment:
    """A role slot, and whatever currently fills it."""

    role: CursorRole
    file: Optional[CursorFile] = None
    confidence: Confidence = Confidence.UNASSIGNED
    score: float = 0.0
    # Other files that scored close enough to be worth surfacing.
    rivals: list[CursorFile] = field(default_factory=list)
    # Overridden hotspot, used for converted images.
    hotspot_override: Optional[tuple[int, int]] = None

    @property
    def filled(self) -> bool:
        return self.file is not None

    def clear(self) -> None:
        self.file = None
        self.confidence = Confidence.UNASSIGNED
        self.score = 0.0
        self.rivals = []
        self.hotspot_override = None


@dataclass
class SchemeRecord:
    """A scheme this app has built, as stored in the library index."""

    name: str
    created: str              # ISO-8601
    directory: str            # where the managed copies live
    roles: dict[str, str]     # registry name -> absolute file path
    thumbnail: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "created": self.created,
            "directory": self.directory,
            "roles": self.roles,
            "thumbnail": self.thumbnail,
        }

    @staticmethod
    def from_json(d: dict) -> "SchemeRecord":
        return SchemeRecord(
            name=d["name"],
            created=d.get("created", ""),
            directory=d.get("directory", ""),
            roles=d.get("roles", {}),
            thumbnail=d.get("thumbnail"),
        )
