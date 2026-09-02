"""Bake the current PyMOL representation into real geometry via VRML2.

PyMOL's OBJ export is broken for anything but flat meshes: spheres/cartoon
come out as one degenerate zero-area triangle per atom (verified against the
actual installed pymol-open-source 3.1 -- a long-standing, still-unfixed
upstream bug). COLLADA (.dae) bakes real triangle meshes but is bulkier and
loses per-atom identity. VRML2 (.wrl) is what PyMOL's own `save` command uses
for its exact real primitives: spheres show up as native `Sphere{radius=...}`
nodes and sticks as native `Cylinder` nodes (not baked triangles), each with
its own Transform + Material -- exact, compact, and per-atom/per-bond. Cartoon
comes out as a real baked `IndexedFaceSet` (there's no primitive shape for an
arbitrary ribbon, so PyMOL bakes that one). VRML2 is what this module uses.
"""

import tempfile


def export_wrl(session, path=None):
    """Save the current view of `session` (a PymolSession) as VRML2.

    Returns the output path. If `path` is None, writes to a fresh temp file.
    """
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".wrl")
        import os

        os.close(fd)
    session.cmd.save(path)
    return path
