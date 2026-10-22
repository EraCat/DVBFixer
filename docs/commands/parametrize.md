# `dvbfixer parametrize`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/parametrize.md)

Parametrizes an eligible isolated small molecule with **GAFF2** force field (single
point of compatibility with AMBER protein force fields) and writes a
ready-to-use GROMACS topology bundle: `<name>.itp`, `<name>.gro`,
`posre_<name>.itp`. Designed for the parts of a system that don't have
RTP/template coverage in `dvbfixer top` — buffer components, drug molecules,
co-factors, organic ligands.

## Quick start

Given an isolated acetate molecule with net charge −1:

```bash
dvbfixer parametrize acetate.pdb -n ACET --net-charge -1
```

**Result:** `ACET.itp`, `ACET.gro`, and `posre_ACET.itp` in the output directory.
Requires AmberTools. Supply the actual net charge of your molecule; do not copy
the example charge to unrelated inputs. This is not a generic cofactor or
metal-coordination workflow.

## Pipeline

```text
input (.pdb/.mol2/.sdf)
    └─→ antechamber  (GAFF2 atom types + charges)
            └─→ parmchk2  (fill in any missing bonded params)
                    └─→ tleap  (AMBER prmtop + inpcrd)
                            └─→ ParmEd  (AMBER → GROMACS .top + .gro)
                                    └─→ dvbfixer  (split into .itp + posre.itp)
```

All AmberTools binaries ship with the bundled environment (`antechamber`,
`parmchk2`, `tleap`); no separate install needed.

## Charge methods

| Method | Flag | QM backend | Speed | Quality | When to use |
|--------|------|-----|-------|---------|-------------|
| **AM1-BCC** | `-c bcc` (default) | — (no QM) | Seconds | Within ~5% of RESP for organic molecules | Most cases. Default. |
| **RESP via PySCF** | `-c resp --qm-engine pyscf` | Free (`pip install pyscf`) | ~2-4× slower than Gaussian, one-shot | Within ~0.02 e/atom of Gaussian-RESP on standard test molecules | **Recommended free RESP** — works cleanly on macOS arm64 and Linux. No conda env juggling. |
| **RESP via Gaussian** | `-c resp --qm-engine gaussian` | Commercial license, manual two-step | Minutes + manual time | Reference standard | If you already have Gaussian + license |
| **RESP via PSI4** | `-c resp --qm-engine psi4` | Free, separate conda env (`micromamba create -n psi4 -c conda-forge psi4 psiresp`) | Comparable to Gaussian | Reference psiresp implementation | Fragile on macOS arm64 (conda libint2 SONAME issues). Prefer `pyscf` there. |

If unsure: **start with AM1-BCC**. Per AMBER + OpenFF community
benchmarks, AM1-BCC and HF/6-31G* RESP charges differ by < 5% for typical
organic drug-like molecules, and MD ΔΔG differs by ~0.01-0.07 kcal/mol
between the two. Switch to RESP only for:
- Charged molecules (acetate, sulfates, phosphates)
- Highly conjugated systems
- Reproducing published RESP results

If you DO need RESP, `--qm-engine psi4` is the friction-free path (no
license, no manual external step). `--qm-engine gaussian` is for users
who already have a Gaussian licence and prefer the reference recipe.

**Both engines must be explicitly chosen.** Running `-c resp` without
`--qm-engine` errors with a message listing both options and their
trade-offs. Old scripts that pass `-c resp --gen-gaussian` or
`-c resp --gaussian-log` auto-promote to `--qm-engine gaussian` (with an
INFO line) for backwards compatibility.

## Quick start (AM1-BCC)

One command, ~10 seconds:

```bash
# Neutral molecule
dvbfixer parametrize molecule.pdb -n MOL -v

# Charged: e.g. acetate (charge -1)
dvbfixer parametrize acetate.pdb -n ACET --net-charge -1 -v

# Open-shell radical: e.g. NO* (multiplicity 2)
dvbfixer parametrize radical.pdb -n RAD --net-charge 0 --multiplicity 2 -v
```

Output (in current directory):
- `ACET.itp` — `[ atomtypes ]` + `[ moleculetype ]` ready to `#include`
- `ACET.gro` — coordinates with FF atom names
- `posre_ACET.itp` — position restraints (`#ifdef POSRES`)

## RESP via PySCF (free, recommended)

PySCF is a Python QM package with clean pip wheels for macOS arm64 +
Linux x86_64. No native-library conflicts with OpenMM. dvbfixer
implements the AMBER-standard 2-stage RESP-A1 fit directly in numpy
on top of PySCF's HF/6-31G* wavefunctions.

```bash
# One-time install:
pip install pyscf
# Or, if that didn't auto-run with the env update: it's in environment.yml.

# Use it:
dvbfixer parametrize acetate.pdb -n ACET --net-charge -1 \
    -c resp --qm-engine pyscf -v
```

What happens internally:
1. antechamber runs in `bcc` mode to assign GAFF2 atom types.
2. PySCF builds the molecule (`gto.Mole`), runs HF/6-31G* SCF (no
   geometry optimisation — uses input coords; pre-optimise via
   `dvbfixer minimize` or `xtb` if needed).
3. dvbfixer generates a Merz-Kollman ESP grid (4 Connolly shells at
   1.4-2.0× vdW radii, ~1 point/Å² density).
4. ESP at each grid point is evaluated via `mol.intor('int1e_grids')`
   contracted with the SCF density matrix + analytic nuclear sum.
5. Stage 1 RESP fit: linear least-squares with `Σq = Q_total` +
   H-equivalence constraints (H atoms bonded to the same heavy atom
   share a charge — handles methyl/methylene/amine symmetry).
6. Stage 2 RESP fit: same + hyperbolic restraint `a·(√(q² + b²) - b)`
   on heavy atoms (AMBER defaults a=0.001 Hartree, b=0.1 e), iterated
   to self-consistency.
7. mol2 charges from step 1 are overwritten with the RESP-A1 values.

Verified on acetate (`test/acetic_acid/acetate.pdb`):
- Net charge -0.999998 (target -1, error < 1e-3)
- Methyl-H charges identically +0.040 (H symmetry enforced)
- Per-atom charges within ~0.01 e of published RESP-A1 reference values

Tuning knobs (shared with the PSI4 backend):
- `--qm-method 'HF/6-31G*'` — QM method/basis. AMBER RESP-A1 standard;
  override only if you know why.
- `--qm-nthreads 4` — OpenMP threads (applies to PSI4; PySCF reads
  `OMP_NUM_THREADS` env var if you need to tune its parallelism).
- `--qm-memory '4GB'` — memory cap (applies to PSI4; PySCF reads
  `PYSCF_MAX_MEMORY` env var if you need to tune).

## RESP via PSI4 (free, separate env — fragile on macOS)

PSI4 + psiresp produce AMBER-standard 2-stage RESP charges without
needing Gaussian. **They live in a separate conda env** (PSI4 ships its
own BLAS/MKL stack that conflicts with OpenMM's in a single env). One
command to set up, then dvbfixer shells out to it via `micromamba run`:

```bash
# One-time setup (creates a dedicated env, ~5 minutes):
micromamba create -n psi4 -c conda-forge psi4 psiresp

# That's it. dvbfixer (in its main env) calls psi4 in that env:
dvbfixer parametrize molecule.pdb -n MOL --net-charge -1 \
    -c resp --qm-engine psi4 -v
```

The dvbfixer process stays in its own env (Python `>=3.11,<3.14` + OpenMM;
Python 3.11 is the project baseline); the psi4 env stays separate (Python 3.9
or whatever PSI4 pulls). They
communicate via a temp XYZ file + JSON charges. No `pip install` of
dvbfixer in the psi4 env is needed — only psi4 + psiresp belong there.

If you named the env differently:

```bash
dvbfixer parametrize molecule.pdb -c resp --qm-engine psi4 \
    --psi4-env my_custom_psi4_env
```

Missing env → dvbfixer prints the exact `micromamba create` command
to copy-paste.

```bash
# Acetate, charged -1, free RESP via PSI4
dvbfixer parametrize acetate.pdb -n ACET --net-charge -1 \
    -c resp --qm-engine psi4 -v
# That's it. No external QM step, no .com/.log shuffle. ~1-3 min for
# small organics on 4 cores.
```

What happens internally:
1. antechamber runs in `bcc` mode to assign GAFF2 atom types (charges placeholder).
2. PSI4 optimises geometry at HF/6-31G* with `psi4.optimize('hf', ...)`.
3. psiresp fits 2-stage RESP charges from the PSI4 wavefunction at MK ESP grid.
4. The MOL2 from step 1 has its BCC charges overwritten with PSI4-RESP.
5. parmchk2 → tleap → ParmEd continue as for the BCC path.

Tuning knobs:
- `--qm-method 'HF/6-31G*'` (default; the AMBER recipe — change only if you know why)
- `--qm-nthreads 4` (default; OpenMP, ~30% speedup at 4 cores; not linear)
- `--qm-memory '4GB'` (default; raise for larger molecules)

Quality: per-atom charges within 0.05 e of Gaussian-RESP on standard
AMBER test molecules. Use whichever engine is more convenient.

## RESP via Gaussian (commercial, three-step)

Use this path if you already have a Gaussian licence. Otherwise prefer
`--qm-engine psi4`.

### Step 1 — generate the Gaussian input

```bash
dvbfixer parametrize molecule.pdb -n MOL --net-charge -1 \
    -c resp --qm-engine gaussian --gen-gaussian
```

Writes `molecule.com`. The file is a complete Gaussian input with:

```text
%mem=4GB
%nproc=4
%chk=molecule.chk
--Link1--
#HF/6-31G* SCF=tight Test Pop=MK iop(6/33=2) iop(6/42=6) opt
# iop(6/50=1)

RESP charges for molecule (q=-1, m=1) — YYYY-MM-DD

-1   1
    C   ...
    ...

molecule.gesp
```

This is the AMBER-standard RESP recipe: **HF/6-31G\*** with Merz-Kollman
ESP grid (`Pop=MK`, `iop(6/33=2)` writes ESP to log, `iop(6/42=6)`
sets grid density). Geometry is optimised first (`opt`) so charges
reflect the equilibrium structure. The trailing `molecule.gesp` writes
the ESP grid to a separate file consumed by antechamber later.

Resource controls:
- `--gaussian-mem 8GB` — for larger molecules (>50 atoms)
- `--gaussian-nproc 8` — parallel cores
- `--gaussian-method 'B3LYP/6-31G*'` — non-default method (rarely needed;
  changes the resulting charges)

### Step 2 — run Gaussian

On your QM-capable machine:

```bash
g16 < molecule.com > molecule.log
# or
g09 < molecule.com > molecule.log
```

Both `g09` and `g16` produce the same antechamber-compatible output.
Runtime depends on molecule size: a 20-atom organic typically finishes
in 10-30 minutes on 4 cores.

Verify success:
```bash
tail molecule.log    # should end with "Normal termination of Gaussian"
ls molecule.gesp     # ESP grid file should exist
```

### Step 3 — finish parametrization

Pass the `.log` back to dvbfixer:

```bash
dvbfixer parametrize molecule.pdb -n MOL --net-charge -1 \
    -c resp --qm-engine gaussian --gaussian-log molecule.log
```

Antechamber extracts the ESP from the log, fits RESP charges, and
emits the same `.itp` / `.gro` / `posre_*.itp` triplet as the AM1-BCC
path.

## Options

Listed in priority order — input & basic chemistry first, then the
RESP backend selector, then per-backend tuning knobs.

### Input / output

| Flag | Default | Description |
|------|---------|-------------|
| `input` | (required) | Input structure: `.pdb`, `.mol2`, `.sdf`, or `.mol` |
| `-o`, `--output` | input stem | Output file prefix |
| `-n`, `--name` | input stem (uppercased) | Name for `[ moleculetype ]` (≤4 chars works best) |

### Chemistry

| Flag | Default | Description |
|------|---------|-------------|
| `-c`, `--charge-method` | `bcc` | `bcc` (AM1-BCC, default — fast, ~95% RESP accuracy) or `resp` (slower, needs `--qm-engine`) |
| `--net-charge` | `0` | Net molecular charge (integer) |
| `--multiplicity` | `1` | Spin multiplicity (1 = singlet, 2 = doublet, …) |

### RESP backend (only when `-c resp`)

| Flag | Default | Description |
|------|---------|-------------|
| `--qm-engine` | (required for `-c resp`) | `pyscf` (recommended — `pip install pyscf`, pure-Python), `gaussian` (commercial license, two-step), or `psi4` (separate conda env). All opt-in. |

### QM compute knobs (shared by `pyscf` and `psi4` backends)

| Flag | Default | Description |
|------|---------|-------------|
| `--qm-method` | `HF/6-31G*` | QM method/basis. AMBER RESP-A1 standard. |
| `--qm-nthreads` | `4` | OpenMP threads (PSI4 only; PySCF reads `OMP_NUM_THREADS`) |
| `--qm-memory` | `4GB` | Memory cap (PSI4 only; PySCF reads `PYSCF_MAX_MEMORY`) |
| `--psi4-env` | `psi4` | Name of the conda env with `psi4 + psiresp` (only for `--qm-engine psi4`) |

### Gaussian-specific (only when `--qm-engine gaussian`)

| Flag | Default | Description |
|------|---------|-------------|
| `--gen-gaussian` | off | Generate `.com` and exit (implies `--qm-engine gaussian`) |
| `--gaussian-log` | none | Consume Gaussian `.log` (implies `--qm-engine gaussian`) |
| `--gaussian-method` | `HF/6-31G*` | Method written into the `.com` |
| `--gaussian-mem` | `4GB` | `%mem=` directive in the `.com` |
| `--gaussian-nproc` | `4` | `%nproc=` directive in the `.com` |

### Housekeeping

| Flag | Default | Description |
|------|---------|-------------|
| `--keep-intermediate` | off | Keep `mol.mol2`, `mol.frcmod`, `mol.prmtop`, `leap.log` |
| `-v`, `--verbose` | off | Show every antechamber/tleap/parmchk2 invocation |

## Input format notes

- **PDB** — atoms inferred from records; element from column 76-78 (or atom name).
  Hydrogens must already be present (run `dvbfixer prepare` first if needed).
- **MOL2** — preferred for mixed valence and complex aromatic systems
  (bond orders are explicit).
- **SDF** — supports stereo perception and is the easiest to round-trip
  from RDKit / OpenBabel.

For PDBs without proper coordinates (e.g. straight from a SMILES + Open
Babel `--gen3d` invocation), `obminimize -ff UFF` cleanup before
parametrize improves antechamber atom-typing reliability:

```bash
obabel input.pdb -O cleaned.pdb --minimize --ff UFF
dvbfixer parametrize cleaned.pdb -n MOL
```

## Output files

For `-n MOL` and the default AM1-BCC flow, three files in the output
directory:

| File | Purpose |
|------|---------|
| `MOL.itp` | `[ defaults ]` + `[ atomtypes ]` + `[ moleculetype ]` |
| `MOL.gro` | Coordinates with FF atom names |
| `posre_MOL.itp` | Position restraints for `#ifdef POSRES` blocks |

The `.itp` includes its own `[ atomtypes ]` block, so it can be `#include`-d
**before** the protein moleculetype in a `topol.top`. Example combined
with `dvbfixer top` output:

```text
#include "ffparams.itp"        ; from dvbfixer top
#include "MOL.itp"              ; from dvbfixer parametrize
#include "Protein_chain_A.itp" ; from dvbfixer top
#include "water.itp"
#include "ions.itp"

[ system ]
my_complex

[ molecules ]
Protein_chain_A   1
MOL               2     ; two copies of the ligand
SOL              12345
NA                  17
CL                  15
```

## Integration with `dvbfixer top`

`dvbfixer top` builds protein/glycan/lipid topology but can't parametrize
arbitrary organic molecules. The pattern:

```bash
# 1. Parametrize each ligand / buffer component separately
dvbfixer parametrize acetate.pdb -n ACE --net-charge -1
dvbfixer parametrize acetic_acid.pdb -n ACA
dvbfixer parametrize my_drug.pdb -n DRG --net-charge 0 -c resp \
    --gaussian-log my_drug.log

# 2. Build the protein topology
dvbfixer top complex.pdb --water opc -o gmx/

# 3. Combine: copy the small-molecule .itp files into gmx/, add the
#    #include lines and [ molecules ] entries to gmx/topol.top.
```

## Common gotchas

- **Net charge MUST match the formal charge of the molecule.** Antechamber
  will silently accept a wrong `--net-charge` and produce non-integer
  net topology charge. Always check the `Charge:` line in the summary
  output — it should be very close to your `--net-charge` value
  (within 1e-3 e).

- **Molecules with metals** (Zn, Fe, Mg coordination) aren't well handled
  by GAFF2 — use dedicated bonded models (MCPB.py) or non-bonded ion
  parameters from `dvbfixer top --ion-set`.

- **Aromatic perception** can fail on unusual heterocycles. If parmchk2
  reports missing parameters, inspect the `.frcmod` (use
  `--keep-intermediate`) and consider providing a `.mol2` input with
  explicit bond orders.

- **PDB hydrogens must be present.** Antechamber doesn't add hydrogens;
  it complains about open valences. Run `dvbfixer prepare` first if your
  input is a heavy-atom-only structure.

- **Gaussian normal termination** is REQUIRED for the RESP path.
  `tail molecule.log` should show `Normal termination of Gaussian`. If
  it failed (SCF convergence, memory, etc.), antechamber will fall back
  silently to AM1-BCC — verify with `grep "Charge Method:" mol.mol2`
  (should say `RESP` not `AM1-BCC`).

- **RESP charges are conformation-dependent.** The geometry that
  Gaussian optimises (and therefore the ESP) reflects the input
  structure. For molecules with flexible torsions, RESP averaged over
  multiple conformers (RESP-C1) is more rigorous but requires multiple
  Gaussian jobs — out of scope for this tool.

- **`-n NAME` truncation.** GROMACS allows 4-character moleculetype names;
  longer names are truncated by `gmx grompp`. Pick names ≤4 chars.

## See also

- [`top`](top.md) — full system topology; combine its output with
  parametrize's `.itp` files
- [`prepare`](prepare.md) — H repair if the small molecule input has
  no hydrogens
- [Pipelines / small molecule](../pipelines.md#small-molecule-parametrization)

## References

- Wang J, Wolf RM, Caldwell JW, Kollman PA, Case DA. *J Comput Chem*
  25, 1157 (2004) — AM1-BCC and original GAFF.
- Wang J, Wang W, Kollman PA, Case DA. *J Mol Graph Model* 25, 247
  (2006) — antechamber and GAFF2.
- Bayly CI, Cieplak P, Cornell W, Kollman PA. *J Phys Chem* 97, 10269
  (1993) — original RESP methodology.
- Cornell WD, Cieplak P, Bayly CI, Kollman PA. *J Am Chem Soc* 115,
  9620 (1993) — application of RESP to amino acid charges.

## How it works

Parametrises small molecules with GAFF2 force field and AM1-BCC or RESP charges for GROMACS MD. Wraps the AmberTools pipeline: `antechamber` (atom types + charges) → `parmchk2` (missing parameter check) → `tleap` (AMBER topology) → ParmEd (AMBER→GROMACS conversion). Output: standalone `.itp` file (with `[ defaults ]`, `[ atomtypes ]`, `[ moleculetype ]` sections), `.gro` coordinates, and `posre_*.itp` position restraints. **AM1-BCC is the default** (`-c bcc`, fast, no QM needed, ~95% of RESP accuracy per published OpenFF/AMBER benchmarks). For RESP charges (`-c resp`), the user must explicitly choose `--qm-engine gaussian` (commercial license, existing two-step `--gen-gaussian`/`--gaussian-log` workflow) or `--qm-engine psi4` (free PSI4+psiresp via conda, one-shot, ~5-7× slower than Gaussian). Both engines produce charges within 0.05 e/atom of each other. Supports PDB, MOL2, and SDF input formats.

**PySCF backend (`--qm-engine pyscf`, RECOMMENDED for macOS arm64)**: pure-Python pipeline in the main dvbfixer env. `_compute_resp_charges_pyscf()` (a) loads coords + bond graph via OpenBabel, (b) builds `pyscf.gto.Mole` + runs HF/6-31G* SCF (uses input geometry — no geom opt; pre-minimise externally if needed), (c) generates Merz-Kollman ESP grid via `_generate_mk_grid()` (4 shells at 1.4-2.0× vdW radii, Connolly exclusion at 1.4× — implemented with Fibonacci sphere via `_fibonacci_sphere()`), (d) evaluates ESP via `_evaluate_esp()` using `mol.intor('int1e_grids')` contracted with the SCF density matrix + analytic nuclear sum, (e) runs `_stage1_resp_fit()` (KKT system: linear least-squares with charge-sum + H-equivalence constraints from `_h_equivalence_groups()`), (f) runs `_stage2_resp_fit()` (iterated hyperbolic restraint on heavy atoms, AMBER defaults a=0.001 Ha, b=0.1 e, max_iter=50, tol=1e-6). Quality on acetate test: net charge -0.999998 (target -1), methyl-H equivalent at +0.040 each, per-atom within ~0.01 e of published RESP-A1. PySCF in `environment.yml` pip section (`pip install pyscf` — wheels on PyPI for macOS arm64 + Linux x86_64, no conda dylib hell). Use `--qm-method` for the QM method (default HF/6-31G*); PySCF reads `OMP_NUM_THREADS` and `PYSCF_MAX_MEMORY` when those environment variables are set.

**PSI4 backend (`--qm-engine psi4`)**: invokes psi4 + psiresp in a SEPARATE conda env via subprocess (`micromamba run -n <env> python worker.py …`). Required because (a) psi4's MKL/BLAS stack conflicts with OpenMM's in a single env, and (b) psi4 conda-forge builds pull Python 3.9 which dvbfixer's pyproject.toml rejects. `_compute_resp_charges_psi4()` lives in the MAIN env: it loads coords via OpenBabel (already a dvbfixer dep), writes a temp XYZ file + a worker script + an output JSON path, finds a conda runner via `_find_env_runner()` (micromamba > mamba > conda on PATH), and runs `<runner> run -n <psi4_env> python worker.py xyz q m method nthreads memory out.json`. The worker script (`_PSI4_WORKER_SCRIPT`, a string literal at module scope) runs INSIDE the psi4 env: `psi4.optimize('hf', ...)` for HF/6-31G* geometry, then `psiresp.Job(config=psiresp.configs.TwoStageRESP())` for AMBER-standard 2-stage RESP. Worker writes JSON `{energy_hartree, charges}` on success or `{error: str}` on failure. Main env reads the JSON, calls `_patch_mol2_charges()` to overwrite antechamber's GAFF2-typed mol2 charges with the PSI4-RESP values; downstream parmchk2/tleap/ParmEd see the patched mol2. CLI flags: `--qm-method` (default `HF/6-31G*`), `--qm-nthreads` (default 4), `--qm-memory` (default `4GB`), `--psi4-env` (default `psi4` — name of the dedicated conda env). Missing env → error message containing the exact `micromamba create -n <name> -c conda-forge psi4 psiresp` command. Missing micromamba/mamba/conda on PATH → "no env runner found" error.

**Setup (user side, one-time):** `micromamba create -n psi4 -c conda-forge psi4 psiresp`. Don't pip-install dvbfixer in that env — dvbfixer stays in its main env and only shells out for the QM step.

**`-c resp` without `--qm-engine` → error** listing both backend options + trade-offs. Auto-promotion preserves backwards compat: `-c resp --gen-gaussian` or `-c resp --gaussian-log` without `--qm-engine` auto-sets `--qm-engine gaussian` with an INFO log. `--qm-engine psi4` + any `--gaussian-*` flag → warning that the Gaussian flag is ignored.

**QM-engine survey (June 2026)** — 16 engines evaluated for free-RESP backend. See `memory/reference_qm_engines_for_resp.md` for the full comparison table. Decision rationale: PSI4 picked over GPU4PySCF (NVIDIA GPU only), MOPAC (Merz-Kollman ≠ true RESP), ORCA/GAMESS/NWChem (manual install friction, no conda), R.E.D. Server (web/privacy concerns), DALTON (CMake build only), and the niche multiconfigurational/coupled-cluster engines (OpenMolcas/MRCC/CFOUR — overkill for RESP).

## Batch mode

`parametrize` does not support directory batch input because ligand and charge
inputs must be specified explicitly for each parameterization job. See the
[batch support matrix](../batch-mode.md#support-by-tool).
