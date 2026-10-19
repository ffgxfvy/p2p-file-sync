"""控制器：把发现 / 传输 / 清单三个服务组合起来，对外只暴露"同步"这一个动作。

设计要点：三个子服务之间**互不引用**，全部通过回调与显式参数协作
（`DiscoveryService` 不知道"同步"存在，`FileTransferService` 不知道"谁需要什么"）。
好处是每个服务都能单独构造与测试。
"""
import os
import socket

from .discovery import DiscoveryService
from .file_transfer import FileTransferService, download_file, fetch_manifest
from .sync_manager import FileSyncManager, SyncPlan

STATUS_IDLE = "空闲"
STATUS_SYNCING = "同步中"


class SyncController:
    """P2Psync 的应用层门面。"""

    def __init__(self, shared_folder, node_name=None, tcp_port=0, enable_broadcast=True,
                 discovery=None, transfer=None):
        self.shared_folder = os.path.abspath(shared_folder)
        self.node_id = node_name or f"设备_{socket.gethostname()}"
        self.status = STATUS_IDLE
        self.last_plan = None
        self.sync_count = 0

        self.sync_manager = FileSyncManager(self.shared_folder)

        self.transfer = transfer or FileTransferService(self.shared_folder, port=tcp_port)
        self.discovery = discovery or DiscoveryService(
            self.node_id, self.transfer.port or tcp_port, enable_broadcast=enable_broadcast
        )
        self.discovery.set_peer_discovered_callback(self._on_peer_discovered)

    # ------------- 生命周期 -------------

    def start(self):
        self.sync_manager.ensure_folder()
        self.transfer.start()
        # 传输服务绑定到真实端口后，再让发现服务广播它
        self.discovery.tcp_port = self.transfer.port
        self.discovery.start()
        return self

    def stop(self):
        self.discovery.stop()
        self.transfer.stop()
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ------------- 回调 -------------

    def _on_peer_discovered(self, peer):
        """发现新节点时的钩子（默认只记录，界面可覆盖）。"""
        return peer

    @property
    def tcp_port(self):
        return self.transfer.port

    @property
    def known_peers(self):
        return self.discovery.peers

    def online_peers(self):
        return self.discovery.online_peers()

    # ------------- 同步 -------------

    def local_files(self):
        return self.sync_manager.get_metadata()

    def plan_for(self, peer):
        """计算与某个节点的同步计划（只拉取，不上传）。"""
        remote = fetch_manifest(peer)
        plan = self.sync_manager.compute_plan(self.local_files(), remote)
        self.last_plan = plan
        return plan, remote

    def sync_with(self, peer, overwrite=False, resume=True, max_workers=4):
        """与指定节点同步：拉取对方有而本地缺失/不一致的文件。

        返回 `(plan, results)`；`results[name]` 为落盘路径或异常对象。
        """
        self.status = STATUS_SYNCING
        try:
            plan, remote = self.plan_for(peer)
            if not plan.to_download:
                # 无事可做也算一次完成的同步操作（否则 sync_count 会被
                # 误当成"下载过的文件数"，在"已是最新"的场景下看起来像没执行）
                self.sync_count += 1
                return plan, {}

            if max_workers and max_workers > 1 and len(plan.to_download) > 1:
                from .file_transfer import download_many

                results = download_many(
                    peer, plan.to_download, self.shared_folder,
                    manifest=remote, max_workers=max_workers,
                    resume=resume, overwrite=overwrite,
                )
            else:
                results = {}
                for name in plan.to_download:
                    meta = remote.get(name)
                    try:
                        results[name] = download_file(
                            peer, name, self.shared_folder,
                            expected_sha256=meta.sha256 if meta else None,
                            expected_size=meta.size if meta else None,
                            resume=resume, overwrite=overwrite,
                        )
                    except Exception as exc:              # noqa: BLE001
                        results[name] = exc

            self.sync_count += 1
            return plan, results
        finally:
            self.status = STATUS_IDLE

    def sync_all(self, **kwargs):
        """与所有在线节点依次同步，返回 {node_id: (plan, results)}。"""
        outcome = {}
        for node_id, peer in self.online_peers().items():
            try:
                outcome[node_id] = self.sync_with(peer, **kwargs)
            except Exception as exc:                      # noqa: BLE001
                outcome[node_id] = (None, {"__error__": exc})
        return outcome

    def add_file(self, source_path, name=None):
        return self.sync_manager.add_local_file(source_path, name=name)
