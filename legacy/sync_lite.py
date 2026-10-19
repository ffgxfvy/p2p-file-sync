import os
import socket
from discovery import DiscoveryService
from file_transfer import FileTransferService
from sync_manager import FileSyncManager

class SyncLiteController:
    def __init__(self, shared_folder, node_name=None):
        self.shared_folder = shared_folder
        self.node_id = node_name or f"设备_{socket.gethostname()}"
        self.tcp_port = 8888

        # 初始化服务
        self.discovery_service = DiscoveryService(self.node_id, self.tcp_port)
        self.file_transfer = FileTransferService(shared_folder, self.tcp_port)
        self.sync_manager = FileSyncManager(shared_folder)

        # 设置回调
        self.discovery_service.set_peer_discovered_callback(self._on_peer_discovered)
        self.file_transfer.on_metadata_received = self._on_metadata_received

        # 已知节点
        self.known_peers = {}

    def start(self):
        """启动所有服务"""
        os.makedirs(self.shared_folder, exist_ok=True)
        self.discovery_service.start_discovery()
        self.file_transfer.start_file_server()
        print("✅ 网络服务已启动，正在寻找其他设备...")

    def _on_peer_discovered(self, peer):
        """发现新节点时的回调"""
        self.known_peers[peer.node_id] = peer
        print(f"🔍 发现新设备: {peer.node_id}")

    def _on_metadata_received(self, peer_ip, metadata):
        """收到文件元数据时的回调"""
        if not metadata:
            # 对方没有共享文件
            print(f"ℹ️  {peer_ip} 设备没有共享文件")
            return
            
        sync_actions = self.sync_manager.compare_with_peer(peer_ip, metadata)
        
        # 只显示可下载的文件
        download_actions = [a for a in sync_actions if a['action'] == 'download']
        
        if download_actions:
            print(f"\n🎉 从 {peer_ip} 发现 {len(download_actions)} 个新文件:")
            for i, action in enumerate(download_actions, 1):
                print(f"  {i}. {action['filename']}")
            
            print("\n💡 输入文件编号下载，或直接回车跳过")
            choice = input("请选择要下载的文件: ").strip()
            
            if choice.isdigit():
                index = int(choice) - 1
                if 0 <= index < len(download_actions):
                    filename = download_actions[index]['filename']
                    print(f"⬇️  正在下载: {filename}")
                    if self.download_file(peer_ip, 8888, filename):
                        print(f"✅ 下载完成: {filename}")
                    else:
                        print(f"❌ 下载失败: {filename}")
                else:
                    print("❌ 无效的文件编号")
            else:
                print("⏭️  跳过下载")
        else:
            print(f"ℹ️  {peer_ip} 设备没有新文件可下载")

    def request_peer_file_list(self, peer_ip, peer_port):
        """请求对等节点的文件列表"""
        self.file_transfer.request_file_list(peer_ip, peer_port)

    def download_file(self, peer_ip, peer_port, filename):
        """从对等节点下载文件"""
        return self.file_transfer.download_file(peer_ip, peer_port, filename)

    def stop(self):
        """停止所有服务"""
        self.discovery_service.stop_discovery()
        self.file_transfer.running = False
        if self.file_transfer.server_socket:
            self.file_transfer.server_socket.close()