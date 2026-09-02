"""M1+M2: PyMOL -> VRML2 -> VTK actors -> rendered pixels, end to end.

This is the concrete test of the whole plan's central bet: that real PyMOL's
VRML2 export gives VTK real, renderable geometry (not just atom-center points,
which is what PyMOL's own OBJ export turned out to produce -- checked and
rejected, see mesh_export.py's docstring) for every representation we care
about, on the actual conda-forge pymol-open-source build, not assumed.
"""

import os

import numpy as np
import pytest
from vtk.util.numpy_support import vtk_to_numpy

from pymol_bridge.mesh_export import export_wrl
from pymol_bridge.session import PymolSession
from vr_pymol.desktop_preview import render_to_png
from vr_pymol.mesh_loader import load_actors

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def session():
    with PymolSession() as s:
        yield s


def _render_png_array(session, molecule, show_reps, tmp_path, hide_first=True):
    session.load(os.path.join(FIXTURES, f"{molecule}.pdb"))
    if hide_first:
        session.cmd.hide("everything")
    for rep in show_reps:
        session.cmd.show(rep)

    wrl_path = export_wrl(session, str(tmp_path / f"{molecule}_{'_'.join(show_reps)}.wrl"))
    actors = load_actors(wrl_path)

    png_path = str(tmp_path / f"{molecule}_{'_'.join(show_reps)}.png")
    render_to_png(actors, png_path)

    reader_img = _read_png(png_path)
    return actors, reader_img


def _read_png(path):
    import vtk

    reader = vtk.vtkPNGReader()
    reader.SetFileName(path)
    reader.Update()
    image = reader.GetOutput()
    dims = image.GetDimensions()
    arr = vtk_to_numpy(image.GetPointData().GetScalars())
    return arr.reshape(dims[1], dims[0], -1)


def _fraction_non_background(img):
    background = img[0, 0]  # corner pixel is guaranteed background
    diff = np.abs(img.astype(int) - background.astype(int)).sum(axis=-1)
    return float((diff > 10).mean())


@pytest.mark.parametrize(
    "molecule,reps,min_actors",
    [
        ("caffeine", ["spheres"], 24),  # one Sphere primitive per atom
        ("caffeine", ["sticks"], 1),  # Cylinder primitives per bond half
        ("1crn", ["cartoon"], 1),  # baked IndexedFaceSet ribbon
        ("1bna", ["cartoon"], 1),  # zero-CONECT DNA stress test, phosphate-backbone cartoon
    ],
)
def test_representation_renders_real_geometry(session, tmp_path, molecule, reps, min_actors):
    actors, img = _render_png_array(session, molecule, reps, tmp_path)

    assert len(actors) >= min_actors, (
        f"expected at least {min_actors} actors for {molecule} {reps}, got {len(actors)}"
    )

    fraction_lit = _fraction_non_background(img)
    assert fraction_lit > 0.01, (
        f"{molecule} {reps}: rendered image is essentially blank "
        f"({fraction_lit:.4%} non-background pixels) -- geometry likely degenerate"
    )
