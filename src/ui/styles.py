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
