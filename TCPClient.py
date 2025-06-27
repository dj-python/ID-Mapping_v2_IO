# 이 코드는 Pusher 동작 IO보드용 클라이언트 TCP 통신 모듈임.
import _thread
from machine import Pin, SPI
import network
import socket
import time

tcpSocket = None
is_initialized = None
_ping_thread_running = None

def init(ipAddress: str, portNumber: int, gateway: str, server_ip: str, server_port: int):
    global tcpSocket, is_initialized, _ping_thread_running

    try:
        # 기본 소켓이 열려 있으면 닫고 초기화
        if tcpSocket:
            try:tcpSocket.close()
            except: pass
            tcpSocket = None

            spi = SPI(0, 1_000_000, polarity=0, phase=0, mosi=Pin(19), miso=Pin(16), sck=Pin(18))
            eth = network.WIZNET5K(spi, Pin(17), Pin(20))
            eth.active(True)

            eth.ifconfig((ipAddress, '255.255.255.0', '8.8.8.8', gateway))
            print("[*] Network Config:", eth.ifconfig())
            print(f"[*] Attempting connection to... {server_ip}:{server_port}")

            # 서버 접속 시도 (재시도 로직 포함)
            try:
                tcpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcpSocket.bind(ipAddress, portNumber)
                tcpSocket.connect((server_ip, server_port))
                is_initialized = True
                tcpSocket.setblocking(True)
                print(f"[*] Connected to TCP Server: {server_ip} : {server_port}")

                # ping 송신 스레드 시작
                if not _ping_thread_running:
                    _thread.start_new_thread(_ping_sender, ())
                    _ping_thread_running = True

            except Exception as e:
                print(f"[-] Unexpected Error: {e}")
                is_initialized = False
                if tcpSocket:
                    try: tcpSocket.close()
                    except: pass
                    tcpSocket = None

    except Exception as e:
        print(f"[-] Initialization Error: {str(e)}")
        is_initialized = False
        try: tcpSocket.close()
        except: pass
        tcpSocket = None

def _ping_sender():
    global tcpSocket, is_initialized, _ping_thread_running

    try:
        while is_initialized and tcpSocket:
            try:
                tcpSocket.sendall(b"ping\n")
                print("[*] Ping sent")
            except Exception as e:
                print(f"[Error] ping send failed: {e}")
                is_initialized = False
                break
            time.sleep(3)
    except Exception as e:
        print(f"[Error] ping sender thread error: {e}")
        is_initialized = False
    finally:
        _ping_thread_running = False

def read_from_socket():
    global tcpSocket, is_initialized
    if tcpSocket is None:
        return b""
    try:
        return tcpSocket.recv(1024)
    except Exception as e:
        print(f"[Error] socket recv failed: {e}")
        is_initialized = False
        return b""

def receive_data(self):
    try:
        data = self.sock.recv(1024)  # 최대 1024바이트 수신
        if data :
            print(f"[클라이언트] 수신된 데이터: {data.decode('utf-8')}")
            return data
    except Exception as e :
        print(f"[클라이언트] Error: {str(e)}")
        raise

def sendMessage(self, msg: str):
    global tcpSocket, is_initialized
    # 메시지 전송
    try:
        tcpSocket.sendall(msg.encode('utf-8'))
        print(f"[클라이언트] Message sent: {msg}")
    except Exception as e:
        print(f"[클라이언트] Send Error: {str(e)}")
        is_initialized = False

def close_connection(self):
    global tcpSocket
    if tcpSocket:
        tcpSocket.close()
        tcpSocket = None
        print("[*] 서버 연결 종료")

