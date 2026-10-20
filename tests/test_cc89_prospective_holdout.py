"""Prospective source selection must not lose Fab cases in the general pool."""

import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace


def test_fab_seen_in_general_search_is_still_screened_as_a_cdr_source(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    builder = importlib.import_module("build_cc89_prospective_holdout")
    monkeypatch.setattr(builder, "history", lambda: ({"1OLD"}, {"AAAAAAAAAA"}))
    metadata = {"data": {"polymer_entities": [{
        "rcsb_id": "9ABC_1",
        "entry": {"rcsb_accession_info": {"initial_release_date": "2026-09-15"}},
        "polymer_entity_instances": [{"rcsb_id": "9ABC.H", "rcsb_polymer_entity_instance_container_identifiers": {"auth_asym_id": "H"}}],
    }]}}
    monkeypatch.setattr(builder, "post_json", lambda url, payload:
        {"result_set": ["9ABC_1"]} if url == builder.SEARCH_URL else metadata)
    monkeypatch.setattr(builder, "urlopen", lambda *args, **kwargs: io.BytesIO(b"synthetic deposited source"))
    monkeypatch.setattr(builder.gemmi, "read_structure", lambda path: object())
    monkeypatch.setattr(builder, "inspect_observed_protein", lambda structure: {
        "supported": True, "reasons": [], "sequences": {"H": "ACDEFGHIKL", "L": "MNPQRSTVWY"},
    })
    monkeypatch.setattr(builder, "normalize_structure", lambda source, destination:
        SimpleNamespace(pdb_path=source, chain_map={}))
    monkeypatch.setattr(builder, "sanitize_protein_hetatm", lambda path: path)
    monkeypatch.setattr(builder, "prepare_intact_pdb", lambda text:
        (b"preserved synthetic reference\n", {"native_breaks": [], "alternative_conformer_atoms_removed": 0}))
    monkeypatch.setattr(builder, "antibody_domains", lambda sequences:
        [{"chain": "H", "chain_type": "H"}, {"chain": "L", "chain_type": "K"}])

    def reject_general_filter(*args):
        raise AssertionError("a Fab must not be screened with the general-protein homology cutoff")

    monkeypatch.setattr(builder, "sequence_overlap", reject_general_filter)
    args = SimpleNamespace(sources=tmp_path / "sources", source_manifest=tmp_path / "manifest.json",
        start_date="2026-01-01", antibody_start_date="2020-01-01", antibody_identity=95)
    builder.screen(args)
    manifest = json.loads(args.source_manifest.read_text())
    general, antibody = manifest["cases"]
    assert general["source_id"] == antibody["source_id"] == "9ABC"
    assert general["status"] == "unsupported"
    assert general["reasons"] == ["antibody-source-reserved-for-cdr-stratum"]
    assert antibody["status"] == "source-eligible"
    assert antibody["domains"] == [{"chain": "H", "chain_type": "H"}, {"chain": "L", "chain_type": "K"}]
