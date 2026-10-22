# DVBfixer GUI

Local graphical workspace for DVBfixer, protein structures, multiple alignment,
and homology modeling. It runs in the browser with a Node backend hosted by
Vite during development or by the bundled standalone server.

For daily use, follow the [GUI user guide](../docs/gui.md). This README covers
setup, server configuration, and implementation details. The broader
[user manual](../docs/README.md) groups scientific tasks and command guides.

Control dimensions, button variants, alignment, wrapping and accessibility follow
the [GUI design system](../docs/gui-design-system.md). Shared MUI defaults live
in `src/theme.ts`; reusable toolbar/action geometry lives in `src/ui/layout.ts`.

The backend invokes `dvbfixer` from `PATH` by default. Configure an alternate
binary with `DVBFIXER_EXECUTABLE` and an optional fixed JSON argument array in
`DVBFIXER_ARGS`; subprocesses have bounded captured output and a configurable
timeout (`DVBFIXER_MAX_OUTPUT_BYTES` and `DVBFIXER_TIMEOUT_MS`).

## What it does

- **3D viewer (×2)** -- interactive [Mol*](https://molstar.org) molecular
  visualization with custom residue-type coloring. Open a second viewer to
  compare structures side-by-side; toggle camera sync via the link icon in
  the top bar.
- **Sequence viewer** -- amino acid sequence with color-coded residue types,
  click or drag to select ranges
- **Pairwise alignment** -- Needleman-Wunsch with BLOSUM62 between any two
  chains, including across two different loaded structures
- **Bidirectional selection** -- click a residue in sequence or alignment, it
  highlights in 3D (solid ball-and-stick) and vice versa
- **Elements tree** -- hierarchical view of polymers, ligands, ions, and water
  with visibility toggles + per-chain **Show Interface** button (5 Å contact
  zone, distinguishes polymer vs ligand on the same chain id)
- **Interactions table** -- computed H-bonds, ionic, disulfide, hydrophobic,
  pi-stacking, and more with chain pair filtering; auto-filters when Show
  Interface is active
- **DVBfixer panel** -- current CLI tools generated from argparse and grouped by
  workflow and argument section. Managed jobs persist across panel reloads,
  stream status, capture bounded logs, and can be cancelled; Atom Names uses a
  separate synchronous naming-conversion request.
- **Homology workspace** -- persistent target/template projects, MAFFT,
  MUSCLE 5, or Clustal Omega MSA, manual gap editing, license-free Biopython
  structural fitting grouped by target chain (with optional Modeller SALIGN), template
  span masks, and model generation
- **Workspaces** -- each workspace owns its files, generated runs/logs,
  active A/B structures, workflow inputs/results, and Homology workflows
- **Workspace file browser** -- alternating rows, Shift/Cmd multi-selection,
  drag-handle and arrow reordering, structure-only filtering, category icons and
  format badges, rename/download/trash context actions, and a dedicated read-only
  Text Files tab
- **Library** -- an ordered list of workspaces; the active workspace's files
  appear in the separate Workspace panel
- **Dockable panels** -- drag panels to rearrange, "+" button to spawn any
  panel into any tabset
- **Local files** -- import files into Workspace or drag and drop them onto it;
  load imported structures into either viewer

The viewer renders in the browser. Workspace uploads, managed DVBFixer jobs,
and their logs are handled by the Node server. With the
default loopback server, data stays on the same machine; when connecting to a
deployed server, files are sent to that server and stored in its workspace data
directory. See the [API guide](../docs/api.md) for authentication and the
[deployment guide](../docs/deployment.md) for a public installation.

### Workspace data and Homology selection

For the complete target-to-model workflow, selection controls, structural
fitting behavior, template-plan schema, diagnostics, and limitations, see the
[GUI Homology Workspace guide](../docs/gui-homology.md).

Workspaces live below `structures/projects/<workspace-id>/` in a versioned
`workspace.json` plus `files/`, `runs/`, and `homology/` directories. On first
start, legacy top-level Library folders become workspaces and ungrouped files go
to `Unsorted`; legacy files remain intact as a recovery source.

Internal bookkeeping (`workspace.json`, run manifests, captured stdout/stderr,
and temporary alignment/model inputs) stays on disk but is hidden from the
workspace file list and workflow file selectors. Right-click a workspace or visible file
to move it to trash. Workspace trash is stored under
`structures/_workspace_trash/`; file trash stays in the owning workspace's
`.trash/` directory.

Library workspaces and Workspace files can be reordered from their drag
handles; the insertion marker shows the future position. The Workspace toolbar
can show only structures without changing their stored order. CIF/mmCIF, PDB,
and other recognized structural formats stay visible; **Show all files** restores
the other files. Both selection and arrow reordering use the same visible rows.
A file context menu
downloads the original file, while a workspace download produces a `.tar.gz`
archive. Structure metadata is stored on the workspace artifact and edited in
Info with revision-aware autosave.

Each file row shows a category icon on the left and a format badge on the right.
The format comes from the actual file path, not the editable display name, so
renaming a PDB to a label without an extension does not hide its format. Recorded
artifact metadata distinguishes reports from generic data/settings even when
both are JSON. The tooltip gives the full workspace-relative path and recorded
creating command/source; unknown provenance is not guessed. Color is supplemental
to the icon shape and text, not the only type indicator.

The Homology Target tab parses FASTA/PIR or protein chains from a workspace
PDB/mmCIF file. **+ Add new** creates a template selector, using the active
viewer structure when available. With multiple target chains, Alignment
shows a target-chain selector and one synchronized, horizontally scrolling
alignment at a time.

| Consensus mark | Meaning |
|---|---|
| `*` | Fully conserved column |
| `:` | Strongly similar residues |
| `.` | Weakly similar residues |
| blank | Mismatch or a column containing a gap |

Click a template residue to select it, Shift-click for a range, and Ctrl/Cmd-
click to add or remove disjoint residues. Selecting a template loads it into
viewer A when necessary and, while linked, synchronizes the 3D highlight. This
selection is transient: **Use selection as modeling span** explicitly copies
it into the persisted model mask. Gap arrows move a gap without changing row
length; the toolbar adds or removes full gap columns.

## Install & run

Use Node.js 22 or newer and an available `dvbfixer` CLI. For the Python/scientific
backends, follow the [installation guide](../docs/installation.md). Both development
and standalone hosting run `dvbfixer --version` before serving requests; they stop
with environment-activation instructions if the probe fails. The GUI does not
automatically choose a scientific environment. A successful version probe does
not guarantee that every optional scientific backend or license is installed.

### Install and start

Create the repository's DVBfixer environment and install the package:

```bash
micromamba create -f environment.yml
micromamba activate dvbfixer
pip install -e .
```

#### Modeller license

`model` and (indirectly) other DVBFixer commands rely on
[Modeller](https://salilab.org/modeller/), which requires a free academic
license. Register at <https://salilab.org/modeller/registration.html>, then:

```bash
micromamba activate dvbfixer
MODELLER_LICENSE_KEY=YOUR_LICENSE_KEY bash gui/scripts/set-modeller-key.sh
```

The helper finds `<env>/lib/modeller-*/modlib/modeller/config.py`, updates it
atomically, validates the license with that environment's Python, and restores
the previous configuration if validation fails. It never prints the key or
leaves a key-bearing backup. You can also pass an explicit prefix as the first
argument.

Start the development server directly with Vite:

```bash
cd gui
npm ci
micromamba activate dvbfixer
npm run dev
```

The development server opens http://localhost:5173 automatically outside test/CI
mode; open it manually if the browser does not launch. Build the browser client and standalone Node server
with `npm run build`; run the build with `npm start`.

**Override DVBFixer** if it's not on PATH (e.g. wrapped in micromamba):

```bash
export DVBFIXER_EXECUTABLE="micromamba"
export DVBFIXER_ARGS='["run", "-n", "dvbfixer", "dvbfixer"]'
```

Set executable overrides before starting the server; the startup probe uses the
same executable and argument prefix as subsequent workflow requests.

In the Model command's **Sequences per chain** editor, residues present in the
loaded coordinates retain structure-presence styling while sequences are
edited. Substitutions update in linear time; insertions/deletions trigger a
short-debounced affine alignment. Very large alignment matrices are skipped to
keep the form responsive. Whitespace is ignored for biological indexing, and
the editing caret remains visible over the highlight layer.

Tool-form autosaves recover automatically when a completed job advances the
workspace revision. Pending local fields are merged into the latest manifest,
so newly registered output files and unrelated panel settings are preserved.

Workspace files and tool outputs open as the complete first coordinate model.
Mol* does not automatically select the first biological assembly: deposited
assembly chain lists may exclude newly assigned ligand chains after Split.
Other models and biological assemblies remain available through Mol* controls.

## Tech stack

React 19, TypeScript 6, Vite 6, Mol*, MUI (Material UI), flexlayout-react,
and Zustand. Host-neutral API composition is in
`server/api-routes.ts`; Vite and the standalone Node server are adapters.

## Panels

| Panel               | Description                                                                 |
|---------------------|-----------------------------------------------------------------------------|
| 3D Structure        | Mol* viewer with custom SCSS skin and residue-type color theme on sticks    |
| 3D Structure (B)    | Independent secondary viewer for side-by-side comparison; camera sync toggle in top bar |
| Sequence            | Monospace amino acid grid, drag-select, independent chain selector per tab  |
| Alignment           | Pairwise Needleman-Wunsch (BLOSUM62) across chains, incl. across structure A and B; click number row to pick the same column on both sides |
| Elements            | Categorized tree (polymer/ligand/ion/water) with per-component visibility + per-chain Show Interface |
| Interactions        | Computed non-covalent + covalent contacts, filterable by type and chain pair |
| DVBfixer            | Generated CLI forms, managed workflow status/logs/Cancel, and synchronous Atom Names conversion |
| Homology            | Target → templates → editable MSA and masks → Modeller (default) or explicit experimental diffusion workflow |
| Library             | Ordered workspace list with rename, archive download, and recoverable trash |
| Workspace           | Active-workspace files with A/B loading, import, filtering, reordering, download, rename, and recoverable trash |
| Info                | Editable artifact metadata and structure statistics with revision-aware autosave |

Every panel can be duplicated via the "+" button on its tabset header.
Sequence panels maintain independent chain selections.

## DVBfixer commands

The panel exposes the [current command set](../docs/commands/index.md), from
structure preparation and modeling through topology generation and diagnostics.
`prepare` uses the `legacy` backend by default and offers `tleap-reduce` for
pure-protein inputs; `salign` uses Biopython by default. The complete command
and flag schema is generated by `../scripts/gen_gui_spec.py` from the argparse
parsers, including repeatable and multi-value options. For exact CLI flags, see
the generated [command reference](../docs/reference/index.md).

Commands other than Atom Names run as workspace-scoped managed jobs. The panel shows queued,
running, succeeded, failed, or cancelled state; restores an active job after a
panel/page reload; streams status with polling fallback; and displays captured
stdout/stderr when the job finishes. Only one job can run in a workspace at a
time. **Cancel** stops the active process, and successful outputs are added to
Workspace and loaded into viewer A when they are structures.

Atom Names calls the dedicated V1 naming endpoint with the selected workspace
artifact ID. **Target FF** selects AMBER, Amber19SB, or CHARMM; **Profile** selects
`gromacs` (default) or native `standard` naming.
**Infer Protonation** (before **Dry Run**, off by default)
identifies supported variants from residue names and existing site H before
dialect conversion; it does not rebuild H or run PROPKA/Reduce. Missing/ambiguous
evidence is reported, not guessed, and explicit overrides win. **Dry Run** returns
a report without registering an output. The GUI reads an optional selected variant-overrides JSON
artifact and sends its array inline. Successful conversions register one new
structure and refresh Workspace; synchronous conversions do not create managed
job history or a Cancel action. See the [naming guide](../docs/commands/atom-names.md).

Status and output belong to the selected tool and workspace. Diagnostic/output
report previews and console logs occupy separate labelled scroll regions;
stderr is not automatically treated as an error. Atom Names displays its
synchronous response inline, not as a nonexistent downloadable report file.

## Workspace management

The **Library** contains workspaces only. Create, activate, reorder, rename,
download, or move a workspace to recoverable trash there. The separate
**Workspace** panel lists files owned by the active workspace. Import local
files with **Import files** in its header, by dropping files onto Workspace, or
with **Import structure** in the global toolbar; generated DVBfixer and
Homology outputs are registered in the same manifest automatically.

When two 3D viewers are open, the `A` / `B` selector in Workspace chooses the
destination for the next structure-file click. Internal run records and logs
remain on disk for reproducibility but stay hidden from ordinary file pickers.

`workspace.json` is the active artifact and metadata source. On first use,
older top-level and per-workspace `index.json` files are imported into workspace
manifests without deleting the legacy files; they remain recovery sources only.
The retired `/structures/index.json` scanner and `/api/library/*` mutation
routes are not served.

## Controls

| Action                       | How                                                          |
|------------------------------|--------------------------------------------------------------|
| Activate workspace           | Click a workspace in Library                                 |
| Load workspace structure     | Click a structure file in Workspace                          |
| Choose target viewer         | `A` / `B` selector in the Workspace header                   |
| Filter workspace files       | **Show structures only** / **Show all files** (includes CIF/mmCIF structures) |
| Reorder workspaces/files     | Drag the row handle to the insertion marker; arrows move selected files |
| Download                     | Context menu → **Download**; workspaces download as `.tar.gz` archives |
| Load your own file           | **Import files** in Workspace, drop files there, or **Import structure** in the top bar |
| Toggle camera sync (A ↔ B)   | Link icon in the top bar                                     |
| Rotate 3D                    | Left-click drag                                              |
| Zoom                         | Scroll wheel                                                 |
| Select residue (3D)          | Click an atom                                                |
| Select residue (seq)         | Click a letter in the Sequence panel                         |
| Select range (seq)           | Click and drag across residues                               |
| Pick aligned column (both A and B) | Click a position in the number row above/below an alignment row |
| Drag-select on alignment     | Click and drag across one side                               |
| Toggle element visibility    | Eye icon in the Elements panel                               |
| Show Interface               | Network/hub icon next to a chain in Elements (zooms to 5 Å contact zone, filters Interactions) |
| Focus interaction            | Click a row in the Interactions panel                        |
| Run a DVBFixer command       | Pick the sub-tab, set the input file, click Run              |
| Cancel a DVBFixer command    | Click **Cancel** while a managed job is queued or running (not synchronous Atom Names) |
| Duplicate a panel            | Click "+" on any tabset header                               |
| Clear 3D markers             | Tap empty space in 3D                                        |
| Clear everything             | Press Escape                                                 |

## Build for production

```bash
npm run build
```

The browser client is written to `dist/` and the Node server bundle to
`dist-server/server.js`. Start both the GUI and API on one origin with:

```bash
npm start
```

The standalone server defaults to `127.0.0.1:5173`. Configuration:

| Variable | Default | Purpose |
|---|---|---|
| `DVBFIXER_HOST` | `127.0.0.1` | Listen address |
| `DVBFIXER_PORT` | `5173` | Listen port |
| `DVBFIXER_GUI_DATA_DIR` | `<gui>/structures` | Workspace storage |
| `DVBFIXER_STATIC_DIR` | `<gui>/dist` | Built browser client |
| `DVBFIXER_SHUTDOWN_GRACE_MS` | `10000` | HTTP drain deadline |
| `DVBFIXER_AUTH_PRINCIPALS` | unset | Versioned JSON principal IDs and SHA-256 token digests |
| `DVBFIXER_LEGACY_WORKSPACE_OWNER` | inferred for one principal | Owner assigned to existing workspaces |
| `DVBFIXER_CORS_ALLOWED_ORIGINS` | `[]` | JSON array of additional exact HTTP(S) origins; same-origin requests remain allowed |
| `DVBFIXER_GUI_MAX_UPLOAD_BYTES` | `268435456` | Maximum workspace import request body (256 MiB) |
| `DVBFIXER_GUI_WORKSPACE_QUOTA_BYTES` | `5368709120` | Logical bytes per workspace (5 GiB); `0` disables the application quota |
| `DVBFIXER_MAX_CONCURRENT_PROCESSES` | `1` | Process-wide FIFO limit for DVBFixer child processes (maximum 64) |
| `DVBFIXER_MAX_QUEUED_PROCESSES` | `16` | Maximum waiting DVBFixer child requests before overload rejection (maximum 256) |
| `DVBFIXER_RATE_LIMIT_REQUESTS` | `120` | Requests allowed per direct client address and window; `0` disables |
| `DVBFIXER_RATE_LIMIT_WINDOW_MS` | `60000` | Fixed rate-limit window duration |
| `DVBFIXER_RATE_LIMIT_MAX_KEYS` | `10000` | Maximum client addresses tracked per server process |
| `DVBFIXER_ACCESS_LOG` | `off` | `off` or structured one-line `json` API access records on stdout |
| `DVBFIXER_AUDIT_LOG` | `off` | `off` or durable `jsonl` audit events on the data filesystem |
| `DVBFIXER_AUDIT_RETENTION_DAYS` | `90` | Local audit retention period in days |
| `DVBFIXER_METRICS` | `off` | `off` or protected process-local Prometheus metrics at `/api/metrics` |
| `DVBFIXER_OS_RESOURCE_LIMITS_REQUIRED` | `0` | Require the Linux systemd/cgroup-v2 resource preflight |
| `DVBFIXER_OS_DATA_FILESYSTEM_MAX_BYTES` | unset | Maximum dedicated data-filesystem capacity when the preflight is enabled |
| `DVBFIXER_OS_TEMP_FILESYSTEM_MAX_BYTES` | unset | Maximum private `/tmp` and `/var/tmp` capacity when the preflight is enabled |
| `DVBFIXER_OS_CPU_QUOTA_PERCENT` | unset | Maximum accepted cgroup CPU quota percentage when the preflight is enabled |
| `DVBFIXER_OS_MEMORY_MAX_BYTES` | unset | Maximum accepted cgroup memory limit when the preflight is enabled |
| `DVBFIXER_OS_MEMORY_SWAP_MAX_BYTES` | unset | Maximum accepted cgroup swap limit when the preflight is enabled |
| `DVBFIXER_OS_TASKS_MAX` | unset | Maximum accepted cgroup task limit when the preflight is enabled |

Without auth configuration, loopback mode uses an implicit `local` principal
and requires no browser token. Configured mode accepts 32-byte base64url bearer
tokens whose SHA-256 digests appear in `DVBFIXER_AUTH_PRINCIPALS`; the GUI keeps
the entered token in `sessionStorage` only. See [the API guide](../docs/api.md#authentication)
for generation and configuration.

Non-loopback binding requires both configured authentication and
`DVBFIXER_ALLOW_INSECURE_REMOTE=1`. API requests enforce same-origin CORS by
default; additional origins must be listed exactly in
`DVBFIXER_CORS_ALLOWED_ORIGINS`. Upload size, workspace storage, and child-process
concurrency have configurable application limits. A fail-closed Linux
systemd/cgroup-v2 resource profile is documented in
[`docs/deployment.md`](../docs/deployment.md). It passed privileged acceptance
on the reference Ubuntu 24.04 VM; provide a trusted TLS proxy and repeat the
acceptance on each installation's host before public access.
Multi-host scheduling is unsupported; same-host processes share durable run
locks and persisted job state. Loopback mode also rejects
non-loopback HTTP `Host` headers to prevent DNS rebinding from bypassing the
local-only boundary. `npm run preview` remains a frontend-only Vite preview and
does not host the APIs.

## Notes

- Water is hidden by default when a structure loads
- The custom color theme (carbons by residue type, non-carbons CPK) applies to focus/stick representations
- Non-canonical amino acids (phosphorylated residues, modified cysteines, protonation variants, etc.) are normalized to standard codes
- Failed workflow output is kept out of the visible workspace manifest and moved to a workspace-scoped failure directory when supported
- The `postinstall` script (`scripts/fix-native-deps.mjs`) handles cross-platform rollup native bindings for macOS and Linux
