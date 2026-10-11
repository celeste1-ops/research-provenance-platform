"""The double-click launcher (D-044): one copy per data folder, port fallback, clean stop."""

from __future__ import annotations

import subprocess
import sys
import textwrap

from app.desktop import InstanceLock, start_server, stop_server, tray_image
from tests.conftest import make_ctx


def test_only_one_copy_holds_the_lock(tmp_path):
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    assert first.acquire()
    first.publish(8771)
    assert not second.acquire()
    assert second.running_port(wait=0) == 8771
    first.release()
    assert second.acquire()  # released (the operating system also releases it if the app dies)
    second.release()


def test_the_lock_is_released_when_the_process_dies(tmp_path):
    holder = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(tmp_path.parent)!r})
        from app.desktop import InstanceLock
        lock = InstanceLock(__import__("pathlib").Path({str(tmp_path)!r}))
        assert lock.acquire()
        print("locked", flush=True)
        time.sleep(60)
    """)
    proc = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        assert proc.stdout.readline().strip() == "locked"
        assert not InstanceLock(tmp_path).acquire()
    finally:
        proc.kill()
        proc.wait()
    lock = InstanceLock(tmp_path)
    assert lock.acquire()
    lock.release()


def test_server_starts_on_the_next_free_port_and_stops(tmp_path):
    a = make_ctx(tmp_path / "a")
    b = make_ctx(tmp_path / "b")
    server_a, thread_a, port_a = start_server(a, 18765)
    try:
        server_b, thread_b, port_b = start_server(b, port_a)  # the first port is taken
        assert port_b == port_a + 1 and b.settings.port == port_b
        stop_server(server_b, thread_b, b)
        assert not thread_b.is_alive()
    finally:
        stop_server(server_a, thread_a, a)
    assert not thread_a.is_alive()


def test_tray_icon_is_drawn_without_files():
    img = tray_image(32)
    assert img.size == (32, 32) and img.getpixel((16, 2))[3] > 0
