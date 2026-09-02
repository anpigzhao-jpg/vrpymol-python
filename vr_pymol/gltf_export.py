"""VTK actors -> glTF, the hand-off point to the WebXR frontend.

Named `.gltf` (not `.glb`): vtkGLTFExporter with InlineDataOn() writes plain
JSON with base64-embedded buffers, not a true binary-packed .glb container.
Content is valid glTF either way and loads fine in a browser's GLTFLoader,
but the .glb extension would be misleading about the actual file format.
"""

import vtk


def export_gltf(actors, path, background=(0.0, 0.0, 0.0)):
    """Render `actors` off-screen and export the scene as glTF to `path`."""
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(*background)
    for actor in actors:
        renderer.AddActor(actor)
    renderer.ResetCamera()

    render_window = vtk.vtkRenderWindow()
    render_window.SetOffScreenRendering(1)
    render_window.AddRenderer(renderer)
    render_window.Render()

    exporter = vtk.vtkGLTFExporter()
    exporter.SetRenderWindow(render_window)
    exporter.SetFileName(path)
    exporter.InlineDataOn()
    exporter.SetSaveNormal(True)
    exporter.Write()
    return path


def read_gltf_as_polydata(path):
    """Round-trip helper: read a glTF back and flatten it to one vtkPolyData.

    Used to verify our own exports are actually loadable, not just written.
    """
    reader = vtk.vtkGLTFReader()
    reader.SetFileName(path)
    reader.Update()

    flatten = vtk.vtkCompositeDataGeometryFilter()
    flatten.SetInputConnection(reader.GetOutputPort())
    flatten.Update()
    return flatten.GetOutput()
