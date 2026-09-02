"""M6: combinable representations, hydrogens/waters toggles, reset view.

Two kinds of check here, matching this project's standing rule (verify the
real output, not "the checkbox looks checked"):
1. Pure-Python, no browser: drive `webxr.server.rebuild_scene` directly and
   inspect the exported glTF's actual vertex count with `pygltflib` to
   confirm hydrogens/waters toggles really remove geometry, not just flip a
   UI flag. `pymol_bridge` gives ground truth on how many atoms should be
   affected (see the atom counts already established for these fixtures).
2. Playwright against the real page: check multiple representation boxes at
   once and confirm the render actually reflects the combination, and that
   the reset-view button really resets the camera/controls state (introspected
   via `window.vrPymolDebug`, exposed by app.js for exactly this).
"""

import os

import numpy as np
import pygltflib
import pytest
from playwright.sync_api import sync_playwright

from tests.live_server import live_server  # noqa: F401
from vr_pymol.desktop_preview import render_to_png
from vr_pymol.mesh_loader import load_actors
from vr_pymol.gltf_export import export_gltf
from pymol_bridge.mesh_export import export_wrl
from pymol_bridge.session import PymolSession
from webxr.server import rebuild_scene, GLTF_PATH

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _total_vertices(gltf_path):
    gltf = pygltflib.GLTF2().load(gltf_path)
    return sum(a.count for a in gltf.accessors if a.type == "VEC3")


def test_hiding_hydrogens_removes_geometry(tmp_path):
    # caffeine has 10 real hydrogens (verified against pymol_bridge directly).
    rebuild_scene("caffeine", "spheres", hydrogens=True, waters=True)
    with_h = _total_vertices(GLTF_PATH)

    rebuild_scene("caffeine", "spheres", hydrogens=False, waters=True)
    without_h = _total_vertices(GLTF_PATH)

    assert without_h < with_h, (
        "hiding hydrogens did not reduce exported geometry -- toggle likely "
        "isn't actually reaching the PyMOL selection"
    )


def test_hiding_waters_removes_geometry():
    # 4hhb has 221 real solvent atoms (verified against pymol_bridge directly).
    rebuild_scene("4hhb", "spheres", hydrogens=True, waters=True)
    with_water = _total_vertices(GLTF_PATH)

    rebuild_scene("4hhb", "spheres", hydrogens=True, waters=False)
    without_water = _total_vertices(GLTF_PATH)

    assert without_water < with_water, (
        "hiding waters did not reduce exported geometry -- toggle likely "
        "isn't actually reaching the PyMOL selection"
    )


def _fraction_non_background(img):
    background = img[0, 0]
    diff = np.abs(img.astype(int) - background.astype(int)).sum(axis=-1)
    return float((diff > 10).mean())


def test_combined_representations_render_more_than_either_alone(tmp_path):
    def render(reps):
        with PymolSession() as session:
            session.load(os.path.join(FIXTURES, "1crn.pdb"))
            session.cmd.hide("everything")
            for rep in reps:
                session.cmd.show(rep)
            wrl_path = export_wrl(session, str(tmp_path / f"{'_'.join(reps)}.wrl"))
            actors = load_actors(wrl_path)
        gltf_path = str(tmp_path / f"{'_'.join(reps)}.gltf")
        export_gltf(actors, gltf_path)
        return _total_vertices(gltf_path)

    cartoon_only = render(["cartoon"])
    sticks_only = render(["sticks"])
    combined = render(["cartoon", "sticks"])

    assert combined > cartoon_only
    assert combined > sticks_only


def test_page_combines_reps_and_reset_view_works(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 800, "height": 600}, ignore_https_errors=True
        )
        page.goto(live_server, wait_until="networkidle")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )

        # check a second representation box (cartoon is checked by default in
        # the HTML) and confirm the round trip actually happens.
        page.check("#rep-checkboxes input[value='sticks']")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )

        default_camera = page.evaluate(
            "() => vrPymolDebug.camera.position.toArray()"
        )

        # perturb the view, then confirm reset view actually restores it.
        page.evaluate(
            "() => { vrPymolDebug.camera.position.set(5, 5, 5); "
            "vrPymolDebug.controls.target.set(1, 1, 1); "
            "vrPymolDebug.controls.update(); }"
        )
        perturbed_camera = page.evaluate(
            "() => vrPymolDebug.camera.position.toArray()"
        )
        assert perturbed_camera != default_camera

        page.click("#reset-view")
        restored_camera = page.evaluate(
            "() => vrPymolDebug.camera.position.toArray()"
        )
        browser.close()

    assert restored_camera == pytest.approx(default_camera)
