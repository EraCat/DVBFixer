"""Admission boundaries are shared by CLI, mosaic construction, and scope."""

from types import MappingProxyType

import pytest

from dvbfixer.model.diffusion import gap_capabilities as capabilities


@pytest.mark.parametrize("length", [False, True, 3.0, "3", -1, 0, None])
def test_invalid_lengths_cannot_be_accepted(length):
    result = capabilities.gap_capability("protenix-v1-cuda", length)
    assert not result.accepted and not result.research_eligible
    assert result.reason == "invalid-gap-length"


@pytest.mark.parametrize("profile", ["protenix-v1-cuda", "protpardelle-1c-mps"])
def test_current_public_ranges_remain_separate_from_long_gap_research(profile):
    assert capabilities.accepted_gap_range_label(profile) == "3-12"
    assert all(capabilities.gap_capability(profile, length).accepted for length in range(3, 13))
    for length in (13, 25, 26, 50):
        result = capabilities.gap_capability(profile, length)
        assert result.research_eligible and not result.accepted
    assert not capabilities.gap_capability(profile, 51).research_eligible


def test_profile_expansion_cannot_leak_to_other_adapters(monkeypatch):
    monkeypatch.setattr(capabilities, "ACCEPTED_INTERNAL_RANGES", MappingProxyType({
        "protenix-v1-cuda": ((3, 12), (13, 25)), "protpardelle-1c-mps": ((3, 12),),
    }))
    assert capabilities.accepted_gap_range_label("protenix-v1-cuda") == "3-12, 13-25"
    accepted = capabilities.gap_capability("protenix-v1-cuda", 25)
    assert accepted.accepted and accepted.stratum == "research-13-25"
    assert not capabilities.gap_capability("protpardelle-1c-mps", 25).accepted
    assert not capabilities.gap_capability("internal-adapter", 25).accepted


def test_public_ranges_cannot_be_mutated_in_place():
    with pytest.raises(TypeError):
        capabilities.ACCEPTED_INTERNAL_RANGES["protenix-v1-cuda"] = ((3, 50),)
