import socket
import threading
import os
import json

class FileTransferService:
    def __init__(self, shared_folder, tcp_port=8888):
        self.shared_folder = shared_folder
        self.tcp_port = tcp_port
        self.running = False
        self.server_socket = None
        self.on_metadata_received = None

    def start_file_server(self):
        """启动文件传输服务器"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind(('0.0.0.0', self.tcp_port))
            self.server_socket.listen(5)
            self.running = True
            
            # 启动接受连接线程
            acceptor_thread = threading.Thread(target=self._accept_connections)
            acceptor_thread.daemon = True
            acceptor_thread.start()
            
        except Exception as e:
            print(f"❌ 启动文件服务失败: {e}")

    def _accept_connections(self):
        """接受传入的连接"""
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                handler_thread = threading.Thread(
                    target=self._handle_client_connection,
                    args=(client_socket, addr)
                )
                handler_thread.daemon = True
                handler_thread.start()
            except:
                pass

    def _handle_client_connection(self, client_socket, addr):
        """处理客户端连接"""
        try:
            while True:
                header_data = self._receive_all(client_socket, 4)
                if not header_data:
                    break
                    
                message_length = int.from_bytes(header_data, 'big')
                message_data = self._receive_all(client_socket, message_length)
                if not message_data:
                    break
                    
                message = message_data.decode('utf-8')
                self._process_message(client_socket, message, addr)
                
        except:
            pass
        finally:
            client_socket.close()

    def _receive_all(self, sock, length):
        """接收指定长度的数据"""
        data = b''
        try:
            sock.settimeout(2.0)
            while len(data) < length:
                chunk = sock.recv(length - len(data))
                if not chunk:
                    return None
                data += chunk
            return data
        except:
            return None

    def _process_message(self, sock, message, addr):
        """处理接收到的消息"""
        try:
            parts = message.split('|', 1)
            command = parts[0]

            if command == 'GET_FILE_LIST':
                self._send_file_list(sock)
            elif command == 'REQUEST_FILE':
                if len(parts) > 1:
                    filename = parts[1]
                    self._send_file(sock, filename)
                    
        except:
            pass

    def _send_file_list(self, sock):
        """发送文件列表"""
        try:
            file_list = self._get_local_file_metadata()
            message = f"FILE_METADATA|{json.dumps(file_list)}"
            self._send_message(sock, message)
        except:
            pass

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

    def _send_file(self, sock, filename):
        """发送文件内容"""
        filepath = os.path.join(self.shared_folder, filename)
        if not os.path.exists(filepath):
            self._send_message(sock, f"FILE_ERROR|{filename}|File not found")
            return

        try:
            file_size = os.path.getsize(filepath)
            file_info = f"FILE_INFO|{filename}|{file_size}"
            self._send_message(sock, file_info)

            with open(filepath, 'rb') as f:
                total_sent = 0
                while total_sent < file_size:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    total_sent += len(chunk)
                    
        except:
            pass

    def _send_message(self, sock, message):
        """发送消息"""
        try:
            encoded_msg = message.encode('utf-8')
            message_length = len(encoded_msg).to_bytes(4, 'big')
            sock.sendall(message_length + encoded_msg)
        except:
            pass

    def request_file_list(self, peer_ip, peer_port):
        """请求对等节点的文件列表"""
        sock = self.connect_to_peer(peer_ip, peer_port)
        if not sock:
            return

        try:
            self._send_message(sock, "GET_FILE_LIST")
            
            header_data = self._receive_all(sock, 4)
            if not header_data:
                return
                
            message_length = int.from_bytes(header_data, 'big')
            message_data = self._receive_all(sock, message_length)
            if not message_data:
                return
                
            message = message_data.decode('utf-8')
            
            if message.startswith("FILE_METADATA|"):
                metadata_str = message.split('|', 1)[1]
                metadata = json.loads(metadata_str)
                
                if self.on_metadata_received:
                    self.on_metadata_received(peer_ip, metadata)
                    
        except:
            pass
        finally:
            sock.close()

    def connect_to_peer(self, peer_ip, peer_port):
        """连接到对等节点"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((peer_ip, peer_port))
            return sock
        except:
            return None

    def download_file(self, peer_ip, peer_port, filename):
        """从对等节点下载文件"""
        sock = self.connect_to_peer(peer_ip, peer_port)
        if not sock:
            return False

        try:
            self._send_message(sock, f"REQUEST_FILE|{filename}")

            header_data = self._receive_all(sock, 4)
            if not header_data:
                return False
                
            message_length = int.from_bytes(header_data, 'big')
            message_data = self._receive_all(sock, message_length)
            if not message_data:
                return False
                
            message = message_data.decode('utf-8')
            
            if message.startswith("FILE_INFO|"):
                parts = message.split('|')
                received_filename = parts[1]
                file_size = int(parts[2])

                local_path = os.path.join(self.shared_folder, received_filename)
                with open(local_path, 'wb') as f:
                    received_size = 0
                    while received_size < file_size:
                        chunk = sock.recv(min(8192, file_size - received_size))
                        if not chunk:
                            break
                        f.write(chunk)
                        received_size += len(chunk)

                return received_size == file_size
            else:
                return False
                
        except:
            return False
        finally:
            sock.close()