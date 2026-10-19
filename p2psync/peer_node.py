"""节点数据模型。"""
from dataclasses import dataclass, field
import time


@dataclass
class PeerNode:
    """局域网中的一个对等节点。"""

    node_id: str
    ip_address: str
    tcp_port: int
    last_seen: float = field(default_factory=time.time)

    # 默认 10 秒无心跳即视为离线（发现服务的广播间隔为 3 秒，
    # 因此可以容忍连续丢失两次广播）
    OFFLINE_TIMEOUT: float = 10.0
    ONLINE: str = "在线"
    OFFLINE: str = "离线"

    def touch(self):
        """收到该节点的心跳/消息时刷新存活时间。"""
        self.last_seen = time.time()
        return self

    def is_online(self, timeout=None):
        timeout = self.OFFLINE_TIMEOUT if timeout is None else timeout
        return (time.time() - self.last_seen) < timeout

    @property
    def address(self):
        return (self.ip_address, self.tcp_port)

    @property
    def status(self):
        return self.ONLINE if self.is_online() else self.OFFLINE

    def __str__(self):
        return f"{self.node_id}@{self.ip_address}:{self.tcp_port} [{self.status}]"
