# 이 코드는 Pusher 동작 IO보드용 클라이언트 UDP 통신 모듈임. (TCP -> UDP 전환)
import _thread
from machine import Pin, SPI
import network
import socket
import time
import sys

tcpSocket = None  # 기존 변수명 유지(외부 영향 최소화). 실제로는 UDP 소켓.
is_initialized = False
_ping_thread_running = False
_ping_thread = None
_socket_lock = _thread.allocate_lock()

_server_ip = None
_server_port = None

def init(ipAddress: str, portNumber: int, gateway: str, server_ip: str, server_port: int):
    print("==> TCPClient.init() called (UDP mode)")
    global tcpSocket, is_initialized, _ping_thread_running, _server_ip, _server_port

    _server_ip = server_ip
    _server_port = server_port

    try:
        # 기존 소켓 정리
        if tcpSocket:
            try:
                tcpSocket.close()
            except:
                pass
            tcpSocket = None
        is_initialized = False
        _ping_thread_running = False

        spi = SPI(0, 500_000, polarity=0, phase=0, mosi=Pin(19), miso=Pin(16), sck=Pin(18))
        eth = network.WIZNET5K(spi, Pin(17), Pin(20))
        eth.active(True)

        # 주의: ifconfig 인자 순서는 (ip, subnet, gateway, dns) 구현에 따라 다를 수 있음. 기존 코드 유지
        eth.ifconfig((ipAddress, '255.255.255.0', '8.8.8.8', gateway))
        print("[*] Network Config:", eth.ifconfig())
        print(f"[*] Attempting UDP setup to... {server_ip}:{server_port}")

        try:
            # UDP 소켓 생성
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # 필요 시 로컬 바인드(원래는 주석이었지만, UDP는 소스 포트 고정이 유용)
            # 포트 번호가 유효하게 들어온 경우에만 바인드
            try:
                if portNumber and portNumber > 0:
                    s.bind((ipAddress, portNumber))
            except Exception as e:
                print(f"[*] UDP bind skipped/failed (non-fatal): {e}")

            # connect를 사용해 기본 목적지 설정(이후 send/recv 사용 가능)
            # UDP의 connect는 실제 네트워크 연결을 만들지 않고 목적지만 설정
            s.connect((server_ip, server_port))

            # 논블로킹
            s.setblocking(False)

            tcpSocket = s
            is_initialized = True

            print(f"[*] Ready for UDP to Server: {server_ip} : {server_port}")


        except Exception as e:
            print(f"[-] Unexpected Error (UDP init): {e}")
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

def read_from_socket():
    global tcpSocket, is_initialized
    if tcpSocket is None:
        is_initialized = False
        return None
    try:
        # UDP에서도 connect 되어 있으면 recv 사용 가능(피어 이외는 수신되지 않음)
        data = tcpSocket.recv(1024)
        if not data:
            # UDP에서 빈 페이로드 datagram은 드묾. 일관성을 위해 연결 종료 처리 유지.
            print("[*] Server sent empty datagram (treated as closed)")
            is_initialized = False
            try:
                tcpSocket.close()
            except:
                pass
            tcpSocket = None
            return None
        return data
    except OSError as e:
        # 논블로킹에서 데이터 없음
        if hasattr(e, 'errno') and e.errno == 11:
            return None
        print(f"[Error] socket recv failed (UDP): {e}")
        is_initialized = False
        try:
            tcpSocket.close()
        except:
            pass
        tcpSocket = None
        return None
    except Exception as e:
        print(f"[Error] socket recv failed (UDP): {e}")
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

        # UDP 전송: send 사용(플랫폼에 따라 sendall 미구현)
        tcpSocket.send(wire.encode('utf-8'))
        print(f"[클라이언트] Message sent (UDP): {wire.rstrip()}")
    except Exception as e:
        print(f"[클라이언트] Send Error (UDP): {str(e)}")
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
    print("[*] 서버 연결 종료 (UDP)")
