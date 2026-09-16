"""Multi-object (view several molecules at once) and multi-state (movie
frame / NMR ensemble) support.

Real pymol-open-source, checked directly rather than guessed: `cmd.load`
with a fresh object name loads *alongside* whatever's already loaded (only
`cmd.delete`/a fresh `cmd.load` onto an existing name replaces it); a
multi-MODEL PDB (e.g. an NMR ensemble) loads as multiple *states* of one
object by default, not separate objects; `cmd.count_states("all")` reports
the max across every loaded object; `cmd.frame(n)` is a real, global (not
per-object) movie-frame setting that changes what `cmd.save` actually
exports -- all verified empirically before relying on any of it here.
"""

import os

import pygltflib
import pytest

from pymol_bridge.session import PymolSession
from webxr.server import (
    add_object_to_scene,
    create_app,
    remove_object_from_scene,
    rebuild_scene,
    GLTF_PATH,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _total_vertices(gltf_path):
    gltf = pygltflib.GLTF2().load(gltf_path)
    return sum(a.count for a in gltf.accessors if a.type == "VEC3")


# --- pymol_bridge.session: real PyMOL session, no Flask ---


def test_add_object_keeps_existing_objects():
    with PymolSession() as s:
        s.load(os.path.join(FIXTURES, "1crn.pdb"))
        s.add_object(os.path.join(FIXTURES, "caffeine.pdb"), base_name="caffeine")
        assert set(s.list_objects()) == {"mol", "caffeine"}


def test_add_object_dedupes_names_on_collision():
    with PymolSession() as s:
        s.add_object(os.path.join(FIXTURES, "caffeine.pdb"), base_name="caffeine")
        s.add_object(os.path.join(FIXTURES, "caffeine.pdb"), base_name="caffeine")
        assert set(s.list_objects()) == {"caffeine", "caffeine_2"}


def test_add_object_arranges_so_bounding_boxes_dont_overlap():
    # 1crn and caffeine both have real coordinates centered near the origin
    # -- without arrangement they'd overlap by coincidence, defeating the
    # point of viewing two molecules "at once".
    with PymolSession() as s:
        s.add_object(os.path.join(FIXTURES, "1crn.pdb"), base_name="1crn")
        s.add_object(os.path.join(FIXTURES, "caffeine.pdb"), base_name="caffeine")
        (min1x, _, _), (max1x, _, _) = s.cmd.get_extent("1crn")
        (min2x, _, _), (max2x, _, _) = s.cmd.get_extent("caffeine")
        assert max1x < min2x, "objects overlap along x after auto-arrangement"


def test_remove_object_leaves_the_rest():
    with PymolSession() as s:
        s.add_object(os.path.join(FIXTURES, "1crn.pdb"), base_name="1crn")
        s.add_object(os.path.join(FIXTURES, "caffeine.pdb"), base_name="caffeine")
        s.remove_object("caffeine")
        assert s.list_objects() == ["1crn"]


def test_nmr_ensemble_loads_as_multiple_states_of_one_object():
    with PymolSession() as s:
        s.load(os.path.join(FIXTURES, "1le0.pdb"))
        assert s.list_objects() == ["mol"]
        assert s.cmd.count_states("mol") == 20


def test_frame_changes_exported_coordinates():
    with PymolSession() as s:
        s.load(os.path.join(FIXTURES, "1le0.pdb"))
        s.cmd.frame(1)
        coord_frame_1 = s.cmd.get_model("mol", state=-1).atom[0].coord
        s.cmd.frame(10)
        coord_frame_10 = s.cmd.get_model("mol", state=-1).atom[0].coord
        assert coord_frame_1 != coord_frame_10


# --- webxr.server: the Flask app's multi-object/state plumbing ---


@pytest.fixture
def client():
    app = create_app()
    return app.test_client()


def test_add_and_remove_object_via_api(client):
    client.get("/api/scene?molecule=1crn&rep=cartoon")

    response = client.post("/api/objects", json={"molecule": "caffeine"})
    data = response.get_json()
    assert data["ok"]
    names = {o["name"] for o in data["objects"]}
    assert names == {"mol", "caffeine"}

    response = client.get("/api/objects")
    assert {o["name"] for o in response.get_json()["objects"]} == {"mol", "caffeine"}

    response = client.delete("/api/objects/caffeine")
    data = response.get_json()
    assert data["ok"]
    assert {o["name"] for o in data["objects"]} == {"mol"}


def test_adding_a_second_object_actually_adds_geometry(client):
    client.get("/api/scene?molecule=1crn&rep=spheres")
    solo = _total_vertices(GLTF_PATH)

    client.post("/api/objects", json={"molecule": "caffeine"})
    combined = _total_vertices(GLTF_PATH)

    assert combined > solo, (
        "adding a second object did not increase exported geometry -- the "
        "new object likely isn't actually being exported alongside the first"
    )


def test_cannot_remove_the_last_remaining_object(client):
    client.get("/api/scene?molecule=1crn&rep=cartoon")
    response = client.delete("/api/objects/mol")
    assert response.status_code == 400


def test_removing_unknown_object_is_a_404(client):
    client.get("/api/scene?molecule=1crn&rep=cartoon")
    response = client.delete("/api/objects/does-not-exist")
    assert response.status_code == 404


def test_changing_rep_does_not_reset_additional_objects(client):
    # A real regression this design specifically guards against: the existing
    # frontend always resends `molecule=<primary>` alongside every rep/color/
    # etc. change, which previously (before the "did it actually change"
    # check) would silently nuke any additional objects on every unrelated
    # settings tweak.
    client.get("/api/scene?molecule=1crn&rep=cartoon")
    client.post("/api/objects", json={"molecule": "caffeine"})

    response = client.get("/api/scene?molecule=1crn&rep=cartoon+sticks")
    data = response.get_json()
    assert {o["name"] for o in data["objects"]} == {"mol", "caffeine"}


def test_switching_the_primary_molecule_does_reset_additional_objects(client):
    client.get("/api/scene?molecule=1crn&rep=cartoon")
    client.post("/api/objects", json={"molecule": "caffeine"})

    response = client.get("/api/scene?molecule=1mbn&rep=cartoon")
    data = response.get_json()
    assert {o["name"] for o in data["objects"]} == {"mol"}


def test_max_states_reported_for_nmr_ensemble(client):
    response = client.get("/api/scene?molecule=1le0&rep=cartoon")
    data = response.get_json()
    assert data["max_states"] == 20


def test_max_states_is_one_for_ordinary_single_state_molecules(client):
    response = client.get("/api/scene?molecule=1crn&rep=cartoon")
    assert response.get_json()["max_states"] == 1


def test_frame_param_changes_exported_geometry_for_nmr_ensemble(client):
    client.get("/api/scene?molecule=1le0&rep=spheres&frame=1")
    frame_1_bytes = open(GLTF_PATH, "rb").read()

    client.get("/api/scene?molecule=1le0&rep=spheres&frame=10")
    frame_10_bytes = open(GLTF_PATH, "rb").read()

    assert frame_1_bytes != frame_10_bytes


def test_pick_reports_object_name_for_multi_object_scenes(client):
    client.get("/api/scene?molecule=1crn&rep=spheres")
    client.post("/api/objects", json={"molecule": "caffeine"})

    # Query the real running server session for the *actual* (auto-arranged)
    # coordinates -- a separate PymolSession would arrange "1crn"/"caffeine"
    # differently (the server's primary "mol" object is never auto-arranged,
    # only additional objects are), so it can't be used as a stand-in here.
    from webxr.server import _get_session

    caffeine_atom_0 = _get_session().cmd.get_model("caffeine").atom[0]

    x, y, z = caffeine_atom_0.coord
    response = client.get(f"/api/pick?x={x}&y={y}&z={z}")
    data = response.get_json()
    assert data["ok"]
    assert data["object"] == "caffeine"


def test_rebuild_scene_still_resets_to_a_single_object_named_mol():
    # Backward compatibility: existing callers (and the primary molecule
    # dropdown) rely on `rebuild_scene` fully replacing the scene.
    rebuild_scene("1crn", "cartoon")
    add_object_to_scene("caffeine")
    rebuild_scene("1mbn", "cartoon")

    from webxr.server import _objects

    assert _objects == {"mol": "1mbn"}


def test_remove_object_from_scene_rejects_removing_primary():
    rebuild_scene("1crn", "cartoon")
    with pytest.raises(ValueError):
        remove_object_from_scene("mol")
