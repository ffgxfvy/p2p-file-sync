"""文件清单与同步差异计算（基于 SHA-256）。"""
import os
from dataclasses import dataclass, field, asdict

from .checksum import sha256_file, file_size

# 断点续传的临时文件后缀。定义在这里（而非 file_transfer）是为了让
# sync_manager 与 file_transfer 都能引用而不产生循环导入。
PART_SUFFIX = ".part"


@dataclass
class FileMeta:
    """一个共享文件的元数据。

    `sha256` 是权威判据；`size` 与 `mtime` 只用于**哈希缓存**的失效判断
    （避免每次同步都重新哈希整个目录）。
    """

    name: str
    size: int
    mtime: float
    sha256: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data["name"],
            size=int(data["size"]),
            mtime=float(data.get("mtime", 0.0)),
            sha256=data.get("sha256", ""),
        )


@dataclass
class SyncPlan:
    """一次同步的计划：要下载什么、已一致什么、跳过什么。"""

    to_download: list = field(default_factory=list)
    identical: list = field(default_factory=list)
    to_upload: list = field(default_factory=list)

    @property
    def is_empty(self):
        """是否无事可做。

        本项目的同步语义是"从对端拉取"，因此只有 `to_download` 非空才算有活干；
        `to_upload` 仅作为信息展示（提示对方可能也需要这些文件），不触发动作。
        """
        return not self.to_download

    @property
    def needs_download(self):
        return bool(self.to_download)

    def describe(self, max_names=5):
        """生成给人看的同步计划说明。"""
        def listing(names):
            shown = ", ".join(names[:max_names])
            more = len(names) - max_names
            return shown + (f" 等 {len(names)} 个" if more > 0 else "")

        lines = []
        if self.to_download:
            lines.append(f"需下载 {len(self.to_download)} 个：{listing(self.to_download)}")
        if self.to_upload:
            lines.append(f"本地独有 {len(self.to_upload)} 个（对方可能需要）：{listing(self.to_upload)}")
        if self.identical:
            lines.append(f"内容一致 {len(self.identical)} 个，跳过：{listing(self.identical)}")
        return "\n".join(lines) if lines else "无需同步"


class FileSyncManager:
    """维护本地共享目录的清单，并计算与远端的差异。"""

    def __init__(self, shared_folder, compute_hash=True):
        self.shared_folder = shared_folder
        self.compute_hash = compute_hash
        self._cache = {}                    # name -> (size, mtime, sha256)

    # ---------------- 本地清单 ----------------

    def ensure_folder(self):
        os.makedirs(self.shared_folder, exist_ok=True)
        return self.shared_folder

    def path_of(self, name):
        return os.path.join(self.shared_folder, name)

    def _hash_cached(self, path, name, size, mtime):
        """哈希缓存：size 与 mtime 都没变就复用上次结果。"""
        cached = self._cache.get(name)
        if cached and cached[0] == size and cached[1] == mtime:
            return cached[2]
        digest = sha256_file(path)
        self._cache[name] = (size, mtime, digest)
        return digest

    def get_metadata(self, include_partials=False):
        """扫描共享目录，返回 {文件名: FileMeta}。

        默认**排除** `*.part` 断点续传残留文件 —— 它们是传输中间态，不是
        用户要共享的内容，出现在清单里会让对端误以为"对方有这个文件"。
        """
        self.ensure_folder()
        result = {}
        for name in sorted(os.listdir(self.shared_folder)):
            if not include_partials and name.endswith(PART_SUFFIX):
                continue
            path = self.path_of(name)
            if not os.path.isfile(path):
                continue
            try:
                size = file_size(path)
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            digest = self._hash_cached(path, name, size, mtime) if self.compute_hash else ""
            result[name] = FileMeta(name=name, size=size, mtime=mtime, sha256=digest)
        return result

    # ---------------- 差异计算 ----------------

    def compute_plan(self, local_manifest, remote_manifest):
        """对比本地与远端清单，得出需要做什么。

        判据优先级：**SHA-256 > 大小**。
        远端有、本地没有 → 下载；两边都有但哈希不同 → 下载；
        哈希相同 → 跳过；本地有远端没有 → 记为"本地独有"（不主动上传，
        因为本项目是"从对端拉取"的同步语义）。
        """
        to_download, identical, to_upload = [], [], []

        for name, remote in remote_manifest.items():
            local = local_manifest.get(name)
            if local is None:
                to_download.append(name)
            elif remote.sha256 and local.sha256:
                (identical if local.sha256 == remote.sha256 else to_download).append(name)
            elif local.size != remote.size:
                to_download.append(name)
            else:
                identical.append(name)

        for name in local_manifest:
            if name not in remote_manifest:
                to_upload.append(name)

        return SyncPlan(
            to_download=sorted(to_download),
            identical=sorted(identical),
            to_upload=sorted(to_upload),
        )

    def add_local_file(self, source_path, name=None):
        """把外部文件复制进共享目录。"""
        import shutil

        self.ensure_folder()
        name = name or os.path.basename(source_path)
        target = self.path_of(name)
        if os.path.abspath(source_path) != os.path.abspath(target):
            shutil.copy2(source_path, target)
        return target

    def resolve_conflict_path(self, name):
        """下载冲突时生成不覆盖的文件名：a.txt -> a (1).txt"""
        base, ext = os.path.splitext(name)
        index = 1
        candidate = name
        while os.path.exists(self.path_of(candidate)):
            candidate = f"{base} ({index}){ext}"
            index += 1
        return candidate
