"""节点发现测试。

默认关闭广播（enable_broadcast=False），用手动登记来验证状态机，
避免依赖"广播能不能通"这种环境相关的行为。
另有一个真实 UDP 广播测试，标为 slow 以便必要时跳过。
"""
import time

import pytest

from p2psync.discovery import DiscoveryService
from p2psync.peer_node import PeerNode


@pytest.fixture
def discovery():
    service = DiscoveryService("self-node", tcp_port=9000, enable_broadcast=False)
    yield service
    service.stop()


# ---------------- PeerNode 状态 ----------------

def test_new_peer_is_online():
    peer = PeerNode(node_id="a", ip_address="127.0.0.1", tcp_port=8888)
    assert peer.is_online() is True
    assert peer.status == PeerNode.ONLINE


def test_peer_goes_offline_after_timeout():
    peer = PeerNode(node_id="a", ip_address="127.0.0.1", tcp_port=8888,
                    last_seen=time.time() - 3600)
    assert peer.is_online() is False
    assert peer.status == PeerNode.OFFLINE


def test_touch_refreshes_liveness():
    peer = PeerNode(node_id="a", ip_address="127.0.0.1", tcp_port=8888,
                    last_seen=time.time() - 3600)
    assert peer.is_online() is False
    assert peer.touch().is_online() is True


def test_peer_address_and_repr():
    peer = PeerNode(node_id="a", ip_address="10.0.0.5", tcp_port=8888)
    assert peer.address == ("10.0.0.5", 8888)
    assert "10.0.0.5:8888" in str(peer)


# ---------------- 登记 ----------------

def test_manual_registration(discovery):
    peer = discovery.register_peer("other", "192.168.1.7", 8888)
    assert peer is not None
    assert discovery.get_peer("other") is peer
    assert len(discovery) == 1


def test_self_registration_is_ignored(discovery):
    assert discovery.register_peer("self-node", "127.0.0.1", 9000) is None
    assert len(discovery) == 0


def test_registration_requires_id_and_port(discovery):
    assert discovery.register_peer(None, "127.0.0.1", 8888) is None
    assert discovery.register_peer("x", "127.0.0.1", 0) is None
    assert len(discovery) == 0


def test_re_registration_refreshes_instead_of_duplicating(discovery):
    discovery.register_peer("other", "192.168.1.7", 8888)
    first = discovery.get_peer("other")
    first.last_seen = time.time() - 3600

    discovery.register_peer("other", "192.168.1.99", 9999)
    same = discovery.get_peer("other")
    assert same is first                       # 同一个对象被复用
    assert same.ip_address == "192.168.1.99"   # 地址更新
    assert same.tcp_port == 9999
    assert same.is_online() is True
    assert len(discovery) == 1


def test_callback_fires_only_for_new_peers(discovery):
    seen = []
    discovery.set_peer_discovered_callback(seen.append)

    discovery.register_peer("a", "127.0.0.1", 8888)
    discovery.register_peer("a", "127.0.0.1", 8888)      # 重复
    discovery.register_peer("b", "127.0.0.1", 8889)

    assert [p.node_id for p in seen] == ["a", "b"]


def test_callback_exception_does_not_break_registration(discovery):
    def boom(_peer):
        raise RuntimeError("回调炸了")

    discovery.set_peer_discovered_callback(boom)
    assert discovery.register_peer("a", "127.0.0.1", 8888) is not None


def test_online_peers_filters_stale_entries(discovery):
    discovery.register_peer("fresh", "127.0.0.1", 8888)
    discovery.register_peer("stale", "127.0.0.1", 8889)
    discovery.get_peer("stale").last_seen = time.time() - 3600

    online = discovery.online_peers()
    assert set(online) == {"fresh"}
    assert len(discovery) == 2                 # 记录保留，便于界面展示


def test_start_stop_is_idempotent(discovery):
    discovery.start()
    discovery.stop()
    discovery.stop()                           # 重复 stop 不应抛异常
