"""P2.3-A: process-group termination must leave no siblings or orphans."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from content_studio import motion_canvas as mc

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="POSIX process groups")


def _sleeper(code: str = "import time; time.sleep(30)") -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", code],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_stop_driver_removes_the_whole_group():
    process = _sleeper()
    pgid = os.getpgid(process.pid)
    assert mc._stop_driver(process, pgid)
    assert not mc._group_alive(pgid)


def test_stop_driver_escalates_after_sigterm_is_ignored():
    process = _sleeper(
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    )
    pgid = os.getpgid(process.pid)
    started = time.monotonic()
    assert mc._stop_driver(process, pgid)
    assert time.monotonic() - started < 15
    assert not mc._group_alive(pgid)


def test_stop_driver_does_not_touch_another_group():
    target = _sleeper()
    sibling = _sleeper()
    try:
        pgid = os.getpgid(target.pid)
        assert mc._stop_driver(target, pgid)
        assert sibling.poll() is None
    finally:
        sibling.kill()
        sibling.wait(timeout=10)


def test_group_check_detects_a_live_group():
    process = _sleeper()
    pgid = os.getpgid(process.pid)
    try:
        assert mc._group_alive(pgid)
    finally:
        mc._stop_driver(process, pgid)
    assert not mc._group_alive(pgid)
