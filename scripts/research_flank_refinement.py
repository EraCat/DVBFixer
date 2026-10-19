"""Private bounded-flank research adapter; does not change production refinement.

An isolated copy of the existing v6 module receives an explicitly extended mobile
mask and an additional positional force. Public fixed-coordinate semantics remain
unchanged; research validation reports that distinction separately.
"""

from __future__ import annotations

import uuid
from functools import wraps
from pathlib import Path

import numpy as np
import openmm
from openmm.app import ForceField
from run_protein_context_ablations import _load

from dvbfixer.model.diffusion.contract import AtomIdentity, ResidueIdentity
from dvbfixer.model.diffusion.runner_refinement import rewrite_generated_coordinates
from dvbfixer.model.diffusion.validate import _parse_pdb_text

ROOT = Path(__file__).resolve().parents[1]
FLANK_K_KJ_MOL_NM2 = 10000.0
FLANK_WALL_K_KJ_MOL_NM2 = 1000000.0
FLANK_WALL_RADIUS_ANGSTROM = 0.25
FLANK_MAX_DISPLACEMENT_ANGSTROM = 0.30


def flank_atoms(request):
    anchors = {anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor}
    return tuple(atom for atom in request.fixed_atoms if ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) in anchors)


def restraint_force(topology, targets):
    force = openmm.CustomExternalForce(
        "0.5*flank_k*r2+0.5*flank_wall*max(0,sqrt(r2+1e-12)-flank_radius)^2;"
        "r2=(x-x0)^2+(y-y0)^2+(z-z0)^2")
    force.addGlobalParameter("flank_k", FLANK_K_KJ_MOL_NM2)
    force.addGlobalParameter("flank_wall", FLANK_WALL_K_KJ_MOL_NM2)
    force.addGlobalParameter("flank_radius", FLANK_WALL_RADIUS_ANGSTROM / 10)
    for name in ("x0", "y0", "z0"):
        force.addPerParticleParameter(name)
    seen = set()
    for atom in topology.atoms():
        identity = AtomIdentity(atom.residue.chain.id, str(atom.residue.id), atom.residue.insertionCode.strip(), atom.name)
        if identity in targets:
            force.addParticle(atom.index, (np.asarray(targets[identity]) / 10).tolist())
            seen.add(identity)
    if seen != set(targets):
        raise ValueError("flank restraint targets are missing from the force-field topology")
    return force


def restrained_forcefield_class(targets):
    class RestrainedForceField(ForceField):
        @wraps(ForceField.createSystem)
        def createSystem(self, topology, *args, **kwargs):
            system = super().createSystem(topology, *args, **kwargs)
            system.addForce(restraint_force(topology, targets))
            return system

    return RestrainedForceField


def refine(pdb_text, request):
    if len(request.gaps) != 1:
        raise ValueError("bounded research protocol requires one gap")
    selected = flank_atoms(request)
    records = _parse_pdb_text(pdb_text)[0]
    targets = {atom: records[atom].coordinates_angstrom for atom in selected}
    if len({ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) for atom in selected}) != 2:
        raise ValueError("bounded research protocol requires two complete flanking anchors")
    module = _load("private_flank_boundary_" + uuid.uuid4().hex, ROOT / "src/dvbfixer/model/diffusion/boundary_refinement.py")

    module.ForceField = restrained_forcefield_class(targets)
    gap = request.gaps[0]
    mobile_residues = tuple(dict.fromkeys((gap.left_anchor, *gap.generated_residues, gap.right_anchor)))
    short = len(gap.generated_residues) <= 5
    result = module.refine_generated_region(pdb_text, generated_residues=mobile_residues,
        generated_atoms=(*request.generated_atoms, *selected), max_iterations=500 if short else module.BOUNDARY_REFINEMENT_MAX_ITERATIONS,
        restart_count=module.BOUNDARY_REFINEMENT_RESTART_COUNT, perturbation_angstrom=0.25 if short else module.BOUNDARY_REFINEMENT_PERTURBATION_ANGSTROM,
        platform_name="CUDA", random_seed=request.seeds[0])
    return rewrite_generated_coordinates(pdb_text, result.coordinates_angstrom)
