import sys
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox

# Import the class but don't run main yet
try:
    from src.ui.main_window import MainWindow
except Exception as e:
    with open("crash_startup.log", "w") as f:
        f.write(traceback.format_exc())
    print("Startup Import Error:", e)
    sys.exit(1)

def main():
    app = QApplication(sys.argv)
    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        error_msg = traceback.format_exc()
        print("RUNTIME ERROR:", error_msg)
        with open("crash_runtime.log", "w") as f:
            f.write(error_msg)
        
        # Try to show a dialog even if crashing
        try:
            error_box = QMessageBox()
            error_box.setText("Application Crashed")
            error_box.setInformativeText(str(e))
            error_box.setDetailedText(error_msg)
            error_box.exec()
        except:
            pass

if __name__ == "__main__":
    main()
