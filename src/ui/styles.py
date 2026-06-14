class AppStyles:
    MAIN_WINDOW_BG = "background-color: #E0F7FA;"  # Light Cyan
    
    HEADER_LABEL = """
        font-family: 'Segoe UI', sans-serif;
        font-size: 32px;
        font-weight: bold;
        color: #006064;
    """
    
    BIG_BUTTON = """
        QPushButton {
            background-color: #FF7043;
            color: white;
            border-radius: 15px;
            font-size: 24px;
            padding: 20px;
            min-width: 200px;
        }
        QPushButton:hover {
            background-color: #F4511E;
        }
        QPushButton:pressed {
            background-color: #E64A19;
        }
    """
    
    RECORD_BUTTON_IDLE = """
        QPushButton {
            background-color: #4CAF50; /* Green */
            border-radius: 40px;
            border: 2px solid #388E3C;
        }
        QPushButton:hover {
            background-color: #43A047;
        }
    """
    
    RECORD_BUTTON_ACTIVE = """
        QPushButton {
            background-color: #F44336; /* Red */
            border-radius: 40px;
            border: 2px solid #D32F2F;
        }
        QPushButton:hover {
            background-color: #E53935;
        }
    """
    
    WORD_DISPLAY = """
        font-size: 48px;
        color: #1A237E;
        font-weight: bold;
    """
    
    PHONETIC_DISPLAY = """
        font-size: 24px;
        color: #5C6BC0;
        font-style: italic;
    """
    
    # Quiz Page Styles
    QUIZ_OPTION_BUTTON = """
        QPushButton {
            background-color: #E3F2FD;
            color: #1A237E;
            border: 2px solid #90CAF9;
            border-radius: 10px;
            font-size: 18px;
            font-weight: normal;
            padding: 15px;
            text-align: left;
        }
        QPushButton:hover {
            background-color: #BBDEFB;
            border-color: #42A5F5;
        }
    """
    
    QUIZ_CORRECT = """
        QPushButton {
            background-color: #C8E6C9;
            border: 2px solid #4CAF50;
            color: #2E7D32;
            border-radius: 10px;
            font-size: 18px;
            font-weight: bold;
            padding: 15px;
            text-align: left;
        }
    """
    
    QUIZ_WRONG = """
        QPushButton {
            background-color: #FFCDD2;
            border: 2px solid #F44336;
            color: #C62828;
            border-radius: 10px;
            font-size: 18px;
            font-weight: bold;
            padding: 15px;
            text-align: left;
        }
    """
    
    QUIZ_INPUT = """
        QLineEdit {
            font-size: 22px;
            padding: 12px;
            border: 2px solid #90CAF9;
            border-radius: 8px;
        }
        QLineEdit:focus {
            border-color: #42A5F5;
        }
    """
    
    QUIZ_PROGRESS_BAR = """
        QProgressBar {
            border: 2px solid #90CAF9;
            border-radius: 5px;
            text-align: center;
            font-size: 12px;
        }
        QProgressBar::chunk {
            background-color: #42A5F5;
        }
    """
