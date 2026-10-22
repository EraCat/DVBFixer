# CIF structure input

[User guide](README.md) · [Command index](commands/index.md) · [Troubleshooting](known-issues.md)

DVBfixer normalizes `.cif` and `.mmcif` at the CLI boundary for commands that
enable structure normalization. Existing PDB inputs are unchanged. `atom-names`
deliberately accepts legacy PDB (`.pdb`/`.ent`) only; `component-info` and
`reconstruct-component` have their own documented authority/input boundaries and
do not use this automatic normalization. See the [command index](commands/index.md).
Outputs follow each command's contract: PDB structure files, reports, topologies,
or directory bundles; accepting CIF does not add CIF output.

PDBx/mmCIF files are read with Gemmi and converted once to a temporary PDB in
the command's output/work directory. The existing scientific pipeline then
processes that PDB normally. The conversion retains coordinate models,
alternate locations, occupancy and B factors, polymer sequences, explicit
links and disulfides, crystal information, and biological-assembly operators.

Small-molecule crystallographic CIF is converted with Open Babel. Fractional
coordinates are transformed to Cartesian coordinates and `_geom_bond`
connectivity is retained. Only sites explicitly present in the asymmetric unit
are converted; DVBfixer does not generate symmetry copies or reconstruct a
molecule crossing a unit-cell boundary.

## Chain identifiers

PDB permits only one-character chain identifiers. DVBfixer preserves existing
unique IDs from `A-Z`, `a-z`, and `0-9`, then deterministically maps only the
remaining CIF identifiers into unused characters. For example, chains `A`,
`heavy`, and `L` become `A`, `B`, and `L`.

The mapping is printed as a warning and added to PDB output as records such as:

```text
REMARK 999 DVBFIXER CIF_CHAIN_MAP B heavy
```

Whitespace or non-ASCII identifiers are percent-encoded in the remark; very
long identifiers use numbered `CIF_CHAIN_MAP_PART` records.

Chain-based command options, FASTA headers, `PATH:CHAIN` template references,
and Homology template plans are translated through the same mapping. A CIF
requiring more than 62 unique PDB chains is rejected.

## PDB limits

Conversion fails before the scientific workflow if the structure cannot be
represented safely in fixed-column PDB. DVBfixer does not silently truncate
chain IDs, atom/residue names, serials, residue identifiers, or coordinates.
CIF output is not supported in this release; choose a `.pdb` output path.

Batch mode discovers `.cif` and `.mmcif` alongside `.pdb` and `.ent`. Temporary
conversion files are created below `--output-dir`, never under `--input-dir`,
and are removed when each command finishes.
