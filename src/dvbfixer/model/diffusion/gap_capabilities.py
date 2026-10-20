"""Profile-specific evidence boundaries, separate from research input capacity."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class GapCapability:
    stratum: str
    accepted: bool
    research_eligible: bool
    reason: str


ACCEPTED_INTERNAL_RANGES = MappingProxyType({
    "protpardelle-1c-cuda": ((5, 10),),
    "protpardelle-1c-mps-local-v1": ((5, 10),),
    "protenix-v1-cuda": ((3, 12),),
    "protpardelle-1c-mps": ((3, 12),),
})


def accepted_gap_ranges(profile: str) -> tuple[tuple[int, int], ...]:
    """Return the immutable public length boundary used by all request builders.

    Unnamed/internal test adapters retain the initial baseline. They cannot
    inherit a future expansion accepted for a named hardware profile.
    """
    return ACCEPTED_INTERNAL_RANGES.get(profile, ((3, 12),))


def accepted_gap_range_label(profile: str) -> str:
    return ", ".join(f"{start}-{stop}" for start, stop in accepted_gap_ranges(profile))


def gap_capability(profile: str, length: int) -> GapCapability:
    """Longer inputs require a separately frozen study, never inherited acceptance."""
    if type(length) is not int or length < 1:
        return GapCapability("unsupported", False, False, "invalid-gap-length")
    accepted_ranges = accepted_gap_ranges(profile)
    if any(start <= length <= stop for start, stop in accepted_ranges):
        stratum = "baseline-3-12" if length <= 12 else "research-13-25" if length <= 25 else "research-26-50"
        return GapCapability(stratum, True, True, "accepted-profile-range")
    if 13 <= length <= 25:
        return GapCapability("research-13-25", False, True, "long-gap-stratum-not-promoted")
    if 26 <= length <= 50:
        return GapCapability("research-26-50", False, True, "high-cost-long-gap-stratum-not-promoted")
    return GapCapability("unsupported", False, False, "outside-declared-reconstruction-strata")
