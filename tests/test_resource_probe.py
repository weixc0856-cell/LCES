"""P3-B: the resource probe reports measurement limits honestly."""

from __future__ import annotations

import os

import pytest

from content_studio.resource_probe import ResourceProbe, dir_bytes, tree_pids


def test_dir_bytes_sums_nested_files(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.bin").write_bytes(b"x" * 100)
    (tmp_path / "two.bin").write_bytes(b"y" * 50)
    assert dir_bytes(tmp_path) == 150


@pytest.mark.skipif(os.name != "posix", reason="the process tree is read from /proc")
def test_tree_pids_contains_the_current_process():
    assert os.getpid() in tree_pids(os.getpid())


def test_probe_samples_and_declares_unavailable_channels(tmp_path):
    (tmp_path / "frame.bin").write_bytes(b"z" * 1024)
    with ResourceProbe(tmp_path, interval_s=0.05) as probe:
        (tmp_path / "later.bin").write_bytes(b"z" * 2048)
    report = probe.report()
    assert report["samples"] >= 1
    assert report["interval_s"] == 0.05
    assert report["method"].startswith("process-tree")
    assert report["peak_disk_bytes"] is None or report["peak_disk_bytes"] >= 1024
    if "rss" in report["unavailable"]:
        assert report["peak_rss_bytes"] is None
    if "disk" in report["unavailable"]:
        assert report["peak_disk_bytes"] is None
    assert report["peak_child_processes"] >= 0


def test_probe_can_be_reported_twice(tmp_path):
    with ResourceProbe(tmp_path, interval_s=0.05) as probe:
        pass
    assert probe.report()["samples"] >= 1
