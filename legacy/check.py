import os
import stat


def detailed_file_check():
    print("=== 详细文件检查 ===")

    shared_path = os.path.join(os.getcwd(), "shared_folder")
    print(f"📁 共享文件夹路径: {shared_path}")
    print(f"✅ 文件夹存在: {os.path.exists(shared_path)}")

    if not os.path.exists(shared_path):
        return

    # 检查文件夹权限
    folder_stat = os.stat(shared_path)
    print(f"🔐 文件夹权限: {oct(folder_stat.st_mode)}")

    # 列出所有文件并详细检查
    print(f"\n📄 文件详细列表:")
    files = os.listdir(shared_path)
    print(f"找到 {len(files)} 个文件/文件夹")

    for item in files:
        item_path = os.path.join(shared_path, item)
        print(f"\n🔍 检查: {item}")
        print(f"   完整路径: {item_path}")
        print(f"   是否存在: {os.path.exists(item_path)}")
        print(f"   是否是文件: {os.path.isfile(item_path)}")

        if os.path.isfile(item_path):
            try:
                file_stat = os.stat(item_path)
                print(f"   文件大小: {file_stat.st_size} bytes")
                print(f"   文件权限: {oct(file_stat.st_mode)}")
                print(f"   最后修改: {file_stat.st_mtime}")

                # 尝试读取文件
                with open(item_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    print(f"   文件内容: '{content[:50]}...'" if len(content) > 50 else f"   文件内容: '{content}'")

            except PermissionError:
                print("   ❌ 权限拒绝")
            except UnicodeDecodeError:
                print("   ⚠️  无法用UTF-8解码")
            except Exception as e:
                print(f"   ❌ 读取错误: {e}")
        else:
            print("   📁 这是一个文件夹")


if __name__ == "__main__":
    detailed_file_check()
    input("\n按回车退出...")