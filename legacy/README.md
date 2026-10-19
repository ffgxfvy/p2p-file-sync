# legacy/ —— 课程项目原始版本（v1）

这里的 7 个 `.py` 文件是《计算机网络与通信》课程小组项目的**原始提交版本**
（程序内部名称为 SyncLite），保留下来是为了看清 v2 的改造幅度。

## 与 v2 的对应关系

| legacy（v1） | v2 | 改动 |
|---|---|---|
| `discovery.py` | `p2psync/discovery.py` | 补上生命周期管理、自环过滤、回调异常隔离、端口占用降级 |
| `file_transfer.py` | `p2psync/file_transfer.py` | **分块收发 + SHA-256 校验 + 断点续传 + 并发**，路径穿越防护 |
| `sync_manager.py` | `p2psync/sync_manager.py` | 从"大小 + mtime"改为 **SHA-256 判据**，加哈希缓存 |
| `sync_lite.py` | `p2psync/controller.py` | 保留"服务组合 + 回调解耦"的设计，补齐启动顺序与同步计划 |
| `main.py` | `p2psync/cli.py` + `main.py` | 增加 `--once` / `--peers` / `--no-broadcast` 等参数，便于脚本化 |
| `peer_node.py` | `p2psync/peer_node.py` | 补 `touch()` / `address` / 状态字符串 |
| `check.py` | 移除 | 诊断功能并入 CLI 的 `info` 命令 |
| （无） | `p2psync/protocol.py` | 新增：把协议从业务逻辑里抽出来，独立可测 |
| （无） | `p2psync/checksum.py` | 新增：哈希工具集中一处 |

## 运行原始版本

```bash
cd legacy && python main.py
```

> ⚠️ v1 的行为差异（也就是 v2 要解决的问题）：
> - 只比"文件大小 + 修改时间"，**内容不同但大小相同的文件会被漏判**；
> - 传输中断会留下损坏的半截文件，且下次同步**从头重传**；
> - 无哈希校验，无法确认收到的内容是否正确；
> - 服务端未校验文件名，理论上存在 `../` 路径穿越风险。

这四条都有对应的 v2 测试：`tests/test_sync_manager.py::test_plan_downloads_when_hash_differs_even_if_size_matches`、
`tests/test_transfer.py::test_resume_completes_a_partial_download`、
`tests/test_transfer.py::test_corrupted_part_file_fails_checksum_and_is_removed`、
`tests/test_transfer.py::test_path_traversal_is_rejected`。
