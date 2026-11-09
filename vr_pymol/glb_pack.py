"""Shrink our exported glTF into a compact .glb for static hosting.

vtkGLTFExporter's output is fine for a local server but heavy to download
onto a headset over Wi-Fi: base64-inlined buffers (+33%), an unused float
TEXCOORD_0 on every vertex, unwelded triangle soups (sticks are fully
unindexed), and float32 positions. This rewrites it losslessly-enough for
viewing, with no tools beyond numpy:

- drop TEXCOORD_0 (no textures are ever exported)
- weld vertices that share position + color, then index them
- quantize POSITION to normalized int16 via KHR_mesh_quantization (three.js
  GLTFLoader supports it natively); a per-mesh child node carries the
  dequantizing translation/scale, so world/local coordinates -- which the
  frontend's atom picking relies on -- are unchanged up to ~1e-3 Angstrom
- write binary .glb instead of base64 JSON

Normals are not added: the exporter writes none, so GLTFLoader already
renders these flat-shaded either way.
"""

import base64
import json
import struct

import numpy as np

_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


def _read_gltf(path):
    with open(path) as f:
        gltf = json.load(f)
    buffers = [base64.b64decode(b["uri"].split(",", 1)[1]) for b in gltf["buffers"]]

    def accessor(i):
        a = gltf["accessors"][i]
        view = gltf["bufferViews"][a["bufferView"]]
        n = _COMPONENTS[a["type"]]
        dtype = np.dtype(_DTYPES[a["componentType"]])
        offset = view.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = view.get("byteStride", 0) or n * dtype.itemsize
        raw = np.frombuffer(buffers[view["buffer"]], np.uint8)
        rows = np.lib.stride_tricks.as_strided(
            raw[offset:], shape=(a["count"], n * dtype.itemsize), strides=(stride, 1)
        )
        return np.ascontiguousarray(rows).view(dtype).reshape(a["count"], n)

    return gltf, accessor


class _Builder:
    def __init__(self):
        self.chunks = []
        self.length = 0
        self.views = []
        self.accessors = []

    def add(self, array, target, byte_stride=None):
        data = np.ascontiguousarray(array).tobytes()
        pad = (-self.length) % 4
        if pad:
            self.chunks.append(b"\0" * pad)
            self.length += pad
        view = {"buffer": 0, "byteOffset": self.length, "byteLength": len(data), "target": target}
        if byte_stride:
            view["byteStride"] = byte_stride
        self.chunks.append(data)
        self.length += len(data)
        self.views.append(view)
        return len(self.views) - 1

    def accessor(self, **fields):
        self.accessors.append(fields)
        return len(self.accessors) - 1


def _weld(positions, colors, indices):
    """Merge vertices with identical position+color; return remapped indices."""
    key = np.concatenate([positions.view(np.uint8).reshape(len(positions), -1), colors], axis=1)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return positions[first], colors[first], inverse.reshape(-1)[indices]


def has_geometry(gltf_path):
    """False when the export is empty (e.g. cartoon of a small molecule with
    no polymer backbone -- PyMOL draws nothing, so the exporter writes no
    meshes and no buffers)."""
    with open(gltf_path) as f:
        gltf = json.load(f)
    return bool(gltf.get("meshes")) and bool(gltf.get("buffers"))


def pack_glb(gltf_path, glb_path):
    gltf, accessor = _read_gltf(gltf_path)
    out = _Builder()
    meshes = []
    dequant = {}  # mesh index -> (translation, scale)

    for mesh_index, mesh in enumerate(gltf["meshes"]):
        prims = []
        for prim in mesh["primitives"]:
            positions = accessor(prim["attributes"]["POSITION"]).astype(np.float32)
            n = len(positions)
            if "COLOR_0" in prim["attributes"]:
                colors = accessor(prim["attributes"]["COLOR_0"])[:n]
                if colors.dtype != np.uint8:
                    colors = np.clip(np.round(colors * 255), 0, 255).astype(np.uint8)
                if colors.shape[1] == 3:
                    colors = np.concatenate([colors, np.full((n, 1), 255, np.uint8)], axis=1)
            else:
                colors = np.full((n, 4), 255, np.uint8)
            if "indices" in prim:
                indices = accessor(prim["indices"]).reshape(-1).astype(np.int64)
            else:
                indices = np.arange(n, dtype=np.int64)
            positions, colors, indices = _weld(positions, colors, indices)
            prims.append((prim, positions, colors, indices))

        all_pos = np.concatenate([p[1] for p in prims])
        lo, hi = all_pos.min(axis=0), all_pos.max(axis=0)
        center = (lo + hi) / 2
        half = float(max((hi - lo).max() / 2, 1e-6))
        dequant[mesh_index] = (center.tolist(), half)

        new_prims = []
        for prim, positions, colors, indices in prims:
            q = np.round((positions - center) / half * 32767).astype(np.int16)
            q4 = np.zeros((len(q), 4), np.int16)
            q4[:, :3] = q
            pos_acc = out.accessor(
                bufferView=out.add(q4, ARRAY_BUFFER, byte_stride=8),
                componentType=5122,
                normalized=True,
                count=len(q),
                type="VEC3",
                min=q.min(axis=0).astype(int).tolist(),
                max=q.max(axis=0).astype(int).tolist(),
            )
            col_acc = out.accessor(
                bufferView=out.add(colors, ARRAY_BUFFER),
                componentType=5121,
                normalized=True,
                count=len(colors),
                type="VEC4",
            )
            if len(positions) < 65536:
                idx, ctype = indices.astype(np.uint16), 5123
            else:
                idx, ctype = indices.astype(np.uint32), 5125
            idx_acc = out.accessor(
                bufferView=out.add(idx, ELEMENT_ARRAY_BUFFER),
                componentType=ctype,
                count=len(idx),
                type="SCALAR",
            )
            new_prim = {
                "attributes": {"POSITION": pos_acc, "COLOR_0": col_acc},
                "indices": idx_acc,
                "mode": prim.get("mode", 4),
            }
            if "material" in prim:
                new_prim["material"] = prim["material"]
            new_prims.append(new_prim)
        meshes.append({"primitives": new_prims})

    # Keep the exporter's node hierarchy; hang each mesh off a child node
    # that dequantizes it back to real Angstrom coordinates.
    nodes = [dict(node) for node in gltf["nodes"]]
    for node in list(nodes):
        if "mesh" in node:
            mesh_index = node.pop("mesh")
            translation, scale = dequant[mesh_index]
            nodes.append({"mesh": mesh_index, "translation": translation, "scale": [scale] * 3})
            node.setdefault("children", []).append(len(nodes) - 1)

    binary = b"".join(out.chunks)
    binary += b"\0" * ((-len(binary)) % 4)
    doc = {
        "asset": {"version": "2.0", "generator": "vrpymol glb_pack"},
        "extensionsUsed": ["KHR_mesh_quantization"],
        "extensionsRequired": ["KHR_mesh_quantization"],
        "scene": gltf.get("scene", 0),
        "scenes": gltf["scenes"],
        "nodes": nodes,
        "meshes": meshes,
        "materials": gltf.get("materials", []),
        "cameras": gltf.get("cameras", []),
        "accessors": out.accessors,
        "bufferViews": out.views,
        "buffers": [{"byteLength": len(binary)}],
    }
    json_chunk = json.dumps(doc, separators=(",", ":")).encode()
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    with open(glb_path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(json_chunk), 0x4E4F534A))
        f.write(json_chunk)
        f.write(struct.pack("<II", len(binary), 0x004E4942))
        f.write(binary)
    return glb_path
