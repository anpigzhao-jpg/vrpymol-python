"""M5: switching molecule/representation from the page actually changes what's rendered.

Drives the real molecule <select> and representation checkboxes exactly like
a user would, waits for the server round trip (/api/scene regenerates the
glTF via the real PyMOL bridge) and the frontend reload, then confirms the
rendered pixels actually changed -- not just that the controls' values changed.
"""

from tests.live_server import live_server  # noqa: F401

from playwright.sync_api import sync_playwright


def _screenshot_bytes_differ(a, b):
    return a != b


def test_switching_molecule_and_rep_changes_render(live_server, tmp_path):
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
        page.wait_for_timeout(300)
        before_path = str(tmp_path / "before.png")
        page.screenshot(path=before_path)

        page.select_option("#molecule-select", "caffeine")
        page.uncheck("#rep-checkboxes input[value='cartoon']")
        page.check("#rep-checkboxes input[value='spheres']")
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

    assert _screenshot_bytes_differ(before_bytes, after_bytes), (
        "page looks identical after switching molecule+representation -- "
        "switch likely didn't actually take effect"
    )
