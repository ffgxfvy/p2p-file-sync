"""端到端测试：两个完整的 P2Psync 节点互相同步（真实 socket，不走广播）。"""
import os

import pytest

from p2psync import SyncController
from p2psync.checksum import sha256_file
from p2psync.file_transfer import part_path_of
from tests.conftest import make_payload, write_file


@pytest.fixture
def node_a(tmp_path):
    """作为「服务端」的节点，共享目录里有文件。"""
    folder = tmp_path / "A"
    folder.mkdir()
    controller = SyncController(str(folder), node_name="node-A",
                                enable_broadcast=False).start()
    yield controller
    controller.stop()


@pytest.fixture
def node_b(tmp_path):
    """作为「客户端」的节点，共享目录为空。"""
    folder = tmp_path / "B"
    folder.mkdir()
    controller = SyncController(str(folder), node_name="node-B",
                                enable_broadcast=False).start()
    yield controller
    controller.stop()


@pytest.fixture
def peer_a(node_a, node_b):
    """在 B 的发现服务里登记 A —— 相当于「B 发现了同一网段的 A」。

    注意：必须登记在 node_b 上；登记在 node_a 上会被自身的 node_id 过滤掉，
    这正是 register_peer 的防自环逻辑。
    """
    peer = node_b.discovery.register_peer("node-A", "127.0.0.1", node_a.tcp_port)
    assert peer is not None, "peer_a fixture 应该成功登记 node-A"
    return peer


# ---------------- 基本同步 ----------------

def test_two_nodes_bind_different_ports(node_a, node_b):
    assert node_a.tcp_port > 0
    assert node_b.tcp_port > 0
    assert node_a.tcp_port != node_b.tcp_port


def test_sync_downloads_all_files(node_a, node_b, peer_a):
    write_file(node_a.shared_folder, "a.txt", "hello")
    write_file(node_a.shared_folder, "b.txt", "world")

    plan, results = node_b.sync_with(peer_a)

    assert sorted(plan.to_download) == ["a.txt", "b.txt"]
    assert all(not isinstance(v, Exception) for v in results.values())
    assert (node_b.sync_manager.path_of("a.txt")).endswith("a.txt")
    with open(node_b.sync_manager.path_of("a.txt"), encoding="utf-8") as f:
        assert f.read() == "hello"


def test_synced_content_is_byte_identical(node_a, node_b, peer_a):
    payload = make_payload(600_000, seed=21)
    write_file(node_a.shared_folder, "blob.bin", payload)

    node_b.sync_with(peer_a)

    downloaded = node_b.sync_manager.path_of("blob.bin")
    with open(downloaded, "rb") as f:
        assert f.read() == payload
    assert sha256_file(downloaded) == sha256_file(node_a.sync_manager.path_of("blob.bin"))


def test_sync_with_empty_remote_is_a_noop(node_a, node_b, peer_a):
    plan, results = node_b.sync_with(peer_a)
    assert plan.is_empty
    assert results == {}


def test_second_sync_downloads_nothing(node_a, node_b, peer_a):
    write_file(node_a.shared_folder, "a.txt", "hello")
    node_b.sync_with(peer_a)

    plan, results = node_b.sync_with(peer_a)
    assert plan.is_empty
    assert results == {}
    assert plan.identical == ["a.txt"]


def test_modified_remote_file_is_detected_by_hash(node_a, node_b, peer_a):
    """内容变了但大小可能相同 —— 靠哈希才能发现。"""
    write_file(node_a.shared_folder, "a.txt", "AAAAA")
    node_b.sync_with(peer_a)

    write_file(node_a.shared_folder, "a.txt", "BBBBB")     # 大小相同、内容不同
    plan, _ = node_b.plan_for(peer_a)
    assert plan.to_download == ["a.txt"]

    node_b.sync_with(peer_a, overwrite=True)
    with open(node_b.sync_manager.path_of("a.txt"), encoding="utf-8") as f:
        assert f.read() == "BBBBB"


def test_local_only_files_are_not_uploaded(node_b, peer_a):
    write_file(node_b.shared_folder, "local.txt", "mine")
    plan, _ = node_b.plan_for(peer_a)
    assert plan.to_upload == ["local.txt"]
    assert plan.to_download == []


# ---------------- 并发与多点 ----------------

def test_concurrent_download_of_many_files(node_a, node_b, peer_a):
    expected = {}
    for i in range(12):
        payload = make_payload(50_000 + i * 1000, seed=i)
        write_file(node_a.shared_folder, f"f{i:02d}.bin", payload)
        expected[f"f{i:02d}.bin"] = payload

    plan, results = node_b.sync_with(peer_a, max_workers=4)

    assert len(plan.to_download) == 12
    assert all(not isinstance(v, Exception) for v in results.values())
    for name, payload in expected.items():
        with open(node_b.sync_manager.path_of(name), "rb") as f:
            assert f.read() == payload


def test_sync_all_with_multiple_peers(tmp_path):
    """两个服务端 + 一个客户端，一次同步拉全。"""
    servers = []
    for index in range(2):
        folder = tmp_path / f"server{index}"
        folder.mkdir()
        controller = SyncController(str(folder), node_name=f"srv-{index}",
                                    enable_broadcast=False).start()
        write_file(folder, f"srv{index}.txt", f"content-{index}")
        servers.append(controller)

    client_dir = tmp_path / "client"
    client_dir.mkdir()
    client = SyncController(str(client_dir), node_name="client",
                            enable_broadcast=False).start()
    try:
        for controller in servers:
            client.discovery.register_peer(controller.node_id, "127.0.0.1", controller.tcp_port)

        outcome = client.sync_all()
        assert len(outcome) == 2
        assert client.sync_manager.path_of("srv0.txt")
        with open(client.sync_manager.path_of("srv1.txt"), encoding="utf-8") as f:
            assert f.read() == "content-1"
    finally:
        client.stop()
        for controller in servers:
            controller.stop()


# ---------------- 断点续传（通过控制器） ----------------

def test_controller_resumes_a_partial_download(node_a, node_b, peer_a):
    payload = make_payload(400_000, seed=31)
    write_file(node_a.shared_folder, "big.bin", payload)

    # 预置半截 .part
    partial = node_b.sync_manager.path_of("big.bin") + ".part"
    with open(partial, "wb") as f:
        f.write(payload[:150_000])

    node_b.sync_with(peer_a)

    final = node_b.sync_manager.path_of("big.bin")
    assert not os.path.exists(part_path_of(final))
    with open(final, "rb") as f:
        assert f.read() == payload


# ---------------- 故障处理 ----------------

def test_sync_against_dead_peer_raises(tmp_path, node_b):
    from p2psync.peer_node import PeerNode
    # 端口 1 上不会有服务
    dead = PeerNode(node_id="dead", ip_address="127.0.0.1", tcp_port=1)
    with pytest.raises(OSError):
        node_b.sync_with(dead)


def test_sync_all_tolerates_a_dead_peer(tmp_path, node_b, node_a, peer_a):
    from p2psync.peer_node import PeerNode
    write_file(node_a.shared_folder, "a.txt", "hello")
    node_b.discovery.register_peer("dead", "127.0.0.1", 1)

    outcome = node_b.sync_all()
    assert "dead" in outcome
    plan, results = outcome["node-A"]
    assert plan.to_download == ["a.txt"]


def test_add_file_via_controller(node_b, tmp_path):
    source = tmp_path / "outside.txt"
    source.write_text("data", encoding="utf-8")
    target = node_b.add_file(source)
    assert os.path.isfile(target)
    assert "outside.txt" in node_b.local_files()


def test_status_returns_to_idle_after_sync(node_a, node_b, peer_a):
    from p2psync.controller import STATUS_IDLE
    write_file(node_a.shared_folder, "a.txt", "x")
    node_b.sync_with(peer_a)
    assert node_b.status == STATUS_IDLE


def test_sync_count_counts_completed_operations(node_a, node_b, peer_a):
    """sync_count 统计"完成的同步操作次数"，无文件可下载的空同步也算。"""
    assert node_b.sync_count == 0
    node_b.sync_with(peer_a)               # 空同步
    assert node_b.sync_count == 1

    write_file(node_a.shared_folder, "a.txt", "x")
    node_b.sync_with(peer_a)               # 实际下载
    assert node_b.sync_count == 2

    node_b.sync_with(peer_a)               # 已是最新
    assert node_b.sync_count == 3
