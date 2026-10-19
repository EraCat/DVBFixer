"""Physical-unit and conservative selection checks for private flank research."""

import importlib
from pathlib import Path

import numpy as np
import openmm
import pytest
from openmm.app import Topology, element
from openmm.unit import kilojoule_per_mole

from dvbfixer.model.diffusion.contract import AtomIdentity


def test_restraint_uses_nanometers_and_has_finite_zero_displacement_forces(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("research_flank_refinement")
    topology = Topology()
    chain = topology.addChain("h")
    residue = topology.addResidue("ALA", chain, "82", "A")
    topology.addAtom("CA", element.carbon, residue)
    targets = {AtomIdentity("h", "82", "A", "CA"): np.zeros(3)}
    system = openmm.System()
    system.addParticle(12)
    system.addForce(module.restraint_force(topology, targets))
    integrator = openmm.VerletIntegrator(0.001)
    context = openmm.Context(system, integrator, openmm.Platform.getPlatformByName("Reference"))
    context.setPositions([[0, 0, 0]])
    assert np.isfinite(context.getState(getForces=True).getForces(asNumpy=True)._value).all()
    context.setPositions([[0.01, 0, 0]])  # 0.1 Å => 0.5 kJ/mol.
    assert context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(kilojoule_per_mole) == pytest.approx(0.5)
    context.setPositions([[0.04, 0, 0]])  # 0.4 Å => wall is also active.
    assert context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(kilojoule_per_mole) > 100


def test_protocol_selection_requires_rescue_without_losing_controls(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("run_flank_comparison")
    values = dict(evaluated_count=64, total_count=64, rigid_passed=58, bounded_passed=59, regressions=0, median_rmsd_change=0.01)
    assert module.choose_protocol(**values) == "bounded-flank"
    assert module.choose_protocol(**{**values, "regressions": 1}) == "rigid"
    assert module.choose_protocol(**{**values, "bounded_passed": 58}) == "rigid"
    assert module.choose_protocol(**{**values, "evaluated_count": 63}) == "rigid"
    assert module.choose_protocol(**{**values, "median_rmsd_change": 0.11}) == "rigid"


def test_forcefield_adapter_preserves_openmm_argument_introspection(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("research_flank_refinement")
    topology = Topology()
    residue = topology.addResidue("HOH", topology.addChain("A"), "1")
    oxygen = topology.addAtom("O", element.oxygen, residue)
    for name in ("H1", "H2"):
        hydrogen = topology.addAtom(name, element.hydrogen, residue)
        topology.addBond(oxygen, hydrogen)
    cls = module.restrained_forcefield_class({AtomIdentity("A", "1", "", "O"): np.zeros(3)})
    system = cls("tip3p.xml").createSystem(topology)
    assert system.getNumParticles() == 3
    assert any(isinstance(force, openmm.CustomExternalForce) for force in system.getForces())


def test_holdout_identity_detects_exact_and_unrelated_proteins(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("build_relaxation_holdout")
    assert module.sequence_identity("ACDEFGHIKLMNPQRSTVWY", "ACDEFGHIKLMNPQRSTVWY") == 1
    assert module.sequence_identity("AAAAAAAAAA", "WWWWWWWWWW") == 0
