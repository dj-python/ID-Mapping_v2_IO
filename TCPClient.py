# 이 코드는 Pusher 동작 IO보드용 클라이언트 TCP 통신 모듈임.

import socket
import time


def init(self, server_ip: str, server_port: int):
    self.server_ip = server_ip
    self.server_port = server_port
    self.sock = None
    self.connect_to_server()

def connect_to_server(self):
    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    while True:
        try:
            self.sock.connect((self.server_ip, self.server_port))
            print(f"[*] 서버에 연결됨: {self.server_ip}:{self.server_port}")
            break                                           # 서버에 성공적으로 연결되면 루프 종료
        except Exception as e:
            print(f"[클라이언트] 서버 연결 실패: {str(e)}, 1초 후 재시도..")
            time.sleep(1)

def receive_data(self):
    try:
        data = self.sock.recv(1024)  # 최대 1024바이트 수신
        if data :
            print(f"[클라이언트] 수신된 데이터: {data.decode('utf-8')}")
            return data
    except Exception as e :
        print(f"[클라이언트] Error: {str(e)}")
        raise

def send_data(self, msg: str):
    try:
        self.sock.sendall(msg.encode())
        print(f"[클라이언트] 응답 메시지 전송: {msg}")
    except Exception as e:
        print(f"Error: {str(e)}")

def close_connection(self):
    self.sock.close()
    print("[*] 서버 연결 종료")

