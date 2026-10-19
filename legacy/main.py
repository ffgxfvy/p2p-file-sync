import os
import time
from sync_lite import SyncLiteController

def main():
    print("🚀 SyncLite - 简易P2P文件共享")
    print("=" * 40)
    
    # 获取节点名称
    node_name = input("请输入您的节点名称 (直接回车使用默认名称): ").strip() or None
    
    # 创建控制器
    shared_folder = os.path.join(os.getcwd(), "shared_files")
    controller = SyncLiteController(shared_folder, node_name)
    
    # 启动系统
    print("\n正在启动系统...")
    controller.start()
    
    print(f"\n✅ 系统启动成功!")
    print(f"📁 您的共享文件夹: {os.path.abspath(shared_folder)}")
    print(f"🆔 您的节点名称: {controller.node_id}")
    
    # 检查共享文件夹状态
    local_files = controller.sync_manager._get_local_file_metadata()
    if not local_files:
        print("\n💡 使用指南:")
        print("1. 将您要共享的文件复制到上面的共享文件夹中")
        print("2. 输入 'files' 查看您的共享文件")
        print("3. 输入 'list' 查看发现的设备")
        print("4. 输入 'sync' 与其他设备同步文件")
    else:
        print(f"✅ 发现 {len(local_files)} 个共享文件，已准备好同步")
    
    def show_help():
        print("\n" + "=" * 40)
        print("📋 可用命令:")
        print("  list  - 查看发现的设备")
        print("  sync  - 自动同步文件")
        print("  files - 查看我的共享文件")
        print("  add   - 添加文件到共享文件夹")
        print("  help  - 显示帮助")
        print("  quit  - 退出程序")
        print("=" * 40)
    
    show_help()
    
    try:
        while True:
            command = input("\n请输入命令 > ").strip().lower()
            
            if command in ['quit', 'exit']:
                print("\n感谢使用 SyncLite!")
                break
                
            elif command == 'list':
                if controller.known_peers:
                    print(f"\n📱 发现 {len(controller.known_peers)} 个设备:")
                    for peer_id, peer in controller.known_peers.items():
                        status = "🟢 在线" if peer.is_online() else "🔴 离线"
                        print(f"  • {peer_id} ({peer.ip_address}) {status}")
                    print("\n💡 输入 'sync' 与这些设备同步文件")
                else:
                    print("\n📭 还没有发现其他设备")
                    print("💡 请确保:")
                    print("  1. 其他设备也在同一网络")
                    print("  2. 其他设备也运行了 SyncLite")
                    print("  3. 等待几秒钟让设备自动发现")
                    
            elif command == 'sync':
                if not controller.known_peers:
                    print("\n⚠️  没有发现其他设备，无法同步")
                    print("💡 请先确保有其他设备在线，或等待设备自动发现")
                    continue
                    
                print(f"\n🔄 正在与 {len(controller.known_peers)} 个设备同步...")
                has_files = False
                
                for peer_id, peer in controller.known_peers.items():
                    if peer.is_online():
                        print(f"  📡 正在检查 {peer_id} 的文件...")
                        controller.request_peer_file_list(peer.ip_address, peer.tcp_port)
                        time.sleep(0.5)
                        has_files = True
                
                if has_files:
                    print("✅ 同步完成！如果发现新文件，系统会提示您下载")
                else:
                    print("ℹ️  所有设备都处于离线状态")
                    
            elif command == 'files':
                local_files = controller.sync_manager._get_local_file_metadata()
                if local_files:
                    total_size = sum(meta['size'] for meta in local_files.values())
                    print(f"\n📁 我的共享文件 ({len(local_files)} 个文件, {total_size/1024:.1f} KB):")
                    for filename, meta in local_files.items():
                        size_kb = meta['size'] / 1024
                        print(f"  • {filename} ({size_kb:.1f} KB)")
                    print(f"\n💡 其他设备可以通过 SyncLite 下载这些文件")
                else:
                    print("\n📭 共享文件夹为空")
                    print(f"💡 请将文件放入: {shared_folder}")
                    print("   或者输入 'add' 查看如何添加文件")
                    
            elif command == 'add':
                print(f"\n📁 如何添加共享文件:")
                print(f"1. 直接复制文件到文件夹: {shared_folder}")
                print(f"2. 或者使用文件管理器打开该文件夹")
                print(f"\n当前文件夹内容:")
                if os.path.exists(shared_folder):
                    items = os.listdir(shared_folder)
                    if items:
                        for item in items:
                            item_path = os.path.join(shared_folder, item)
                            if os.path.isfile(item_path):
                                size = os.path.getsize(item_path)
                                print(f"  📄 {item} ({size/1024:.1f} KB)")
                            else:
                                print(f"  📁 {item} (文件夹)")
                    else:
                        print("  📭 文件夹为空")
                else:
                    print("  ❌ 文件夹不存在")
                    
            elif command == 'help':
                show_help()
                
            elif command == '':
                continue
            else:
                print("❌ 未知命令，输入 'help' 查看可用命令")
                
    except KeyboardInterrupt:
        print("\n\n正在退出...")
    finally:
        controller.stop()

if __name__ == "__main__":
    main()