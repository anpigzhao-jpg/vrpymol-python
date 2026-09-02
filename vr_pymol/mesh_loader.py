"""Load a PyMOL-exported VRML2 (.wrl) scene into VTK actors."""

import vtk


def load_actors(wrl_path):
    """Return the list of vtkActors baked into a PyMOL VRML2 export."""
    importer = vtk.vtkVRMLImporter()
    importer.SetFileName(wrl_path)
    importer.Update()
    actors = list(importer.GetImportedActors())
    renderer = importer.GetRenderer()
    # Detach actors from the importer's own throwaway renderer so callers can
    # add them to a renderer of their own (VR window, desktop preview, ...).
    for actor in actors:
        renderer.RemoveActor(actor)
    return actors
