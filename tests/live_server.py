"""Shared pytest fixture: run webxr/server.py as a real subprocess.

Deliberately NOT a background Python thread in the test process: VTK's
render-window creation touches Cocoa APIs on macOS that are only safe to
call from a process's main thread. A thread-based fixture handles requests
(which render) on a worker thread and hard-crashes the whole interpreter
(an uncaught ObjC exception, not a catchable Python one). Running the
server as its own subprocess gives it its own real main thread, which is
also how it's actually deployed, so the test matches actual usage.
"""

import os
import socket
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    env = {**os.environ, "PORT": str(port)}
    process = subprocess.Popen(
        [sys.executable, "-m", "webxr.server"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    try:
        for _ in range(100):
            if process.poll() is not None:
                output = process.stdout.read().decode(errors="replace")
                raise RuntimeError(f"server process exited early:\n{output}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("test server did not start in time")

        # https, not http: the server now always terminates TLS (self-signed
        # dev cert, see webxr/dev_cert.py) since WebXR requires a secure
        # context and won't expose navigator.xr over plain HTTP to anything
        # but localhost. Tests must pass ignore_https_errors=True to
        # browser.new_page() to get past the untrusted-cert warning.
        yield f"https://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
