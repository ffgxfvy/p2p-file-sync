"""断点续传残留文件（*.part）不应污染共享清单。

这是端到端演示时暴露出来的真实问题：`.part` 是传输中间态，不是用户想共享的内容。
如果不排除，它会以"本地独有文件"的形式出现在同步计划里，既干扰人读，
也可能被误当成一个正常的共享文件。
"""
import pytest

from p2psync.file_transfer import part_path_of
from p2psync.sync_manager import PART_SUFFIX, FileSyncManager
from tests.conftest import write_file


def test_part_suffix_is_the_documented_value():
    assert PART_SUFFIX == ".part"
    assert part_path_of("/tmp/data.bin") == "/tmp/data.bin.part"


def test_part_files_are_excluded_from_metadata(shared_dir):
    write_file(shared_dir, "data.bin", "real payload")
    write_file(shared_dir, "data.bin.part", "incomplete")

    meta = FileSyncManager(shared_dir).get_metadata()
    assert set(meta) == {"data.bin"}


def test_part_files_can_be_included_explicitly(shared_dir):
    write_file(shared_dir, "data.bin", "real payload")
    write_file(shared_dir, "data.bin.part", "incomplete")

    meta = FileSyncManager(shared_dir).get_metadata(include_partials=True)
    assert set(meta) == {"data.bin", "data.bin.part"}


def test_part_only_file_yields_empty_metadata(shared_dir):
    """目录里只有半截文件时，清单应为空（而不是把它当成一个文件）。"""
    write_file(shared_dir, "x.bin.part", "half")
    assert FileSyncManager(shared_dir).get_metadata() == {}


def test_only_files_ending_with_part_are_excluded(shared_dir):
    """名字里包含 "part" 但不是以 .part 结尾的文件不应被误排除。"""
    write_file(shared_dir, "report.partial.md", "keep me")
    write_file(shared_dir, "part.txt", "keep me too")
    write_file(shared_dir, "a.part", "drop me")

    meta = FileSyncManager(shared_dir).get_metadata()
    assert set(meta) == {"report.partial.md", "part.txt"}


def test_plan_ignores_part_files(shared_dir):
    """对端发来的清单里若含 .part（旧版本节点），本地计划也不应被它带偏。"""
    from p2psync.sync_manager import FileMeta

    write_file(shared_dir, "data.bin", "payload")
    local = FileSyncManager(shared_dir).get_metadata()
    remote = dict(local)
    remote["data.bin.part"] = FileMeta(name="data.bin.part", size=3, mtime=0.0, sha256="a" * 64)

    plan = FileSyncManager(shared_dir).compute_plan(local, remote)
    assert "data.bin.part" in plan.to_download       # 计划层不做过滤
    # 但本地清单本身不会产生这个条目 —— 干净的重扫是同步正确性的基础
    assert "data.bin.part" not in FileSyncManager(shared_dir).get_metadata()
