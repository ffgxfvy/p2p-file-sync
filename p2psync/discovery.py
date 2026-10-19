"""UDP 广播节点发现。

机制
----
- 每个节点周期性（默认 3 s）向广播地址 `255.255.255.255:<broadcast_port>` 发送
  一条 `HELLO` 消息，内容为 `{node_id, tcp_port}`；
- 同时监听同一端口，收到别人的 `HELLO` 就登记/刷新 `PeerNode.last_seen`；
- 超过 `PeerNode.OFFLINE_TIMEOUT`（10 s）没刷新即视为离线，但记录保留
  （便于界面显示"曾经见过的设备"）。

为什么用"发送方也用同一个端口监听"这种写法：无需中心服务器，也无需握手，
每台机器既是生产者也是消费者，天然支持多节点。

限制：UDP 广播无法跨网段，因此仅适用于局域网。跨网段需要中心节点或 UDP 打洞。
"""
import json
import socket
import threading
import time

from . import protocol as P
from .peer_node import PeerNode

BROADCAST_PORT = 8889
BROADCAST_INTERVAL = 3.0


class DiscoveryService:
    def __init__(self, node_id, tcp_port, broadcast_port=BROADCAST_PORT,
                 broadcast_interval=BROADCAST_INTERVAL, enable_broadcast=True,
                 broadcast_address="255.255.255.255"):
        self.node_id = node_id
        self.tcp_port = tcp_port
        self.broadcast_port = broadcast_port
        self.broadcast_interval = broadcast_interval
        self.broadcast_address = broadcast_address
        self.enable_broadcast = enable_broadcast

        self.peers = {}                       # node_id -> PeerNode
        self.on_peer_discovered = None
        self._socket = None
        self._threads = []
        self._running = False
        self._lock = threading.Lock()

    # ------------- 生命周期 -------------

    def start(self):
        self._running = True
        if self.enable_broadcast:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                self._socket.bind(("", self.broadcast_port))
            except OSError:
                # 端口被占用（例如同时跑两个实例）时降级为只发不收，
                # 这样至少还能被别的节点发现，而不是直接崩掉
                pass
            self._socket.settimeout(0.5)

            self._spawn(self._listen_loop)
            self._spawn(self._announce_loop)
        return self

    def stop(self):
        self._running = False
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def _spawn(self, target):
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self._threads.append(thread)
        return thread

    # ------------- 广播 -------------

    def _hello_message(self):
        return {"type": P.HELLO, "node_id": self.node_id, "tcp_port": self.tcp_port}

    def _announce_loop(self):
        while self._running:
            try:
                self._socket.sendto(
                    P.encode(self._hello_message()),
                    (self.broadcast_address, self.broadcast_port),
                )
            except OSError:
                pass
            # 分段 sleep，保证 stop() 能及时退出
            deadline = time.time() + self.broadcast_interval
            while self._running and time.time() < deadline:
                time.sleep(0.1)

    def announce_once(self):
        """立即广播一次（测试用，免去等 3 秒）。"""
        if self._socket is not None:
            self._socket.sendto(
                P.encode(self._hello_message()),
                (self.broadcast_address, self.broadcast_port),
            )

    def _listen_loop(self):
        while self._running:
            try:
                data, addr = self._socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                message = json.loads(data.decode(P.ENCODING))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict) or message.get("type") != P.HELLO:
                continue
            self.register_peer(
                node_id=message.get("node_id"),
                ip_address=addr[0],
                tcp_port=message.get("tcp_port"),
            )

    # ------------- 节点登记 -------------

    def register_peer(self, node_id, ip_address, tcp_port):
        """登记或刷新一个节点；自身节点会被忽略。返回 PeerNode 或 None。"""
        if not node_id or node_id == self.node_id or not tcp_port:
            return None

        with self._lock:
            existing = self.peers.get(node_id)
            if existing is None:
                peer = PeerNode(node_id=node_id, ip_address=ip_address, tcp_port=int(tcp_port))
                self.peers[node_id] = peer
                is_new = True
            else:
                existing.ip_address = ip_address
                existing.tcp_port = int(tcp_port)
                existing.touch()
                peer = existing
                is_new = False

        if is_new and self.on_peer_discovered is not None:
            try:
                self.on_peer_discovered(peer)
            except Exception:
                pass
        return peer

    def set_peer_discovered_callback(self, callback):
        self.on_peer_discovered = callback
        return self

    # ------------- 查询 -------------

    def online_peers(self):
        with self._lock:
            return {nid: p for nid, p in self.peers.items() if p.is_online()}

    def get_peer(self, node_id):
        with self._lock:
            return self.peers.get(node_id)

    def __len__(self):
        with self._lock:
            return len(self.peers)
