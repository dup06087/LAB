# 오른쪽 밑에 hbox, vbox를 이용하여 ok, cancel을 놓는 프로그램
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QLineEdit

# class Exam1(QWidget): # Qwidget 상속
#     def __init__(self):
#         super().__init__() # 상위 개체 생성
#         self.initUI()
#
#     def initUI(self):
#         okButton = QPushButton("OK")
#         cancelButton = QPushButton("Cancel")
#
#         hbox = QHBoxLayout()
#         hbox.addStretch(1) # 차지하지 않는 만큼 자동 채워짐
#         hbox.addWidget(okButton)
#         hbox.addWidget(cancelButton)
#
#         vbox = QVBoxLayout()
#         vbox.addStretch(1)
#         vbox.addLayout(hbox)
#
#         self.setLayout(vbox)
#
#         self.setGeometry(300,300,300,150)
#         self.setWindowTitle('Buttons')
#         self.resize(500,400)
#         self.show() # 필수
#
# app = QApplication(sys.argv) # Qapplication 객체 생성
# w = Exam1()
# sys.exit(app.exec_()) # 시스템 종료 ## 이벤트 메인 루프 실행 # app.exec_가 돌아가다가 끝나면 sys.exit()가 실행

### grid Layout > 바둑판 같은것

# class Exam2(QWidget): # Qwidget 상속
#     def __init__(self):
#         super().__init__() # 상위 개체 생성
#         self.initUI()
#
#     def initUI(self):
#         grid = QGridLayout()
#         self.setLayout(grid)
#
#         names = ['Cls', 'Bck', '', 'Close', '7','8','9','/','4','5','6','*','1','2','3','-','0','.','=','+']
#         positions = [(i,j) for i in range(5) for j in range(4)]
#
#         for positions, name in zip(positions, names):
#             if name == '':
#                 continue
#             button = QPushButton(name)
#             grid.addWidget(button,*positions)
#
#         self.move(300, 150)
#         self.setWindowTitle('Calculator')
#         self.show() # 필수
#
# app = QApplication(sys.argv) # Qapplication 객체 생성
# w = Exam2()
# sys.exit(app.exec_())

### ex3

class Exam3(QWidget): # Qwidget 상속
    def __init__(self):
        super().__init__() # 상위 개체 생성
        self.initUI()

    def initUI(self):
        title = QLabel('Title')
        author = QLabel('Author')
        review = QLabel('Review')

        titleEdit = QLineEdit()
        authorEdit = QLineEdit()
        reviewEdit = QLineEdit()

        grid = QGridLayout()
        grid.setSpacing(10)

        grid.addWidget(title, 1,0)
        grid.addWidget(titleEdit,1,1)

        grid.addWidget(author,2,0)
        grid.addWidget(authorEdit,2,1)

        grid.addWidget(review,3,0)
        grid.addWidget(reviewEdit,3,1,5,1)

        self.setLayout(grid)

        self.setGeometry(300,300,350,300)
        self.setWindowTitle('review')
        self.show() # 필수

app = QApplication(sys.argv) # Qapplication 객체 생성
w = Exam3()
sys.exit(app.exec_())
