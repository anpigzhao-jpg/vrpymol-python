"""The real page's coloring/size controls actually change what's rendered.

Same pattern as test_m5_switching.py: drives the real <select>/<input> the
user would touch, waits for the server round trip, confirms the rendered
pixels actually changed -- not just that the control's value changed.
"""

from tests.live_server import live_server  # noqa: F401

from playwright.sync_api import sync_playwright


def test_color_scheme_change_changes_render(live_server, tmp_path):
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
        # default molecule/rep is 1crn cartoon -- switch to cartoon+sticks
        # first so there's real per-atom color variety for "rainbow" to show.
        page.check("#rep-checkboxes input[value='sticks']")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )
        page.wait_for_timeout(300)
        before_path = str(tmp_path / "before.png")
        page.screenshot(path=before_path)

        page.select_option("#color-select", "rainbow")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )
        page.wait_for_timeout(300)
        after_path = str(tmp_path / "after.png")
        page.screenshot(path=after_path)
        browser.close()

    with open(before_path, "rb") as f:
        before_bytes = f.read()
    with open(after_path, "rb") as f:
        after_bytes = f.read()

    assert before_bytes != after_bytes, (
        "page looks identical after switching color scheme -- "
        "control likely isn't wired to /api/scene"
    )


def test_stick_radius_slider_changes_render(live_server, tmp_path):
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
        page.check("#rep-checkboxes input[value='sticks']")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )
        page.wait_for_timeout(300)
        before_path = str(tmp_path / "before.png")
        page.screenshot(path=before_path)

        page.eval_on_selector(
            "#stick-radius",
            "el => { el.value = '0.5'; el.dispatchEvent(new Event('change')); }",
        )
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )
        page.wait_for_timeout(300)
        after_path = str(tmp_path / "after.png")
        page.screenshot(path=after_path)
        browser.close()

    with open(before_path, "rb") as f:
        before_bytes = f.read()
    with open(after_path, "rb") as f:
        after_bytes = f.read()

    assert before_bytes != after_bytes, (
        "page looks identical after widening stick radius -- "
        "slider likely isn't wired to /api/scene"
    )
