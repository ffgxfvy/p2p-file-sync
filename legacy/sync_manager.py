import os

class FileSyncManager:
    def __init__(self, shared_folder):
        self.shared_folder = shared_folder

    def _get_local_file_metadata(self):
        """获取本地文件元数据"""
        metadata = {}
        if not os.path.exists(self.shared_folder):
            os.makedirs(self.shared_folder, exist_ok=True)

        for filename in os.listdir(self.shared_folder):
            filepath = os.path.join(self.shared_folder, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)
                metadata[filename] = {
                    'size': stat.st_size,
                    'modified_time': stat.st_mtime
                }
        return metadata

    def compare_with_peer(self, peer_ip, peer_metadata):
        """比较本地与对端文件差异"""
        local_metadata = self._get_local_file_metadata()
        sync_actions = []

        # 只检查对端有而本地没有的文件
        for filename, peer_file in peer_metadata.items():
            if filename not in local_metadata:
                sync_actions.append({
                    'filename': filename,
                    'action': 'download',
                    'reason': 'file_only_peer'
                })

        return sync_actions