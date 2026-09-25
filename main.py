import sys
from PyQt6.QtWidgets import QApplication
from src.ui.styles import load_fonts
from src.ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    load_fonts()  # register bundled Nunito before any widget is built
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
