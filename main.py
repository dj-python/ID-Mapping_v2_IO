# H/W 제어 (실린더, 시그널 타워, 스위치 등등)

from machine import Pin, I2C
import time
import TCPClient

class PusherStatus:
    UNKNOWN = 1
    READY = 2
    DOING = 3
    ERROR = 4

class PusherError:
    NONE = 'ERROR_NONE'
    PUSHER_BACK = 'ERROR_PUSHER_BACK'
    PUSHER_FRONT = 'ERROR_PUSHER_FRONT'
    PUSHER_UP = 'ERROR_PUSHER_UP'
    PUSHER_DOWN = 'ERROR_PUSHER_DOWN'
    INIT_PUSHER_POS = 'ERROR_PUSHER_INITIAL'
    LOAD_UNLOAD = 'ERROR_LOAD_UNLOAD'

class MainPusher:
    cTemp = 0

    def __init__(self, server_ip, server_port):
        self.idxExecProcess_load = None
        self.idxExecProcess_Unload = False
        self.isExecProcess_load = False
        self.isExecProcess_Unload = False
        self.sysLed_pico = Pin(25, Pin.OUT)

        #region Init GPIO_OUT
        self.gpioOut_pusherDown = Pin(10, Pin.OUT)
        self.gpioOut_pusherUp = Pin(11, Pin.OUT)
        self.gpioOut_pusherBack = Pin(14, Pin.OUT)
        self.gpioOut_pusherFront = Pin(15, Pin.OUT)
        #end region

        #region Init GPIO_IN
        self.gpioIn_PusherDown = Pin(0, Pin.IN)
        self.gpioIn_PusherUp = Pin(1, Pin.IN)
        self.gpioIn_PusherBack = Pin(2, Pin.IN)
        self.gpioIn_PusherFront = Pin(3, Pin.IN)
        self.gpioIn_STOP = Pin(4, Pin.IN)
        self.gpioIn_Start_R = Pin(5, Pin.IN)
        self.gpioIn_Start_L = Pin(6, Pin.IN)
        #end region

        # Start 버튼 눌림 감지를 위한 시간 추적용 변수
        self.start_btn_hold_start_time = None
        self.mapping_start_sent = False
        self.MAPPING_START_HOLD_MS = 500


        ipAddress = '192.168.1.105'
        portNumber = 8005
        gateway = '192.168.1.1'

        try:
            TCPClient.init(ipAddress=ipAddress, portNumber=portNumber, server_ip= server_ip, server_port=server_port, gateway=gateway)
        except Exception as e:
            print(f"[-] Initialization Error: {str(e)}")

        self.rxMessage = str()

        self.cntExecProcess = 0
        self.cntTimeOutExecProcess = 0

        self.isExecProcess_manualHandle = False
        self.idxExecProcess_unit0p = 0

        self.pusherStatus = PusherStatus.UNKNOWN
        self.pusherError = PusherError.NONE

        self.isInitedSocket = False
        self.isExecProcess_initPusherPos = False
        self.idxExecProcess_initPusherPos = 0

        self.isInitedPusher = None

    # Push button 2개가 0.5초 동안 눌린 상태이면 main PC 에 신호 보내는 코드
    def check_and_send_mapping_start(self):
        # 두 버튼이 모두 눌린 상태(False)여야만 동작
        if not self.gpioIn_Start_L and not self.gpioIn_Start_R:
            if self.start_btn_hold_start_time is None:
                self.start_btn_hold_start_time = time.ticks_ms()
            elif not self.mapping_start_sent:
                held_ms = time.ticks_diff(time.ticks_ms(), self.start_btn_hold_start_time)
                if held_ms >= self.MAPPING_START_HOLD_MS:
                    TCPClient.sendMessage('Mapping start')
                    print('[Mapping start] sent to server by Start_R + Start_L')
                    self.mapping_start_sent = True
        else:
            self.start_btn_hold_start_time = None
            self.mapping_start_sent = False


    def func_10msec(self):
        # 버튼 지속 감지 및 메시지 전송
        self.check_and_send_mapping_start()

        message, address = TCPClient.receive_data()
        if message is not None:
            self.rxMessage = message.decode('utf-8')
            print(address, self.rxMessage, self.pusherStatus)

            # Init Pusher
            if self.rxMessage == 'initial_pusher':
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_initPusherPos = 0
                self.pusherStatus = PusherStatus.DOING
                self.isExecProcess_initPusherPos = True
            # Reset Pusher
            elif self.rxMessage == 'Reset':
                if self.isInitedPusher:
                    self.pusherStatus = PusherStatus.READY
                    self.pusherError = PusherError.NONE
                    self.replyMessage('Reset finished')
                else:
                    self.replyMessage('Reset failed')

            elif self.rxMessage == 'Start':
                if self.pusherStatus is PusherStatus.READY:
                    self.idxExecProcess_load = 0
                    self.isExecProcess_load = True
                    # unit operation
                else:
                    self.idxExecProcess_unit0p = 0
                    self.isExecProcess_manualHandle = True
                self.cntTimeOutExecProcess = 0
                self.pusherStatus = PusherStatus.DOING

            elif self.rxMessage == 'Finish':
                if self.pusherStatus is PusherStatus.READY:
                    self.idxExecProcess_Unload = 0
                    self.isExecProcess_Unload = True
                self.cntTimeOutExecProcess = 0
                self.pusherStatus = PusherStatus.DOING


    def func_25msec(self):
        if self.isExecProcess_initPusherPos:
            self.execProcess_setPusherPos()

    # 검사 시작(load), 검사 종료(unload), 수동 제어
    def func_100msec(self):
        if self.isExecProcess_load:
            self.execProcess_load()
        elif self.isExecProcess_Unload:
            self.execProcess_Unload()
        elif self.isExecProcess_manualHandle:
            self.execProcess_manualHandle()

    def execProcess_setPusherPos(self):
        if self.idxExecProcess_initPusherPos == 0:                          # Pusher up
            self.gpioOut_pusherUp(True)
            self.gpioOut_pusherDown(False)
            self.idxExecProcess_initPusherPos += 1
        elif self.idxExecProcess_initPusherPos == 1:
            self.pusherError = PusherError.PUSHER_UP                        # Pusher up 확인
            if self.gpioIn_PusherUp:
                self.cntExecProcess = 0
                self.idxExecProcess_initPusherPos += 1
        elif self.idxExecProcess_initPusherPos == 2:                        # 125msec 대기
            self.cntExecProcess += 1
            if self.cntExecProcess >= 5:                                    # Pusher Back
                self.gpioOut_pusherBack(True)
                self.gpioOut_pusherFront(False)
                self.idxExecProcess_initPusherPos += 1
        elif self.idxExecProcess_initPusherPos == 3:                        # Pusher Back 확인
            self.pusherError = PusherError.PUSHER_BACK
            if self.gpioIn_PusherBack :
                self.pusherError = PusherError.NONE
                self.pusherStatus = PusherStatus.READY
                self.isInitedPusher = True                                  # 초기화 완료 처리
                self.replyMessage('S' + self.rxMessage[1:5] + '000')        # Init 완료 송신

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 400 :                              # 8초 경과시 에러
            errorCode = self.checkErrorCode()

            self.isExecProcess_initPusherPos = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.INIT_PUSHER_POS
            self.isInitedPusher = False
            self.replyMessage('S' + self.rxMessage[1:5] + errorCode)


    def temp_test(self):
        pass




    def execProcess_load(self):
        if self.idxExecProcess_load == 0:                     # Pusher 초기상태 확인
            if not self.gpioIn_PusherUp and not self.gpioIn_PusherBack:
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_load += 1
            else:
                if self.gpioIn_PusherUp:
                    self.pusherError = PusherError.PUSHER_UP
                elif self.gpioIn_PusherBack:
                    self.pusherError = PusherError.PUSHER_BACK
        if self.idxExecProcess_load == 1:                     # Pusher 전진 동작
            self.gpioOut_pusherFront(True)
            self.gpioOut_pusherBack(False)
            self.idxExecProcess_load += 1
        elif self.idxExecProcess_load == 2:                   # Pusher 전진 확인
            self.pusherError = PusherError.PUSHER_FRONT
            if not self.gpioIn_PusherFront:
                self.cntTimeOutExecProcess = 0
                self.cntExecProcess = 0
                self.idxExecProcess_load += 1
        elif self.idxExecProcess_load == 3:                   # delay 500ms 부여 구간
            self.cntExecProcess += 1
            if self.cntExecProcess >= 5:
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_load += 1
        elif self.idxExecProcess_load ==4:                   # Pusher 하강 동작
            self.gpioOut_pusherUp(False)
            self.gpioOut_pusherDown(True)
            self.cntExecProcess = 0
            self.idxExecProcess_load += 1
        elif self.idxExecProcess_load == 5:                   # Pusher 하강 확인
            self.pusherError = PusherError.PUSHER_DOWN
            if not self.gpioIn_PusherDown:
                self.isExecProcess_load = False
                self.pusherStatus = PusherStatus.READY
                self.pusherError = PusherError.NONE
                self.replyMessage('S' + self.rxMessage[1:5] + '000')

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 30:
            errorCode = self.checkErrorCode()

            self.isExecProcess_load = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.LOAD_UNLOAD
            self.replyMessage('Error' + errorCode)

    def execProcess_Unload(self):
        # unload (Pusher Back)
        if self.idxExecProcess_load == 0:                     # Pusher 상승
            self.gpioOut_pusherUp(True)
            self.gpioOut_pusherDown(False)
            self.idxExecProcess_load += 1
        elif self.idxExecProcess_load == 1:                   # Pusher 상승 확인
            self.pusherError = PusherError.PUSHER_UP
            if not self.gpioIn_PusherUp:
                self.cntTimeOutExecProcess = 0
                self.cntExecProcess = 0
                self.idxExecProcess_load += 1
        elif self.idxExecProcess_load == 2:                   # 대기 500msec
            self.cntExecProcess += 1
            if self.cntExecProcess >= 5:
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_load += 1
        elif self.idxExecProcess_load == 3:                   # Pusher 후진
            self.gpioOut_pusherFront(False)
            self.gpioOut_pusherBack(True)
            self.cntExecProcess = 0
            self.idxExecProcess_load += 1
        elif self.idxExecProcess_load == 4:                   # Pusher 후진 확인
            self.pusherError = PusherError.PUSHER_BACK
            if not self.gpioIn_PusherBack:
                self.idxExecProcess_load = False
                self.pusherStatus = PusherStatus.READY
                self.pusherError = PusherError.NONE
                self.replyMessage('S' + self.rxMessage[1:5] + '000')

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 30:
            errorCode = self.checkErrorCode()

            self.isExecProcess_Unload = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.LOAD_UNLOAD
            self.replyMessage('Error' + errorCode)



    def replyMessage(self, message):
        if self.rxMessage == 'Check_status':
            pass
        else:
            TCPClient.sendMessage(message)

    def checkErrorCode(self):
        errorCode = '001'

        if self.pusherError == PusherError.PUSHER_FRONT:
            errorCode = '010'
        elif self.pusherError == PusherError.PUSHER_BACK:
            errorCode = '011'
        elif self.pusherError == PusherError.PUSHER_UP:
            errorCode = '012'
        elif self.pusherError == PusherError.PUSHER_DOWN:
            errorCode = '013'
        elif self.pusherError == PusherError.INIT_PUSHER_POS:
            errorCode = '014'
        elif self.pusherError == PusherError.LOAD_UNLOAD:
            errorCode = '015'
        return errorCode

    def execProcess_manualHandle(self):
        pass

if __name__ == "__main__":
    cnt_msec = 0

    ipAddress = '192.168.1.105'
    portNumber = 8005
    gateway = '192.168.1.1'
    server_ip = '192.168.1.2'
    server_port = 8000

    main = MainPusher(server_ip=server_ip, server_port=server_port)

    # 상태머신 구조
    # 상태 : "DISCONNECTED", "CONNECTED"
    conn_state = "CONNECTED" if TCPClient.is_initialized else "DISCONNECTED"



    reconnect_timer = 0

    while True:
        cnt_msec += 1

        # 연결이 끊어진 경우에만 재접속 시도
        if conn_state == "DISCONNECTED":
            if reconnect_timer <= 0:
                print("[*] Trying to reconnect to server...")
                try:
                    TCPClient.init(ipAddress=ipAddress, portNumber=portNumber, gateway=gateway, server_ip=server_ip, server_port=server_port)
                    if TCPClient.is_initialized:
                        print("[*] Reconnected to server")
                        conn_state = 'CONNECTED'
                    else:
                        print("[*] Reconnect failed")
                except Exception as e:
                    print(f"[-] Reconnect error: {e}")
                reconnect_timer = 3000
            else:
                reconnect_timer -= 1

        elif conn_state == "CONNECTED":

            #연결된 상태에서 연결이 끊어졌는지 체크
            if not TCPClient.is_initialized:
                print("[-] Lost connection to server")
                conn_state = 'DISCONNECTED'

        if not cnt_msec % 10:
            if TCPClient.is_initialized :
                main.func_10msec()

        if not cnt_msec % 25:
            main.func_25msec()



        if not cnt_msec % 100:
            main.func_100msec()


        time.sleep_ms(1)