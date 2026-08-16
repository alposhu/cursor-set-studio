"""Filename-to-role matching.

A keyword and substring heuristic, deliberately not machine learning: the
scoring below is meant to be readable and adjustable. Anything that does not
clear MATCH_THRESHOLD stays unassigned rather than being forced into the
nearest-sounding role.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .models import (ALL_ROLES, Assignment, Confidence, CursorFile, CursorRole,
                     FileKind)

# Score floor for a match to count at all.
MATCH_THRESHOLD = 55.0
# A match at or above this, with no close rival, is treated as confident.
HIGH_CONFIDENCE = 85.0
# A rival within this many points makes an otherwise-strong match ambiguous.
RIVAL_MARGIN = 12.0

# Points by match quality.
SCORE_EXACT_TOKEN = 100.0   # a whole token is exactly the keyword
SCORE_EXACT_NGRAM = 95.0    # adjacent tokens joined equal the keyword
SCORE_TOKEN_PREFIX = 70.0   # token starts with the keyword, or vice versa
SCORE_SUBSTRING = 60.0      # keyword appears somewhere in the joined name

SPECIFICITY_WEIGHT = 0.5    # per keyword character, to break within-tier ties

BONUS_ANIMATED = 8.0        # .ani offered to a role that expects animation
BONUS_PARENT_DIR = 4.0      # the containing folder names the role too
PENALTY_SIZE_VARIANT = 6.0  # prefer "arrow.cur" over "arrow_xl.cur"

# Suffix tokens marking an alternate size or inverted variant of the same art.
SIZE_VARIANT_TOKENS = {"l", "xl", "xxl", "s", "m", "lg", "sm",
                       "large", "small", "medium", "il", "im", "ixl"}

# Substring/prefix matching below this keyword length is too loose to trust:
# it is what turns "normal" into a match for the "no" role.
MIN_FUZZY_KEYWORD_LEN = 4

_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_DIGIT_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")


@dataclass
class Normalized:
    tokens: list[str]
    ngrams: set[str]
    joined: str


def normalize(name: str) -> Normalized:
    """Turn a filename into tokens for matching.

    Splits on separators, camelCase boundaries, and letter/digit boundaries,
    then adds joined pairs and triples so that "size_all" can still match the
    keyword "sizeall".
    """
    stem = Path(name).stem
    spaced = _CAMEL_RE.sub(" ", stem)
    spaced = _DIGIT_BOUNDARY_RE.sub(" ", spaced.lower())
    tokens = [t for t in _SPLIT_RE.split(spaced) if t]

    ngrams: set[str] = set(tokens)
    for n in (2, 3):
        for i in range(len(tokens) - n + 1):
            ngrams.add("".join(tokens[i:i + n]))
    ngrams.add("".join(tokens))

    # A trailing number is often semantic rather than a frame index
    # ("Diagonal Resize 1"), so also offer each word glued to it. Frame runs
    # are unaffected: "busy_01" still carries "busy" as a plain token.
    if len(tokens) > 1 and tokens[-1].isdigit():
        for t in tokens[:-1]:
            ngrams.add(t + tokens[-1])

    return Normalized(tokens=tokens, ngrams=ngrams, joined="".join(tokens))


def score_role(cf: CursorFile, role: CursorRole,
               norm: Optional[Normalized] = None) -> float:
    """Score how well one file fits one role. 0 means no match at all."""
    norm = norm or normalize(cf.name)
    best = 0.0

    for kw in role.keywords:
        # A longer keyword is a more specific claim on the name, so it breaks
        # ties within a tier: "uparrow" must outrank "arrow" on up_arrow.cur.
        # The bonus is far smaller than the gap between tiers, so it can never
        # let a weak match overtake a strong one.
        specificity = len(kw) * SPECIFICITY_WEIGHT

        if kw in norm.tokens:
            best = max(best, SCORE_EXACT_TOKEN + specificity)
            continue
        if kw in norm.ngrams:
            best = max(best, SCORE_EXACT_NGRAM + specificity)
            continue
        if len(kw) >= MIN_FUZZY_KEYWORD_LEN:
            if any(t.startswith(kw) or (len(t) >= MIN_FUZZY_KEYWORD_LEN
                                        and kw.startswith(t))
                   for t in norm.tokens):
                best = max(best, SCORE_TOKEN_PREFIX + specificity)
            elif kw in norm.joined:
                best = max(best, SCORE_SUBSTRING + specificity)

    if best <= 0:
        return 0.0

    if role.prefers_animation and cf.is_animated:
        best += BONUS_ANIMATED

    if any(t in SIZE_VARIANT_TOKENS for t in norm.tokens):
        best -= PENALTY_SIZE_VARIANT

    # A folder named after the role is weak but real evidence.
    parent = cf.path.parent.name.lower()
    if parent and any(kw in parent for kw in role.keywords
                      if len(kw) >= MIN_FUZZY_KEYWORD_LEN):
        best += BONUS_PARENT_DIR

    return max(best, 0.0)


@dataclass
class MatchResult:
    assignments: dict[str, Assignment]      # registry name -> Assignment
    unassigned: list[CursorFile]            # everything left over

    @property
    def matched_count(self) -> int:
        return sum(1 for a in self.assignments.values() if a.filled)

    @property
    def confident_count(self) -> int:
        return sum(1 for a in self.assignments.values()
                   if a.confidence is Confidence.HIGH)

    @property
    def core_matched(self) -> int:
        return sum(1 for a in self.assignments.values()
                   if a.filled and a.role.core)


def match_files(
    files: Sequence[CursorFile],
    roles: Iterable[CursorRole] = ALL_ROLES,
    *,
    include_convertibles: bool = False,
) -> MatchResult:
    """Assign files to roles by score, best match first.

    Every file is accounted for: anything not assigned comes back in
    `unassigned` so the UI can show it. Nothing is ever silently dropped.
    """
    roles = list(roles)
    assignments = {r.registry_name: Assignment(role=r) for r in roles}

    eligible = [
        f for f in files
        if f.ok and (include_convertibles
                     or f.kind is not FileKind.CONVERTIBLE
                     or f.convert_opted_in)
    ]

    # Score every eligible file against every role once.
    norms = {f.path: normalize(f.name) for f in eligible}
    scored: list[tuple[float, CursorFile, CursorRole]] = []
    by_role: dict[str, list[tuple[float, CursorFile]]] = {
        r.registry_name: [] for r in roles}

    for f in eligible:
        for r in roles:
            s = score_role(f, r, norms[f.path])
            if s >= MATCH_THRESHOLD:
                scored.append((s, f, r))
                by_role[r.registry_name].append((s, f))

    for lst in by_role.values():
        lst.sort(key=lambda p: -p[0])

    # Greedy global assignment: strongest pairing wins, then the next
    # strongest among what is left. Ties break on filename for determinism.
    scored.sort(key=lambda t: (-t[0], t[1].name.lower(), t[2].registry_name))

    used: set[Path] = set()
    for s, f, r in scored:
        slot = assignments[r.registry_name]
        if slot.filled or f.path in used:
            continue
        slot.file = f
        slot.score = s
        used.add(f.path)

    # Confidence, and the rival list that justifies a "needs a look" badge.
    #
    # Only files still sitting in the pool count as rivals. One that landed in
    # another role is not an unresolved alternative - it already has a home,
    # and flagging it here would mark a perfectly clean pack as uncertain
    # (UpArrow.cur tokenises to "up"+"arrow", so it ties with Arrow.cur for
    # the Arrow role even though both end up correctly placed).
    for slot in assignments.values():
        if not slot.filled:
            continue
        rivals = [f for s, f in by_role[slot.role.registry_name]
                  if f.path != slot.file.path and f.path not in used
                  and s >= slot.score - RIVAL_MARGIN]
        slot.rivals = rivals[:4]
        strong = slot.score >= HIGH_CONFIDENCE
        slot.confidence = (Confidence.HIGH if strong and not rivals
                           else Confidence.LOW)

    unassigned = [f for f in files if f.path not in used]
    unassigned.sort(key=lambda f: (not f.ok, f.name.lower()))

    return MatchResult(assignments=assignments, unassigned=unassigned)


def best_roles_for(cf: CursorFile, limit: int = 5) -> list[tuple[CursorRole, float]]:
    """Rank the roles a single file could fill, for the reassign menu."""
    norm = normalize(cf.name)
    ranked = [(r, score_role(cf, r, norm)) for r in ALL_ROLES]
    ranked = [(r, s) for r, s in ranked if s > 0]
    ranked.sort(key=lambda p: -p[1])
    return ranked[:limit]
