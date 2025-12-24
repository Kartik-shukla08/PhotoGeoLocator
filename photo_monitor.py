import os
import time
import json
import zipfile
import queue
import threading
import shutil
import subprocess
import sys
import traceback

import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PIL import Image, ImageDraw, ExifTags
import pystray
from geopy.geocoders import Nominatim

# ----------------- CONFIGURATION -----------------
CONFIG_FILE = "photo_organizer_config.json"
USER_AGENT = "photo_organizer_client_vFinal"
LOG_FILE = "photo_organizer.log"

# Popup Settings
POPUP_TIMEOUT_MS = 10000   # Auto-close popup after 10s
POPUP_SINGLE_INSTANCE = True

# ----------------- GLOBAL STATE -----------------
event_queue = queue.Queue()
popup_active = False
paused = False
shutdown_event = threading.Event()

# Geolocator with Timeout
geolocator = Nominatim(user_agent=USER_AGENT, timeout=5)

# ----------------- UTILITIES -----------------
def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass 

def open_file_with_default_app(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        log(f"Failed to open {path}")

# ----------------- STARTUP PERSISTENCE LOGIC -----------------
def get_startup_path():
    """Returns the path to the Windows Startup folder."""
    return os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup', 'PhotoGeoLocator.lnk')

def is_startup_enabled():
    """Checks if the shortcut exists."""
    return os.path.exists(get_startup_path())

def set_startup(enable=True):
    """Creates or removes the startup shortcut using a VBScript hack (No extra pip install needed)."""
    shortcut_path = get_startup_path()
    
    if not enable:
        if os.path.exists(shortcut_path):
            try:
                os.remove(shortcut_path)
                log("Startup shortcut removed.")
            except Exception as e:
                log(f"Failed to remove startup shortcut: {e}")
        return

    # If enabling, create the shortcut
    # We use sys.executable to link to the .exe file (or python.exe if testing)
    target = sys.executable
    
    # If running as a script (not frozen), this might link to python.exe. 
    # Best strictly tested when compiled to EXE.
    working_dir = os.path.dirname(target)

    # VBScript to create a shortcut (Native Windows method)
    vbs_content = f"""
    Set oWS = WScript.CreateObject("WScript.Shell")
    Set oLink = oWS.CreateShortcut("{shortcut_path}")
    oLink.TargetPath = "{target}"
    oLink.WorkingDirectory = "{working_dir}"
    oLink.Description = "Photo Geo Locator Auto-Start"
    oLink.Save
    """
    
    vbs_file = os.path.join(os.getenv('TEMP'), "create_shortcut.vbs")
    try:
        with open(vbs_file, "w") as f:
            f.write(vbs_content)
        subprocess.call(["cscript", "//Nologo", vbs_file])
        os.remove(vbs_file)
        log("Startup shortcut created successfully.")
    except Exception as e:
        log(f"Failed to create startup shortcut: {e}")

# ----------------- GEOLOCATION LOGIC -----------------
def rational_to_float(r):
    try:
        if isinstance(r, tuple) and len(r) == 2:
            return float(r[0]) / float(r[1]) if r[1] != 0 else 0.0
        if hasattr(r, "numerator") and hasattr(r, "denominator"):
            return float(r.numerator) / float(r.denominator) if r.denominator != 0 else 0.0
        return float(r)
    except Exception:
        return 0.0

def get_decimal_from_dms(dms):
    try:
        deg = rational_to_float(dms[0])
        minute = rational_to_float(dms[1])
        sec = rational_to_float(dms[2])
        return deg + (minute / 60.0) + (sec / 3600.0)
    except Exception:
        return None

def get_coordinates(image_path):
    try:
        img = Image.open(image_path)
        exif_data = img._getexif()
        if not exif_data: return None
        
        gps_info = None
        for tag, value in exif_data.items():
            if ExifTags.TAGS.get(tag) == "GPSInfo":
                gps_info = value
                break
        if not gps_info: return None

        lat_ref = gps_info.get(1)
        lat_dms = gps_info.get(2)
        lon_ref = gps_info.get(3)
        lon_dms = gps_info.get(4)

        if lat_ref and lat_dms and lon_ref and lon_dms:
            lat = get_decimal_from_dms(lat_dms)
            lon = get_decimal_from_dms(lon_dms)
            if lat is None or lon is None: return None
            
            if lat_ref.upper() == 'S': lat = -lat
            if lon_ref.upper() == 'W': lon = -lon
            return (lat, lon)
    except Exception:
        return None
    return None

def get_address_from_coords(lat, lon):
    try:
        location = geolocator.reverse((lat, lon), exactly_one=True, language='en')
        if location: return location.address
    except Exception:
        log(f"Geocoding failed for {lat}, {lon}")
    return None

def clean_filename(filename):
    clean = "".join([c for c in filename if c.isalnum() or c in (' ', ',')]).strip()
    return clean

# ----------------- PROCESSING -----------------
def process_zip(zip_path, target_root):
    try:
        log(f"Processing: {zip_path}")
        temp_extract_path = os.path.join(target_root, "Temp_Processing")
        
        if os.path.exists(temp_extract_path):
            shutil.rmtree(temp_extract_path, ignore_errors=True)
        os.makedirs(temp_extract_path, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_path)
        except zipfile.BadZipFile:
            log(f"Bad Zip File: {zip_path}")
            return None

        coords_list = []
        for root_dir, dirs, files in os.walk(temp_extract_path):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.heic', '.png')):
                    coords = get_coordinates(os.path.join(root_dir, file))
                    if coords: coords_list.append(coords)

        found_coords = None
        if coords_list:
            avg_lat = sum([c[0] for c in coords_list]) / len(coords_list)
            avg_lon = sum([c[1] for c in coords_list]) / len(coords_list)
            found_coords = (avg_lat, avg_lon)

        final_name = f"Site_Photos_{int(time.time())}"
        if found_coords:
            address = get_address_from_coords(found_coords[0], found_coords[1])
            if address:
                final_name = clean_filename(address)[:50]

        final_path = os.path.join(target_root, final_name)
        if os.path.exists(final_path):
            final_path += f"_{int(time.time())}"

        os.rename(temp_extract_path, final_path)
        log(f"Success: Moved to {final_name}")
        return final_name
    except Exception:
        log(f"Critical Error: {traceback.format_exc()}")
        return None

# ----------------- MONITORING -----------------
class QueueHandler(FileSystemEventHandler):
    def on_created(self, event):
        self._queue_event(event)
    def on_moved(self, event):
        self._queue_event(event)
        
    def _queue_event(self, event):
        if shutdown_event.is_set() or paused: return
        path = event.dest_path if hasattr(event, 'dest_path') else event.src_path
        if not event.is_directory and path.lower().endswith(".zip"):
            event_queue.put(path)

# ----------------- SYSTEM TRAY -----------------
class TrayController:
    def __init__(self, observer):
        self.icon = None
        self.paused = False
        self.observer = observer

    def _create_image(self):
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse([(8, 8), (56, 56)], fill=(0, 120, 215, 255))
        draw.ellipse([(20, 20), (44, 44)], fill=(255, 255, 255, 255))
        return image

    def toggle_pause(self, icon, item):
        global paused
        paused = not paused
        self.paused = paused
        icon.menu = self.build_menu()
        icon.update_menu()

    def toggle_startup(self, icon, item):
        # Check current state and flip it
        currently_enabled = is_startup_enabled()
        set_startup(not currently_enabled)
        # Refresh menu to show new checkbox state
        icon.menu = self.build_menu()
        icon.update_menu()

    def open_log(self, icon, item):
        open_file_with_default_app(LOG_FILE)

    def exit_app(self, icon, item):
        shutdown_event.set()
        if self.observer: self.observer.stop()
        icon.stop()
        if 'root' in globals():
            root.after(100, root.destroy)

    def build_menu(self):
        # Dynamic check for startup status
        startup_checked = pystray.MenuItem("Run on Startup", self.toggle_startup, checked=lambda item: is_startup_enabled())
        
        return pystray.Menu(
            pystray.MenuItem("Resume" if self.paused else "Pause Monitoring", self.toggle_pause),
            startup_checked,  # <-- Added here
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Log File", self.open_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.exit_app)
        )

    def run(self):
        self.icon = pystray.Icon("photo_monitor", self._create_image(), "Photo Monitor", menu=self.build_menu())
        self.icon.run()

# ----------------- GUI -----------------
def run_process_task(file_path, target_folder):
    name = process_zip(file_path, target_folder)
    if name:
        root.after(0, lambda: show_success_popup(name))

def show_custom_notification(root_window, filename, file_path, target_folder):
    global popup_active
    if POPUP_SINGLE_INSTANCE and popup_active: return
    popup_active = True

    notif = tk.Toplevel(root_window)
    notif.title("New Photos")
    notif.overrideredirect(True)
    notif.attributes("-topmost", True)
    notif.configure(bg="#202020")

    screen_width = notif.winfo_screenwidth()
    screen_height = notif.winfo_screenheight()
    width, height = 360, 130
    x_pos = screen_width - width - 20
    y_pos = screen_height - height - 50
    notif.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    tk.Label(notif, text="New Photos Detected", fg="white", bg="#202020", font=("Segoe UI", 10, "bold")).pack(pady=(15, 2))
    tk.Label(notif, text=filename, fg="#aaaaaa", bg="#202020", font=("Segoe UI", 9)).pack(pady=2)

    btn_frame = tk.Frame(notif, bg="#202020")
    btn_frame.pack(pady=12)

    def close_popup():
        global popup_active
        popup_active = False
        try: notif.destroy()
        except: pass

    def on_process():
        close_popup()
        threading.Thread(target=run_process_task, args=(file_path, target_folder), daemon=True).start()

    def on_ignore():
        close_popup()

    tk.Button(btn_frame, text="Process", command=on_process, bg="#0078D7", fg="white", width=12, relief="flat").pack(side="left", padx=10)
    tk.Button(btn_frame, text="Ignore", command=on_ignore, bg="#333333", fg="white", width=12, relief="flat").pack(side="right", padx=10)

    notif.after(POPUP_TIMEOUT_MS, lambda: on_ignore() if popup_active else None)

def show_success_popup(name):
    success = tk.Toplevel(root)
    success.overrideredirect(True)
    success.attributes("-topmost", True)
    success.configure(bg="#006400")
    
    screen_width = success.winfo_screenwidth()
    screen_height = success.winfo_screenheight()
    w, h = 360, 80
    success.geometry(f"{w}x{h}+{screen_width-w-20}+{screen_height-h-50}")
    
    tk.Label(success, text="✔ Processed Successfully", fg="white", bg="#006400", font=("Segoe UI", 10, "bold")).pack(pady=(15, 2))
    tk.Label(success, text=name, fg="#dddddd", bg="#006400", font=("Segoe UI", 9)).pack()
    
    success.after(4000, success.destroy)

# ----------------- MAIN APP -----------------
def start_app():
    global root
    
    # 1. Config Loading
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f: config = json.load(f)
    else:
        # First Run Wizard
        setup = tk.Tk()
        setup.withdraw()
        
        messagebox.showinfo("Welcome", "Please select the folder where you want to STORE your photos.")
        target = filedialog.askdirectory(title="Select Storage Folder")
        if not target: return
        
        messagebox.showinfo("Setup", "Now select your DOWNLOADS folder.")
        down = filedialog.askdirectory(title="Select Downloads Folder")
        if not down: return
        
        # ASK FOR STARTUP PERMISSION
        startup_ans = messagebox.askyesno("Setup", "Do you want this tool to start automatically when Windows starts?")
        if startup_ans:
            set_startup(True)
        
        config = {"target_folder": target, "downloads_folder": down}
        with open(CONFIG_FILE, 'w') as f: json.dump(config, f)
        setup.destroy()

    # 2. Start Monitoring
    event_handler = QueueHandler()
    observer = Observer()
    observer.schedule(event_handler, config["downloads_folder"], recursive=False)
    observer.start()

    # 3. Start System Tray
    tray = TrayController(observer)
    threading.Thread(target=tray.run, daemon=True).start()

    # 4. Main GUI Loop
    root = tk.Tk()
    root.withdraw()

    def check_queue():
        if shutdown_event.is_set():
            root.destroy()
            return
        try:
            file_path = event_queue.get_nowait()
            time.sleep(1.0) 
            show_custom_notification(root, os.path.basename(file_path), file_path, config["target_folder"])
        except queue.Empty:
            pass
        root.after(1000, check_queue)

    root.after(1000, check_queue)
    root.mainloop()
    
    sys.exit(0)

if __name__ == "__main__":
    start_app()