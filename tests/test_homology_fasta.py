from dvbfixer.homology import parse_fasta_chains


def test_vh_vl_headers_map_to_unique_output_chains(tmp_path):
    fasta = tmp_path / "target.fasta"
    fasta.write_text(">VH\nAA\n>VL\nGG\n")
    assert parse_fasta_chains(fasta) == [("H", "AA"), ("L", "GG")]


def test_mosaic_logical_target_ids_are_preserved_case_sensitively(tmp_path):
    fasta = tmp_path / "target.fasta"
    fasta.write_text(">VH\nAA\n>VL\nGG\n>vh\nCC\n")
    assert parse_fasta_chains(fasta, logical_ids=True) == [("VH", "AA"), ("VL", "GG"), ("vh", "CC")]
