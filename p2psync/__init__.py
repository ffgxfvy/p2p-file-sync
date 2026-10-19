"""P2Psync —— 局域网点对点文件同步工具。

纯 Python 标准库实现：UDP 广播做节点发现，TCP 做可靠传输。
"""

__version__ = "2.0.0"

from .peer_node import PeerNode
from .checksum import sha256_file, sha256_stream
from .sync_manager import FileSyncManager, FileMeta, SyncPlan
from .discovery import DiscoveryService
from .file_transfer import FileTransferService, download_file
from .controller import SyncController

__all__ = [
    "__version__",
    "PeerNode",
    "sha256_file",
    "sha256_stream",
    "FileSyncManager",
    "FileMeta",
    "SyncPlan",
    "DiscoveryService",
    "FileTransferService",
    "download_file",
    "SyncController",
]
