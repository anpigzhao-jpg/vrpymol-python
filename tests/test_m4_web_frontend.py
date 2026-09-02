"""M4: the actual web page, loaded in a real (headless) browser.

This is the WebXR-era equivalent of the VTK offscreen-screenshot checks used
for M1-M3: a real browser (not just "the server returned 200") loads the
page, resolves the vendored three.js via the native <script type="importmap">,
GLTFLoader parses our own vtkGLTFExporter output, and Three.js actually
renders it to a canvas -- verified by screenshotting that canvas, the same
non-blank-pixel-fraction check used throughout this project, plus a check
that no JS errors were thrown along the way.

Cannot verify from here: actually entering a WebXR session (needs a real
headset). This only exercises the plain (non-XR) render path.
"""

from tests.live_server import live_server  # noqa: F401

import numpy as np
from playwright.sync_api import sync_playwright


def _fraction_non_background(img):
    background = img[0, 0]
    diff = np.abs(img.astype(int) - background.astype(int)).sum(axis=-1)
    return float((diff > 10).mean())


def test_page_loads_and_renders_without_errors(live_server, tmp_path):
    console_errors = []
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 800, "height": 600}, ignore_https_errors=True
        )
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        page.goto(live_server, wait_until="networkidle")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )
        # let a few animation frames render after the model swaps in
        page.wait_for_timeout(300)

        screenshot_path = str(tmp_path / "page.png")
        page.screenshot(path=screenshot_path)
        browser.close()

    assert not page_errors, f"uncaught JS errors: {page_errors}"
    assert not console_errors, f"console errors: {console_errors}"

    from PIL import Image

    img = np.array(Image.open(screenshot_path).convert("RGB"))
    fraction_lit = _fraction_non_background(img)
    assert fraction_lit > 0.01, (
        f"rendered page looks essentially blank ({fraction_lit:.4%} non-background pixels)"
    )
