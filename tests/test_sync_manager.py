"""清单与差异计算测试 —— 重点是"内容相同但时间戳不同"这类误判。"""
import os
import time

import pytest

from p2psync.sync_manager import FileMeta, FileSyncManager, SyncPlan
from tests.conftest import write_file


def _meta(name, size, mtime=0.0, sha="a" * 64):
    return FileMeta(name=name, size=size, mtime=mtime, sha256=sha)


# ---------------- 本地清单 ----------------

def test_metadata_of_empty_folder(shared_dir):
    assert FileSyncManager(shared_dir).get_metadata() == {}


def test_metadata_includes_size_hash_and_skips_subdirs(shared_dir):
    write_file(shared_dir, "a.txt", "hello")
    (shared_dir / "subdir").mkdir()

    meta = FileSyncManager(shared_dir).get_metadata()
    assert set(meta) == {"a.txt"}
    assert meta["a.txt"].size == 5
    assert len(meta["a.txt"].sha256) == 64


def test_metadata_hash_is_cached_until_file_changes(shared_dir, monkeypatch):
    """哈希缓存：size 与 mtime 都未变时不应重复读盘（大目录同步的性能关键）。"""
    import p2psync.sync_manager as sm

    calls = {"n": 0}
    real_sha256_file = sm.sha256_file

    def counting_sha256_file(*args, **kwargs):
        calls["n"] += 1
        return real_sha256_file(*args, **kwargs)

    monkeypatch.setattr(sm, "sha256_file", counting_sha256_file)

    write_file(shared_dir, "a.txt", "hello")
    manager = FileSyncManager(shared_dir)

    first = manager.get_metadata()["a.txt"].sha256
    assert calls["n"] == 1

    # 内容与 mtime 未变 → 命中缓存
    assert manager.get_metadata()["a.txt"].sha256 == first
    assert calls["n"] == 1

    # 内容变了（mtime 也会变）→ 重新哈希
    write_file(shared_dir, "a.txt", "hello world")
    future = time.time() + 5
    os.utime(str(shared_dir / "a.txt"), (future, future))
    manager.get_metadata()
    assert calls["n"] == 2


def test_compute_hash_can_be_disabled(shared_dir):
    write_file(shared_dir, "a.txt", "hello")
    meta = FileSyncManager(shared_dir, compute_hash=False).get_metadata()
    assert meta["a.txt"].sha256 == ""


# ---------------- 差异计算 ----------------

def test_plan_downloads_files_missing_locally():
    plan = FileSyncManager("/tmp").compute_plan({}, {"new.txt": _meta("new.txt", 10)})
    assert plan.to_download == ["new.txt"]
    assert plan.identical == []
    assert plan.needs_download is True


def test_plan_skips_files_with_equal_hash():
    """核心诉求：内容一致就跳过，哪怕修改时间不同。"""
    local = {"a.txt": _meta("a.txt", 5, mtime=1000, sha="x" * 64)}
    remote = {"a.txt": _meta("a.txt", 5, mtime=9999, sha="x" * 64)}
    plan = FileSyncManager("/tmp").compute_plan(local, remote)
    assert plan.to_download == []
    assert plan.identical == ["a.txt"]
    assert plan.is_empty


def test_plan_downloads_when_hash_differs_even_if_size_matches():
    """初版（只比大小 + mtime）会漏判的场景：大小相同但内容不同。"""
    local = {"a.txt": _meta("a.txt", 5, sha="1" * 64)}
    remote = {"a.txt": _meta("a.txt", 5, sha="2" * 64)}
    plan = FileSyncManager("/tmp").compute_plan(local, remote)
    assert plan.to_download == ["a.txt"]


def test_plan_falls_back_to_size_when_hash_unavailable():
    local = {"a.txt": _meta("a.txt", 5, sha="")}
    remote = {"a.txt": _meta("a.txt", 7, sha="")}
    assert FileSyncManager("/tmp").compute_plan(local, remote).to_download == ["a.txt"]

    same_size = {"a.txt": _meta("a.txt", 5, sha="")}
    assert FileSyncManager("/tmp").compute_plan(local, same_size).identical == ["a.txt"]


def test_plan_records_local_only_files_without_uploading():
    local = {"mine.txt": _meta("mine.txt", 3)}
    plan = FileSyncManager("/tmp").compute_plan(local, {})
    assert plan.to_upload == ["mine.txt"]
    assert plan.to_download == []
    assert plan.is_empty                        # 拉取语义下，本地独有 ⇒ 无事可做
    assert plan.needs_download is False


def test_plan_is_deterministic_and_sorted():
    local = {"b.txt": _meta("b.txt", 1, sha="1" * 64)}
    remote = {"a.txt": _meta("a.txt", 1), "b.txt": _meta("b.txt", 1, sha="2" * 64),
              "c.txt": _meta("c.txt", 1)}
    plan = FileSyncManager("/tmp").compute_plan(local, remote)
    assert plan.to_download == ["a.txt", "b.txt", "c.txt"]


def test_plan_describe_lists_names_and_counts():
    plan = SyncPlan(to_download=["a.txt"], identical=["b.txt"], to_upload=["c.txt"])
    text = plan.describe()
    assert "a.txt" in text and "b.txt" in text and "c.txt" in text


def test_plan_describe_truncates_long_lists():
    plan = SyncPlan(to_download=[f"f{i}.txt" for i in range(20)])
    text = plan.describe(max_names=5)
    assert "等 20 个" in text


def test_plan_describe_on_empty_plan():
    assert SyncPlan().describe() == "无需同步"


# ---------------- 文件操作 ----------------

def test_add_local_file_copies_into_shared_folder(shared_dir, tmp_path):
    source = tmp_path / "outside.txt"
    source.write_text("data", encoding="utf-8")

    manager = FileSyncManager(shared_dir)
    target = manager.add_local_file(source)
    assert os.path.isfile(target)
    assert (shared_dir / "outside.txt").read_text(encoding="utf-8") == "data"


def test_add_local_file_accepts_custom_name(shared_dir, tmp_path):
    source = tmp_path / "outside.txt"
    source.write_text("data", encoding="utf-8")
    target = FileSyncManager(shared_dir).add_local_file(source, name="renamed.txt")
    assert os.path.basename(target) == "renamed.txt"


def test_ensure_folder_creates_missing_directory(tmp_path):
    folder = tmp_path / "not" / "there"
    result = FileSyncManager(folder).ensure_folder()
    assert str(result) == str(folder)
    assert folder.is_dir()


def test_resolve_conflict_path_appends_index(shared_dir):
    write_file(shared_dir, "a.txt", "x")
    manager = FileSyncManager(shared_dir)
    assert manager.resolve_conflict_path("a.txt") == "a (1).txt"
    write_file(shared_dir, "a (1).txt", "y")
    assert manager.resolve_conflict_path("a.txt") == "a (2).txt"


def test_file_meta_roundtrip():
    meta = FileMeta(name="a.txt", size=3, mtime=1.5, sha256="f" * 64)
    assert FileMeta.from_dict(meta.to_dict()) == meta
