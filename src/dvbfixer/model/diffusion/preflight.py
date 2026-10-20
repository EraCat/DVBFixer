"""Fail-closed local preflight primitives for external diffusion adapters."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import stat
import subprocess
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from dvbfixer.model.diffusion.contract import DIFFUSION_SCHEMA_VERSION
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION

DIFFUSION_PREFLIGHT_SCHEMA_VERSION = 1
MAX_PREFLIGHT_OUTPUT_BYTES = 65_536
MAX_PREFLIGHT_ISSUES = 32
MAX_PREFLIGHT_TEXT_LENGTH = 256
_PREFLIGHT_PIPE_DRAIN_TIMEOUT_SECONDS = 1.0
_PREFLIGHT_PROCESS_STARTUP_GRACE_SECONDS = 0.5


class AdapterPreflightCode(StrEnum):
    """Stable machine-readable adapter preflight failure categories."""

    MISSING_RUNNER = "missing-runner"
    MISSING_IMAGE = "missing-image"
    MISSING_CHECKPOINT = "missing-checkpoint"
    CHECKPOINT_DIGEST_MISMATCH = "checkpoint-digest-mismatch"
    MISSING_CUDA = "missing-cuda"
    MISSING_MPS = "missing-mps"
    MISSING_RESOURCE = "missing-resource"
    INCOMPATIBLE_PROTOCOL = "incompatible-protocol"
    INCOMPATIBLE_SCHEMA = "incompatible-schema"
    INCOMPATIBLE_PLATFORM = "incompatible-platform"
    INCOMPATIBLE_ARCHITECTURE = "incompatible-architecture"
    INCOMPATIBLE_PYTHON = "incompatible-python"
    INCOMPATIBLE_SOURCE = "incompatible-source"
    INCOMPATIBLE_PATCH = "incompatible-patch"
    INCOMPATIBLE_ENVIRONMENT = "incompatible-environment"
    INCOMPATIBLE_FRAMEWORK = "incompatible-framework"
    INCOMPATIBLE_DEVICE = "incompatible-device"
    FALLBACK_ENABLED = "fallback-enabled"
    INCOMPATIBLE_REFINEMENT_PLATFORM = "incompatible-refinement-platform"
    RUNNER_TIMEOUT = "runner-timeout"
    RUNNER_FAILED = "runner-failed"
    MALFORMED_RESPONSE = "malformed-response"
    OVERSIZED_RESPONSE = "oversized-response"


@dataclass(frozen=True, slots=True)
class DiffusionProfileMetadata:
    """Immutable public metadata for one maintained diffusion runner profile."""

    profile: str
    status: str
    evidence_labels: tuple[str, ...]
    engine: str
    source_revision: str
    patch_identity: str
    expected_checkpoint_sha256: str
    sampling_platform: str
    refinement_platform: str
    runner_protocol_version: int
    contract_schema_version: int
    fallback_policy: str
    training_membership_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "status": self.status,
            "evidence_labels": list(self.evidence_labels),
            "engine": self.engine,
            "source_revision": self.source_revision,
            "patch_identity": self.patch_identity,
            "expected_checkpoint_sha256": self.expected_checkpoint_sha256,
            "sampling_platform": self.sampling_platform,
            "refinement_platform": self.refinement_platform,
            "runner_protocol_version": self.runner_protocol_version,
            "contract_schema_version": self.contract_schema_version,
            "fallback_policy": self.fallback_policy,
            "training_membership_status": self.training_membership_status,
        }


DIFFUSION_PROFILES = {
    "protpardelle-1c-cuda": DiffusionProfileMetadata(
        profile="protpardelle-1c-cuda",
        status="experimental-local-context-accepted",
        evidence_labels=("experimental", "source-disjoint-24-of-24", "no-per-step-reinjection"),
        engine="Protpardelle-1c",
        source_revision="ee378400f25b801fa481028000f9060183d7fb4c",
        patch_identity="cc89-neutral-v1;source-physical-v1;callback-patch-v1",
        expected_checkpoint_sha256="dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483",
        sampling_platform="Linux amd64 / NVIDIA CUDA 12.4",
        refinement_platform="OpenMM CUDA",
        runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
        contract_schema_version=DIFFUSION_SCHEMA_VERSION,
        fallback_policy="disabled; no profile, device, or MODELLER fallback",
        training_membership_status="not-independently-attested",
    ),
    "protenix-v1-cuda": DiffusionProfileMetadata(
        profile="protenix-v1-cuda",
        status="production-wrapper-frozen-cohort-replayed-deployment-pending",
        evidence_labels=(
            "experimental",
            "confirmatory-selected-in-frozen-scope",
            "public-cli-frozen-cohort-replayed",
        ),
        engine="Protenix v1",
        source_revision="85767b811c40ed46e73a9b39519cf6bfca8701ba",
        patch_identity="sha256:cc4153be3dfd241124ea183d592884799300046b6ea7d3eccae8409b9fe21aa0",
        expected_checkpoint_sha256="2b7d5a8b30494514fc47fd2271a16260528cdba170ba09cc112fdecd8f85ec04",
        sampling_platform="Linux amd64 / NVIDIA CUDA 12.9",
        refinement_platform="OpenMM Reference",
        runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
        contract_schema_version=DIFFUSION_SCHEMA_VERSION,
        fallback_policy="disabled; no profile, device, or MODELLER fallback",
        training_membership_status="temporally-eligible-frozen-cohort",
    ),
    "protpardelle-1c-mps": DiffusionProfileMetadata(
        profile="protpardelle-1c-mps",
        status="production-wrapper-frozen-cohort-accepted",
        evidence_labels=(
            "experimental",
            "descriptive-evidence",
            "training-membership-unresolved",
            "no-per-step-reinjection",
        ),
        engine="Protpardelle-1c",
        source_revision="ee378400f25b801fa481028000f9060183d7fb4c",
        patch_identity="sha256:627891e28d5055cb0d903f542af695569d7133b0480cab8f25d154dc8ccc78c9",
        expected_checkpoint_sha256="dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483",
        sampling_platform="native macOS arm64 / MPS",
        refinement_platform="OpenMM CPU",
        runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
        contract_schema_version=DIFFUSION_SCHEMA_VERSION,
        fallback_policy="PYTORCH_ENABLE_MPS_FALLBACK=0; no profile, device, or MODELLER fallback",
        training_membership_status="unresolved",
    ),
}


@dataclass(frozen=True, slots=True)
class _RuntimeExpectation:
    platform: str
    architectures: frozenset[str]
    python_version: str
    framework_version: str
    device_prefix: str
    environment_identity: str


_PROFILE_RUNTIME_EXPECTATIONS = {
    "protpardelle-1c-cuda": _RuntimeExpectation(
        platform="linux", architectures=frozenset({"x86_64", "amd64"}),
        python_version="3.12", framework_version="2.6.0",
        device_prefix="cuda:",
        environment_identity="linux-amd64;cc89-cuda-v1;python=3.12;torch=2.6.0+cu124;refinement=openmm-8.6.1-cuda",
    ),
    "protenix-v1-cuda": _RuntimeExpectation(
        platform="linux",
        architectures=frozenset({"x86_64", "amd64"}),
        python_version="3.13",
        framework_version="2.13.0",
        device_prefix="cuda:",
        environment_identity=(
            "linux-amd64;profile-lock-sha256="
            "3fb3661be2b6748650b90bf9b0aaa7a09cbba9accc13253a6c29f644001b5d2e"
        ),
    ),
    "protpardelle-1c-mps": _RuntimeExpectation(
        platform="darwin",
        architectures=frozenset({"arm64"}),
        python_version="3.12",
        framework_version="2.6.0",
        device_prefix="mps",
        environment_identity="macos-arm64;python=3.12;torch=2.6.0",
    ),
}


@dataclass(frozen=True, slots=True)
class LocalCheckpoint:
    """A local-only checkpoint requirement with an immutable expected digest."""

    path: Path
    sha256: str

    def __post_init__(self) -> None:
        if len(self.sha256) != 64:
            raise ValueError("checkpoint SHA-256 must contain 64 hexadecimal characters")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ValueError("checkpoint SHA-256 must be hexadecimal") from exc


@dataclass(frozen=True, slots=True)
class AdapterAvailability:
    """Runtime facts supplied by an engine-specific launcher or container host."""

    available_images: frozenset[str] = frozenset()
    cuda_devices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterPreflightSpec:
    """Requirements that must be satisfied before launching an adapter."""

    runner: str
    protocol_version: int
    checkpoint: LocalCheckpoint | None = None
    image: str = ""
    requires_cuda: bool = False

    def __post_init__(self) -> None:
        if not self.runner:
            raise ValueError("adapter runner must not be empty")
        if self.protocol_version <= 0:
            raise ValueError("adapter protocol version must be positive")


@dataclass(frozen=True, slots=True)
class AdapterPreflightIssue:
    code: AdapterPreflightCode
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True, slots=True)
class RunnerPreflightFacts:
    """Sanitized runtime facts returned by a maintained production wrapper."""

    platform: str = ""
    architecture: str = ""
    python_version: str = ""
    engine_revision: str = ""
    patch_identity: str = ""
    environment_identity: str = ""
    checkpoint_sha256: str = ""
    framework_version: str = ""
    accelerator_available: bool = False
    effective_device: str = ""
    fallback_disabled: bool = False
    sampling_platform: str = ""
    refinement_platform: str = ""

    _KEYS: ClassVar[tuple[str, ...]] = (
        "platform", "architecture", "python_version", "engine_revision",
        "patch_identity", "environment_identity", "checkpoint_sha256",
        "framework_version", "accelerator_available", "effective_device",
        "fallback_disabled", "sampling_platform", "refinement_platform",
    )

    def to_dict(self) -> dict[str, str | bool]:
        return {name: getattr(self, name) for name in self._KEYS}


@dataclass(frozen=True, slots=True)
class RunnerPreflightReport:
    """Strict, bounded handshake response from an external runner."""

    profile: str
    runner_protocol_version: int
    contract_schema_version: int
    facts: RunnerPreflightFacts
    issues: tuple[AdapterPreflightIssue, ...] = ()
    preflight_schema_version: int = DIFFUSION_PREFLIGHT_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "preflight_schema_version": self.preflight_schema_version,
            "profile": self.profile,
            "runner_protocol_version": self.runner_protocol_version,
            "contract_schema_version": self.contract_schema_version,
            "passed": self.passed,
            "facts": self.facts.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, text: str) -> RunnerPreflightReport:
        if len(text.encode("utf-8")) > MAX_PREFLIGHT_OUTPUT_BYTES:
            raise ValueError("preflight response exceeds the size limit")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("preflight response is not valid JSON") from exc
        keys = {
            "preflight_schema_version", "profile", "runner_protocol_version",
            "contract_schema_version", "passed", "facts", "issues",
        }
        if not isinstance(raw, dict) or set(raw) != keys:
            raise ValueError("preflight response fields do not match the schema")
        facts_raw = raw["facts"]
        if not isinstance(facts_raw, dict) or set(facts_raw) != set(RunnerPreflightFacts._KEYS):
            raise ValueError("preflight facts do not match the schema")
        issues_raw = raw["issues"]
        if not isinstance(issues_raw, list) or len(issues_raw) > MAX_PREFLIGHT_ISSUES:
            raise ValueError("preflight issues are invalid or exceed the limit")
        issues: list[AdapterPreflightIssue] = []
        for item in issues_raw:
            if not isinstance(item, dict) or set(item) != {"code", "message"}:
                raise ValueError("preflight issue fields do not match the schema")
            message = item["message"]
            if not isinstance(message, str) or len(message) > MAX_PREFLIGHT_TEXT_LENGTH:
                raise ValueError("preflight issue message is invalid or exceeds the limit")
            try:
                code = AdapterPreflightCode(item["code"])
            except (TypeError, ValueError) as exc:
                raise ValueError("preflight issue code is unknown") from exc
            issues.append(AdapterPreflightIssue(code, message))
        string_fields = set(RunnerPreflightFacts._KEYS) - {
            "accelerator_available", "fallback_disabled",
        }
        if any(
            not isinstance(facts_raw[name], str)
            or len(facts_raw[name]) > MAX_PREFLIGHT_TEXT_LENGTH
            for name in string_fields
        ) or any(
            not isinstance(facts_raw[name], bool)
            for name in ("accelerator_available", "fallback_disabled")
        ):
            raise ValueError("preflight facts contain invalid values")
        scalar_types = (
            type(raw["preflight_schema_version"]) is int,
            isinstance(raw["profile"], str),
            type(raw["runner_protocol_version"]) is int,
            type(raw["contract_schema_version"]) is int,
            isinstance(raw["passed"], bool),
        )
        if not all(scalar_types) or len(raw["profile"]) > MAX_PREFLIGHT_TEXT_LENGTH:
            raise ValueError("preflight response contains invalid values")
        report = cls(
            preflight_schema_version=raw["preflight_schema_version"],
            profile=raw["profile"],
            runner_protocol_version=raw["runner_protocol_version"],
            contract_schema_version=raw["contract_schema_version"],
            facts=RunnerPreflightFacts(**facts_raw),
            issues=tuple(issues),
        )
        if raw["passed"] != report.passed:
            raise ValueError("preflight passed flag is inconsistent with issues")
        return report


def runtime_preflight_facts(
    *,
    engine_revision: str = "",
    patch_identity: str = "",
    environment_identity: str = "",
    checkpoint_sha256: str = "",
    framework_version: str = "",
    accelerator_available: bool = False,
    effective_device: str = "",
    fallback_disabled: bool = False,
    sampling_platform: str = "",
    refinement_platform: str = "",
) -> RunnerPreflightFacts:
    """Build sanitized host facts without exposing paths or raw environment values."""
    return RunnerPreflightFacts(
        platform=sys_platform_name(),
        architecture=platform.machine(),
        python_version=f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}",
        engine_revision=engine_revision,
        patch_identity=patch_identity,
        environment_identity=environment_identity,
        checkpoint_sha256=checkpoint_sha256,
        framework_version=framework_version,
        accelerator_available=accelerator_available,
        effective_device=effective_device,
        fallback_disabled=fallback_disabled,
        sampling_platform=sampling_platform,
        refinement_platform=refinement_platform,
    )


def sys_platform_name() -> str:
    """Return the stable platform token used by profile handshakes."""
    import sys

    return sys.platform


def invoke_runner_preflight(
    *,
    profile: str,
    runner: str,
    checkpoint: Path | None = None,
    timeout_seconds: float = 30.0,
) -> RunnerPreflightReport:
    """Run one bounded no-inference handshake and validate immutable profile facts."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("preflight timeout must be a positive finite number")
    metadata = DIFFUSION_PROFILES[profile]
    empty_facts = RunnerPreflightFacts()

    class Capture:
        def __init__(self) -> None:
            self.data = bytearray()
            self.oversized = False

        def drain(self, stream: Any) -> None:
            while chunk := stream.read(8192):
                remaining = MAX_PREFLIGHT_OUTPUT_BYTES - len(self.data)
                if remaining > 0:
                    self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.oversized = True

    allowed_environment = {
        name: os.environ[name]
        for name in (
            "CUDA_VISIBLE_DEVICES",
            "DYLD_LIBRARY_PATH",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "LD_LIBRARY_PATH",
            "PATH",
            "PYTHONNOUSERSITE",
            "PYTORCH_ENABLE_MPS_FALLBACK",
            "PYTORCH_MPS_FAST_MATH",
            "PYTORCH_MPS_HIGH_WATERMARK_RATIO",
            "PYTORCH_MPS_LOW_WATERMARK_RATIO",
            "PYTORCH_MPS_PREFER_METAL",
            "SYSTEMROOT",
        )
        if name in os.environ
    }
    command = [runner, "--preflight", "--profile", profile]
    if checkpoint is not None:
        command.extend(("--checkpoint", str(checkpoint)))
    try:
        process = subprocess.Popen(
            command,
            env=allowed_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        return RunnerPreflightReport(
            profile, DIFFUSION_RUNNER_PROTOCOL_VERSION, DIFFUSION_SCHEMA_VERSION,
            empty_facts,
            (AdapterPreflightIssue(AdapterPreflightCode.MISSING_RUNNER, "diffusion runner could not be started"),),
        )
    assert process.stdout is not None and process.stderr is not None
    stdout = Capture()
    stderr = Capture()
    threads = (
        threading.Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
        threading.Thread(target=stderr.drain, args=(process.stderr,), daemon=True),
    )
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        return_code = process.wait(
            timeout=timeout_seconds + _PREFLIGHT_PROCESS_STARTUP_GRACE_SECONDS
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        return_code = -1
    if process.poll() is None or any(thread.is_alive() for thread in threads):
        try:
            os.killpg(process.pid, 9)
        except (AttributeError, ProcessLookupError, PermissionError):
            if process.poll() is None:
                process.kill()
    if process.poll() is None:
        return_code = process.wait()
    for thread in threads:
        thread.join(timeout=_PREFLIGHT_PIPE_DRAIN_TIMEOUT_SECONDS)
    readers_alive = any(thread.is_alive() for thread in threads)
    if readers_alive:
        timed_out = True
    else:
        process.stdout.close()
        process.stderr.close()
    if timed_out:
        return RunnerPreflightReport(
            profile, DIFFUSION_RUNNER_PROTOCOL_VERSION, DIFFUSION_SCHEMA_VERSION,
            empty_facts,
            (AdapterPreflightIssue(AdapterPreflightCode.RUNNER_TIMEOUT, "diffusion runner preflight timed out"),),
        )
    if stdout.oversized or stderr.oversized:
        return RunnerPreflightReport(
            profile, DIFFUSION_RUNNER_PROTOCOL_VERSION, DIFFUSION_SCHEMA_VERSION,
            empty_facts,
            (AdapterPreflightIssue(AdapterPreflightCode.OVERSIZED_RESPONSE, "diffusion runner preflight output exceeded the size limit"),),
        )
    if return_code != 0:
        return RunnerPreflightReport(
            profile, DIFFUSION_RUNNER_PROTOCOL_VERSION, DIFFUSION_SCHEMA_VERSION,
            empty_facts,
            (AdapterPreflightIssue(AdapterPreflightCode.RUNNER_FAILED, "diffusion runner preflight exited unsuccessfully"),),
        )
    try:
        report = RunnerPreflightReport.from_json(stdout.data.decode("utf-8"))
    except (UnicodeError, ValueError):
        return RunnerPreflightReport(
            profile, DIFFUSION_RUNNER_PROTOCOL_VERSION, DIFFUSION_SCHEMA_VERSION,
            empty_facts,
            (AdapterPreflightIssue(AdapterPreflightCode.MALFORMED_RESPONSE, "diffusion runner returned an invalid preflight response"),),
        )
    issues = list(report.issues)
    runtime = _PROFILE_RUNTIME_EXPECTATIONS[profile]
    expected = (
        (report.profile == profile, AdapterPreflightCode.INCOMPATIBLE_ENVIRONMENT, "runner reported a different profile"),
        (report.preflight_schema_version == DIFFUSION_PREFLIGHT_SCHEMA_VERSION, AdapterPreflightCode.INCOMPATIBLE_SCHEMA, "runner preflight schema is incompatible"),
        (report.runner_protocol_version == metadata.runner_protocol_version, AdapterPreflightCode.INCOMPATIBLE_PROTOCOL, "runner protocol is incompatible"),
        (report.contract_schema_version == metadata.contract_schema_version, AdapterPreflightCode.INCOMPATIBLE_SCHEMA, "diffusion contract schema is incompatible"),
        (report.facts.engine_revision == metadata.source_revision, AdapterPreflightCode.INCOMPATIBLE_SOURCE, "runner engine revision is incompatible"),
        (report.facts.patch_identity == metadata.patch_identity, AdapterPreflightCode.INCOMPATIBLE_PATCH, "runner patch identity is incompatible"),
        (report.facts.checkpoint_sha256 == metadata.expected_checkpoint_sha256, AdapterPreflightCode.CHECKPOINT_DIGEST_MISMATCH, "runner checkpoint digest is incompatible"),
        (report.facts.platform == runtime.platform, AdapterPreflightCode.INCOMPATIBLE_PLATFORM, "runner platform is incompatible"),
        (report.facts.architecture in runtime.architectures, AdapterPreflightCode.INCOMPATIBLE_ARCHITECTURE, "runner architecture is incompatible"),
        (report.facts.python_version == runtime.python_version, AdapterPreflightCode.INCOMPATIBLE_PYTHON, "runner Python version is incompatible"),
        (report.facts.environment_identity == runtime.environment_identity, AdapterPreflightCode.INCOMPATIBLE_ENVIRONMENT, "runner environment identity is incompatible"),
        (report.facts.framework_version == runtime.framework_version, AdapterPreflightCode.INCOMPATIBLE_FRAMEWORK, "runner framework version is incompatible"),
        (report.facts.accelerator_available, AdapterPreflightCode.MISSING_CUDA if runtime.device_prefix.startswith("cuda") else AdapterPreflightCode.MISSING_MPS, "runner accelerator is unavailable"),
        (report.facts.effective_device.startswith(runtime.device_prefix), AdapterPreflightCode.INCOMPATIBLE_DEVICE, "runner effective device is incompatible"),
        (report.facts.sampling_platform == metadata.sampling_platform, AdapterPreflightCode.INCOMPATIBLE_PLATFORM, "runner sampling platform is incompatible"),
        (report.facts.fallback_disabled, AdapterPreflightCode.FALLBACK_ENABLED, "runner fallback is not disabled"),
        (report.facts.refinement_platform == metadata.refinement_platform, AdapterPreflightCode.INCOMPATIBLE_REFINEMENT_PLATFORM, "runner refinement platform is incompatible"),
    )
    existing = {issue.code for issue in issues}
    for matches, code, message in expected:
        if not matches and code not in existing:
            issues.append(AdapterPreflightIssue(code, message))
            existing.add(code)
    return RunnerPreflightReport(
        report.profile,
        report.runner_protocol_version,
        report.contract_schema_version,
        report.facts,
        tuple(issues),
        report.preflight_schema_version,
    )


@dataclass(frozen=True, slots=True)
class AdapterPreflightReport:
    issues: tuple[AdapterPreflightIssue, ...]
    runner_path: str = ""
    checkpoint_sha256: str = ""

    @property
    def passed(self) -> bool:
        return not self.issues


def assess_adapter_preflight(
    spec: AdapterPreflightSpec,
    *,
    availability: AdapterAvailability | None = None,
) -> AdapterPreflightReport:
    """Check local immutable adapter requirements without downloading artifacts."""
    runtime = availability or AdapterAvailability()
    issues: list[AdapterPreflightIssue] = []
    runner_path = _resolve_runner(spec.runner)
    if not runner_path:
        issues.append(
            AdapterPreflightIssue(
                AdapterPreflightCode.MISSING_RUNNER,
                "external diffusion runner executable is unavailable",
            )
        )
    if spec.protocol_version != DIFFUSION_RUNNER_PROTOCOL_VERSION:
        issues.append(
            AdapterPreflightIssue(
                AdapterPreflightCode.INCOMPATIBLE_PROTOCOL,
                "adapter protocol version does not match the DVBFixer runner protocol",
            )
        )
    if spec.image and spec.image not in runtime.available_images:
        issues.append(
            AdapterPreflightIssue(
                AdapterPreflightCode.MISSING_IMAGE,
                "required immutable diffusion image is unavailable",
            )
        )
    checkpoint_sha256 = ""
    if spec.checkpoint is not None:
        checkpoint_sha256, checkpoint_issue = _checkpoint_digest(spec.checkpoint)
        if checkpoint_issue is not None:
            issues.append(checkpoint_issue)
    if spec.requires_cuda and not runtime.cuda_devices:
        issues.append(
            AdapterPreflightIssue(
                AdapterPreflightCode.MISSING_CUDA,
                "adapter requires a CUDA device but none was reported",
            )
        )
    return AdapterPreflightReport(
        issues=tuple(issues),
        runner_path=runner_path,
        checkpoint_sha256=checkpoint_sha256,
    )


def _resolve_runner(runner: str) -> str:
    if os.sep in runner or (os.altsep is not None and os.altsep in runner):
        path = Path(runner).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            return ""
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            return ""
        return str(resolved)
    return shutil.which(runner) or ""


def _checkpoint_digest(
    checkpoint: LocalCheckpoint,
) -> tuple[str, AdapterPreflightIssue | None]:
    path = checkpoint.path.expanduser()
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return "", AdapterPreflightIssue(
            AdapterPreflightCode.MISSING_CHECKPOINT,
            "required local checkpoint is unavailable",
        )
    except OSError:
        return "", AdapterPreflightIssue(
            AdapterPreflightCode.MISSING_CHECKPOINT,
            "required local checkpoint could not be opened safely",
        )
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            return "", AdapterPreflightIssue(
                AdapterPreflightCode.MISSING_CHECKPOINT,
                "required local checkpoint is not a regular file",
            )
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    actual = digest.hexdigest()
    if actual != checkpoint.sha256.lower():
        return actual, AdapterPreflightIssue(
            AdapterPreflightCode.CHECKPOINT_DIGEST_MISMATCH,
            "local checkpoint SHA-256 does not match the pinned digest",
        )
    return actual, None
