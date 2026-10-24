"""Deterministic, explainable campus identity matcher (P2.3, ADR-014). Pure: no I/O, no models.

Identity is a physical campus, not a brand. The matcher never merges: its
strongest output for two different source identities is `suggest_review`,
which a human must confirm. Missing evidence stays `unknown`, never a match.
Features are scores and labels only; no upstream text is copied into them.
"""

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

ALGORITHM_VERSION = "campus-match-1.0"
Resolution = Literal["exact_reobservation", "suggest_review", "distinct", "insufficient_evidence"]

MAX_NAME = 250
NEAR_NAME = 0.88  # SequenceMatcher ratio on the core name, same script only
POINT_SAME_SITE_KM = 0.15
POINT_CONFLICT_KM = 0.5
AREA_CONFLICT_KM = 2.0
CO_LOCATED_KM = 0.05

# Generic words dropped only for the "core" comparison; originals are always kept.
_GENERIC = frozenset({"the", "school", "schools", "sch"})
# Tokens that identify a particular campus; a conflict between them means "different campus".
_BRANCH_WORDS = frozenset({"campus", "branch", "block", "phase", "sector", "town", "wing"})
_ROMAN_VALUE = {
    r: i for i, r in enumerate(("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"), 1)
}
_ROMAN = frozenset(_ROMAN_VALUE)
_NOT_BRANCH_NAMES = _BRANCH_WORDS | _GENERIC | {"no", "number", "num"}
_ARABIC_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭ]")
# Safe Arabic-script letter variants common in Urdu text (Arabic yeh/kaf/heh vs Urdu forms).
_ARABIC_VARIANTS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ"})


@dataclass(frozen=True)
class Side:
    """One side of a comparison: a staged candidate or an existing account (with its aliases)."""

    ref: str  # opaque id used only for ordering/explanations
    provider: str | None
    external_key: str | None
    names: tuple[str, ...]  # display name, local-script name, account aliases; originals
    city: str | None
    locality: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    precision: Literal["point", "area_center"] | None = None
    website_domain: str | None = None  # weak hint only; chains share domains


@dataclass(frozen=True)
class Match:
    resolution: Resolution
    reason_codes: tuple[str, ...]
    features: dict[str, str | float | None] = field(default_factory=dict)
    algorithm_version: str = ALGORITHM_VERSION


def _script(text: str) -> str:
    latin = arabic = 0
    for ch in text:
        if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ" or "ﭐ" <= ch <= "﻿":
            arabic += 1
        elif ch.isalpha():
            latin += 1
    if arabic and not latin:
        return "arabic"
    if latin and not arabic:
        return "latin"
    return "mixed" if latin and arabic else "none"


def tokens(name: str) -> list[str]:
    """NFKC, casefold, punctuation to spaces; digits and branch words are kept."""
    text = unicodedata.normalize("NFKC", name[:MAX_NAME]).casefold()
    text = _ARABIC_DIACRITICS.sub("", text).translate(_ARABIC_VARIANTS)
    kept = "".join(ch if ch.isalnum() else " " for ch in text)
    return kept.split()


def core(name: str) -> str:
    return " ".join(t for t in tokens(name) if t not in _GENERIC)


def branch_marks(name: str) -> tuple[frozenset[str], frozenset[str]]:
    """(numbers, words) that identify a campus: "No. 2", "Phase V" (= 5), "Gulberg Campus", "Johar Town"."""
    parts = tokens(name)
    numbers: set[str] = {str(int(t)) for t in parts if t.isdigit()}
    words: set[str] = set()
    for i, token in enumerate(parts):
        if token in _BRANCH_WORDS:
            neighbours = [parts[j] for j in (i - 1, i + 1) if 0 <= j < len(parts)]
            words.update(n for n in neighbours if n not in _NOT_BRANCH_NAMES and not n.isdigit())
        if token in _ROMAN and i > 0 and parts[i - 1] in _BRANCH_WORDS:
            numbers.add(str(_ROMAN_VALUE[token]))
            words.discard(token)
    return frozenset(numbers), frozenset(words)


def _branch(a: Side, b: Side) -> str:
    """'conflict' when both name a campus and the marks disagree; numbers must match exactly."""
    marks_a = [branch_marks(n) for n in a.names]
    marks_b = [branch_marks(n) for n in b.names]
    nums_a = frozenset().union(*(m[0] for m in marks_a)) if marks_a else frozenset()
    nums_b = frozenset().union(*(m[0] for m in marks_b)) if marks_b else frozenset()
    words_a = frozenset().union(*(m[1] for m in marks_a)) if marks_a else frozenset()
    words_b = frozenset().union(*(m[1] for m in marks_b)) if marks_b else frozenset()
    if (nums_a and nums_b and nums_a != nums_b) or (words_a and words_b and not words_a & words_b):
        return "conflict"
    if (nums_a and nums_a == nums_b) or (words_a & words_b):
        return "same"
    return "unknown"


def _norm_place(value: str | None) -> str | None:
    if value is None:
        return None
    joined = " ".join(tokens(value))
    return joined or None


def _distance_km(a: Side, b: Side) -> float | None:
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return None
    lat1, lon1, lat2, lon2 = (math.radians(float(v)) for v in (a.latitude, a.longitude, b.latitude, b.longitude))  # type: ignore[arg-type]
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371.0 * math.asin(min(1.0, math.sqrt(h))), 3)


def _best_name(a: Side, b: Side) -> tuple[str, float, str]:
    """Best same-script comparison: (label, ratio, script). Cross-script pairs are never compared."""
    best: tuple[str, float, str] = ("unknown", 0.0, "none")
    for left in a.names:
        for right in b.names:
            script_l, script_r = _script(left), _script(right)
            if script_l != script_r or script_l in ("none", "mixed"):
                continue
            core_l, core_r = core(left), core(right)
            if not core_l or not core_r:
                continue
            ratio = 1.0 if core_l == core_r else round(SequenceMatcher(None, core_l, core_r).ratio(), 3)
            label = "exact" if ratio == 1.0 else ("near" if ratio >= NEAR_NAME else "different")
            if ratio > best[1] or best[0] == "unknown":
                best = (label, ratio, script_l)
    return best


def compare(a: Side, b: Side) -> Match:
    features: dict[str, str | float | None] = {"buying_authority": "unknown"}  # a match never implies authority
    same_provider = a.provider is not None and a.provider == b.provider
    features["same_provider"] = "yes" if same_provider else "no"
    if same_provider and a.external_key is not None and a.external_key == b.external_key:
        return Match("exact_reobservation", ("same_provider_same_external_key",), features)

    city_a, city_b = _norm_place(a.city), _norm_place(b.city)
    features["city"] = "unknown" if not (city_a and city_b) else ("same" if city_a == city_b else "different")
    if features["city"] == "different":
        return Match("distinct", ("different_city",), features)

    label, ratio, script = _best_name(a, b)
    features |= {"name_match": label, "name_similarity": ratio, "name_script": script}
    features["branch"] = _branch(a, b)
    loc_a, loc_b = _norm_place(a.locality), _norm_place(b.locality)
    features["locality"] = "unknown" if not (loc_a and loc_b) else ("same" if loc_a == loc_b else "different")
    distance = _distance_km(a, b)
    features["distance_km"] = distance
    approximate = "area_center" in (a.precision, b.precision)
    features["location_precision"] = None if distance is None else ("approximate" if approximate else "point")
    if a.website_domain and b.website_domain:
        features["domain"] = "same" if a.website_domain.casefold() == b.website_domain.casefold() else "different"
    else:
        features["domain"] = "unknown"

    reasons: list[str] = []
    if features["domain"] == "same":
        reasons.append("shared_domain_weak")  # chains share domains: never evidence of one campus
    if features["city"] == "unknown":
        return Match("insufficient_evidence", ("missing_city", *reasons), features)
    if features["branch"] == "conflict":
        return Match("distinct", ("conflicting_branch", *reasons), features)
    if features["locality"] == "different":
        return Match("distinct", ("different_locality", *reasons), features)
    if distance is not None:
        if not approximate and distance > POINT_CONFLICT_KM:
            return Match("distinct", ("coordinate_conflict", *reasons), features)
        if approximate and distance > AREA_CONFLICT_KM:
            return Match("distinct", ("coordinate_conflict", *reasons), features)

    near_site = distance is not None and not approximate and distance <= POINT_SAME_SITE_KM
    if label == "unknown":
        return Match("insufficient_evidence", ("no_comparable_name_script", *reasons), features)
    if label == "different":
        if distance is not None and not approximate and distance <= CO_LOCATED_KM:
            return Match("suggest_review", ("co_located_different_names", *reasons), features)
        return Match("distinct", ("name_dissimilar", *reasons), features)

    reasons.insert(0, f"name_{label}")
    if features["domain"] == "same" and features["locality"] == "unknown" and distance is None:
        # A shared brand domain with no site evidence is how chains look: separate campuses until shown otherwise.
        return Match("distinct", (*reasons, "chain_without_site_evidence"), features)
    if same_provider:
        # The provider itself keeps two identities apart; same name/area alone cannot overrule it.
        return Match("insufficient_evidence", (*reasons, "same_provider_distinct_ids"), features)
    if features["locality"] == "same":
        return Match("suggest_review", (*reasons, "same_locality"), features)
    if near_site:
        return Match("suggest_review", (*reasons, "coordinates_near"), features)
    if distance is not None and approximate:
        return Match("insufficient_evidence", (*reasons, "area_center_ambiguous"), features)
    return Match("insufficient_evidence", (*reasons, "locality_unknown"), features)


def block_keys(side: Side) -> set[str]:
    """Blocking keys: (city, core token). Pairs are proposed only when they share one."""
    city = _norm_place(side.city) or "?"
    keys = {f"{city}|{t}" for name in side.names for t in core(name).split() if len(t) > 1}
    return keys


def candidate_pairs(sides: Iterable[Side], max_block: int = 60) -> tuple[list[tuple[Side, Side]], int]:
    """Local blocking by city + name token. Blocks larger than `max_block` (very common tokens such as
    "public") are skipped and counted; pairs that share only such tokens are not proposed (documented limit)."""
    ordered = sorted(sides, key=lambda s: s.ref)
    blocks: dict[str, list[Side]] = {}
    for side in ordered:
        for key in block_keys(side):
            blocks.setdefault(key, []).append(side)
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[Side, Side]] = []
    skipped = 0
    for members in blocks.values():
        if len(members) > max_block:
            skipped += 1
            continue
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                pair_key = (left.ref, right.ref)
                if left.ref != right.ref and pair_key not in seen:
                    seen.add(pair_key)
                    pairs.append((left, right))
    return sorted(pairs, key=lambda p: (p[0].ref, p[1].ref)), skipped
