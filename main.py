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
        self.gpioIn_PusherDown = Pin(0, Pin.IN, Pin.PULL_UP)
        self.gpioIn_PusherUp = Pin(1, Pin.IN, Pin.PULL_UP)
        self.gpioIn_PusherBack = Pin(2, Pin.IN, Pin.PULL_UP)
        self.gpioIn_PusherFront = Pin(3, Pin.IN, Pin.PULL_UP)
        self.gpioIn_STOP = Pin(4, Pin.IN, Pin.PULL_UP)
        self.gpioIn_Start_R = Pin(5, Pin.IN, Pin.PULL_UP)
        self.gpioIn_Start_L = Pin(6, Pin.IN, Pin.PULL_UP)
        #end region

        print("Start_R:", self.gpioIn_Start_R.value(), "Start_L", self.gpioIn_Start_L.value())
        self.gpioIn_Start_R.value(1)
        self.gpioIn_Start_L.value(1)

        # Start 버튼 눌림 감지를 위한 시간 추적용 변수
        self.start_btn_hold_start_time = None
        self.mapping_start_sent = False
        self.MAPPING_START_HOLD_MS = 100


        # ipAddress = '192.168.1.105'
        # portNumber = 8005
        # gateway = '192.168.1.1'

        self.server_ip = server_ip
        self.server_port = server_port
        self.ipAddress = '192.168.1.105'
        self.portNumber = 8005
        self.gateway = '192.168.1.1'

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
        self.try_init_tcp()

    def try_init_tcp(self):
        try:
            TCPClient.init(ipAddress=self.ipAddress,
                           portNumber=self.portNumber,
                           server_ip= server_ip,
                           server_port=self.server_port,
                           gateway=self.gateway)
        except Exception as e:
            print(f"[-] Initialization Error: {str(e)}")



    def check_and_send_mapping_start(self):
        left = self.gpioIn_Start_L.value()
        right = self.gpioIn_Start_R.value()

        if left == 0 and right == 0:
            if self.start_btn_hold_start_time is None:
                self.start_btn_hold_start_time = time.ticks_ms()
                print("Both buttons pressed, timer started")
            elif not self.mapping_start_sent:
                held_ms = time.ticks_diff(time.ticks_ms(), self.start_btn_hold_start_time)
                print(f"Buttons held for {held_ms} ms")
                if held_ms >= self.MAPPING_START_HOLD_MS:
                    print("Sending message: Mapping start")
                    TCPClient.sendMessage('Mapping start\n')
                    print('[Mapping start] sent to server by Start_R + Start_L')
                    self.mapping_start_sent = True
        else:
            if self.start_btn_hold_start_time is not None:
                print(
                    f"Buttons released after holding {time.ticks_diff(time.ticks_ms(), self.start_btn_hold_start_time)} ms")
            self.start_btn_hold_start_time = None
            self.mapping_start_sent = False

    def func_10msec(self):
        #print("func_10msec called")
        # 버튼 지속 감지 및 메시지 전송
        self.check_and_send_mapping_start()
        time.sleep(0.01)

        message = TCPClient.read_from_socket()
        if message is not None:
            self.rxMessage = message.decode('utf-8')
            print(self.rxMessage, self.pusherStatus)

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

    def func_500msec(self):
        pass
        # self.sysLed_pico.toggle()

        # 아래 코드는 gpio High(0), low(1) 상태를 0.5초마다 프린트 해주는 테스트 코드임.
        # gpio_states = {
        #     "PusherDown": self.gpioIn_PusherDown.value(),
        #     "PusherUp": self.gpioIn_PusherUp.value(),
        #     "PusherBack": self.gpioIn_PusherBack.value(),
        #     "PusherFront": self.gpioIn_PusherFront.value(),
        #     "STOP": self.gpioIn_STOP.value(),
        #     "Start_R": self.gpioIn_Start_R.value(),
        #     "Start_L": self.gpioIn_Start_L.value(),
        # }
        # print("[GPIO Input States 500ms]", gpio_states)


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




# 안정적 재접속을 위해 Main loop를 수정함(7/7).
# Write card 함수는 변경하지 않았으므로 문제가 있으면 원복할 것.

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
        try:
            cnt_msec += 1

            # 항상 TCPClient 상태 확인, 끊어진 경우 즉시 재접속 시도
            if not TCPClient.is_initialized:
                conn_state = "DISCONNECTED"
                if reconnect_timer <= 0:
                    print("[*] Trying to reconnect to server...")
                    main.try_init_tcp()
                    if TCPClient.is_initialized:
                        print("[*] Reconnected to server")
                        conn_state = 'CONNECTED'
                        reconnect_timer = 0
                    else:
                        print("[*] Reconnect failed")
                        reconnect_timer = 100
                else:
                    reconnect_timer -= 1
            else:
                conn_state = 'CONNECTED'

            if not cnt_msec % 10:
                if TCPClient.is_initialized :
                    main.func_10msec()

            if not cnt_msec % 25:
                main.func_25msec()

            if not cnt_msec % 100:
                main.func_100msec()

            if not cnt_msec % 500:
                main.func_500msec()

            time.sleep_ms(1)
        except KeyboardInterrupt:
            print("KeyboardInterrupt: cleaning up TCP...")
            TCPClient.close_connection()
            break
        except Exception as e:
            print("Exception in main loop", e)
            import sys
            sys.print_exception(e)
            # sys.exit()