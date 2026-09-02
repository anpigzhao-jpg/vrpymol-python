"""Non-VR VTK preview window -- the "does it actually look right" checkpoint.

Runs on any machine with a GPU or OSMesa/EGL software rendering (VTK 9.4+
wheels bundle these by default), no VR hardware or runtime required. Used
both for interactive desktop viewing and for headless screenshot verification.
"""

import vtk


def build_renderer(actors, background=(0.0, 0.0, 0.3)):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(*background)
    for actor in actors:
        renderer.AddActor(actor)
    renderer.ResetCamera()
    return renderer


def render_to_png(actors, out_path, width=800, height=600):
    """Headless offscreen render, for automated verification."""
    renderer = build_renderer(actors)

    render_window = vtk.vtkRenderWindow()
    render_window.SetOffScreenRendering(1)
    render_window.AddRenderer(renderer)
    render_window.SetSize(width, height)
    render_window.Render()

    image_filter = vtk.vtkWindowToImageFilter()
    image_filter.SetInput(render_window)
    image_filter.Update()

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(out_path)
    writer.SetInputConnection(image_filter.GetOutputPort())
    writer.Write()
    return out_path


def show_interactive(actors, width=1024, height=768):
    """On-screen window with mouse orbit/zoom (trackball camera)."""
    renderer = build_renderer(actors)

    render_window = vtk.vtkRenderWindow()
    render_window.AddRenderer(renderer)
    render_window.SetSize(width, height)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(render_window)
    style = vtk.vtkInteractorStyleTrackballCamera()
    interactor.SetInteractorStyle(style)

    render_window.Render()
    interactor.Start()
