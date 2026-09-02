"""M3: VTK actors -> glTF -> verified both structurally and by re-rendering.

Two independent checks per export, neither trusting "the file was written":
1. pygltflib parses it as structurally valid glTF with a sane mesh/accessor count.
2. VTK reads its own export back (vtkGLTFReader) and re-rendering that produces
   a non-blank image -- the same round trip a browser's GLTFLoader will do.
"""

import os

import numpy as np
import pygltflib
import pytest
import vtk
from vtk.util.numpy_support import vtk_to_numpy

from pymol_bridge.mesh_export import export_wrl
from pymol_bridge.session import PymolSession
from vr_pymol.desktop_preview import render_to_png
from vr_pymol.gltf_export import export_gltf, read_gltf_as_polydata
from vr_pymol.mesh_loader import load_actors

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def session():
    with PymolSession() as s:
        yield s


def _fraction_non_background(img):
    background = img[0, 0]
    diff = np.abs(img.astype(int) - background.astype(int)).sum(axis=-1)
    return float((diff > 10).mean())


def _read_png(path):
    reader = vtk.vtkPNGReader()
    reader.SetFileName(path)
    reader.Update()
    image = reader.GetOutput()
    dims = image.GetDimensions()
    arr = vtk_to_numpy(image.GetPointData().GetScalars())
    return arr.reshape(dims[1], dims[0], -1)


@pytest.mark.parametrize(
    "molecule,reps",
    [
        ("caffeine", ["spheres"]),
        ("caffeine", ["sticks"]),
        ("1crn", ["cartoon"]),
    ],
)
def test_gltf_export_structurally_valid_and_renders(session, tmp_path, molecule, reps):
    session.load(os.path.join(FIXTURES, f"{molecule}.pdb"))
    session.cmd.hide("everything")
    for rep in reps:
        session.cmd.show(rep)

    wrl_path = export_wrl(session, str(tmp_path / "scene.wrl"))
    actors = load_actors(wrl_path)
    gltf_path = str(tmp_path / "scene.gltf")
    export_gltf(actors, gltf_path)

    # 1. structural validity via an independent parser (not VTK).
    gltf = pygltflib.GLTF2().load(gltf_path)
    assert len(gltf.meshes) > 0
    assert len(gltf.accessors) > 0
    total_vertices = sum(
        a.count for a in gltf.accessors if a.type == "VEC3"
    )
    assert total_vertices > 0

    # 2. round trip through VTK's own reader, then re-render.
    polydata = read_gltf_as_polydata(gltf_path)
    assert polydata.GetNumberOfPoints() > 0
    assert polydata.GetNumberOfCells() > 0

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(polydata)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    png_path = str(tmp_path / "roundtrip.png")
    render_to_png([actor], png_path)
    img = _read_png(png_path)
    fraction_lit = _fraction_non_background(img)
    assert fraction_lit > 0.01, (
        f"{molecule} {reps}: glTF round-trip render is essentially blank "
        f"({fraction_lit:.4%} non-background pixels)"
    )
