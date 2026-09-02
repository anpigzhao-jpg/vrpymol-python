"""Thin wrapper around real pymol-open-source's Python API (pymol2), headless."""

import pymol2


class PymolSession:
    def __init__(self):
        self._pymol = pymol2.PyMOL()
        self._pymol.start()
        self.cmd = self._pymol.cmd
        self.cmd.feedback("disable", "all", "everything")

    def load(self, path, object_name="mol"):
        self.cmd.delete("all")
        self.cmd.load(path, object_name)
        return object_name

    def atom_count(self, selection="all"):
        return self.cmd.count_atoms(selection)

    def bond_count(self, selection="all"):
        model = self.cmd.get_model(selection)
        return len(model.bond)

    def close(self):
        self._pymol.stop()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
