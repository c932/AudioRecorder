import sys
import os
import shutil

def get_resource_path(relative_path):
    """ 
    Get absolute path to resource, works for dev and for PyInstaller.
    Maps 'src/...' to the bundled location.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def get_user_data_path(filename):
    """ 
    Get path for user writable data.
    In dev: returns local src/data/filename
    In prod: returns path in USER_PROFILE/.english_coach/filename
    """
    if getattr(sys, 'frozen', False):
        # Prod: Use Executable Directory (Portable Mode)
        # sys.executable points to the exe file, so we take dirname
        base_path = os.path.dirname(sys.executable)
        
        target_path = os.path.join(base_path, filename)
        
        # If file doesn't exist in exe dir, try to copy from bundled resources
        if not os.path.exists(target_path):
             # We assume the default data is bundled at src/data/filename
             # Note: You must ensure 'src/data' is added to datas in spec file
             bundled_path = get_resource_path(os.path.join("src", "data", filename))
             if os.path.exists(bundled_path):
                 try:
                     shutil.copy2(bundled_path, target_path)
                     print(f"[Info] Copied default data to {target_path}")
                 except Exception as e:
                     print(f"[Error] Failed to copy default data: {e}")
        
        return target_path
    else:
        # Dev
        return os.path.join("src", "data", filename)
