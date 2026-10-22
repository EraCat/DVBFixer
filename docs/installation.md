# Installation

[User guide](README.md) · [Quick start](quick-start.md) · [Troubleshooting](known-issues.md)

## 1. Get the source

Install [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html)
and Git first. The commands below assume a terminal on macOS or Linux; on
Windows use WSL. Check backend availability with `doctor` after installation.

```bash
git clone https://github.com/lilpoundcake/DVBFixer.git
cd DVBFixer
```

## 2. Create the environment

Run these commands from the repository root:

```bash
micromamba create -f environment.yml
micromamba activate dvbfixer
pip install -e .
```

The full environment includes the scientific Python stack and external tools.
Keep Python in the supported `>=3.11,<3.14` range. Editable installation uses
the checkout directly; keep it in place while using this environment.

## 3. Configure MODELLER

Gap rebuilding and comparative modeling need a MODELLER license. Complete the
[license instructions](#modeller-installation-and-license) before those workflows.
Other tools can be checked without it.

## 4. Verify the installation

```bash
dvbfixer --version
# dvbfixer 0.9.1
dvbfixer doctor
dvbfixer msa --list-engines
```

Read unavailable-backend messages in the capability report. A missing optional
tool does not block every workflow; consult the command you plan to run.

Without activating the environment, prefix a command with
`micromamba run -n dvbfixer`, for example:

```bash
micromamba run -n dvbfixer dvbfixer doctor
```

Continue to the [quick start](quick-start.md) or [GUI guide](gui.md).
The remaining sections cover alternative installations and specific dependencies.

## Wheel installation and bundled force fields

For a non-editable installation, build or install the wheel normally. Release
wheels include the AMBER99SB-ILDN/Lipid21, official GROMACS `v2026.3`
Amber19SB, and CHARMM36 GROMACS force-field trees used by `dvbfixer top`; no
repository checkout or separate GROMACS force-field installation is required. At runtime they resolve under the active
environment's `share/dvbfixer/FF/` directory. Editable installs continue to use
the checkout's top-level `FF/` directory.

The Amber19SB tree is redistributed unmodified under the GROMACS LGPL 2.1
terms. Wheels install its complete byte-verified inventory and corresponding
notice under `share/dvbfixer/`. Source provenance, hashes, citations, and the
license assessment are recorded in
[`provenance/amber19sb-gromacs.md`](provenance/amber19sb-gromacs.md).

## CIF conversion backends

PDBx/mmCIF input uses Gemmi; small-molecule crystallographic CIF uses Open
Babel. Both are installed by `environment.yml`, and pip installations declare
`gemmi` plus the prebuilt `openbabel-wheel` explicitly. Verify the active
environment with `python -c "import gemmi; from openbabel import openbabel"`.
If only PDB input is used, the conversion layer is not invoked.

## AmberTools and MolProbity Reduce

The `tleap-reduce` preparation backend requires both `tleap` (AmberTools) and
the `reduce` executable (MolProbity). `environment.yml` declares `ambertools`
and `reduce` separately; an existing environment containing `tleap` is not proof
that Reduce is installed. Repair an incomplete environment with:

```bash
micromamba install -n dvbfixer -c conda-forge -c bioconda ambertools reduce
micromamba run -n dvbfixer dvbfixer doctor
```

Missing Reduce is fatal for the explicitly selected `tleap-reduce` backend.
Legacy preparation reports the missing optional Reduce step and falls back to
its documented input-H/tautomer policy; that warning does not establish that the
external tool ran successfully.

## Multiple-sequence alignment executables

`dvbfixer msa`, `dvbfixer homology --template-plan`, and the GUI Homology
workspace run an external alignment
program. The full `environment.yml` installs all three supported engines:

```bash
micromamba create -f environment.yml
micromamba activate dvbfixer
dvbfixer msa --list-engines
```

For an existing conda/micromamba environment, install one or more engines
from conda-forge/bioconda. MAFFT is the default and is sufficient by itself:

```bash
micromamba install -n dvbfixer -c conda-forge -c bioconda mafft
# Optional alternatives:
micromamba install -n dvbfixer -c conda-forge -c bioconda "muscle>=5" clustalo
```

The commands must be available on `PATH` under these exact names:

| Engine | Required executable | Check |
|---|---|---|
| MAFFT | `mafft` | `mafft --version` |
| MUSCLE 5 | `muscle` | `muscle -version` |
| Clustal Omega | `clustalo` | `clustalo --version` |

On macOS, Homebrew users can install the native packages with
`brew install mafft muscle clustal-omega`. On Debian/Ubuntu, distribution
packages are commonly available as `mafft`, `muscle`, and `clustalo`, but
verify that the `muscle` package is version 5: MUSCLE 3 uses a different CLI
and is not supported. Native Windows users should use WSL with the Linux
instructions, or download upstream binaries and put their directory on
`PATH`. When installing a standalone MUSCLE binary, rename it to `muscle`
(`muscle.exe` on Windows); rename a standalone Clustal Omega binary to
`clustalo` (`clustalo.exe` on Windows).

After any standalone installation, restart the GUI/dev server so it inherits
the updated `PATH`, then confirm detection with:

```bash
dvbfixer msa --list-engines
```

`--engine auto` selects the first installed engine in this order: MAFFT,
MUSCLE 5, Clustal Omega. See the official download pages for
[MAFFT](https://mafft.cbrc.jp/alignment/software/),
[MUSCLE 5](https://drive5.com/muscle5/manual/install.html), and
[Clustal Omega](http://www.clustal.org/omega/).

## Modeller installation and license

Salilab MODELLER is currently required for `dvbfixer model` when gaps need to be
built and for final `dvbfixer homology` comparative-model construction. It is
also required when `dvbfixer salign --engine modeller` is selected; the default
Biopython SALIGN engine does not need MODELLER. Fast `model` inputs with no
sequence gaps can take the Python-only copy path without invoking it.

MODELLER needs a free academic license key. Register at
<https://salilab.org/modeller/registration.html>, then set the key in
`<env>/lib/modeller-10.8/modlib/modeller/config.py`.

MODELLER remains the default modeling backend. Experimental runners below are
separate installations, not replacements installed by the main environment.

## Experimental diffusion runner environments

`dvbfixer model --backend diffusion` is an explicit, narrow experimental path;
MODELLER remains the default. The core DVBFixer environment intentionally does
not install PyTorch, CUDA/MPS packages, Protenix, Protpardelle, or checkpoints.
Create the selected runner environment separately and register it once with its
deployment README. The registration verifies the local checkpoint and installs
a private launcher; normal `model --backend diffusion` calls do not accept or
require runner, profile, checkpoint, or digest paths. DVBFixer never downloads
checkpoints and never falls back to another profile or MODELLER.

- Linux/NVIDIA `protenix-v1-cuda`: follow
  [`deploy/protenix-v1/README.md`](../deploy/protenix-v1/README.md). The portable
  wrapper and one public-CLI reconstruction passed on the pinned NVIDIA host;
  the frozen 231-case production-wrapper replay remains pending.
- Linux/NVIDIA `protpardelle-1c-cuda`: follow the
  [CUDA setup](../deploy/protpardelle-1c/README.md#public-linuxnvidia-cuda-profile).
  Sampling and refinement use separate pinned environments. The profile provides
  automatic local context for one internal 5–10-residue gap in canonical proteins.
- Native Apple Silicon `protpardelle-1c-mps-local-v1`: follow
  [`deploy/protpardelle-1c/README.md`](../deploy/protpardelle-1c/README.md) and
  use its pinned arm64 sampling environment and a separate core CPU-refinement
  interpreter via `--refinement-python` (keep the venv path, not its resolved
  symlink target). Sampling requires Torch 2.6.0; initial refinement is pinned to
  Python 3.12, OpenMM 8.5.2 and NumPy 2.4.6. Set
  `PYTORCH_ENABLE_MPS_FALLBACK=0` before Python starts. The bounded corrected profile
  does not replace the historical `protpardelle-1c-mps` identity; optional legacy
  registration uses `protpardelle-mps-legacy`. Evidence remains descriptive and
  training membership is not independently attested.

The supported input slice and directory-bundle output are documented under
[`dvbfixer model`](commands/model.md#experimental-diffusion-scope).
Before inference, inspect static profile status or run the no-inference
environment handshake with `dvbfixer doctor`; see the
[`doctor` command](commands/doctor.md). A successful handshake verifies the
selected wrapper and checkpoint environment but does not replace hardware
cohort acceptance or prove broader scientific support.

## Optional RESP charge engines

**PySCF** is already included in `environment.yml`:

PySCF is pip-installed automatically by `environment.yml`. It enables the recommended free RESP path:

```bash
dvbfixer parametrize molecule.pdb -c resp --qm-engine pyscf -v
```

The default AM1-BCC charge method needs no QM engine. Select RESP when your
parameterization protocol requires it; see [parametrize](commands/parametrize.md).

**Optional: PSI4 backend for RESP (alternative to PySCF).** The `--qm-engine psi4` path is supported but requires a **separate conda env** (PSI4 ships its own BLAS/MKL stack that conflicts with OpenMM's, and PSI4 conda-forge builds pull Python 3.9 which dvbfixer doesn't accept):

```bash
# One-time setup (~5 minutes):
micromamba create -n psi4 -c conda-forge psi4 psiresp
```

**Do NOT pip-install dvbfixer in the psi4 env** — dvbfixer stays in its main env and shells out to the psi4 env via `micromamba run -n psi4 python …` when `--qm-engine psi4` is invoked. Override the env name via `--psi4-env <name>`.

Fragile on macOS arm64 (libint2 SONAME mismatches). On macOS, prefer `--qm-engine pyscf`.

## NumPy/SciPy BLAS backend

The main conda environment selects OpenBLAS for all three BLAS/LAPACK wrappers.
If an older Linux environment aborts with missing `libmkl_gf_lp64.so.3`, repair it:

```bash
micromamba install -n dvbfixer -c conda-forge \
  'libblas=*=*openblas' 'libcblas=*=*openblas' 'liblapack=*=*openblas'
micromamba run -n dvbfixer python scripts/check_scientific_linalg.py
```

Run the smoke check from the checkout. It exercises real NumPy/SciPy solves.
This policy does not change pip wheels or isolated RESP/research environments.

## Other installation problems

- Python 3.14 breaks the supported PROPKA version: retain the Python upper bound.
- NumPy remains pinned below 2.5 for the Python 3.11 development baseline.
- On macOS Docker bind mounts, create the environment on the container's native
  filesystem if ncurses symlink creation fails.

See [environment troubleshooting](known-issues.md#environment-and-developer-notes)
for symptoms and repair details.

## Next steps

- Try the [quick start](quick-start.md) or [GUI guide](gui.md)
- Browse the [command index](commands/index.md)
- Read the [pipelines](pipelines.md) page for end-to-end recipes
- Skim the [known issues](known-issues.md)
