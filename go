import os
import sys
import numpy as np
import cv2

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QPushButton, QWidget
from PyQt5.QtGui import QImage, QPixmap


class ThreadOpenCV(QThread):
    changePixmap = pyqtSignal(QImage)

    def __init__(self, source):
        super().__init__()

        self.source = source

        self.running = True
        self.grayscale = False
        self.blur = False

    def run(self):
        print('start')

        cap = cv2.VideoCapture(self.source)

        self.running = True

        while self.running:
            ret, frame = cap.read()

            if ret:
                if self.grayscale:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                else:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                if self.blur:
                    frame = cv2.blur(frame, (15, 15))

                h, w, ch = frame.shape
                bytes_per_line = ch * w  # PEP8: `lower_case_names` for variables

                image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                image = image.scaled(640, 480, Qt.KeepAspectRatio)

                self.changePixmap.emit(image)

        cap.release()
        print('stop')

    def stop(self):
        self.running = False


class Widget(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()

        # MODEL_NAME = 'inference_graph'
        VIDEO_NAME = 'movie1.mp4'
        CWD_PATH = os.getcwd()
        PATH_TO_VIDEO = os.path.join(CWD_PATH, VIDEO_NAME)

        # webcam
        # PATH_TO_VIDEO = 0

        self.thread = ThreadOpenCV(PATH_TO_VIDEO)
        self.thread.changePixmap.connect(self.setImage)

        layout = QVBoxLayout()

        self.label_video = QLabel()
        layout.addWidget(self.label_video)

        self.btn1 = QPushButton("PLAY")
        self.btn1.clicked.connect(self.playVideo)
        layout.addWidget(self.btn1)

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.clicked.connect(self.stopVideo)
        layout.addWidget(self.btn_stop)

        self.btn_gray = QPushButton("RGB <-> GRAYSCALE")
        self.btn_gray.clicked.connect(self.grayVideo)
        layout.addWidget(self.btn_gray)

        self.btn_blur = QPushButton("NORMAL <-> BLURED")
        self.btn_blur.clicked.connect(self.blurVideo)
        layout.addWidget(self.btn_blur)

        self.widget = QWidget()
        self.widget.setLayout(layout)

        self.setCentralWidget(self.widget)

    def playVideo(self):
        self.thread.start()

    def stopVideo(self):
        self.thread.running = False

    def grayVideo(self):
        self.thread.grayscale = not self.thread.grayscale

    def blurVideo(self):
        self.thread.blur = not self.thread.blur

    def setImage(self, image):
        self.label_video.setPixmap(QPixmap.fromImage(image))


if __name__ == '__main__':
    app = QtWidgets.QApplication([])

    mw = Widget()
    mw.show()

    app.exec()
