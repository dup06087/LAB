#event+signal
# esc누르면 종료, 마우스 좌표 출력
import sys
from PyQt5.QtWidgets import QWidget, QLCDNumber, QSlider, QVBoxLayout, QApplication, QGridLayout, QLabel, QMainWindow
from PyQt5.QtCore import Qt, pyqtSignal, QObject

# class Exam1(QWidget): # Qwidget 상속
#     def __init__(self):
#         super().__init__() # 상위 개체 생성
#         self.initUI()
#
#     def initUI(self):
#         lcd = QLCDNumber(self) # lcd의 숫자
#         sld = QSlider(Qt.Horizontal, self) # slider생성, Horizontal한 막대
#
#         vbox = QVBoxLayout()
#         vbox.addWidget(lcd)
#         vbox.addWidget(sld)
#
#         self.setLayout(vbox)
#         sld.valueChanged.connect(lcd.display) # 막대가 바뀌면 값이 바뀜
#
#         self.setGeometry(300,300,250,150)
#         self.setWindowTitle('Signal and slot')
#         self.show() # 필수
#
#     def keyPressEvent(self, e):  ## esc누르면 종료 (overriding 이용)
#         if e.key() == Qt.Key_Escape:
#             self.close()
#
#
# if __name__ == '__main__':
#     app = QApplication(sys.argv) # Qapplication 객체 생성
#     w = Exam1()
#     sys.exit(app.exec_()) # 시스템 종료 ## 이벤트 메인 루프 실행 # app.exec_가 돌아가다가 끝나면 sys.exit()가 실행


# class Exam2(QMainWindow): # Qwidget 상속
#     def __init__(self):
#         super().__init__() # 상위 개체 생성
#         self.initUI()
#
#     def initUI(self):
#         grid = QGridLayout()
#         grid.setSpacing(10)
#
#         x, y = 0, 0
#
#         self.text = "x: {0}, y : {1}".format(x,y)
#
#         self.label = QLabel(self.text, self)
#         grid.addWidget(self.label, 0, 0, Qt.AlignTop)
#
#         self.setMouseTracking(True)
#
#         self.setLayout(grid)
#
#
#         self.setGeometry(300,300,350,200)
#         self.setWindowTitle('Event object')
#         self.show() # 필수
#
#     def mouseMoveEvent(self, e):
#         x = e.x()
#         y = e.y()
#
#         text = "x: {0}, y: {1}".format(x,y)
#         self.label.setText(text)
#
# if __name__ == '__main__':
#     app = QApplication(sys.argv) # Qapplication 객체 생성
#     w = Exam2()
#     sys.exit(app.exec_()) # 시스템 종료 ## 이벤트 메인 루프 실행 # app.exec_가 돌아가다가 끝나면 sys.exit()가 실행

class Communicate(QObject): # pyqtSignal()을 사용하기 위해 QObject를 상속
    closeApp = pyqtSignal()

class Exam3(QMainWindow): # Qwidget 상속
    def __init__(self):
        super().__init__() # 상위 개체 생성
        self.initUI()

    def initUI(self):
        self.c = Communicate()
        self.c.closeApp.connect(self.close)

        self.setGeometry(300,300,350,200)
        self.setWindowTitle('Event object')
        self.show() # 필수

    def mousePressEvent(self, event):
        self.c.closeApp.emit()

if __name__ == '__main__':
    app = QApplication(sys.argv) # Qapplication 객체 생성
    w = Exam3()
    sys.exit(app.exec_()) # 시스템 종료 ## 이벤트 메인 루프 실행 # app.exec_가 돌아가다가 끝나면 sys.exit()가 실행