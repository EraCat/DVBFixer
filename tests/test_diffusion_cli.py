"""Tests for the narrow ``model --backend diffusion`` CLI slice."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from dvbfixer.model.cli import parse_args
from dvbfixer.model.diffusion.contract import GapKind
from dvbfixer.model.diffusion.preflight import (
    AdapterPreflightCode,
    AdapterPreflightIssue,
    RunnerPreflightFacts,
    RunnerPreflightReport,
)
from dvbfixer.model.diffusion.runtime import DiffusionRuntime
from dvbfixer.model.diffusion.scope import assess_diffusion_scope
from dvbfixer.model.diffusion_cli import (
    DiffusionCliError,
    build_cli_diffusion_request,
    run_diffusion_model,
)

FIXTURE = Path(__file__).parent / "fixtures" / "8cz8" / "8cz8_a_u.pdb"


def _gap_input(tmp_path: Path) -> Path:
    generated = {str(number) for number in range(65, 70)}
    selected = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True):
        if not line.startswith("ATOM  ") or line[21] != "C":
            continue
        number = line[22:26].strip()
        if number not in {str(value) for value in range(61, 74)} or number in generated:
            continue
        selected.append(line)
    path = tmp_path / "gap.pdb"
    path.write_text("".join(selected) + "TER\nEND\n", encoding="utf-8")
    return path


def _multichain_gap_input(tmp_path: Path) -> Path:
    single = _gap_input(tmp_path)
    chain_c = [
        line
        for line in single.read_text(encoding="utf-8").splitlines(keepends=True)
        if line.startswith("ATOM  ")
    ]
    chain_d = []
    for line in chain_c:
        x = float(line[30:38]) + 50.0
        chain_d.append(f"{line[:21]}D{line[22:30]}{x:8.3f}{line[38:]}")
    path = tmp_path / "multichain-gap.pdb"
    path.write_text(
        "".join(chain_c) + "TER\n" + "".join(chain_d) + "TER\nEND\n",
        encoding="utf-8",
    )
    return path


def test_cli_and_scope_use_the_same_profile_specific_length_policy(tmp_path, monkeypatch):
    from dvbfixer.model.diffusion import gap_capabilities

    path = _gap_input(tmp_path)
    request = build_cli_diffusion_request(path, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protenix-v1-cuda")
    monkeypatch.setattr(gap_capabilities, "ACCEPTED_INTERNAL_RANGES", {"protenix-v1-cuda": ((3, 4),)})
    with pytest.raises(DiffusionCliError, match="accepted range 3-4"):
        build_cli_diffusion_request(path, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protenix-v1-cuda")
    assert not assess_diffusion_scope(request, path.read_bytes()).supported
    other = build_cli_diffusion_request(path, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-mps")
    assert assess_diffusion_scope(other, path.read_bytes()).supported


def test_diffusion_parser_accepts_optional_model_selection() -> None:
    args = parse_args(
        [
            "input.pdb",
            "--backend",
            "diffusion",
            "--diffusion-model",
            "protpardelle",
            "--diffusion-seed",
            "7",
            "--diffusion-seed",
            "11",
        ]
    )

    assert args.backend == "diffusion"
    assert args.diffusion_model == "protpardelle"
    assert args.diffusion_seeds == [7, 11]


def test_diffusion_parser_accepts_frozen_request() -> None:
    args = parse_args(
        ["input.pdb", "--backend", "diffusion", "--diffusion-request", "request.json"]
    )

    assert args.diffusion_request == "request.json"


@pytest.mark.parametrize(
    "option",
    (
        ("--fasta", "target.fasta"),
        ("--diffusion-seed", "11"),
        ("--diffusion-heterogen-smiles", "LIG=CO"),
        ("--no-terminal",),
        ("--strip-heterogens",),
    ),
)
def test_frozen_request_rejects_request_construction_options(
    option: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "input.pdb",
                "--backend",
                "diffusion",
                "--diffusion-request",
                "request.json",
                *option,
            ]
        )


def test_modeller_remains_the_default_backend() -> None:
    assert parse_args(["input.pdb"]).backend == "modeller"


def test_diffusion_parser_allows_automatic_runtime_selection() -> None:
    args = parse_args(["input.pdb", "--backend", "diffusion"])

    assert args.diffusion_model is None


def test_diffusion_parser_accepts_explicit_heterogen_stripping() -> None:
    args = parse_args([
        "input.pdb", "--backend", "diffusion", "--strip-heterogens",
    ])

    assert args.keep_heterogens is False


def test_diffusion_parser_accepts_no_terminal() -> None:
    args = parse_args(["input.pdb", "--backend", "diffusion", "--no-terminal"])

    assert args.no_terminal is True


def test_diffusion_parser_accepts_authoritative_heterogen_smiles() -> None:
    args = parse_args([
        "input.pdb",
        "--backend",
        "diffusion",
        "--diffusion-heterogen-smiles",
        "LIG=CO",
    ])

    assert args.diffusion_heterogen_smiles == ["LIG=CO"]


def test_diffusion_parser_rejects_modeller_only_options() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "input.pdb",
                "--backend",
                "diffusion",
                "--num-loops",
                "3",
            ]
        )


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "-1"])
def test_diffusion_parser_rejects_invalid_timeout(timeout: str) -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "input.pdb",
                "--backend",
                "diffusion",
                "--diffusion-timeout",
                timeout,
            ]
        )


def test_request_builder_produces_admitted_one_gap_request(tmp_path: Path) -> None:
    input_path = _gap_input(tmp_path)
    request = build_cli_diffusion_request(
        input_path,
        {"C": "SNRFSGSKSGNTA"},
        seeds=(7,),
        profile="protpardelle-1c-mps",
    )

    assert request.gaps[0].target_interval.start == 4
    assert request.gaps[0].target_interval.stop == 9
    assert [residue.residue_number for residue in request.gaps[0].generated_residues] == [
        "65", "66", "67", "68", "69",
    ]
    assert request.candidate_count == 1
    assert assess_diffusion_scope(request, input_path.read_bytes()).supported


@pytest.mark.parametrize("legacy", [False, True])
def test_frozen_request_uses_exact_request_and_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
) -> None:
    (tmp_path / "input").mkdir()
    input_path = _gap_input(tmp_path / "input")
    request = build_cli_diffusion_request(
        input_path,
        {"C": "SNRFSGSKSGNTA"},
        seeds=(7,),
        profile="protpardelle-1c-mps",
    )
    request_path = tmp_path / "request.json"
    persisted = replace(request, backend_options=()) if legacy else request
    request = replace(
        request,
        normalized_pdb=replace(request.normalized_pdb, path="input/gap.pdb"),
    )
    persisted = replace(persisted, normalized_pdb=request.normalized_pdb)
    request_path.write_text(persisted.to_json(), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.resolve_diffusion_runtime",
        lambda _model: DiffusionRuntime(
            "protpardelle", "protpardelle-1c-mps", "/installed/protpardelle-runner"
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.invoke_runner_preflight",
        lambda **_kwargs: RunnerPreflightReport(
            profile="protpardelle-1c-mps",
            runner_protocol_version=4,
            contract_schema_version=4,
            facts=RunnerPreflightFacts(),
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli._target_sequences",
        lambda *_args: pytest.fail("frozen request must not reconstruct placement"),
    )

    def fake_pipeline(observed, _command, *, source_root, **_kwargs):
        assert observed == request
        assert source_root == tmp_path
        return SimpleNamespace(published_bundle=output, status=SimpleNamespace(value="success"))

    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.run_diffusion_pipeline",
        fake_pipeline,
    )
    args = parse_args(
        [
            str(input_path),
            "--backend",
            "diffusion",
            "--diffusion-model",
            "protpardelle",
            "--diffusion-request",
            str(request_path),
            "-o",
            str(output),
        ]
    )

    run_diffusion_model(args)


def test_frozen_request_rejects_mutated_input_before_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = _gap_input(tmp_path)
    request = build_cli_diffusion_request(
        input_path,
        {"C": "SNRFSGSKSGNTA"},
        seeds=(7,),
        profile="protpardelle-1c-mps",
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(request.to_json(), encoding="utf-8")
    input_path.write_text(input_path.read_text() + "REMARK mutated\n")
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.resolve_diffusion_runtime",
        lambda _model: DiffusionRuntime(
            "protpardelle", "protpardelle-1c-mps", "/installed/protpardelle-runner"
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.invoke_runner_preflight",
        lambda **_kwargs: pytest.fail("digest admission must precede preflight"),
    )
    args = parse_args(
        [
            str(input_path),
            "--backend",
            "diffusion",
            "--diffusion-request",
            str(request_path),
            "-o",
            str(tmp_path / "output"),
        ]
    )

    with pytest.raises(DiffusionCliError, match="SHA-256"):
        run_diffusion_model(args)


@pytest.mark.parametrize(
    ("problem", "message"),
    (
        ("input", "normalized PDB referenced"),
        ("profile", "profile does not match"),
        ("legacy", "requires --diffusion-model"),
    ),
)
def test_frozen_request_rejects_input_or_profile_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str, message: str,
) -> None:
    input_path = _gap_input(tmp_path)
    request = build_cli_diffusion_request(
        input_path, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-mps",
    )
    if problem == "legacy":
        request = replace(request, backend_options=())
    request_path = tmp_path / "request.json"
    request_path.write_text(request.to_json())
    if problem == "input":
        other = tmp_path / "other.pdb"
        other.write_bytes(input_path.read_bytes())
        input_path = other
    runtime_profile = "protenix-v1-cuda" if problem == "profile" else "protpardelle-1c-mps"
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.resolve_diffusion_runtime",
        lambda _model: DiffusionRuntime("protpardelle", runtime_profile, "/installed/runner"),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.invoke_runner_preflight",
        lambda **_kwargs: pytest.fail("invalid request must fail before preflight"),
    )
    args = parse_args([
        str(input_path), "--backend", "diffusion", "--diffusion-request", str(request_path),
    ])
    with pytest.raises(DiffusionCliError, match=message):
        run_diffusion_model(args)


def test_request_builder_uses_insertion_codes_when_numbers_are_not_reserved(
    tmp_path: Path,
) -> None:
    input_path = _gap_input(tmp_path)
    renumbered: list[str] = []
    for line in input_path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("ATOM  ") and int(line[22:26]) >= 70:
            line = f"{line[:22]}{int(line[22:26]) - 5:4d}{line[26:]}"
        renumbered.append(line)
    input_path.write_text("".join(renumbered), encoding="utf-8")

    request = build_cli_diffusion_request(
        input_path,
        {"C": "SNRFSGSKSGNTA"},
        seeds=(7,),
        profile="protpardelle-1c-mps",
    )

    generated = request.gaps[0].generated_residues
    assert [residue.residue_number for residue in generated] == ["64"] * 5
    assert [residue.insertion_code for residue in generated] == list("ABCDE")
    assert not set(generated) & set(request.sequence_placements[0].observed_residues)
    assert assess_diffusion_scope(request, input_path.read_bytes()).supported


def test_request_builder_supports_gaps_across_multiple_chains(tmp_path: Path) -> None:
    input_path = _multichain_gap_input(tmp_path)

    request = build_cli_diffusion_request(
        input_path,
        {"C": "SNRFSGSKSGNTA", "D": "SNRFSGSKSGNTA"},
        seeds=(7,),
        profile="protpardelle-1c-mps",
    )

    assert [target.chain for target in request.target_sequences] == ["C", "D"]
    assert [gap.chain for gap in request.gaps] == ["C", "D"]
    assert [len(gap.generated_residues) for gap in request.gaps] == [5, 5]
    assert {atom.chain for atom in request.generated_atoms} == {"C", "D"}
    assert assess_diffusion_scope(request, input_path.read_bytes()).supported


def test_multichain_cli_warning_distinguishes_local_context_from_joint_sampling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = _multichain_gap_input(tmp_path)
    fasta = tmp_path / "target.fasta"
    fasta.write_text(
        ">C\nSNRFSGSKSGNTA\n>D\nSNRFSGSKSGNTA\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.resolve_diffusion_runtime",
        lambda _model: DiffusionRuntime(
            "protpardelle",
            "protpardelle-1c-mps",
            "/installed/protpardelle-runner",
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.invoke_runner_preflight",
        lambda **_kwargs: RunnerPreflightReport(
            profile="protpardelle-1c-mps",
            runner_protocol_version=4,
            contract_schema_version=4,
            facts=RunnerPreflightFacts(),
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.run_diffusion_pipeline",
        lambda *_args, **_kwargs: SimpleNamespace(
            published_bundle=output,
            status=SimpleNamespace(value="success"),
        ),
    )
    args = SimpleNamespace(
        input=str(input_path),
        output=str(output),
        diffusion_model="protpardelle",
        diffusion_timeout=1.0,
        diffusion_seeds=[7],
        diffusion_work_parent=None,
        fasta=str(fasta),
        keep_heterogens=True,
        no_terminal=False,
        verbose=False,
    )

    run_diffusion_model(args)

    warning = capsys.readouterr().out
    assert "2 independent chain-level sampler invocation(s)" in warning
    assert "nearby fixed partner-chain residues as local denoiser context" in warning
    assert "not jointly sampled" in warning


def test_request_builder_crops_terminal_targets_under_no_terminal(tmp_path: Path) -> None:
    input_path = _gap_input(tmp_path)

    request = build_cli_diffusion_request(
        input_path,
        {"C": "AAASNRFSGSKSGNTA"},
        seeds=(7,),
        profile="protpardelle-1c-mps",
        no_terminal=True,
    )

    assert request.target_sequences[0].sequence == "SNRFSGSKSGNTA"
    assert len(request.gaps) == 1


def test_request_builder_generates_one_anchor_terminal_regions(tmp_path: Path) -> None:
    input_path = _gap_input(tmp_path)

    request = build_cli_diffusion_request(
        input_path,
        {"C": "AAASNRFSGSKSGNTAGGG"},
        seeds=(7,),
        profile="protpardelle-1c-mps",
    )

    assert [gap.gap_kind for gap in request.gaps] == [
        GapKind.N_TERMINAL,
        GapKind.INTERNAL,
        GapKind.C_TERMINAL,
    ]
    n_terminal, _internal, c_terminal = request.gaps
    assert n_terminal.left_anchor is None
    assert n_terminal.right_anchor == request.sequence_placements[0].observed_residues[0]
    assert [residue.residue_number for residue in n_terminal.generated_residues] == [
        "58", "59", "60",
    ]
    assert c_terminal.right_anchor is None
    assert c_terminal.left_anchor == request.sequence_placements[0].observed_residues[-1]
    assert [residue.residue_number for residue in c_terminal.generated_residues] == [
        "74", "75", "76",
    ]
    assert assess_diffusion_scope(request, input_path.read_bytes()).supported


def test_oversized_terminal_region_recommends_no_terminal(tmp_path: Path) -> None:
    input_path = _gap_input(tmp_path)

    with pytest.raises(
        DiffusionCliError,
        match=(
            "N-terminal missing region length 13 on chain C.*"
            "pass --no-terminal"
        ),
    ):
        build_cli_diffusion_request(
            input_path,
            {"C": "A" * 13 + "SNRFSGSKSGNTA"},
            seeds=(7,),
            profile="protpardelle-1c-mps",
        )


def test_terminal_regions_are_fail_closed_for_unaccepted_profile(tmp_path: Path) -> None:
    input_path = _gap_input(tmp_path)
    request = build_cli_diffusion_request(
        input_path,
        {"C": "AAASNRFSGSKSGNTA"},
        seeds=(7,),
        profile="protenix-v1-cuda",
    )

    admission = assess_diffusion_scope(request, input_path.read_bytes())

    assert admission.supported is False
    assert "terminal-gaps-unsupported-by-profile" in admission.reasons


def test_failed_profile_preflight_blocks_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = _gap_input(tmp_path)
    fasta = tmp_path / "target.fasta"
    fasta.write_text(">C\nSNRFSGSKSGNTA\n")
    report = RunnerPreflightReport(
        profile="protenix-v1-cuda",
        runner_protocol_version=4,
        contract_schema_version=4,
        facts=RunnerPreflightFacts(),
        issues=(
            AdapterPreflightIssue(
                AdapterPreflightCode.MISSING_CUDA,
                "required CUDA device is unavailable",
            ),
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.invoke_runner_preflight",
        lambda **_kwargs: report,
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.resolve_diffusion_runtime",
        lambda _model: DiffusionRuntime(
            "protenix", "protenix-v1-cuda", "/installed/protenix-runner"
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.run_diffusion_pipeline",
        lambda *_args, **_kwargs: pytest.fail("inference must not run"),
    )
    args = SimpleNamespace(
        input=str(input_path),
        output=str(tmp_path / "output"),
        diffusion_model=None,
        diffusion_timeout=1.0,
        diffusion_seeds=[7],
        diffusion_work_parent=None,
        fasta=str(fasta),
        keep_heterogens=True,
        verbose=False,
    )

    with pytest.raises(DiffusionCliError, match="missing-cuda"):
        run_diffusion_model(args)


def test_scope_rejection_precedes_runner_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = _gap_input(tmp_path)
    input_path.write_text(input_path.read_text().replace("ATOM  ", "HETATM", 1))
    fasta = tmp_path / "target.fasta"
    fasta.write_text(">C\nSNRFSGSKSGNTA\n")
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.resolve_diffusion_runtime",
        lambda _model: DiffusionRuntime(
            "protenix", "protenix-v1-cuda", "/installed/protenix-runner"
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.invoke_runner_preflight",
        lambda **_kwargs: pytest.fail("preflight must follow scope admission"),
    )
    args = SimpleNamespace(
        input=str(input_path),
        output=str(tmp_path / "output"),
        diffusion_model=None,
        diffusion_timeout=1.0,
        diffusion_seeds=[7],
        diffusion_work_parent=None,
        fasta=str(fasta),
        keep_heterogens=True,
        verbose=False,
    )

    with pytest.raises(DiffusionCliError):
        run_diffusion_model(args)


def test_diffusion_strip_heterogens_preprocesses_without_mutating_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = _gap_input(tmp_path)
    original = input_path.read_text(encoding="utf-8")
    heterogen = (
        "HETATM 9001  C1  LIG C 900      20.000  20.000  20.000  1.00  0.00           C  \n"
    )
    input_path.write_text(
        original.replace("TER\n", heterogen + "CONECT 9001    1\nTER\n"),
        encoding="utf-8",
    )
    source_with_heterogen = input_path.read_text(encoding="utf-8")
    fasta = tmp_path / "target.fasta"
    fasta.write_text(">C\nSNRFSGSKSGNTA\n", encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.resolve_diffusion_runtime",
        lambda _model: DiffusionRuntime(
            "protpardelle", "protpardelle-1c-mps", "/installed/protpardelle-runner"
        ),
    )
    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.invoke_runner_preflight",
        lambda **_kwargs: RunnerPreflightReport(
            profile="protpardelle-1c-mps",
            runner_protocol_version=4,
            contract_schema_version=4,
            facts=RunnerPreflightFacts(),
        ),
    )

    def fake_pipeline(request, _command, *, source_root, **_kwargs):
        prepared = (source_root / request.normalized_pdb.path).read_text(encoding="utf-8")
        assert "HETATM" not in prepared
        assert "CONECT 9001" not in prepared
        return SimpleNamespace(published_bundle=output, status=SimpleNamespace(value="success"))

    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.run_diffusion_pipeline",
        fake_pipeline,
    )
    args = SimpleNamespace(
        input=str(input_path),
        output=str(output),
        diffusion_model=None,
        diffusion_timeout=1.0,
        diffusion_seeds=[7],
        diffusion_work_parent=None,
        fasta=str(fasta),
        keep_heterogens=False,
        verbose=False,
    )

    run_diffusion_model(args)

    assert input_path.read_text(encoding="utf-8") == source_with_heterogen
