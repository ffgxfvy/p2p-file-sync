# Changelog

## [2.0.0] - 2026-10

作品集整理时对课程版本（v1）的工程化重写。**v1 完整保留在 `legacy/`**，可逐文件对照。

### 新增能力

- **断点续传**：传输写入 `<name>.part`，中断后保留现场；下次同步以 `.part` 的实际长度
  作为 `offset` 请求续传，校验通过后才改名为正式文件。
- **SHA-256 完整性校验**：收完后校验全量哈希，不匹配则删除残留并抛 `ChecksumError`。
- **并发传输**：客户端线程池，服务端每连接一线程。
- `p2psync/protocol.py` —— 把线协议从业务逻辑中抽出：JSON Lines 控制消息 + 裸字节块，
  含 `recv_exactly`（截断即报错，避免把半截文件当成功）。
- `p2psync/checksum.py` —— SHA-256 工具集中一处，支持流式哈希。
- `p2psync/controller.py` —— 应用层门面（沿用 v1 `sync_lite.py` 的"服务组合 + 回调解耦"设计）。
- CLI 新增 `plan`（只预览差异不下载）、`info` 命令，以及 `--once` / `--wait` / `--peers` /
  `--no-broadcast` / `--port` 参数，使其可用于定时任务。
- 可安装包：`pip install -e .`、`python -m p2psync`、`p2psync` 命令。
- `tests/` —— 90 个测试，含真实 TCP 集成测试与两节点端到端测试。
- `examples/run_demo.py` —— 本机起两个节点跑完整流程的可运行演示。
- `.github/workflows/ci.yml` —— Ubuntu + Windows × Python 3.8/3.12。

### 修复

1. **同步判据从"大小 + 修改时间"改为 SHA-256**（`FileSyncManager`）。
   v1 只比较 `size` 与 `mtime`：大小相同、内容不同的文件会被漏判为"一致"；
   同时 mtime 在不同文件系统上的精度与时区差异会导致无谓的重复下载。
   v2 保留按 `size` + `mtime` 的哈希缓存，避免大目录每次同步都全量重算。
   测试：`test_plan_downloads_when_hash_differs_even_if_size_matches`。

2. **`.part` 残留文件不再进入共享清单**（`FileSyncManager.get_metadata`）。
   这个问题是写 `examples/run_demo.py` 时暴露的：半截文件会以"本地独有文件"的
   形式出现在同步计划里，污染输出。测试：`tests/test_partial_files.py`。

3. **无路径穿越防护**。v1 直接把清单里的文件名拼进路径；v2 只允许共享目录内的
   普通文件，拒绝 `../`、绝对路径与含路径分隔符的文件名。
   测试：`test_path_traversal_is_rejected`。

4. **无传输完整性校验**。v1 收到什么就写什么；v2 校验全量哈希。
   测试：`test_corrupted_part_file_fails_checksum_and_is_removed`。

5. **发现服务的端口占用处理**。v1 在 `bind` 失败时直接 `return`，
   监听线程静默退出且不做任何提示；v2 降级为"只发不收"并继续运行，
   至少还能被其他节点发现。

6. **重复注册不更新地址**。v1 收到已存在节点的广播时只刷新 `last_seen`；
   节点换 IP 或换端口后会一直连到旧地址。v2 会更新 `ip_address` 与 `tcp_port`。
   测试：`test_re_registration_refreshes_instead_of_duplicating`。

7. **大量裸 `except:`**。v1 在多处使用 `except: pass`，会把 `KeyboardInterrupt`、
   `SystemExit` 一并吞掉，也不利于定位问题。v2 收窄为具体异常类型，
   并在回调边界做异常隔离（用户回调抛错不再中断节点登记）。

8. **`SyncController.sync_count` 语义**。v1 的计数器只在确有文件下载时自增，
   导致"已是最新"的正常同步看起来像没有执行。v2 统计"完成的同步操作次数"。

### 变更

- 包结构从平铺的 `src/*.py` 改为可安装的 `p2psync/` 包。
- `FileSyncManager.compute_plan` 明确"拉取"语义：`to_upload` 仅作信息展示，
  不触发动作；`SyncPlan.is_empty` 相应定义为"没有需要下载的内容"，
  新增 `needs_download` 属性。
- 线协议从 v1 的自定义分隔符字符串（`SYNCLITE_DISCOVERY|id|port`）改为 JSON Lines；
  文件名含 `|` 时不再会解析错位。
- `PeerNode` 新增 `touch()` / `address` / 状态字符串；`is_online(timeout=None)`
  使用类默认值。
- `check.py` 的诊断功能并入 CLI 的 `info` 命令。
