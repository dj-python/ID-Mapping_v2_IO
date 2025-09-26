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
        self.gpioOut_pusherDown = Pin(10, Pin.OUT)  # GP10
        self.gpioOut_pusherUp = Pin(11, Pin.OUT)    # GP11
        self.gpioOut_pusherBack = Pin(14, Pin.OUT)  # GP14
        self.gpioOut_pusherFront = Pin(15, Pin.OUT) # GP15
        #end region

        #region Init GPIO_IN (풀업: 일반적으로 Active-Low)
        self.gpioIn0 = Pin(0, Pin.IN, Pin.PULL_UP)    # GP0
        self.gpioIn1 = Pin(1, Pin.IN, Pin.PULL_UP)      # GP1
        self.gpioIn2 = Pin(2, Pin.IN, Pin.PULL_UP)    # GP2
        self.gpioIn3 = Pin(3, Pin.IN, Pin.PULL_UP)   # GP3
        self.gpioIn_STOP = Pin(4, Pin.IN, Pin.PULL_UP)          # GP4
        self.gpioIn_Start_R = Pin(5, Pin.IN, Pin.PULL_UP)       # GP5
        self.gpioIn_Start_L = Pin(6, Pin.IN, Pin.PULL_UP)       # GP6
        #end region

        self.gpioIn_PusherDown = None
        self.gpioIn_PusherUp = None
        self.gpioIn_PusherBack = None
        self.gpioIn_PusherFront = None

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

        self.idxExecProcess_unit0p = 0
        self.isExecProcess_unit0p = False

        self.pusherStatus = PusherStatus.UNKNOWN
        self.pusherError = PusherError.NONE

        self.isExecProcess_initPusherPos = False
        self.idxExecProcess_initPusherPos = 0

        # ADD: 중단/복귀 상태머신용 플래그/카운터
        self.isExecProcess_returnToInit = False
        self.idxExecProcess_returnToInit = 0
        self.cntReturn = 0
        self.cntReturnTimeout = 0
        self.abort_reason = None

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

    def get_gpioIn(self):
        # 센서 활성 여부를 bool로 저장
        self.gpioIn_PusherDown = self.in_active(self.gpioIn0)
        self.gpioIn_PusherUp = self.in_active(self.gpioIn1)
        self.gpioIn_PusherBack = self.in_active(self.gpioIn2)
        self.gpioIn_PusherFront = self.in_active(self.gpioIn3)

    # def get_gpioIn(self):
    #     self.gpioIn_PusherDown = not self.gpioIn0.value()
    #     self.gpioIn_PusherUp = not self.gpioIn1.value()
    #     self.gpioIn_PusherBack = not self.gpioIn2.value()
    #     self.gpioIn_PusherFront = not self.gpioIn3.value()

    # 출력/입력 헬퍼
    def set_out(self, pin: Pin, on: bool):
        # Active-Low 출력이면 on=True일 때 0을 출력
        if ACTIVE_LOW_OUT:
            pin.value(0 if on else 1)
        else:
            pin.value(1 if on else 0)

    def in_active(self, pin) -> bool:
        """
        입력이 '활성(True)'인지 반환.
        - pin이 machine.Pin이면 raw 레벨을 읽어서 ACTIVE_LOW_IN 규칙 적용
        - pin이 bool이면 이미 활성 여부이므로 그대로 반환
        - pin이 int(0/1)이면 ACTIVE_LOW_IN 규칙 적용
        """
        if hasattr(pin, 'value'):
            v = pin.value()
            return (v == 0) if ACTIVE_LOW_IN else (v == 1)

        if isinstance(pin, bool):
            return pin

        if isinstance(pin, int):
            return (pin == 0) if ACTIVE_LOW_IN else (pin == 1)

        raise TypeError("in_active expected Pin, bool, or int")

    def raw_in_level(self, pin) -> int:
        """
        디버그 출력용으로 raw 전기 레벨(0 또는 1)을 반환.
        pin이 bool(활성 여부)이어도 raw로 환산해서 반환.
        """
        if hasattr(pin, 'value'):
            return pin.value()
        if isinstance(pin, bool):
            # ACTIVE_LOW_IN일 때 True(활성) => raw 0, False => raw 1
            # ACTIVE_LOW_IN이 False면 True(활성) => raw 1, False => raw 0
            return (0 if pin else 1) if ACTIVE_LOW_IN else (1 if pin else 0)
        if isinstance(pin, int):
            return 1 if pin else 0
        raise TypeError("raw_in_level expected Pin, bool, or int")



    # def in_active(self, pin: Pin) -> bool:
    #     v = pin.value()
    #     return (v == 0) if ACTIVE_LOW_IN else (v == 1)

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
        # Read current raw levels
        left_val = self.gpioIn_Start_L.value()
        right_val = self.gpioIn_Start_R.value()

        # Determine pressed state considering Active-Low inputs
        def is_pressed(v):
            return v == 0 if ACTIVE_LOW_IN else v == 1

        left_pressed = is_pressed(left_val)
        right_pressed = is_pressed(right_val)
        both_pressed = left_pressed and right_pressed

        # Lazy init of edge tracking vars
        if not hasattr(self, 'both_pressed_prev'):
            self.both_pressed_prev = both_pressed
        if not hasattr(self, 'mapping_start_sent'):
            self.mapping_start_sent = False

        # Rising edge: both become pressed now (from not-both-pressed)
        if both_pressed and not self.both_pressed_prev:
            TCPClient.sendMessage('Mapping start\n')
            print('[Mapping start] sent to server (Start_R + Start_L pressed simultaneously)')
            self.mapping_start_sent = True

        # Falling edge: leaving both-pressed state → at least one button released
        if (not both_pressed) and self.both_pressed_prev:
            if self.mapping_start_sent:
                TCPClient.sendMessage('Button unpushed\n')
                print('[Button unpushed] sent to server (one or both buttons released)')
            # Reset for next cycle
            self.mapping_start_sent = False

        # Update previous state
        self.both_pressed_prev = both_pressed

    #
    #
    # def check_and_send_mapping_start(self):
    #     left = self.gpioIn_Start_L.value()
    #     right = self.gpioIn_Start_R.value()
    #
    #     if left == 0 and right == 0:
    #         if self.start_btn_hold_start_time is None:
    #             self.start_btn_hold_start_time = time.ticks_ms()
    #             print("Both buttons pressed, timer started")
    #         elif not self.mapping_start_sent:
    #             held_ms = time.ticks_diff(time.ticks_ms(), self.start_btn_hold_start_time)
    #             print(f"Buttons held for {held_ms} ms")
    #             if held_ms >= self.MAPPING_START_HOLD_MS:
    #                 print("Sending message: Mapping start")
    #                 TCPClient.sendMessage('Mapping start\n')
    #                 print('[Mapping start] sent to server by Start_R + Start_L')
    #                 self.mapping_start_sent = True
    #     else:
    #         if self.start_btn_hold_start_time is not None:
    #             print(f"Buttons released after holding {time.ticks_diff(time.ticks_ms(), self.start_btn_hold_start_time)} ms")
    #         self.start_btn_hold_start_time = None
    #         self.mapping_start_sent = False

    def func_10msec(self):
        self.get_gpioIn()

        # ADD: 현지 비상정지 버튼(E-STOP) 감지 → 즉시 복귀 요청
        if self.in_active(self.gpioIn_STOP):
            if not self.isExecProcess_returnToInit:
                self.request_return_to_init('E-STOP')
                # 서버 통지(선택)
                TCPClient.sendMessage('EmergencyStop\n')
            # 비상 시에는 수신 명령 무시해도 됨(선택)
            # return

        self.check_and_send_mapping_start()

        message = TCPClient.read_from_socket()
        if message is not None:
            self.rxMessage = message.decode('utf-8').strip()
            print("[RX]", self.rxMessage, "status:", self.pusherStatus)

            # 2) 서버 복귀 명령: STOP 상태와 무관하게 즉시 복귀 상태머신으로 전환
            if self.rxMessage in ('go_init', 'ReturnInit'):
                if not self.isExecProcess_returnToInit:
                    self.request_return_to_init(f'server:{self.rxMessage}')
                    # 선택: 즉시 수신 확인 응답
                    TCPClient.sendMessage('ReturnInit Requested\n')
                else:
                    print('[go_init] already returning to init; ignoring duplicate')
                return  # 복귀 우선 처리

            # 3) 복귀 중이면 다른 명령 무시(권장)
            if self.isExecProcess_returnToInit:
                print('[func_10msec] return-to-init in progress; ignoring command:', self.rxMessage)
                return

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

            # elif self.rxMessage == 'Start':
            #     if self.pusherStatus == PusherStatus.READY:
            #         self.idxExecProcess_load = 0
            #         self.isExecProcess_load = True
            #         print("[Start] load started")
            #     else:
            #         self.idxExecProcess_unit0p = 0
            #         self.isExecProcess_manualHandle = True
            #         print("[Start] manual handle started (not READY)")
            #     self.cntTimeOutExecProcess = 0
            #     self.pusherStatus = PusherStatus.DOING

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

            elif self.rxMessage.startswith('Manual'):
                if self.isExecProcess_load == False:
                    self.pusherStatus=PusherStatus.DOING
                    self.idxExecProcess_unit0p = 0
                    self.isExecProcess_unit0p = True

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
        if not TCPClient.is_initialized:
            return
        if self.isExecProcess_initPusherPos:
            self.execProcess_setPusherPos()

    def func_100msec(self):
        # 복귀 상태머신을 최우선 실행
        if self.isExecProcess_returnToInit:
            self.execProcess_returnToInit()
            return
        elif self.isExecProcess_unit0p:
            self.execProcess_unit0p()

        # 상태머신 디버그
        # try:
        #     print(f"[100ms] flags load={self.isExecProcess_load}, unload={self.isExecProcess_Unload}, manual={self.isExecProcess_manualHandle} | idx_load={self.idxExecProcess_load}, idx_unload={self.idxExecProcess_Unload}, status={self.pusherStatus}")
        # except Exception as e:
        #     print("[100ms] debug print error:", e)

        if self.isExecProcess_load:
            self.execProcess_load()
        elif self.isExecProcess_Unload:
            self.execProcess_Unload()


    def func_500msec(self):
        pass

        # # 입출력 상태 주기 출력(진단용)
        # inputs = {
        #     "Down": self.gpioIn_PusherDown.value(),
        #     "Up": self.gpioIn_PusherUp.value(),
        #     "Back": self.gpioIn_PusherBack.value(),
        #     "Front": self.gpioIn_PusherFront.value(),
        #     "STOP": self.gpioIn_STOP.value(),
        #     "Start_R": self.gpioIn_Start_R.value(),
        #     "Start_L": self.gpioIn_Start_L.value(),
        # }
        # outputs = {
        #     "OutFront": self.gpioOut_pusherFront.value(),
        #     "OutBack": self.gpioOut_pusherBack.value(),
        #     "OutUp": self.gpioOut_pusherUp.value(),
        #     "OutDown": self.gpioOut_pusherDown.value(),
        # }
        # print("[IO] IN", inputs, "| OUT", outputs, f"(ACTIVE_LOW_IN={ACTIVE_LOW_IN}, ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")

    def execProcess_unit0p(self):
        if self.idxExecProcess_unit0p == 0:
            if self.rxMessage == 'ManualPusherFront':
                if not self.gpioIn_PusherDown:
                    self.set_out(self.gpioOut_pusherBack, False)
                    self.set_out(self.gpioOut_pusherFront, True)
            elif self.rxMessage == 'ManualPusherBack':
                if not self.gpioIn_PusherDown:
                    self.set_out(self.gpioOut_pusherFront, False)
                    self.set_out(self.gpioOut_pusherBack, True)
            elif self.rxMessage == 'ManualPusherDown':
                self.set_out(self.gpioOut_pusherUp, False)
                self.set_out(self.gpioOut_pusherDown, True)
            elif self.rxMessage == 'ManualPusherUp':
                self.set_out(self.gpioOut_pusherDown, False)
                self.set_out(self.gpioOut_pusherUp, True)
            elif self.rxMessage == 'ManualPusherInitial':
                # 변경: 단순 플래그가 아니라 공용 복귀 루틴을 호출하여
                # Down/Front 해제, 타임아웃/카운터 초기화, abort_reason 설정까지 수행
                self.request_return_to_init('ManualPusherInitial')
                # 이 명령은 1회 트리거로 처리
                self.isExecProcess_unit0p = False
                self.rxMessage = ''  # 같은 명령의 반복 트리거 방지



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

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 400:                               # 8초 타임아웃
            errorCode = self.checkErrorCode()
            self.isExecProcess_initPusherPos = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.INIT_PUSHER_POS
            self.isInitedPusher = False

    def execProcess_load(self):

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
            self.set_out(self.gpioOut_pusherBack, False)
            self.set_out(self.gpioOut_pusherFront, True)
            print(f"[load idx1] OUT Front=ON, Back=OFF (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
            print(f"[load idx1] OUT raw levels Front={self.gpioOut_pusherFront.value()}, Back={self.gpioOut_pusherBack.value()}")
            self.idxExecProcess_load += 1

        elif self.idxExecProcess_load == 2:
            self.pusherError = PusherError.PUSHER_FRONT
            fv = self.raw_in_level(self.gpioIn_PusherFront)
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

        elif self.idxExecProcess_load == 5:
            self.pusherError = PusherError.PUSHER_DOWN
            dv = self.raw_in_level(self.gpioIn_PusherDown)
            print(f"[load idx5] Down sensor raw={dv} (active={'0' if ACTIVE_LOW_IN else '1'})")
            TCPClient.sendMessage('Pusher down finished\n')
            if self.in_active(self.gpioIn_PusherDown):
                self.isExecProcess_load = False
                self.pusherStatus = PusherStatus.READY
                self.pusherError = PusherError.NONE

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

        elif self.idxExecProcess_Unload == 1:
            self.pusherError = PusherError.PUSHER_UP
            uv = self.raw_in_level(self.gpioIn_PusherUp)
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

        elif self.idxExecProcess_Unload == 4:
            self.pusherError = PusherError.PUSHER_BACK
            bv = self.raw_in_level(self.gpioIn_PusherBack)
            print(f"[unload idx4] Back sensor raw={bv} (active={'0' if ACTIVE_LOW_IN else '1'})")
            if self.in_active(self.gpioIn_PusherBack):
                self.replyMessage('Pusher back finished')
                self.isExecProcess_Unload = False
                self.pusherStatus = PusherStatus.READY
                self.pusherError = PusherError.NONE

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 30:
            errorCode = self.checkErrorCode()
            self.isExecProcess_Unload = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.LOAD_UNLOAD
            self.replyMessage('Error' + errorCode)

    # 송신 표준 헬퍼: 모든 송신은 이 함수로 통일
    def send_line(self, message: str):
        if message is None:
            return
        # 메시지 경계 보장을 위해 개행 추가(중복 방지)
        if not message.endswith('\n'):
            message = message + '\n'
        TCPClient.sendMessage(message)

    def replyMessage(self, message):
        # Check_status는 원래 의도대로 무시
        if self.rxMessage == 'Check_status':
            return
        # 개행 보장하여 송신
        self.send_line(message)

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


    # --- ADD: 공통 중단용 헬퍼들 ---
    def clear_all_processes(self):
        # 현재 진행 중인 모든 상태머신 즉시 해제
        self.isExecProcess_load = False
        self.isExecProcess_Unload = False
        self.isExecProcess_unit0p = False
        self.isExecProcess_initPusherPos = False

        # 인덱스/카운터 초기화
        self.idxExecProcess_load = 0
        self.idxExecProcess_Unload = 0
        self.idxExecProcess_unit0p = 0
        self.idxExecProcess_initPusherPos = 0
        self.cntExecProcess = 0
        self.cntTimeOutExecProcess = 0

    def request_return_to_init(self, reason: str):
        # 어떤 상태에서든 즉시 복귀 상태머신으로 전환
        print(f"[RETURN_INIT] requested: {reason}")
        self.clear_all_processes()
        self.isExecProcess_returnToInit = True
        self.idxExecProcess_returnToInit = 0
        self.cntReturn = 0
        self.cntReturnTimeout = 0
        self.abort_reason = reason
        self.pusherStatus = PusherStatus.DOING
        self.pusherError = PusherError.NONE
        # 즉시 일부 안전 출력 세팅(충돌 최소화: Down/Front 해제)
        # 실제 구동은 상태머신에서 단계적으로 수행
        self.set_out(self.gpioOut_pusherDown, False)
        self.set_out(self.gpioOut_pusherFront, False)


    def execProcess_returnToInit(self):
        """
        비상/복귀 전용 상태머신
        목표: Up=ON, Down=OFF, Back=ON, Front=OFF로 만들고, Up/Back 센서 확인 후 READY
        타임아웃: 단계별 5초 (100ms tick 기준 50카운트)
        """
        TIMEOUT_TICKS = 50  # 5초 (func_100msec 기준)

        if self.idxExecProcess_returnToInit == 0:
            # 1) Up 방향 구동. Down은 반드시 OFF (중복 보정)
            self.set_out(self.gpioOut_pusherDown, False)  # 추가: 안전 보정
            self.set_out(self.gpioOut_pusherUp, True)
            # Front는 OFF 유지
            self.set_out(self.gpioOut_pusherFront, False)
            print(f"[returnToInit idx0] Up=ON, Down=OFF, Front=OFF (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
            self.cntReturnTimeout = 0
            self.idxExecProcess_returnToInit = 1

        elif self.idxExecProcess_returnToInit == 1:
            # 2) Up 센서 확인
            self.pusherError = PusherError.PUSHER_UP
            if self.in_active(self.gpioIn_PusherUp):
                self.cntReturnTimeout = 0
                self.idxExecProcess_returnToInit = 2
                print("[returnToInit idx1] Up sensor active")
            else:
                self.cntReturnTimeout += 1

        elif self.idxExecProcess_returnToInit == 2:
            # 3) Back 구동 (Front는 OFF 유지)
            self.set_out(self.gpioOut_pusherBack, True)
            self.set_out(self.gpioOut_pusherFront, False)
            print(f"[returnToInit idx2] Back=ON, Front=OFF (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
            self.cntReturnTimeout = 0
            self.idxExecProcess_returnToInit = 3

        elif self.idxExecProcess_returnToInit == 3:
            # 4) Back 센서 확인
            self.pusherError = PusherError.PUSHER_BACK
            if self.in_active(self.gpioIn_PusherBack):
                self.isExecProcess_returnToInit = False
                self.pusherStatus = PusherStatus.READY
                self.pusherError = PusherError.NONE
                print("[returnToInit idx3] Back sensor active -> READY")
                TCPClient.sendMessage('ReturnInit OK\n')
            else:
                self.cntReturnTimeout += 1

        # 공통 타임아웃 처리
        if self.isExecProcess_returnToInit and self.cntReturnTimeout >= TIMEOUT_TICKS:
            errorCode = self.checkErrorCode()
            self.isExecProcess_returnToInit = False
            self.pusherStatus = PusherStatus.ERROR
            print(f"[returnToInit] TIMEOUT -> ERROR {errorCode}, reason={self.abort_reason}")
            TCPClient.sendMessage('ReturnInit Error' + errorCode + '\n')



    # def execProcess_returnToInit(self):
    #     """
    #     비상/복귀 전용 상태머신
    #     목표: Up=ON, Down=OFF, Back=ON, Front=OFF로 만들고, Up/Back 센서 확인 후 READY
    #     타임아웃: 단계별 5초 (100ms tick 기준 50카운트)
    #     """
    #     TIMEOUT_TICKS = 50  # 5초 (func_100msec 기준)
    #
    #     if self.idxExecProcess_returnToInit == 0:
    #         # 1) Up 방향 구동 (Down OFF는 request에서 이미 수행)
    #         self.set_out(self.gpioOut_pusherUp, True)
    #         # Front는 이미 OFF. Back은 나중에 ON 시킴(앞축 해제 후 후진)
    #         print(f"[returnToInit idx0] Up=ON, Down=OFF, Front=OFF (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
    #         self.cntReturnTimeout = 0
    #         self.idxExecProcess_returnToInit = 1
    #
    #     elif self.idxExecProcess_returnToInit == 1:
    #         # 2) Up 센서 확인
    #         self.pusherError = PusherError.PUSHER_UP
    #         if self.in_active(self.gpioIn_PusherUp):
    #             self.cntReturnTimeout = 0
    #             self.idxExecProcess_returnToInit = 2
    #             print("[returnToInit idx1] Up sensor active")
    #         else:
    #             self.cntReturnTimeout += 1
    #
    #     elif self.idxExecProcess_returnToInit == 2:
    #         # 3) Back 구동 (Front는 이미 OFF 유지)
    #         self.set_out(self.gpioOut_pusherBack, True)
    #         self.set_out(self.gpioOut_pusherFront, False)
    #         print(f"[returnToInit idx2] Back=ON, Front=OFF (ACTIVE_LOW_OUT={ACTIVE_LOW_OUT})")
    #         self.cntReturnTimeout = 0
    #         self.idxExecProcess_returnToInit = 3
    #
    #     elif self.idxExecProcess_returnToInit == 3:
    #         # 4) Back 센서 확인
    #         self.pusherError = PusherError.PUSHER_BACK
    #         if self.in_active(self.gpioIn_PusherBack):
    #             self.isExecProcess_returnToInit = False
    #             self.pusherStatus = PusherStatus.READY
    #             self.pusherError = PusherError.NONE
    #             print("[returnToInit idx3] Back sensor active -> READY")
    #             TCPClient.sendMessage('ReturnInit OK\n')
    #         else:
    #             self.cntReturnTimeout += 1
    #
    #     # 공통 타임아웃 처리
    #     if self.isExecProcess_returnToInit and self.cntReturnTimeout >= TIMEOUT_TICKS:
    #         errorCode = self.checkErrorCode()
    #         self.isExecProcess_returnToInit = False
    #         self.pusherStatus = PusherStatus.ERROR
    #         print(f"[returnToInit] TIMEOUT -> ERROR {errorCode}, reason={self.abort_reason}")
    #         TCPClient.sendMessage('ReturnInit Error' + errorCode + '\n')

    # ADD: 연결 끊김 시 런타임 상태 리셋용 메서드
    def reset_runtime_state(self):
        print("[reset_runtime_state] Disconnected: clearing in-progress states and counters")
        # 진행 중 플래그 해제
        self.isExecProcess_load = False
        self.isExecProcess_Unload = False
        self.isExecProcess_unit0p = False
        self.isExecProcess_initPusherPos = False
        # (있다면) 복귀 상태머신도 해제
        if hasattr(self, 'isExecProcess_returnToInit'):
            self.isExecProcess_returnToInit = False
            if hasattr(self, 'idxExecProcess_returnToInit'):
                self.idxExecProcess_returnToInit = 0

        # 인덱스/카운터 초기화
        self.idxExecProcess_load = 0
        self.idxExecProcess_Unload = 0
        self.idxExecProcess_unit0p = 0
        self.idxExecProcess_initPusherPos = 0
        self.cntExecProcess = 0
        self.cntTimeOutExecProcess = 0

        # 입력 관련 상태 초기화
        self.start_btn_hold_start_time = None
        self.mapping_start_sent = False
        self.rxMessage = ''

        # 주의: 물리 출력은 즉시 바꾸지 않습니다.
        # 필요 시 안전 상태로 출력 변경하려면 아래 주석을 해제하세요.
        # self.init_gpioOut()
        #
        # 상태값은 애매할 수 있으므로 UNKNOWN으로 두는 것을 권장합니다.
        # (원한다면 READY로 바꿀 수 있으나, 센서 확인 없이 READY는 위험할 수 있음)
        self.pusherStatus = PusherStatus.UNKNOWN
        self.pusherError = PusherError.NONE


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
                            TCPClient.start_ping_sender()
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
