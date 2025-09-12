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

# 극성 설정: 하드웨어가 Active-Low라면 True (출력 On=0, 입력 감지=0)
ACTIVE_LOW_IN = True
ACTIVE_LOW_OUT = True

class MainPusher:
    cTemp = 0

    def __init__(self, server_ip, server_port):
        self.idxExecProcess_load = None
        self.idxExecProcess_Unload = 0
        self.isExecProcess_load = False
        self.isExecProcess_Unload = False
        self.sysLed_pico = Pin(25, Pin.OUT)

        #region Init GPIO_OUT
        # 주의: 아래 GPIO 번호는 Pico의 GP 번호입니다. 보드 물리 핀 번호와 다릅니다.
        self.gpioOut_pusherDown = Pin(10, Pin.OUT)  # GP10
        self.gpioOut_pusherUp = Pin(11, Pin.OUT)    # GP11
        self.gpioOut_pusherBack = Pin(14, Pin.OUT)  # GP14
        self.gpioOut_pusherFront = Pin(15, Pin.OUT) # GP15
        #end region

        #region Init GPIO_IN (풀업: 일반적으로 Active-Low)
        self.gpioIn_PusherDown = Pin(0, Pin.IN, Pin.PULL_UP)    # GP0
        self.gpioIn_PusherUp = Pin(1, Pin.IN, Pin.PULL_UP)      # GP1
        self.gpioIn_PusherBack = Pin(2, Pin.IN, Pin.PULL_UP)    # GP2
        self.gpioIn_PusherFront = Pin(3, Pin.IN, Pin.PULL_UP)   # GP3
        self.gpioIn_STOP = Pin(4, Pin.IN, Pin.PULL_UP)          # GP4
        self.gpioIn_Start_R = Pin(5, Pin.IN, Pin.PULL_UP)       # GP5
        self.gpioIn_Start_L = Pin(6, Pin.IN, Pin.PULL_UP)       # GP6
        #end region

        print("Start_R:", self.gpioIn_Start_R.value(), "Start_L", self.gpioIn_Start_L.value())

        # Start 버튼 눌림 감지를 위한 시간 추적용 변수
        self.start_btn_hold_start_time = None
        self.mapping_start_sent = False
        self.MAPPING_START_HOLD_MS = 100

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

        self.isExecProcess_initPusherPos = False
        self.idxExecProcess_initPusherPos = 0

        self.isInitedPusher = None
        self.try_init_tcp()
        self.init_gpioOut()

    def init_gpioOut(self):
        # 부팅 시 모든 출력 OFF(안전)
        self.set_out(self.gpioOut_pusherFront, False)
        self.set_out(self.gpioOut_pusherBack, True)
        self.set_out(self.gpioOut_pusherUp, True)
        self.set_out(self.gpioOut_pusherDown, False)
        print(f"[init_gpioOut] Front={self.gpioOut_pusherFront.value()} Back={self.gpioOut_pusherBack.value()} Up={self.gpioOut_pusherUp.value()} Down={self.gpioOut_pusherDown.value()} (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")

    # 출력/입력 헬퍼
    def set_out(self, pin: Pin, on: bool):
        # Active-Low 출력이면 on=True일 때 0을 출력
        if ACTIVE_LOW_OUT:
            pin.value(0 if on else 1)
        else:
            pin.value(1 if on else 0)

    def in_active(self, pin: Pin) -> bool:
        v = pin.value()
        return (v == 0) if ACTIVE_LOW_IN else (v == 1)

    def try_init_tcp(self):
        try:
            TCPClient.init(
                ipAddress=self.ipAddress,
                portNumber=self.portNumber,
                server_ip=self.server_ip,
                server_port=self.server_port,
                gateway=self.gateway
            )
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
                print(f"Buttons released after holding {time.ticks_diff(time.ticks_ms(), self.start_btn_hold_start_time)} ms")
            self.start_btn_hold_start_time = None
            self.mapping_start_sent = False

    def func_10msec(self):
        self.check_and_send_mapping_start()

        message = TCPClient.read_from_socket()
        if message is not None:
            self.rxMessage = message.decode('utf-8').strip()
            print("[RX]", self.rxMessage, "status:", self.pusherStatus)

            if self.rxMessage == 'initial_pusher':
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_initPusherPos = 0
                self.pusherStatus = PusherStatus.DOING
                self.isExecProcess_initPusherPos = True

            elif self.rxMessage == 'Reset':
                if self.isInitedPusher:
                    self.pusherStatus = PusherStatus.READY
                    self.pusherError = PusherError.NONE
                    self.replyMessage('Reset finished')
                else:
                    self.replyMessage('Reset failed')

            elif self.rxMessage == 'Start':
                if self.pusherStatus == PusherStatus.READY:
                    self.idxExecProcess_load = 0
                    self.isExecProcess_load = True
                    print("[Start] load started")
                else:
                    self.idxExecProcess_unit0p = 0
                    self.isExecProcess_manualHandle = True
                    print("[Start] manual handle started (not READY)")
                self.cntTimeOutExecProcess = 0
                self.pusherStatus = PusherStatus.DOING

            elif self.rxMessage == 'Finish':
                if self.pusherStatus == PusherStatus.READY:
                    self.idxExecProcess_Unload = 0
                    self.isExecProcess_Unload = True
                    print("[Finish] unload started")
                else:
                    print("[Finish] ignored (not READY)")
                self.cntTimeOutExecProcess = 0
                self.pusherStatus = PusherStatus.DOING

            elif self.rxMessage == 'Pusher front':
                print('rxMessage Pusher front received')
                self.idxExecProcess_load = 0
                self.isExecProcess_Unload = False
                self.isExecProcess_load = True
                print(f"[FORCE FRONT] Front={self.gpioOut_pusherFront.value()} Back={self.gpioOut_pusherBack.value()} (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")

            elif self.rxMessage == 'Pusher back':
                print('rxMessage Pusher back received')
                self.idxExecProcess_Unload = 0
                self.isExecProcess_load = False
                self.isExecProcess_Unload = True
                print(f"[FORCE BACK] Front={self.gpioOut_pusherFront.value()} Back={self.gpioOut_pusherBack.value()} (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")

            elif self.rxMessage.startswith('OUT '):
                # 수동 출력 테스트: 예) OUT front on / OUT back off / OUT up on / OUT down off
                try:
                    _, name, state = self.rxMessage.split()
                    on = (state.lower() == 'on')
                    if name == 'front':
                        self.set_out(self.gpioOut_pusherFront, on)
                    elif name == 'back':
                        self.set_out(self.gpioOut_pusherBack, on)
                    elif name == 'up':
                        self.set_out(self.gpioOut_pusherUp, on)
                    elif name == 'down':
                        self.set_out(self.gpioOut_pusherDown, on)
                    else:
                        print("[OUT] unknown name:", name)
                        return
                    print(f"[OUT] {name} set to {state}. raw={{'front':self.gpioOut_pusherFront.value(),'back':self.gpioOut_pusherBack.value(),'up':self.gpioOut_pusherUp.value(),'down':self.gpioOut_pusherDown.value()}}")
                except Exception as e:
                    print("[OUT] parse error:", e)

    def func_25msec(self):
        if self.isExecProcess_initPusherPos:
            self.execProcess_setPusherPos()

    def func_100msec(self):
        # 상태머신 디버그
        # try:
        #     print(f"[100ms] flags load={self.isExecProcess_load}, unload={self.isExecProcess_Unload}, manual={self.isExecProcess_manualHandle} | idx_load={self.idxExecProcess_load}, idx_unload={self.idxExecProcess_Unload}, status={self.pusherStatus}")
        # except Exception as e:
        #     print("[100ms] debug print error:", e)
        if self.isExecProcess_load:
            self.execProcess_load()
        elif self.isExecProcess_Unload:
            self.execProcess_Unload()
        elif self.isExecProcess_manualHandle:
            self.execProcess_manualHandle()

    def func_500msec(self):
        # 입출력 상태 주기 출력(진단용)
        inputs = {
            "Down": self.gpioIn_PusherDown.value(),
            "Up": self.gpioIn_PusherUp.value(),
            "Back": self.gpioIn_PusherBack.value(),
            "Front": self.gpioIn_PusherFront.value(),
            "STOP": self.gpioIn_STOP.value(),
            "Start_R": self.gpioIn_Start_R.value(),
            "Start_L": self.gpioIn_Start_L.value(),
        }
        outputs = {
            "OutFront": self.gpioOut_pusherFront.value(),
            "OutBack": self.gpioOut_pusherBack.value(),
            "OutUp": self.gpioOut_pusherUp.value(),
            "OutDown": self.gpioOut_pusherDown.value(),
        }
        print("[IO] IN", inputs, "| OUT", outputs, f"(ACTIVE_LOW_IN={ACTIVE_LOW_IN}, ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")

    def execProcess_setPusherPos(self):
        # 초기 위치 설정
        if self.idxExecProcess_initPusherPos == 0:                          # Pusher up
            self.set_out(self.gpioOut_pusherUp, True)
            self.set_out(self.gpioOut_pusherDown, False)
            self.idxExecProcess_initPusherPos += 1

        elif self.idxExecProcess_initPusherPos == 1:                        # Pusher up 확인
            self.pusherError = PusherError.PUSHER_UP
            if self.in_active(self.gpioIn_PusherUp):
                self.cntExecProcess = 0
                self.idxExecProcess_initPusherPos += 1

        elif self.idxExecProcess_initPusherPos == 2:                        # 125msec 대기
            self.cntExecProcess += 1
            if self.cntExecProcess >= 5:                                    # Pusher Back
                self.set_out(self.gpioOut_pusherBack, True)
                self.set_out(self.gpioOut_pusherFront, False)
                self.idxExecProcess_initPusherPos += 1

        elif self.idxExecProcess_initPusherPos == 3:                        # Pusher Back 확인
            self.pusherError = PusherError.PUSHER_BACK
            if self.in_active(self.gpioIn_PusherBack):
                self.pusherError = PusherError.NONE
                self.pusherStatus = PusherStatus.READY
                self.isInitedPusher = True
                self.isExecProcess_initPusherPos = False
                self.replyMessage('S' + self.rxMessage[1:5] + '000')

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 400:                               # 8초 타임아웃
            errorCode = self.checkErrorCode()
            self.isExecProcess_initPusherPos = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.INIT_PUSHER_POS
            self.isInitedPusher = False
            self.replyMessage('S' + self.rxMessage[1:5] + errorCode)

    def execProcess_load(self):
        print('execProcess_load started')

        if self.idxExecProcess_load == 0:                     # 초기상태 확인 (Up, Back 감지되어야)
            if self.in_active(self.gpioIn_PusherUp) and self.in_active(self.gpioIn_PusherBack):
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_load += 1
            else:
                if not self.in_active(self.gpioIn_PusherUp):
                    self.pusherError = PusherError.PUSHER_UP
                elif not self.in_active(self.gpioIn_PusherBack):
                    self.pusherError = PusherError.PUSHER_BACK
                return

        if self.idxExecProcess_load == 1:                     # Pusher 전진 동작
            self.set_out(self.gpioOut_pusherFront, True)
            self.set_out(self.gpioOut_pusherBack, False)
            print(f"[load idx1] OUT Front=ON, Back=OFF (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
            print(f"[load idx1] OUT raw levels Front={self.gpioOut_pusherFront.value()}, Back={self.gpioOut_pusherBack.value()}")
            self.idxExecProcess_load += 1

        elif self.idxExecProcess_load == 2:                   # Pusher 전진 확인
            self.pusherError = PusherError.PUSHER_FRONT
            fv = self.gpioIn_PusherFront.value()
            print(f"[load idx2] Front sensor raw={fv} (active={'0' if ACTIVE_LOW_IN else '1'})")
            if self.in_active(self.gpioIn_PusherFront):
                self.cntTimeOutExecProcess = 0
                self.cntExecProcess = 0
                self.idxExecProcess_load += 1

        elif self.idxExecProcess_load == 3:                   # delay 500ms (100ms * 5)
            self.cntExecProcess += 1
            if self.cntExecProcess >= 5:
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_load += 1

        elif self.idxExecProcess_load == 4:                   # Pusher 하강
            self.set_out(self.gpioOut_pusherUp, False)
            self.set_out(self.gpioOut_pusherDown, True)
            print(f"[load idx4] OUT Up=OFF, Down=ON (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
            self.cntExecProcess = 0
            self.idxExecProcess_load += 1

        elif self.idxExecProcess_load == 5:                   # Pusher 하강 확인
            self.pusherError = PusherError.PUSHER_DOWN
            dv = self.gpioIn_PusherDown.value()
            print(f"[load idx5] Down sensor raw={dv} (active={'0' if ACTIVE_LOW_IN else '1'})")
            if self.in_active(self.gpioIn_PusherDown):
                self.isExecProcess_load = False
                self.pusherStatus = PusherStatus.READY
                self.pusherError = PusherError.NONE
                self.replyMessage('S' + self.rxMessage[1:5] + '000')

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 30:                  # 3초 타임아웃
            errorCode = self.checkErrorCode()
            self.isExecProcess_load = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.LOAD_UNLOAD
            self.replyMessage('Error' + errorCode)

    def execProcess_Unload(self):
        # unload (Pusher Back)
        if self.idxExecProcess_Unload == 0:                   # Pusher 상승
            self.set_out(self.gpioOut_pusherUp, True)
            self.set_out(self.gpioOut_pusherDown, False)
            print(f"[unload idx0] OUT Up=ON, Down=OFF (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
            self.idxExecProcess_Unload += 1

        elif self.idxExecProcess_Unload == 1:                 # Pusher 상승 확인
            self.pusherError = PusherError.PUSHER_UP
            uv = self.gpioIn_PusherUp.value()
            print(f"[unload idx1] Up sensor raw={uv} (active={'0' if ACTIVE_LOW_IN else '1'})")
            if self.in_active(self.gpioIn_PusherUp):
                self.cntTimeOutExecProcess = 0
                self.cntExecProcess = 0
                self.idxExecProcess_Unload += 1

        elif self.idxExecProcess_Unload == 2:                 # 대기 500msec
            self.cntExecProcess += 1
            if self.cntExecProcess >= 5:
                self.cntTimeOutExecProcess = 0
                self.idxExecProcess_Unload += 1

        elif self.idxExecProcess_Unload == 3:                 # Pusher 후진
            self.set_out(self.gpioOut_pusherFront, False)
            self.set_out(self.gpioOut_pusherBack, True)
            print(f"[unload idx3] OUT Front=OFF, Back=ON (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
            self.cntExecProcess = 0
            self.idxExecProcess_Unload += 1

        elif self.idxExecProcess_Unload == 4:                 # Pusher 후진 확인
            self.pusherError = PusherError.PUSHER_BACK
            bv = self.gpioIn_PusherBack.value()
            print(f"[unload idx4] Back sensor raw={bv} (active={'0' if ACTIVE_LOW_IN else '1'})")
            if self.in_active(self.gpioIn_PusherBack):
                self.isExecProcess_Unload = False
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

        conn_state = "CONNECTED" if TCPClient.is_initialized else "DISCONNECTED"
        reconnect_timer = 0

        while True:
            try:
                cnt_msec += 1

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
                    if TCPClient.is_initialized:
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
