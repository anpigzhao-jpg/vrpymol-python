"""The real page's multi-object UI (add/remove additional molecules) and the
state/frame slider that appears for multi-state (e.g. NMR ensemble)
molecules -- driven through the actual page controls via Playwright, same
pattern as test_m5_switching.py/test_m6_representations.py.
"""

from tests.live_server import live_server  # noqa: F401

from playwright.sync_api import sync_playwright


def test_adding_and_removing_an_object_updates_the_list_and_render(live_server, tmp_path):
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

        page.select_option("#add-object-select", "caffeine")
        page.click("#add-object-button")
        page.wait_for_function(
            "document.getElementById('object-list').children.length === 1",
            timeout=10000,
        )
        assert "caffeine" in page.inner_text("#object-list")
        page.wait_for_timeout(300)
        after_path = str(tmp_path / "after.png")
        page.screenshot(path=after_path)

        with open(before_path, "rb") as f:
            before_bytes = f.read()
        with open(after_path, "rb") as f:
            after_bytes = f.read()
        assert before_bytes != after_bytes, (
            "adding a second object did not change the render -- it likely "
            "isn't actually being added to the exported scene"
        )

        page.click("#object-list button")
        page.wait_for_function(
            "document.getElementById('object-list').children.length === 0",
            timeout=10000,
        )

        browser.close()


def test_frame_slider_appears_only_for_multi_state_molecules(live_server):
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

        # 1crn is single-state -- the slider stays hidden.
        assert page.is_hidden("#frame-section")

        # 1le0 is a real 20-model NMR ensemble -- switching the primary
        # molecule to it should reveal the slider with the real state count.
        page.select_option("#molecule-select", "1le0")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )
        page.wait_for_function(
            "!document.getElementById('frame-section').hidden", timeout=10000
        )
        assert page.eval_on_selector("#frame-slider", "el => el.max") == "20"


def test_dragging_the_frame_slider_changes_the_render(live_server, tmp_path):
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
        page.select_option("#molecule-select", "1le0")
        page.check("#rep-checkboxes input[value='spheres']")
        page.wait_for_function(
            "document.getElementById('hud').textContent.startsWith('loaded')",
            timeout=10000,
        )
        page.wait_for_function(
            "!document.getElementById('frame-section').hidden", timeout=10000
        )
        page.wait_for_timeout(300)
        before_path = str(tmp_path / "before.png")
        page.screenshot(path=before_path)

        page.eval_on_selector(
            "#frame-slider",
            "el => { el.value = 15; el.dispatchEvent(new Event('change')); }",
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
        "changing the frame slider did not change the render -- it likely "
        "isn't actually reaching the server's cmd.frame"
    )
