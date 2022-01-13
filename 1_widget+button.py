import sys
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton *

class Exam(QWidget): # Qwidget 상속
    def __init__(self):
        super().__init__() # 상위 개체 생성
        self.initUI()

    def initUI(self):
        btn = QPushButton('push1', self)
        btn.resize(btn.sizeHint()) # 글자 수에 따라 동적으로 할당
        btn.move(20,30)
        btn.setToolTip("툴팁입니다 <b>안녕하세요.<b/>")

        self.setGeometry(300,300,400,500)
        self.setWindowTitle("첫 번째") # window 이름 바꾸기
        self.show() # 필수

app = QApplication(sys.argv) # Qapplication 객체 생성
w = Exam()
sys.exit(app.exec_()) # 시스템 종료 ## 이벤트 메인 루프 실행 # app.exec_가 돌아가다가 끝나면 sys.exit()가 실행
