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
            tcpSocket.bind((ipAddress, portNumber))
            tcpSocket.connect((server_ip, server_port))
            tcpSocket.setblocking(False)
            is_initialized = True
            tcpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                tcpSocket.setsockopt(socket.IPPROTO_TCP, 0x3, 30)       # TCP_KEEPIDEL 30초
                tcpSocket.setsockopt(socket.IPPROTO_TCP, 0x4, 10)       # TCP_KEEPINTVL 10초
                tcpSocket.setsockopt(socket.IPPROTO_TCP, 0x5, 3)        # TCP_KEEPCNT 3회
            except Exception as e:
                print(f"[*] Custom Keep-Alive 옵션 적용 실패(무시):", e)
            print(f"[*] Connected to TCP Server: {server_ip} : {server_port}")

            # ping 송신 스레드가 중복 없이 반드시 새로 시작되도록 보장
            #_ping_thread_running = False  # 재접속 시 항상 False로
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
                try:
                    tcpSocket.close()
                except:
                    pass
                tcpSocket = None
                break
            time.sleep(1)
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
        # 논블로킹 소켓에서 데이터가 없을 때는 연결 끊지 않음
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
        tcpSocket.sendall(msg.encode('utf-8'))
        print(f"[클라이언트] Message sent: {msg}")
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