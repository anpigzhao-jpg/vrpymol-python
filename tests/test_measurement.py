"""Click-to-select / real-distance measurement (`/api/pick`, `/api/distance`).

Picking deliberately avoids threading a custom per-vertex atom-ID through the
batched glyph geometry/glTF export (mesh_loader.py already found
vtkGLTFExporter silently drops things it doesn't understand) -- instead the
frontend inverts a raycast hit back into the model's own local coordinate
space (real PyMOL Angstrom coordinates, since glTF export bakes those
straight into vertex positions) and asks the server for the real nearest
atom. Distance uses real `cmd.get_distance`, PyMOL's own measurement command,
not a client-side recomputation.
"""

import os

import pytest

from webxr.server import create_app

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "fixtures")


@pytest.fixture
def client():
    app = create_app()
    return app.test_client()


def test_pick_finds_real_nearest_atom(client):
    client.get("/api/scene?molecule=caffeine&rep=spheres")

    # Real atom 1 (C1) is at (0.858, 0.259, -0.001) per the actual PDB file --
    # picking exactly at that point must return that same atom, not just any
    # atom (rules out an off-by-one in the min-distance search or in how
    # `index` is threaded through to `/api/distance`).
    response = client.get("/api/pick?x=0.858&y=0.259&z=-0.001")
    data = response.get_json()
    assert data["ok"]
    assert data["index"] == 1
    assert data["name"] == "C1"
    assert data["element"] == "C"
    assert data["resn"] == "CFF"


def test_pick_is_robust_to_a_nearby_point_not_exactly_on_an_atom(client):
    # Slightly off the real atom-1 center (0.858, 0.259, -0.001) -- as a real
    # raycast hit landing on the sphere's surface, not its exact center,
    # would be -- must still resolve to that same nearest atom.
    client.get("/api/scene?molecule=caffeine&rep=spheres")
    response = client.get("/api/pick?x=0.95&y=0.3&z=0.05")
    data = response.get_json()
    assert data["ok"]
    assert data["index"] == 1


def test_pick_requires_coordinates(client):
    client.get("/api/scene?molecule=caffeine&rep=spheres")
    response = client.get("/api/pick")
    assert response.status_code == 400


def test_distance_matches_real_pymol_get_distance(client):
    client.get("/api/scene?molecule=caffeine&rep=spheres")

    pick_a = client.get("/api/pick?x=0.858&y=0.259&z=-0.001").get_json()
    pick_b = client.get("/api/pick?x=-3.19&y=-0.487&z=0").get_json()

    response = client.get(f"/api/distance?atom1={pick_a['index']}&atom2={pick_b['index']}")
    data = response.get_json()
    assert data["ok"]

    from pymol_bridge.session import PymolSession

    with PymolSession() as s:
        s.load(os.path.join(FIXTURES, "caffeine.pdb"))
        expected = s.cmd.get_distance(
            f"mol and index {pick_a['index']}", f"mol and index {pick_b['index']}"
        )
    assert data["distance"] == pytest.approx(expected, abs=1e-4)
