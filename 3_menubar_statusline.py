# qwidget이 아니라 qmainwindow
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QAction, QMenu
from PyQt5.QtCore import QCoreApplication

class Exam(QMainWindow): # Qwidget 상속
    def __init__(self):
        super().__init__() # 상위 개체 생성
        self.initUI()

    def initUI(self):
        self.statusBar() # 상태표시줄
        self.statusBar().showMessage("status Bar")

        menu =  self.menuBar() # 메뉴생성
        menu_file =menu.addMenu('File') # 그룹생성
        menu_edit = menu.addMenu('Edit') # 그룹생성

        file_exit = QAction('Exit', self) # exit라는 이름의 것을 메모리에 만듦
        file_exit.setShortcut('Ctrl+Q') # 그룹명 오른쪽에 단축키 쓰여있는곳에 글 쓰기
        file_exit.setStatusTip('누르면 닫힘') # statusbar에 글 쓰기

        new_txt = QAction("텍스트 파일",self)
        new_py = QAction("파이썬 파일",self)
        file_new = QMenu('New',self)

        file_exit.triggered.connect(QCoreApplication.instance().quit) # triggered 선택되었을 때 connect가 실행

        file_new.addAction(new_txt)
        file_new.addAction(new_py)

        menu_file.addMenu(file_new)
        menu_file.addAction(file_exit)

        self.resize(300,400)
        self.show() # 필수

app = QApplication(sys.argv) # Qapplication 객체 생성
w = Exam()
sys.exit(app.exec_()) # 시스템 종료 ## 이벤트 메인 루프 실행 # app.exec_가 돌아가다가 끝나면 sys.exit()가 실행
