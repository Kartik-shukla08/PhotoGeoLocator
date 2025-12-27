# PhotoGeoLocator 📸📍

**PhotoGeoLocator** is a lightweight, background automation tool for Windows that streamlines the workflow of organizing site visit photos. It monitors your Downloads folder for ZIP files (specifically from Google Photos), extracts them, reads the GPS metadata from the images, and automatically renames the folder to the physical address where the photos were taken.

> **Download the Executable (.exe)** > Due to GitHub file size limits, the standalone application is hosted externally:  
> 📥 **[Download PhotoGeoLocator v1.0 (Google Drive)](https://drive.google.com/file/d/1PtM4pTIL1qgW4hx7Jutd0a6GQEO4Dy_S/view?usp=sharing)**

---

## 🚀 Key Features

* **Automated Monitoring:** Uses `watchdog` to listen for file system events in real-time. Instantly detects when a ZIP file enters the Downloads folder.
* **Smart Geotagging:** Extracts EXIF GPS data from images (`.jpg`, `.jpeg`, `.heic`) and uses Reverse Geocoding (OpenStreetMap/Nominatim) to find the street address.
* **Non-Intrusive UI:** Runs silently in the background with a **System Tray Icon**.
* **Custom Notifications:** Features a custom, native-feeling popup UI allowing users to "Process" or "Ignore" specific files.
* **Thread-Safe Architecture:** Heavy processing (unzipping/network calls) happens in background threads to ensure the UI never freezes.
* **Startup Persistence:** Optional setting to automatically launch the tool when Windows starts.
* **Robust Logging:** maintain a local `.log` file for debugging and error tracking.

---

## 🛠️ Technical Architecture

The application is built in **Python 3.12** and compiled to a standalone executable using **PyInstaller**.

### Core Libraries
| Library | Purpose |
| :--- | :--- |
| **`watchdog`** | Implements the Observer pattern to monitor the filesystem for new `.zip` files. |
| **`pillow` (PIL)** | Parses binary image headers to extract EXIF tags and GPS info. |
| **`geopy`** | Interface for the Nominatim API to convert Latitude/Longitude into a human-readable address. |
| **`tkinter`** | Handles the "First Run" setup wizard and the custom notification popups. |
| **`pystray`** | Manages the System Tray icon and context menu (Pause/Resume/Exit). |

### Workflow Logic
1.  **Observer:** The `QueueHandler` detects a `created` or `moved` event for a `.zip` file.
2.  **Queue:** The file path is pushed to a thread-safe `queue`.
3.  **Consumer:** The main thread checks the queue every 1 second.
4.  **Interaction:** A popup asks the user for confirmation.
5.  **Processing (Background Thread):**
    * Unzips to a temporary folder.
    * Scans images for GPS tags.
    * Calculates the average coordinate of the batch.
    * Fetches the address via API.
    * Renames and moves the folder to the target directory.

---

## 📥 Installation & Usage

### Method 1: For End Users (EXE)
1.  **Download** the file from the [Google Drive Link](https://drive.google.com/file/d/1PtM4pTIL1qgW4hx7Jutd0a6GQEO4Dy_S/view?usp=sharing).
2.  **Move** the `PhotoGeoLocator.exe` to a permanent folder (e.g., `Documents/PhotoTool`).
    * *Note: Do not run it directly from inside a ZIP or the Downloads folder.*
3.  **Run** the executable.
4.  **Setup:** On the first run, it will ask for:
    * The folder where you want to **store** the organized photos.
    * Your **Downloads** folder location.
    * Permission to run on **Startup**.
5.  **Minimize:** The app will sit in your System Tray. When you download a ZIP from Google Photos, a popup will appear.

### Method 2: For Developers (Source Code)
If you wish to modify or build the code yourself:

**Prerequisites:**
* Python 3.x
* Pip

**Clone and Install:**
```bash
git clone [https://github.com/Kartik-shukla08/PhotoGeoLocator.git](https://github.com/Kartik-shukla08/PhotoGeoLocator.git)
cd PhotoGeoLocator
pip install watchdog pillow geopy pystray pyinstaller
```
**2. Run Locally (Testing):**
```bash
python monitor_persistent.py
```

**3. Build EXE:**
To compile the script into a single executable file, run the following command. Note the specific hidden import flag required for PIL to work correctly inside the package.

```bash
python -m PyInstaller --onefile --noconsole --name "PhotoGeoLocator" --hidden-import="PIL._tkinter_finder" monitor_persistent.py
```

The resulting `.exe` file will appear in the `dist/` folder.

---

## ⚙️ Configuration & Logs

The application creates two files in the same directory as the executable:

1.  `photo_organizer_config.json`: Stores your directory paths. Delete this file to reset the setup wizard.
2.  `photo_organizer.log`: Records all events, processing attempts, and errors.

---
