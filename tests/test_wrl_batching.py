"""Batched Sphere/Cylinder loading (see vr_pymol/wrl_parser.py + mesh_loader.py).

Guards the real perf fix for the M6-documented finding: vtkVRMLImporter's own
Update() -- not PyMOL's export, not file size -- was the bottleneck for
multi-thousand-atom structures (profiled ~70s for 4hhb cartoon+sticks, 8782
per-atom/per-bond Shape nodes). mesh_loader now parses Sphere/Cylinder nodes
itself and batches them into two actors, routing only the rest (cartoon's
baked mesh, lights, viewpoint) through vtkVRMLImporter as before.
"""

import os
import time

import pytest

from pymol_bridge.mesh_export import export_wrl
from pymol_bridge.session import PymolSession
from vr_pymol.mesh_loader import load_actors
from vr_pymol.wrl_parser import parse_wrl

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def session():
    with PymolSession() as s:
        yield s


def test_parse_wrl_matches_real_atom_and_element_counts(session, tmp_path):
    session.load(os.path.join(FIXTURES, "caffeine.pdb"))
    session.cmd.hide("everything")
    session.cmd.show("spheres")
    session.cmd.show("sticks")
    wrl_path = export_wrl(session, str(tmp_path / "caffeine.wrl"))

    spheres, cylinders, leftover = parse_wrl(wrl_path)

    assert len(spheres) == session.cmd.count_atoms("all") == 24
    assert len(cylinders) > 0
    assert "Viewpoint" in leftover  # header/lights still come through untouched

    # Per-element sphere counts should match real PyMOL atom counts, order-
    # independent (export order isn't guaranteed to match iterate order) --
    # grouping by each sphere's own rounded diffuseColor is a robust way to
    # check colors were extracted correctly without hardcoding CPK values.
    color_groups = {}
    for s in spheres:
        key = tuple(round(c, 2) for c in s["color"])
        color_groups[key] = color_groups.get(key, 0) + 1
    real_element_counts = sorted(
        session.cmd.count_atoms(f"elem {e}")
        for e in ("C", "H", "N", "O")
        if session.cmd.count_atoms(f"elem {e}") > 0
    )
    assert sorted(color_groups.values()) == real_element_counts


def test_load_actors_renders_same_geometry_as_plain_importer(session, tmp_path):
    """Batched actors must cover the same real geometry vtkVRMLImporter finds.

    Not just "some actor exists" -- checks total point/cell counts land in
    the same ballpark as importing every node individually (ground truth),
    since a bug here could silently produce technically-non-empty but wrong
    geometry (e.g. only spheres, no cylinders).
    """
    import vtk

    session.load(os.path.join(FIXTURES, "caffeine.pdb"))
    session.cmd.hide("everything")
    session.cmd.show("spheres")
    session.cmd.show("sticks")
    wrl_path = export_wrl(session, str(tmp_path / "caffeine.wrl"))

    batched_actors = load_actors(wrl_path)
    batched_points = sum(
        a.GetMapper().GetInput().GetNumberOfPoints() for a in batched_actors
    )

    importer = vtk.vtkVRMLImporter()
    importer.SetFileName(wrl_path)
    importer.Update()
    ground_truth_actors = list(importer.GetImportedActors())
    ground_truth_points = sum(
        a.GetMapper().GetInput().GetNumberOfPoints() for a in ground_truth_actors
    )

    assert len(batched_actors) < len(ground_truth_actors)
    # Both use different tessellation resolutions, so require rough parity
    # (same order of magnitude), not an exact match.
    assert ground_truth_points * 0.3 <= batched_points <= ground_truth_points * 3


def test_load_actors_4hhb_completes_quickly(session, tmp_path):
    """Regression guard for the documented ~70s vtkVRMLImporter bottleneck.

    Generous bound (real measured time was ~15s): guards against silently
    falling back to the slow per-node importer path for every shape (e.g. a
    future PyMOL export format change routing everything to "leftover"),
    not meant to be a tight perf benchmark.
    """
    session.load(os.path.join(FIXTURES, "4hhb.pdb"))
    session.cmd.hide("everything")
    session.cmd.show("cartoon")
    session.cmd.show("sticks")
    wrl_path = export_wrl(session, str(tmp_path / "4hhb.wrl"))

    start = time.time()
    actors = load_actors(wrl_path)
    elapsed = time.time() - start

    assert len(actors) < 20, "expected a handful of batched actors, not one per node"
    assert elapsed < 35, f"load_actors took {elapsed:.1f}s -- batching regression?"
