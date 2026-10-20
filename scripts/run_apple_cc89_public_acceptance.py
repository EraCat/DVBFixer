#!/usr/bin/env python3
"""Freeze, execute and independently audit corrected Apple public workflows.

Four source-only workflows / five candidates match the CUDA integration controls.
No reference PDB enters execution or evaluation; every started outcome is terminal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from dvbfixer.homology_plan import build_mosaic_diffusion_request, materialize_template_plan
from dvbfixer.model.diffusion.contract import DiffusionRequest, SamplerTrace
from dvbfixer.model.diffusion.protein_context import MPS_CC89_PROFILE, prepare_mps_cc89_request
from dvbfixer.model.diffusion.publication import read_published_bundle
from dvbfixer.model.diffusion_cli import build_cli_diffusion_request
from dvbfixer.model.pipeline import parse_fasta

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("homology", "prospective-9ww8-gap5", (7,)),
    ("homology", "prospective-8ek6-H-cdr1-gap5", (7,)),
    ("homology", "prospective-9z0u-H-cdr3-gap10", (7,)),
    ("model", "prospective-9ww8-gap10", (7, 19)),
)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump_new(path, data):
    with path.open("x") as stream:
        stream.write(json.dumps(data, indent=2, sort_keys=True) + "\n")


def environment(protocol):
    return {**os.environ, "HOME": protocol["launcher_home"], "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(ROOT / "src"), "OPENMM_CPU_THREADS": "1",
        "PATH": os.pathsep.join((str(Path(protocol["core_python"]).parent), str(Path(protocol["runner"]).parent), os.environ.get("PATH", "")))}


def verify(protocol):
    for path, digest in protocol["sha256"].items():
        if sha(Path(path)) != digest:
            raise ValueError(f"frozen public acceptance artifact changed: {path}")


def freeze(args):
    if args.root.exists():
        raise ValueError("public acceptance root must be new")
    args.root.mkdir(parents=True)
    protocol = {"status": "frozen-before-corrected-apple-public-execution", "profile": MPS_CC89_PROFILE,
        "runner": str(args.runner), "core_python": str(args.core_python), "launcher_home": str(args.launcher_home),
        "timeout_seconds": 1500, "no_replacement": True, "reference_rmsd_used": False,
        "wider_operational_acceptance": False, "jobs": [], "sha256": {}}
    if args.supersedes is not None:
        protocol["supersedes_failed_execution_sha256"] = sha(args.supersedes)
    environment_record = subprocess.run([str(args.runner), "--profile", MPS_CC89_PROFILE, "--preflight"],
        env=environment(protocol), capture_output=True, text=True, check=True, timeout=120)
    preflight = json.loads(environment_record.stdout)
    if not preflight["passed"]:
        raise ValueError("corrected Apple public preflight failed")
    protocol["preflight"] = preflight
    for tool, case, seeds in CASES:
        source = args.controls / case
        inputs = args.root / "inputs" / case
        inputs.mkdir(parents=True)
        for name, original in (("normalized.pdb", source / "input/normalized.pdb"),
                ("target.fasta", source / "target.fasta"), ("masked-template.pdb", source / "masked-template.pdb")):
            shutil.copyfile(original, inputs / name)
        plan = json.loads((source / "template-plan.json").read_text())
        for template in plan["templates"]:
            template["path"] = str(inputs / "masked-template.pdb")
        dump_new(inputs / "template-plan.json", plan)
        targets = parse_fasta(str(inputs / "target.fasta"))
        expected = args.root / "expected" / case
        expected.mkdir(parents=True)
        if tool == "homology":
            materialize_template_plan(inputs / "template-plan.json", expected)
            normalized, request_path = build_mosaic_diffusion_request(expected / "selected_template_mosaic.coverage.json",
                list(targets.items()), expected, seeds=seeds, profile=MPS_CC89_PROFILE)
            request = DiffusionRequest.from_json(request_path.read_text())
        else:
            normalized = inputs / "normalized.pdb"
            request = prepare_mps_cc89_request(build_cli_diffusion_request(normalized, targets,
                seeds=seeds, profile=MPS_CC89_PROFILE), normalized.read_bytes(), "auto")
            # Explicit CLI replay resolves the normalized artifact relative to
            # the frozen request, so keep both private inputs together.
            request_path = inputs / "request.json"
            request_path.write_text(request.to_json())
        protocol["jobs"].append({"tool": tool, "case_id": case, "seeds": seeds,
            "request": str(request_path), "source_root": str(normalized.parent), "inputs": str(inputs)})
    paths = [*sorted((ROOT / "src/dvbfixer").rglob("*.py")),
        *sorted((ROOT / "deploy/protpardelle-1c").glob("*.py")), Path(__file__),
        ROOT / "scripts/install_diffusion_backend.py", args.runner,
        *sorted((args.root / "inputs").rglob("*")), *sorted((args.root / "expected").rglob("*"))]
    protocol["sha256"] = {str(path): sha(path) for path in paths if path.is_file()}
    dump_new(args.root / "protocol.json", protocol)
    print(json.dumps({"workflows": 4, "candidates": 5, "protocol_sha256": sha(args.root / "protocol.json")}))


def command(protocol, job, output, *, resume=False, frozen=False):
    if frozen and job["tool"] != "model":
        raise ValueError("explicit frozen-request replay uses the model CLI")
    inputs = Path(job["inputs"])
    argv = [protocol["core_python"], "-B", "-m", "dvbfixer.cli", job["tool"]]
    if job["tool"] == "homology":
        argv += [str(inputs / "target.fasta"), "--template-plan", str(inputs / "template-plan.json")]
    else:
        argv += [str(inputs / "normalized.pdb")]
        if not frozen:
            argv += ["--fasta", str(inputs / "target.fasta")]
    argv += ["--backend", "diffusion", "--diffusion-model", "protpardelle", "--diffusion-timeout", "1200",
        "--diffusion-work-parent", str(output.parent), "-o", str(output)]
    if not frozen:
        for seed in job["seeds"]:
            argv += ["--diffusion-seed", str(seed)]
    if resume:
        argv += ["--diffusion-resume"]
    if frozen:
        argv += ["--diffusion-request", job["request"]]
    return argv


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "complete.json"}


def execute(args):
    protocol_path = args.root / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    verify(protocol)
    for job in protocol["jobs"]:
        output = args.root / "outputs" / job["case_id"]
        marker = output / "complete.json"
        if output.exists():
            if not marker.exists():
                raise ValueError("interrupted public outcome is terminal; do not replace it")
            data = json.loads(marker.read_text())
            if (data["protocol_sha256"] != sha(protocol_path) or data["job"] != job or data["artifacts"] != inventory(output)):
                raise ValueError("public archive identity changed")
            continue
        output.mkdir(parents=True)
        prefix = output / "result"
        with (output / "execution.log").open("x") as log:
            try:
                completed = subprocess.run(command(protocol, job, prefix), env=environment(protocol), cwd=ROOT,
                    stdout=log, stderr=subprocess.STDOUT, timeout=protocol["timeout_seconds"], check=False)
                status = {"status": "completed" if completed.returncode == 0 else "failed", "exit_code": completed.returncode}
            except subprocess.TimeoutExpired:
                status = {"status": "timeout"}
        bundle = output / ("result_homology_diffusion" if job["tool"] == "homology" else "result")
        resumes = []
        if status["status"] == "completed":
            before = {p.relative_to(bundle).as_posix(): (sha(p), p.stat().st_mtime_ns) for p in bundle.rglob("*") if p.is_file()}
            for frozen in ([False, True] if job["tool"] == "model" else [False]):
                with (output / ("frozen-resume.log" if frozen else "resume.log")).open("x") as log:
                    replay = subprocess.run(command(protocol, job, prefix, resume=True, frozen=frozen),
                        env=environment(protocol), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                        timeout=120, check=False)
                after = {p.relative_to(bundle).as_posix(): (sha(p), p.stat().st_mtime_ns) for p in bundle.rglob("*") if p.is_file()}
                resumes.append({"frozen_request": frozen, "exit_code": replay.returncode, "bundle_unchanged": before == after})
        dump_new(marker, {"protocol_sha256": sha(protocol_path), "job": job, "execution": status,
            "resume": resumes, "artifacts": inventory(output)})
        print(json.dumps({"case_id": job["case_id"], "execution": status, "resume": resumes}), flush=True)


def audit(args):
    protocol_path = args.root / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    verify(protocol)
    rows, workflows = [], []
    for job in protocol["jobs"]:
        output = args.root / "outputs" / job["case_id"]
        marker = json.loads((output / "complete.json").read_text())
        if marker["protocol_sha256"] != sha(protocol_path) or marker["job"] != job or marker["artifacts"] != inventory(output):
            raise ValueError("public outcome archive changed")
        workflows.append({"case_id": job["case_id"], "tool": job["tool"], "execution": marker["execution"], "resume": marker["resume"]})
        if marker["execution"]["status"] != "completed":
            continue
        request = DiffusionRequest.from_json(Path(job["request"]).read_text())
        bundle = output / ("result_homology_diffusion" if job["tool"] == "homology" else "result")
        published = read_published_bundle(bundle, request=request, source_root=Path(job["source_root"]), work_parent=output)
        if published.status != "success" or {candidate.seed for candidate in published.candidates} != set(job["seeds"]):
            raise ValueError("public bundle failed independent revalidation or omitted a seed")
        index = json.loads((bundle / "bundle.json").read_text())
        generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
        source = (Path(job["source_root"]) / request.normalized_pdb.path).read_text()

        def outside(text, generated=generated):
            return [line for line in text.splitlines(keepends=True) if line.startswith(("ATOM  ", "HETATM"))
                and (line[21], line[22:26].strip(), line[26].strip()) not in generated]

        for candidate in published.candidates:
            if outside(candidate.pdb_bytes.decode()) != outside(source):
                raise ValueError("public output changed outside-gap atom records")
            entry = next(row for row in index["candidates"] if row["seed"] == candidate.seed)
            trace = SamplerTrace.from_json((bundle / entry["sampler_trace"]["path"]).read_text())
            provenance = json.loads((bundle / entry["provenance"]["path"]).read_text())
            metrics = {metric["name"]: metric["value"] for metric in provenance["validation_summary"]["metrics"]}
            if (metrics["detectable-d-ca"] != 0 or metrics["fixed-heavy-atom-max-displacement"] != 0
                    or trace.profile != MPS_CC89_PROFILE or trace.device != "mps" or not trace.fallback_disabled
                    or not any(option.name == "platform" and option.value == "CPU" for option in trace.refinement_parameters)):
                raise ValueError("public result lacks corrected MPS/CPU/preservation evidence")
            rows.append({"case_id": job["case_id"], "tool": job["tool"], "seed": candidate.seed,
                "passed": True, "request_sha256": sha(Path(job["request"])), "coordinate_sha256": sha(candidate.pdb),
                "bundle_sha256": sha(bundle / "bundle.json"), "profile": trace.profile,
                "d_ca": 0, "fixed_max_displacement_angstrom": 0, "outside_gap_atom_records_identical": True,
                "dat_generated_atom_count": len(candidate.dat_record.added_atoms),
                "denoising_updates": trace.denoising_update_count, "callback_updates": trace.callback_update_count})
    report = {"execution_protocol_sha256": sha(protocol_path), "planned_workflows": 4, "planned_candidates": 5,
        "accepted": len(rows), "workflows": workflows, "rows": rows,
        "reference_rmsd_used": False, "wider_operational_acceptance": False}
    dump_new(args.report, report)
    print(json.dumps({"accepted": len(rows), "planned_candidates": 5}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "audit"))
    parser.add_argument("--root", required=True, type=Path)
    for name in ("controls", "runner", "core-python", "launcher-home", "report", "supersedes"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.expanduser().absolute())
    if args.action == "freeze" and any(getattr(args, name) is None for name in ("controls", "runner", "core_python", "launcher_home")):
        parser.error("freeze requires --controls, --runner, --core-python and --launcher-home")
    if args.action == "audit" and args.report is None:
        parser.error("audit requires --report")
    {"freeze": freeze, "run": execute, "audit": audit}[args.action](args)


if __name__ == "__main__":
    main()
