"""Local server: real PyMOL scene -> glTF -> WebXR page.

Runs on any machine that can run the `vrpymol` conda env (this Mac included);
the headset just needs a browser and Wi-Fi to whatever host this binds to --
no SteamVR, no OpenXR desktop runtime, no PC tether.
"""

import os
import threading

from flask import Flask, Response, jsonify, request, send_from_directory

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

app = Flask(__name__, static_folder=None)
_lock = threading.Lock()
_session = None


def _get_session():
    global _session
    if _session is None:
        _session = PymolSession()
    return _session


def rebuild_scene(molecule, rep, hydrogens=True, waters=True):
    """Load `molecule`, show `rep` (one or more reps, "+"-joined), export glTF.

    `hydrogens`/`waters` toggle real PyMOL selections (`hydro`, `solvent`)
    off after showing the requested reps, same toggles the Unity project's
    hotbar exposed.
    """
    pdb_path = os.path.join(FIXTURES_DIR, f"{molecule}.pdb")
    if not os.path.isfile(pdb_path):
        raise FileNotFoundError(molecule)

    os.makedirs(SCENE_DIR, exist_ok=True)
    with _lock:
        session = _get_session()
        session.load(pdb_path)
        session.cmd.hide("everything")
        for one_rep in rep.split("+"):
            session.cmd.show(one_rep)
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
    try:
        rebuild_scene(molecule, rep, hydrogens=hydrogens, waters=waters)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": f"unknown molecule {molecule!r}"}), 404
    return jsonify(
        {
            "ok": True,
            "molecule": molecule,
            "rep": rep,
            "hydrogens": hydrogens,
            "waters": waters,
        }
    )


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
