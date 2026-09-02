"""M0: real headless PyMOL loads real PDB files with correct atom/bond counts.

Atom counts are cross-checked against the Unity project's independently
written PdbParser (see project memory) as a sanity check across two parsers.
Bond counts are NOT cross-checked the same way: PyMOL's real bond-perception
algorithm is more sophisticated than the Unity project's own BondInferencer
approximation (337 vs 331 for 1CRN), and per this project's whole premise --
trust real PyMOL over a homemade approximation -- PyMOL's own number is
ground truth here, not something to match against the other implementation.
"""

import os

import pytest

from pymol_bridge.session import PymolSession

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

EXPECTED = {
    "1crn": {"atoms": 327, "bonds": 337},
    "caffeine": {"atoms": 24, "bonds": 25},
}


@pytest.fixture
def session():
    with PymolSession() as s:
        yield s


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_known_atom_and_bond_counts(session, name):
    session.load(os.path.join(FIXTURES, f"{name}.pdb"))
    assert session.atom_count() == EXPECTED[name]["atoms"]
    assert session.bond_count() == EXPECTED[name]["bonds"]


@pytest.mark.parametrize(
    "name", ["1crn", "caffeine", "1mbn", "1bna", "4hhb", "1lyz", "1gfl"]
)
def test_loads_without_error(session, name):
    session.load(os.path.join(FIXTURES, f"{name}.pdb"))
    assert session.atom_count() > 0
