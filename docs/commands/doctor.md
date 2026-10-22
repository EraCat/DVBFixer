# `dvbfixer doctor`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/doctor.md)

Reports installed Python backends, external chemistry executables, available
OpenMM platforms, and static experimental diffusion profile metadata without
starting a structure-processing job.
Modeller is probed in an isolated subprocess, so an installed package with an
invalid or missing license is reported as unavailable without crashing Doctor.

## Quick start

```bash
dvbfixer doctor
dvbfixer doctor --format json
dvbfixer doctor --format json --diffusion-model protpardelle
```

Missing optional tools are reported rather than treated as an error. Use the
JSON form in CI or before submitting a large folder-input run.

## Experimental runner checks

Without `--diffusion-model`, the additive `diffusion` section reports only
the two profiles' immutable status, evidence labels, engine/source/patch and
checkpoint identities, sampling/refinement platforms, protocol versions,
fallback policy, and training-membership status. Selecting a model discovers
its installed, host-compatible private launcher and performs a bounded JSON
handshake. Runner and checkpoint paths are backend-installation details.

The handshake verifies the pinned platform, architecture, Python, engine and
patch state, checkpoint digest, framework version, CUDA or MPS availability,
effective device, disabled fallback, and refinement platform. It does not run
sampling, refinement, or checkpoint/model loading. The runner is trusted
operator code as described by ADR 0011; Doctor invokes it without a shell and
with timeout/output bounds, but does not sandbox it. Reports omit runner and
checkpoint paths, raw environment, credentials, and child stdout/stderr.

`model --backend diffusion` performs the same fail-closed profile handshake
before building the request or starting inference; running Doctor separately is
useful for diagnostics but is not required for enforcement.

## Batch mode

`doctor` does not support directory batch input. It checks the DVBfixer
installation once and has no per-structure input. See the
[batch support matrix](../batch-mode.md#support-by-tool).
