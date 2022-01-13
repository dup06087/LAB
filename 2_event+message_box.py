import sys
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton,QMessageBox
from PyQt5.QtCore import QCoreApplication

class Exam(QWidget): # Qwidget 상속
    def __init__(self):
        super().__init__() # 상위 개체 생성
        self.initUI()

    def initUI(self):
        btn = QPushButton('push', self) # (버튼에 표시될 텍스트, 버튼이 위치할 부모 위젯)
        btn.resize(btn.sizeHint())
        btn.move(50,50)
        btn.clicked.connect(QCoreApplication.instance().quit) #프로그램 종료
        # 시그널(signal)과 슬롯(slot)
        ''' 버튼(btn)을 클릭하면 clicked시그널 발생
            instance() 메서드는 현재 인스턴스 반환
            clicked는 quit 메서드에 연결
            이렇게 발신자(sender)와 수신자(receiver) 두 객체 간의 커뮤니케이션이 이루어짐
            이 때, 발신자는 푸시버튼(btn)이고, 수신자는 어플리케이션 객체 (app)임 
        '''

        self.resize(500,500)
        self.setWindowTitle("2번째")
        self.show() # 필수

    def closeEvent(self, QCloseEvent): # close event가 발생하면 실행
        ans = QMessageBox.question(self, "종료 확인", "종료하시겠습니까?",
                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No) #제목,내용, 버튼추가(|), 기본값 #이 상태로는 아무거나 눌러도 꺼짐
        if ans == QMessageBox.Yes:
            QCloseEvent.accept()
        if ans == QMessageBox.No:
            QCloseEvent.ignore()

app = QApplication(sys.argv) # Qapplication 객체 생성
w = Exam()
sys.exit(app.exec_()) # 시스템 종료 ## 이벤트 메인 루프 실행 # app.exec_가 돌아가다가 끝나면 sys.exit()가 실행
