from dataclasses import dataclass
import time


@dataclass
class PeerNode:
    node_id: str
    ip_address: str
    last_seen: float
    tcp_port: int

    def is_online(self, timeout=10):
        """检查节点是否在线"""
        return time.time() - self.last_seen < timeout