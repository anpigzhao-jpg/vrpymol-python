"""Local server: real PyMOL scene -> glTF -> WebXR page.

Runs on any machine that can run the `vrpymol` conda env (this Mac included);
the headset just needs a browser and Wi-Fi to whatever host this binds to --
no SteamVR, no OpenXR desktop runtime, no PC tether.
"""

import os
import threading

from flask import Flask, Response, jsonify, request, send_from_directory
from pymol import util

from pymol_bridge.mesh_export import export_wrl
from pymol_bridge.session import PymolSession
from vr_pymol.gltf_export import export_gltf
from vr_pymol.mesh_loader import load_actors
from webxr.dev_cert import ensure_dev_cert

HERE = os.path.dirname(__file__)
STATIC_DIR = os.path.join(HERE, "static")
SCENE_DIR = os.path.join(HERE, "_scene")
FIXTURES_DIR = os.path.join(os.path.dirname(HERE), "tests", "fixtures")
GLTF_PATH = os.path.join(SCENE_DIR, "scene.gltf")

DEFAULT_MOLECULE = "1crn"
DEFAULT_REP = "cartoon"
DEFAULT_COLOR = "default"

# Real PyMOL coloring commands, checked directly against the installed
# pymol-open-source (`pymol/util.py`) rather than guessed: `util.cbc` (color
# by chain), `util.cbss` (by secondary structure: red helix/yellow sheet/
# green loop), `util.chainbow` (real N-to-C rainbow spectrum), and
# `cmd.spectrum("b", ...)` (by temperature factor) are all real, existing
# commands -- "default" just skips recoloring, since `session.load` already
# gives a fresh object in PyMOL's own default (CPK-like) atom colors.
_COLOR_SCHEMES = {
    "default": None,
    "chain": lambda session: util.cbc("all", _self=session.cmd),
    "rainbow": lambda session: util.chainbow("all", _self=session.cmd),
    "secondary-structure": lambda session: util.cbss("all", _self=session.cmd),
    "b-factor": lambda session: session.cmd.spectrum("b", "blue_white_red", "all"),
}

app = Flask(__name__, static_folder=None)
_lock = threading.Lock()
_session = None


def _get_session():
    global _session
    if _session is None:
        _session = PymolSession()
    return _session


def rebuild_scene(
    molecule,
    rep,
    hydrogens=True,
    waters=True,
    color=DEFAULT_COLOR,
    stick_radius=None,
    sphere_scale=None,
    cartoon_flat_sheets=True,
    cartoon_smooth_loops=False,
):
    """Load `molecule`, show `rep` (one or more reps, "+"-joined), export glTF.

    `hydrogens`/`waters` toggle real PyMOL selections (`hydro`, `solvent`)
    off after showing the requested reps, same toggles the Unity project's
    hotbar exposed. `color` picks a real PyMOL coloring scheme (see
    `_COLOR_SCHEMES`); `stick_radius`/`sphere_scale` are real PyMOL settings
    (`cmd.set`), left untouched (PyMOL's own current default) when None.
    `cartoon_flat_sheets`/`cartoon_smooth_loops` are real PyMOL cartoon
    settings, checked to actually change the exported cartoon mesh before
    wiring up (transparency, by contrast, was checked and found to never
    survive PyMOL's own VRML2 export at all, so it isn't exposed here).
    Defaults here match PyMOL's own real defaults (checked via `cmd.get`,
    not assumed): `cartoon_flat_sheets` is on, `cartoon_smooth_loops` is
    off.
    """
    pdb_path = os.path.join(FIXTURES_DIR, f"{molecule}.pdb")
    if not os.path.isfile(pdb_path):
        raise FileNotFoundError(molecule)
    if color not in _COLOR_SCHEMES:
        raise ValueError(f"unknown color scheme {color!r}")

    os.makedirs(SCENE_DIR, exist_ok=True)
    with _lock:
        session = _get_session()
        session.load(pdb_path)
        if stick_radius is not None:
            session.cmd.set("stick_radius", stick_radius)
        if sphere_scale is not None:
            session.cmd.set("sphere_scale", sphere_scale)
        session.cmd.set("cartoon_flat_sheets", int(cartoon_flat_sheets))
        session.cmd.set("cartoon_smooth_loops", int(cartoon_smooth_loops))
        session.cmd.hide("everything")
        for one_rep in rep.split("+"):
            session.cmd.show(one_rep)
        color_fn = _COLOR_SCHEMES[color]
        if color_fn is not None:
            color_fn(session)
        if not hydrogens:
            session.cmd.hide("everything", "hydro")
        if not waters:
            session.cmd.hide("everything", "solvent")

        wrl_path = os.path.join(SCENE_DIR, "scene.wrl")
        export_wrl(session, wrl_path)
        actors = load_actors(wrl_path)
        export_gltf(actors, GLTF_PATH)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/scene.gltf")
def scene_gltf():
    with open(GLTF_PATH, "rb") as f:
        data = f.read()
    response = Response(data, mimetype="model/gltf+json")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/scene")
def api_scene():
    molecule = request.args.get("molecule", DEFAULT_MOLECULE)
    rep = request.args.get("rep", DEFAULT_REP)
    hydrogens = request.args.get("hydrogens", "1") != "0"
    waters = request.args.get("waters", "1") != "0"
    color = request.args.get("color", DEFAULT_COLOR)
    stick_radius = request.args.get("stick_radius", type=float)
    sphere_scale = request.args.get("sphere_scale", type=float)
    cartoon_flat_sheets = request.args.get("cartoon_flat_sheets", "1") != "0"
    cartoon_smooth_loops = request.args.get("cartoon_smooth_loops", "0") != "0"
    try:
        rebuild_scene(
            molecule,
            rep,
            hydrogens=hydrogens,
            waters=waters,
            color=color,
            stick_radius=stick_radius,
            sphere_scale=sphere_scale,
            cartoon_flat_sheets=cartoon_flat_sheets,
            cartoon_smooth_loops=cartoon_smooth_loops,
        )
    except FileNotFoundError:
        return jsonify({"ok": False, "error": f"unknown molecule {molecule!r}"}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify(
        {
            "ok": True,
            "molecule": molecule,
            "rep": rep,
            "hydrogens": hydrogens,
            "waters": waters,
            "color": color,
            "stick_radius": stick_radius,
            "sphere_scale": sphere_scale,
            "cartoon_flat_sheets": cartoon_flat_sheets,
            "cartoon_smooth_loops": cartoon_smooth_loops,
        }
    )


@app.route("/api/pick")
def api_pick():
    """Nearest real atom to a 3D point, for click-to-select/measure.

    Takes a point in the *molecule's own local coordinate space* (i.e. real
    PyMOL/PDB Angstrom coordinates, unchanged by whatever fit/scale/rotation
    the frontend currently has the model under -- the frontend inverts its
    own display transform via `object3D.worldToLocal()` before calling this,
    since glTF export bakes real absolute coordinates into vertex positions
    with no extra node transforms in between).

    Deliberately does NOT thread a custom per-vertex "atom ID" through the
    batched glyph geometry/glTF export to support picking -- checked earlier
    that `vtkGLTFExporter` already silently drops things it doesn't
    understand (see mesh_loader.py's vtkGlyph3DMapper finding), so a custom
    attribute surviving that export was a real risk not worth taking when
    "ask PyMOL for the nearest real atom" does the same job with zero
    changes to the rendering pipeline.
    """
    x = request.args.get("x", type=float)
    y = request.args.get("y", type=float)
    z = request.args.get("z", type=float)
    if x is None or y is None or z is None:
        return jsonify({"ok": False, "error": "x, y, z are required"}), 400

    with _lock:
        session = _get_session()
        atoms = session.cmd.get_model("all").atom
        if not atoms:
            return jsonify({"ok": False, "error": "no atoms loaded"}), 404
        best = min(
            atoms,
            key=lambda a: (a.coord[0] - x) ** 2 + (a.coord[1] - y) ** 2 + (a.coord[2] - z) ** 2,
        )

    return jsonify(
        {
            "ok": True,
            "index": best.index,
            "name": best.name,
            "resn": best.resn,
            "resi": best.resi,
            "chain": best.chain,
            "element": best.symbol,
            "coord": list(best.coord),
        }
    )


@app.route("/api/distance")
def api_distance():
    """Real PyMOL distance between two atoms, by their `/api/pick` index."""
    atom1 = request.args.get("atom1", type=int)
    atom2 = request.args.get("atom2", type=int)
    if atom1 is None or atom2 is None:
        return jsonify({"ok": False, "error": "atom1, atom2 are required"}), 400

    with _lock:
        session = _get_session()
        distance = session.cmd.get_distance(f"mol and index {atom1}", f"mol and index {atom2}")

    return jsonify({"ok": True, "distance": distance})


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


def create_app():
    rebuild_scene(DEFAULT_MOLECULE, DEFAULT_REP)
    return app


if __name__ == "__main__":
    create_app()
    port = int(os.environ.get("PORT", "8420"))
    # HTTPS (even self-signed) is required here, not optional: WebXR only
    # exposes `navigator.xr` in a "secure context", and a headset opening
    # this over the LAN by IP is neither `localhost` nor real HTTPS unless
    # we terminate TLS ourselves -- see dev_cert.py for the why/how.
    cert_path, key_path, ip = ensure_dev_cert()
    print(f" * WebXR needs HTTPS: open https://{ip}:{port} on the headset")
    # threaded=False: on macOS, VTK's render-window creation touches Cocoa
    # APIs that are only safe to call from the process's main thread. A
    # threaded dev server would handle /api/scene requests (which render)
    # on a worker thread and hard-crash the whole process (not a catchable
    # Python exception -- an uncaught ObjC exception aborts the interpreter).
    app.run(host="0.0.0.0", port=port, threaded=False, ssl_context=(cert_path, key_path))
