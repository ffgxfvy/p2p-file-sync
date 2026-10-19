import socket
import threading
import time
from peer_node import PeerNode

class DiscoveryService:
    def __init__(self, my_node_id, tcp_port=8888, broadcast_port=8889):
        self.my_node_id = my_node_id
        self.tcp_port = tcp_port
        self.broadcast_port = broadcast_port
        self.peers = {}
        self.running = False
        self.udp_socket = None
        self.on_peer_discovered = None

    def start_discovery(self):
        """启动发现服务"""
        self.running = True

        # 创建UDP socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.settimeout(1.0)

        # 启动监听线程
        listener_thread = threading.Thread(target=self._listen_for_broadcasts)
        listener_thread.daemon = True
        listener_thread.start()

        # 启动广播线程
        broadcaster_thread = threading.Thread(target=self._broadcast_presence)
        broadcaster_thread.daemon = True
        broadcaster_thread.start()

    def _listen_for_broadcasts(self):
        """监听其他节点的广播"""
        try:
            self.udp_socket.bind(('', self.broadcast_port))
        except OSError:
            return

        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(1024)
                message = data.decode('utf-8')
                self._process_broadcast_message(message, addr[0])
            except socket.timeout:
                continue
            except:
                pass

    def _process_broadcast_message(self, message, source_ip):
        """处理收到的广播消息"""
        try:
            if message.startswith("SYNCLITE_DISCOVERY|"):
                parts = message.split("|")
                if len(parts) >= 3:
                    node_id = parts[1]
                    tcp_port = int(parts[2])

                    # 忽略自己的广播
                    if node_id == self.my_node_id:
                        return

                    # 更新或添加peer
                    if node_id in self.peers:
                        self.peers[node_id].last_seen = time.time()
                    else:
                        new_peer = PeerNode(
                            node_id=node_id,
                            ip_address=source_ip,
                            last_seen=time.time(),
                            tcp_port=tcp_port
                        )
                        self.peers[node_id] = new_peer

                        # 回调通知有新节点
                        if self.on_peer_discovered:
                            self.on_peer_discovered(new_peer)
        except:
            pass

    def _broadcast_presence(self):
        """定期广播本节点的存在"""
        message = f"SYNCLITE_DISCOVERY|{self.my_node_id}|{self.tcp_port}"
        encoded_msg = message.encode('utf-8')

        while self.running:
            try:
                self.udp_socket.sendto(encoded_msg, ('255.255.255.255', self.broadcast_port))
                time.sleep(5)
            except:
                time.sleep(5)

    def stop_discovery(self):
        """停止发现服务"""
        self.running = False
        if self.udp_socket:
            self.udp_socket.close()

    def set_peer_discovered_callback(self, callback):
        """设置发现新节点时的回调函数"""
        self.on_peer_discovered = callback