# 이 코드는 Pusher 동작 IO보드용 클라이언트 TCP 통신 모듈임.
import _thread
from machine import Pin, SPI
import network
import socket
import time
import sys

tcpSocket = None
is_initialized = False
_ping_thread_running = False
_ping_thread = None
_socket_lock = _thread.allocate_lock()

def init(ipAddress: str, portNumber: int, gateway: str, server_ip: str, server_port: int):
    print("==> TCPClient.init() called")
    global tcpSocket, is_initialized, _ping_thread_running

    try:
        # 기본 소켓이 열려 있으면 닫고 초기화
        if tcpSocket:
            try:
                tcpSocket.close()
            except:
                pass
            tcpSocket = None
        is_initialized = False
        _ping_thread_running = False

        spi = SPI(0, 1_000_000, polarity=0, phase=0, mosi=Pin(19), miso=Pin(16), sck=Pin(18))
        eth = network.WIZNET5K(spi, Pin(17), Pin(20))
        eth.active(True)

        eth.ifconfig((ipAddress, '255.255.255.0', '8.8.8.8', gateway))
        print("[*] Network Config:", eth.ifconfig())
        print(f"[*] Attempting connection to... {server_ip}:{server_port}")

        # 서버 접속 시도 (재시도 로직 포함)
        try:
            tcpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            #tcpSocket.bind((ipAddress, portNumber))
            tcpSocket.connect((server_ip, server_port))
            tcpSocket.setblocking(False)
            is_initialized = True
            try:
                tcpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception as e:
                print(f"[*] Custom Keep-Alive 옵션 적용 실패(무시):", e)
            print(f"[*] Connected to TCP Server: {server_ip} : {server_port}")

            # ping 송신 스레드가 중복 없이 반드시 새로 시작되도록 보장
            _ping_thread_running = False  # 재접속 시 항상 False로
            if not _ping_thread_running:
                _thread.start_new_thread(_ping_sender, ())
                _ping_thread_running = True

        except Exception as e:
            print(f"[-] Unexpected Error: {e}")
            sys.print_exception(e)
            is_initialized = False
            if tcpSocket:
                try:
                    tcpSocket.close()
                except:
                    pass
                tcpSocket = None

    except Exception as e:
        print(f"[-] Initialization Error: {str(e)}")
        is_initialized = False
        try:
            if tcpSocket:
                tcpSocket.close()
        except:
            pass
        tcpSocket = None



def start_ping_sender():
    global _ping_thread, _ping_thread_running
    if _ping_thread_running:
        return
    _ping_thread_running = True
    try:
        # MicroPython은 daemon 개념이 없고, 함수가 끝나면 스레드가 종료됩니다.
        _ping_thread = _thread.start_new_thread(_ping_sender, ())
    except Exception:
        # 스레드 시작 실패 시 플래그 롤백
        _ping_thread_running = False
        raise



def _ping_sender():
    global tcpSocket, is_initialized, _ping_thread_running
    try:
        while is_initialized and tcpSocket:
            try:
                with _socket_lock:
                    sock=tcpSocket
                if not sock:
                    break
                tcpSocket.sendall(b"ping\n")
                print("[*] Ping sent")
            except Exception as e:
                print(f"[Error] ping send failed: {e}")
                is_initialized = False
                try:
                    tcpSocket.close()
                except:
                    pass
                tcpSocket = None
                break
            time.sleep(2)
    except Exception as e:
        print(f"[Error] ping sender thread error: {e}")
        is_initialized = False
    finally:
        _ping_thread_running = False
        print("[*] _ping_sender thread terminated")

def read_from_socket():
    global tcpSocket, is_initialized
    if tcpSocket is None:
        is_initialized = False
        return None
    try:
        data = tcpSocket.recv(1024)
        if not data:
            # 실제로 연결이 닫힌 경우만!
            print("[*] Server closed connection (read 0 bytes)")
            is_initialized = False
            try:
                tcpSocket.close()
            except:
                pass
            tcpSocket = None
            return None
        return data
    except OSError as e:
        # 데이터 없음(논블로킹)일 때 연결 유지
        if hasattr(e, 'errno') and e.errno == 11:
            return None
        print(f"[Error] socket recv failed: {e}")
        is_initialized = False
        try:
            tcpSocket.close()
        except:
            pass
        tcpSocket = None
        return None
    except Exception as e:
        print(f"[Error] socket recv failed: {e}")
        is_initialized = False
        try:
            tcpSocket.close()
        except:
            pass
        tcpSocket = None
        return None

def sendMessage(msg: str):
    global tcpSocket, is_initialized
    try:
        if not is_initialized or tcpSocket is None:
            print("[클라이언트] sendMessage: Not initialized, message not sent.")
            return

        # 메시지 경계 보장: 끝의 개행류 제거 후 '\n' 하나만 부여
        if not isinstance(msg, str):
            msg = str(msg)
        wire = msg.rstrip('\r\n') + '\n'

        tcpSocket.sendall(wire.encode('utf-8'))
        print(f"[클라이언트] Message sent: {wire.rstrip()}")
    except Exception as e:
        print(f"[클라이언트] Send Error: {str(e)}")
        is_initialized = False
        if tcpSocket:
            try:
                tcpSocket.close()
            except:
                pass
            tcpSocket = None

def close_connection():
    global tcpSocket, is_initialized, _ping_thread_running
    if tcpSocket:
        try:
            tcpSocket.close()
        except:
            pass
        tcpSocket = None
    is_initialized = False
    _ping_thread_running = False
    print("[*] 서버 연결 종료")
