# H/W 제어 (실린더, 시그널 타워, 스위치 등등)

from machine import Pin
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

    def __init__(self):
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
        self.init_gpioOut()

        TCPClient.init(server_ip= '', server_port='')

        self.rxMessage = str()

        self.cntExecProcess = 0
        self.cntTimeOutExecProcess = 0

        self.isExecProcess_unit0p = False
        self.idxExecProcess_unit0p = 0

        self.pusherStatus = PusherStatus.UNKNOWN
        self.pusherError = PusherError.NONE

        self.isInitedSocket = False
        self.isExecProcess_initPusherPos = False
        self.idxExecProcess_initPusherPos = 0

        self.isInitedPusher = None

        self.TCP_Server = ('166.79.25.110', 8000)

    def init_gpioOut(self):
        self.set_gpioOut(self.gpioIn_PusherDown, False)
        self.set_gpioOut(self.gpioIn_PusherUp, False)
        self.set_gpioOut(self.gpioIn_PusherBack, False)
        self.set_gpioOut(self.gpioIn_PusherFront, False)
        self.set_gpioOut(self.gpioIn_STOP, False)
        self.set_gpioOut(self.gpioIn_Start_R, False)
        self.set_gpioOut(self.gpioIn_Start_L, False)

    @staticmethod
    def set_gpioOut(target, value):
        target.value(not value)

    def func_10msec(self):
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

            else:
                if self.pusherStatus is PusherStatus.READY:
                    # load/unload
                    if self.rxMessage == 'Unload':
                        self.idxExecProcess_loadUnload = 0
                        self.isExecProcess_loadUnload = True
                    # unit operation
                    else:
                        self.idxExecProcess_unit0p = 0
                        self.isExecProcess_unit0p = True

                    self.cntTimeOutExecProcess = 0
                    self.pusherStatus = PusherStatus.DOING


    def func_25msec(self):
        if self.isExecProcess_initPusherPos:
            self.execProcess_setPusherPos()

    def func_100msec(self):
        if self.isExecProcess_loadUnload:
            self.execProcess_loadUnload()
        elif self.isExecProcess_unit0p:
            self.execProcess_unit0p()

    def execProcess_setPusherPos(self):
        if self.idxExecProcess_initPusherPos == 0:                          # Pusher up
            self.set_gpioOut(self.gpioOut_pusherUp, True)
            self.set_gpioOut(self.gpioOut_pusherDown, False)
            self.idxExecProcess_initPusherPos += 1
        elif self.idxExecProcess_initPusherPos == 1:
            self.pusherError = PusherError.PUSHER_UP                        # Pusher up 확인
            if self.gpioIn_PusherUp:
                self.cntExecProcess = 0
                self.idxExecProcess_initPusherPos += 1
        elif self.idxExecProcess_initPusherPos == 2:                        # 125msec 대기
            self.cntExecProcess += 1
            if self.cntExecProcess >= 5:                                    # Pusher Back
                self.set_gpioOut(self.gpioOut_pusherBack, True)
                self.set_gpioOut(self.gpioOut_pusherFront, False)
                self.idxExecProcess_initPusherPos += 1
        elif self.idxExecProcess_initPusherPos == 3:                        # Pusher Back 확인
            self.pusherError = PusherError.PUSHER_BACK
            if self.gpioIn_pusherBack :
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

    def execProcess_loadUnload(self):
        # unload (Pusher Back)
        if self.rxMessage[3:5] == '00':
            if self.idxExecProcess_loadUnload == 0:                     # Pusher 상승
                self.set_gpioOut(self.gpioOut_pusherUp, True)
                self.set_gpioOut(self.gpioOut_pusherDown, False)
                self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload == 1:                   # Pusher 상승 확인
                self.pusherError = PusherError.PUSHER_UP
                if self.gpioIn_PusherUp:
                    self.cntTimeOutExecProcess = 0
                    self.cntExecProcess = 0
                    self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload == 2:                   # 대기 500msec
                self.cntExecProcess += 1
                if self.cntExecProcess >= 5:
                    self.cntTimeOutExecProcess = 0
                    self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload == 3:                   # Pusher 후진
                self.set_gpioOut(self.gpioOut_pusherFront, False)
                self.set_gpioOut(self.gpioOut_pusherBack, True)
                self.cntExecProcess = 0
                self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload == 4:                   # Pusher 후진 확인
                self.pusherError = PusherError.PUSHER_BACK
                if self.gpioIn_pusherBack:
                    self.idxExecProcess_loadUnload = False
                    self.pusherStatus = PusherStatus.READY
                    self.pusherError = PusherError.NONE
                    self.replyMessage('S' + self.rxMessage[1:5] + '000')

        # load
        else :
            if self.idxExecProcess_loadUnload == 0:                     # Pusher 초기상태 확인
                if self.gpioIn_PusherUp and self.gpioIn_pusherBack :
                    self.cntTimeOutExecProcess = 0
                    self.idxExecProcess_loadUnload += 1
                else:
                    if not self.gpioIn_PusherUp:
                        self.pusherError = PusherError.PUSHER_UP
                    elif not self.gpioIn_pusherBack:
                        self.pusherError = PusherError.PUSHER_BACK
            if self.idxExecProcess_loadUnload == 1:                     # Pusher 전진 동작
                self.set_gpioOut(self.gpioOut_pusherFront, True)
                self.set_gpioOut(self.gpioOut_pusherBack, False)
                self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload == 2:                   # Pusher 전진 확인
                self.pusherError = PusherError.PUSHER_FRONT
                if self.gpioIn_PusherFront:
                    self.cntTimeOutExecProcess = 0
                    self.cntExecProcess = 0
                    self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload == 3:                   # delay 500ms 부여 구간
                self.cntExecProcess += 1
                if self.cntExecProcess >= 5:
                    self.cntTimeOutExecProcess = 0
                    self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload ==4:                   # Pusher 하강 동작
                self.set_gpioOut(self.gpioOut_pusherUp, False)
                self.set_gpioOut(self.gpioOut_pusherDown, True)
                self.cntExecProcess = 0
                self.idxExecProcess_loadUnload += 1
            elif self.idxExecProcess_loadUnload == 5:                   # Pusher 하강 확인
                self.pusherError = PusherError.PUSHER_DOWN
                if self.gpioIn_PusherDown:
                    self.isExecProcess_loadUnload = False
                    self.pusherStatus = PusherStatus.READY
                    self.pusherError = PusherError.NONE
                    self.replyMessage('S' + self.rxMessage[1:5] + '000')

        self.cntTimeOutExecProcess += 1
        if self.cntTimeOutExecProcess >= 30:
            errorCode = self.checkErrorCode()

            self.isExecProcess_loadUnload = False
            self.pusherStatus = PusherStatus.ERROR
            self.pusherError = PusherError.LOAD_UNLOAD
            self.replyMessage('S' + self.rxMessage[1:5] + errorCode)

    def replyMessage(self, message):
        if self.rxMessage[1:3] == '31':
            pass
        else:
            TCPClient.send_data(self.TCP_Server, message)

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

    def execProcess_unit0p(self):
        pass

if __name__ == "__main__":
    cnt_msec = 0
    main = MainPusher()

    while True:
        cnt_msec += 1

        if not cnt_msec % 10:
            main.func_10msec()

        if not cnt_msec % 25:
            main.func_25msec()

        if not cnt_msec % 100:
            main.func_100msec()

        time.sleep_ms(1)