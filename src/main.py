
import base64
import csv
import glob
import hashlib
import json
import math
import os
import re
import shutil
import socket
import struct
import sys
import threading
import tempfile
import zipfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QSize, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPixmap, QImage, QDesktopServices, QIcon, QLinearGradient, QRadialGradient, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QFileDialog,
    QHBoxLayout, QVBoxLayout, QGridLayout, QListWidget, QListWidgetItem, QStackedWidget,
    QLineEdit, QMessageBox, QScrollArea, QTabWidget, QSpinBox, QDoubleSpinBox, QComboBox, QColorDialog, QSlider, QCheckBox, QSplitter
)

APP_VERSION = "1.3.10"
APP_NAME = "WN Forza Tuner"
TUNE_FILE_SIZE = 598
ORDINAL_OFFSET = 2
UPGRADE_OFFSET = 10
UPGRADE_SLOT_COUNT = 48
DATA_OFFSET = 414
TUNE_FLOAT_COUNT = 46
THUMBNAIL_FILENAME = "Thumb.png"
SHARE_SCHEMA_VERSION = "fh6-tuner-share-v1"
DISCORD_INVITE_URL = "https://discord.gg/jvXwbKwCp"
KOFI_URL = "https://ko-fi.com/wn123"
DEFAULT_GITHUB_REPO_OWNER = "WN2323"
DEFAULT_GITHUB_REPO_NAME = "FHT"
DEFAULT_THUMBNAIL_CACHE_BRANCH = "main"
DEFAULT_THUMBNAIL_CACHE_PATH = "thumbnail_cache"
PUBLIC_THUMBNAIL_REPO_URL = "https://github.com/WN2323/FHT/tree/main/thumbnail_cache"


def github_releases_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases"


def github_latest_release_api(owner: str, repo: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def github_contents_api(owner: str, repo: str, path: str, branch: str = "main") -> str:
    clean_path = str(path or "").strip().strip("/")
    return f"https://api.github.com/repos/{owner}/{repo}/contents/{clean_path}?ref={branch}"

IS_PYINSTALLER_BUILD = bool(getattr(sys, "frozen", False))
IS_NUITKA_BUILD = "__compiled__" in globals()

if IS_PYINSTALLER_BUILD:
    # PyInstaller onedir layout:
    #   WN Forza Tuner.exe lives in BASE_DIR
    #   bundled resources live in sys._MEIPASS, usually BASE_DIR / "_internal"
    BASE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_BASE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
elif IS_NUITKA_BUILD:
    # Nuitka standalone layout:
    #   WN Forza Tuner.exe and the bundled data folder live in the .dist folder.
    BASE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_BASE_DIR = BASE_DIR
else:
    BASE_DIR = Path(__file__).resolve().parents[1]
    RESOURCE_BASE_DIR = BASE_DIR

DATA_DIR = RESOURCE_BASE_DIR / "data"
LOGO_IMAGE_PATH = DATA_DIR / "wn23_logo_sidebar_clean.png"
LOGO_IMAGE_PATH_ALT = LOGO_IMAGE_PATH
APP_ICON_PATH = DATA_DIR / "WNFT.ico"
APP_ICON_PNG_PATH = DATA_DIR / "WNFT.png"
DISCORD_ICON_PATH = DATA_DIR / "discord_logo.png"
KOFI_ICON_PATH = DATA_DIR / "kofi_logo.png"

# User-writable folders stay beside the app/exe, not inside PyInstaller _internal.
THUMBNAIL_CACHE_DIR = BASE_DIR / "thumbnail_cache"
IMPORTED_SHARE_DIR = BASE_DIR / "imported_share_tunes"
CONFIG_PATH = BASE_DIR / "qt_tunelab_config.json"
UPDATE_DOWNLOAD_DIR = BASE_DIR / "_update_downloads"
UPDATE_STAGING_DIR = BASE_DIR / "_update_staging"
SHARED_LAPS_DIR = BASE_DIR / "shared_laps"
SHARE_PACK_EXTENSION = ".fh6share"
DEFAULT_TUNE_FOLDER_GLOB = "C:\\XboxGames\\GameSave\\pgs\\u_*\\current\\ContainersRoot"


def load_json(path: Path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return fallback


CAR_DB = load_json(DATA_DIR / "car_db.json", {})
DT_DB = load_json(DATA_DIR / "drivetrain_db.json", {})
DT_LABELS = {"F": "FWD", "R": "RWD", "A": "AWD", "?": "?"}


@dataclass
class UpgradeEntry:
    slot_index: int
    raw: int
    key: Optional[int]
    index: Optional[int]
    state: str


@dataclass
class TuneFile:
    path: Path
    raw_bytes: bytes
    ordinal: int
    values: list
    upgrades: list
    md5: str
    header_name: str = ""
    header_description: str = ""
    header_created: str = ""
    header_created_sort: int = 0

    @property
    def car_name(self) -> str:
        return CAR_DB.get(str(self.ordinal), f"Unknown car #{self.ordinal}")

    @property
    def drivetrain_code(self) -> str:
        return DT_DB.get(str(self.ordinal), "?")

    @property
    def drivetrain_label(self) -> str:
        return DT_LABELS.get(self.drivetrain_code, self.drivetrain_code)

    @property
    def header_path(self) -> Path:
        return self.path.parent / "header"

    @property
    def has_header_metadata(self) -> bool:
        return bool(self.header_name or self.header_description or self.header_created)

    @property
    def display_name(self) -> str:
        return f"{self.car_name} — {self.header_name}" if self.header_name else self.car_name

    @property
    def tune_name_or_folder(self) -> str:
        return self.header_name or self.path.parent.name or self.path.name

    @property
    def active_gear_count(self) -> int:
        return sum(1 for value in self.values[36:46] if value >= 0.0)

    def save_to(self, out_path: Path):
        data = bytearray(self.raw_bytes)
        for i, value in enumerate(self.values):
            struct.pack_into("<f", data, DATA_OFFSET + i * 4, float(value))
        out_path.write_bytes(data)


@dataclass
class FieldDef:
    index: int
    section: str
    label: str
    display_min: float = 0.0
    display_max: float = 1.0
    unit: str = "raw"
    decimals: int = 2
    step: float = 0.01
    note: str = ""

    def raw_to_display(self, raw: float) -> Optional[float]:
        if raw is None or raw < 0:
            return None
        clamped = max(0.0, min(1.0, float(raw)))
        return self.display_min + clamped * (self.display_max - self.display_min)

    def display_text(self, raw: float) -> str:
        value = self.raw_to_display(raw)
        if value is None:
            return "N/A"
        formatted = f"{value:.{self.decimals}f}"
        if self.unit:
            return f"{formatted} {self.unit}"
        return formatted

    def display_to_raw(self, value: float) -> float:
        if self.display_max == self.display_min:
            return 0.0
        raw = (float(value) - self.display_min) / (self.display_max - self.display_min)
        return max(0.0, min(1.0, raw))

    def clamp_display(self, value: float) -> float:
        """Clamp a displayed tuning value to this field's display range."""
        lo = min(self.display_min, self.display_max)
        hi = max(self.display_min, self.display_max)
        return max(lo, min(hi, float(value)))

    def format_display(self, value) -> str:
        """Format a displayed tuning value for Tune Assist UI boxes."""
        if value is None:
            return "--"
        try:
            number = float(value)
        except Exception:
            return str(value)

        decimals = int(getattr(self, "decimals", 2) or 0)
        unit = getattr(self, "unit", "") or ""
        formatted = f"{number:.{decimals}f}"
        return f"{formatted} {unit}".rstrip()



    @property
    def slider_steps(self) -> int:
        span = abs(self.display_max - self.display_min)
        if self.step <= 0:
            return 1000
        return max(1, int(round(span / self.step)))

    def display_to_slider(self, value: float) -> int:
        if self.display_max == self.display_min:
            return 0
        frac = (float(value) - self.display_min) / (self.display_max - self.display_min)
        return max(0, min(self.slider_steps, int(round(frac * self.slider_steps))))

    def slider_to_display(self, slider_value: int) -> float:
        frac = max(0.0, min(1.0, float(slider_value) / max(1, self.slider_steps)))
        return self.display_min + frac * (self.display_max - self.display_min)


FIELD_DEFS = [
    # Aero
    FieldDef(0, "Aero", "Front aero", 0, 100, "%", 0, 1, "Car-specific force; percentage placeholder."),
    FieldDef(1, "Aero", "Rear aero", 0, 100, "%", 0, 1, "Car-specific force; percentage placeholder."),

    # Gearing
    FieldDef(2, "Gearing", "Final drive", 2.00, 6.10, ":1", 2, 0.01, "Calibrated from sample tunes."),
    *[FieldDef(36 + i, "Gearing", f"{i + 1}{'st' if i == 0 else 'nd' if i == 1 else 'rd' if i == 2 else 'th'} Gear", 0.48, 6.00, ":1", 2, 0.01, "Calibrated from sample tunes.") for i in range(10)],

    # Tyres
    FieldDef(12, "Tyres", "Front tyre pressure", 15.0, 55.0, "PSI", 1, 0.1, "Common FH range; still being verified."),
    FieldDef(23, "Tyres", "Rear tyre pressure", 15.0, 55.0, "PSI", 1, 0.1, "Common FH range; still being verified."),

    # Alignment
    FieldDef(13, "Alignment", "Front camber", -5.0, 5.0, "°", 1, 0.1, "Common FH range; still being verified."),
    FieldDef(24, "Alignment", "Rear camber", -5.0, 5.0, "°", 1, 0.1, "Common FH range; still being verified."),
    FieldDef(14, "Alignment", "Front toe", -5.0, 5.0, "°", 1, 0.1, "Common FH range; still being verified."),
    FieldDef(25, "Alignment", "Rear toe", -5.0, 5.0, "°", 1, 0.1, "Common FH range; still being verified."),
    FieldDef(15, "Alignment", "Caster", 1.0, 7.0, "°", 1, 0.1, "Common FH range; still being verified."),

    # Anti-roll bars
    FieldDef(17, "Anti-roll Bars", "Front anti-roll bar", 1.0, 65.0, "", 2, 0.01, "Common FH range; still being verified."),
    FieldDef(28, "Anti-roll Bars", "Rear anti-roll bar", 1.0, 65.0, "", 2, 0.01, "Common FH range; still being verified."),

    # Springs / ride height
    FieldDef(16, "Springs", "Front spring stiffness", 1.00, 20.80, "KGF/MM", 2, 0.01, "Approx game-style unit; car-specific range."),
    FieldDef(27, "Springs", "Rear spring stiffness", 1.00, 17.98, "KGF/MM", 2, 0.01, "Approx game-style unit; car-specific range."),
    FieldDef(18, "Springs", "Front ride height", 10.0, 22.2, "CM", 1, 0.1, "Approx game-style unit; car-specific range."),
    FieldDef(29, "Springs", "Rear ride height", 10.0, 21.2, "CM", 1, 0.1, "Approx game-style unit; car-specific range."),

    # Damping
    FieldDef(20, "Damping", "Front rebound", 1.0, 20.0, "", 2, 0.01, "Common FH range; still being verified."),
    FieldDef(31, "Damping", "Rear rebound", 1.0, 20.0, "", 2, 0.01, "Common FH range; still being verified."),
    FieldDef(19, "Damping", "Front bump", 1.0, 20.0, "", 2, 0.01, "Common FH range; still being verified."),
    FieldDef(30, "Damping", "Rear bump", 1.0, 20.0, "", 2, 0.01, "Common FH range; still being verified."),

    # Brakes
    FieldDef(4, "Brakes", "Brake balance", 0, 100, "%", 0, 1, "Direction/inversion still being verified."),
    FieldDef(3, "Brakes", "Brake pressure", 50, 200, "%", 0, 1, "Common FH range; still being verified."),

    # Differential
    FieldDef(21, "Differential", "Front accel", 0, 100, "%", 0, 1, "Active only when front diff is tunable."),
    FieldDef(22, "Differential", "Front decel", 0, 100, "%", 0, 1, "Active only when front diff is tunable."),
    FieldDef(32, "Differential", "Rear accel", 0, 100, "%", 0, 1, "Active only when rear diff is tunable."),
    FieldDef(33, "Differential", "Rear decel", 0, 100, "%", 0, 1, "Active only when rear diff is tunable."),
    FieldDef(6, "Differential", "Centre balance / power bias", 0, 100, "% rear", 0, 1, "AWD only; label still being verified."),
    FieldDef(5, "Differential", "Torque split / unknown", 0, 100, "%", 0, 1, "Needs more validation."),
]

FIELD_BY_INDEX = {field.index: field for field in FIELD_DEFS}
FIELDS_BY_SECTION = {}
for field in FIELD_DEFS:
    FIELDS_BY_SECTION.setdefault(field.section, []).append(field)


def decode_upgrade(slot_index: int, raw: int) -> UpgradeEntry:
    if raw == 0xFFFFFFFF:
        return UpgradeEntry(slot_index, raw, None, None, "absent")
    return UpgradeEntry(slot_index, raw, raw // 1000, raw % 1000, "present")


UPGRADE_SLOT_INFO = {
    # The exact FH upgrade slot names can vary, but these groupings match the
    # common Forza upgrade layout and make the raw slot list usable again.
    0: ("Conversion / Presets", "Conversion or preset"),
    1: ("Engine", "Engine swap / engine package"),
    2: ("Engine", "Aspiration / intake package"),
    3: ("Engine", "Engine variant / aspiration"),
    4: ("Aero & Body", "Front bumper / front aero"),
    5: ("Aero & Body", "Rear wing / rear aero"),
    6: ("Aero & Body", "Rear bumper / rear body"),
    7: ("Aero & Body", "Side skirts / side body"),
    8: ("Tyres & Rims", "Tyre compound"),
    9: ("Tyres & Rims", "Front tyre width"),
    10: ("Tyres & Rims", "Rear tyre width"),
    11: ("Tyres & Rims", "Rim style"),
    12: ("Tyres & Rims", "Front rim size"),
    13: ("Tyres & Rims", "Rear rim size"),
    14: ("Drivetrain", "Clutch"),
    15: ("Drivetrain", "Transmission"),
    16: ("Drivetrain", "Driveline"),
    17: ("Drivetrain", "Differential"),
    18: ("Platform & Handling", "Brakes"),
    19: ("Platform & Handling", "Springs / dampers"),
    20: ("Platform & Handling", "Front anti-roll bars"),
    21: ("Platform & Handling", "Rear anti-roll bars"),
    22: ("Platform & Handling", "Chassis reinforcement / roll cage"),
    23: ("Platform & Handling", "Weight reduction"),
    24: ("Engine", "Intake"),
    25: ("Engine", "Fuel system"),
    26: ("Engine", "Ignition"),
    27: ("Engine", "Exhaust"),
    28: ("Engine", "Camshaft"),
    29: ("Engine", "Valves"),
    30: ("Engine", "Displacement"),
    31: ("Engine", "Pistons / compression"),
    32: ("Engine", "Turbo / supercharger"),
    33: ("Engine", "Intercooler"),
    34: ("Engine", "Oil / cooling"),
    35: ("Engine", "Flywheel"),
}


UPGRADE_CATEGORY_ORDER = [
    "Conversion / Presets",
    "Engine",
    "Aero & Body",
    "Tyres & Rims",
    "Drivetrain",
    "Platform & Handling",
    "Other / Unknown",
]


def upgrade_slot_category(slot_index: int) -> str:
    return UPGRADE_SLOT_INFO.get(slot_index, ("Other / Unknown", f"Upgrade slot {slot_index:02d}"))[0]


def upgrade_slot_label(slot_index: int) -> str:
    return UPGRADE_SLOT_INFO.get(slot_index, ("Other / Unknown", f"Upgrade slot {slot_index:02d}"))[1]



def _read_header_utf16(data: bytes, pos: int):
    if pos + 4 > len(data):
        raise ValueError("Header string length is out of range")
    length = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    byte_len = int(length) * 2
    if length < 0 or pos + byte_len > len(data):
        raise ValueError("Header string data is out of range")
    value = data[pos:pos + byte_len].decode("utf-16le", errors="replace").strip("\x00").strip()
    return value, pos + byte_len


def parse_tune_header_metadata(data_path: Path) -> dict:
    """Auto-read safe tune metadata from the sibling FH tune header file.

    When a user loads/selects a Data file, the app checks that Data file's
    folder for a file named `header` and reads only the tune name, description
    and created date. Creator/gamertag/ID fields are intentionally ignored.
    """
    try:
        header_path = Path(data_path).parent / "header"
        if not header_path.exists() or not header_path.is_file():
            return {}

        data = header_path.read_bytes()
        if len(data) < 8:
            return {}

        version = struct.unpack_from("<I", data, 0)[0]
        if version != 7:
            return {}

        pos = 4
        tune_name, pos = _read_header_utf16(data, pos)
        description, pos = _read_header_utf16(data, pos)

        created = ""
        created_sort = 0
        if pos + 16 <= len(data):
            year, month, _dow, day, hour, minute, second, ms = struct.unpack_from("<8H", data, pos)
            if 2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                created = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}.{ms:03d}"
                created_sort = (
                    int(year) * 10_000_000_000_000
                    + int(month) * 100_000_000_000
                    + int(day) * 1_000_000_000
                    + int(hour) * 10_000_000
                    + int(minute) * 100_000
                    + int(second) * 1_000
                    + int(ms)
                )

        return {
            "header_name": tune_name,
            "header_description": description,
            "header_created": created,
            "header_created_sort": created_sort,
        }
    except Exception:
        return {}


def parse_tune_file(path: Path) -> TuneFile:
    data = path.read_bytes()
    if len(data) != TUNE_FILE_SIZE:
        raise ValueError(f"Expected {TUNE_FILE_SIZE} bytes, got {len(data)} bytes")
    ordinal = struct.unpack_from("<I", data, ORDINAL_OFFSET)[0]
    upgrades = [
        decode_upgrade(i, struct.unpack_from("<I", data, UPGRADE_OFFSET + i * 4)[0])
        for i in range(UPGRADE_SLOT_COUNT)
    ]
    values = list(struct.unpack_from(f"<{TUNE_FLOAT_COUNT}f", data, DATA_OFFSET))
    header_meta = parse_tune_header_metadata(path)
    return TuneFile(
        path=path,
        raw_bytes=data,
        ordinal=ordinal,
        values=values,
        upgrades=upgrades,
        md5=hashlib.md5(data).hexdigest(),
        header_name=header_meta.get("header_name", ""),
        header_description=header_meta.get("header_description", ""),
        header_created=header_meta.get("header_created", ""),
        header_created_sort=int(header_meta.get("header_created_sort", 0) or 0),
    )


def is_probable_tune_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size == TUNE_FILE_SIZE and path.name.lower().startswith("data")
    except Exception:
        return False


def discover_tune_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if is_probable_tune_file(root) else []
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        if len(found) >= 1500:
            break
        for name in filenames:
            p = Path(dirpath) / name
            if is_probable_tune_file(p):
                found.append(p)
    return found


def thumbnail_cache_path(ordinal: int) -> Path:
    return THUMBNAIL_CACHE_DIR / f"{int(ordinal)}.png"


def thumbnail_ordinal_from_filename(path: Path) -> Optional[int]:
    stem = Path(path).stem.strip()

    # Already cache-style: 1034.png or duplicate-style: 1034_2.png
    match = re.match(r"^(\d{3,7})(?:[_-]\d+)?$", stem)
    if match:
        return int(match.group(1))

    # Forza style: Thumbnail_1034_Big.png
    match = re.search(r"thumbnail[_\-\s]*(\d{3,7})", stem, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Fallback: first useful 3-7 digit token.
    nums = re.findall(r"(?<!\d)(\d{3,7})(?!\d)", stem)
    if nums:
        return int(nums[0])

    return None


def source_thumbnail_path_for_tune(path: Path) -> Path:
    return path.parent / THUMBNAIL_FILENAME


def is_forza_edition_name(name: str) -> bool:
    name_l = str(name or "").lower()
    return "forza edition" in name_l or name_l.endswith(" fe") or " forza ed." in name_l


def car_year_from_name(name: str) -> str:
    match = re.match(r"^\s*(\d{4})\b", str(name or ""))
    return match.group(1) if match else "Unknown"


def car_brand_from_name(name: str) -> str:
    raw = str(name or "").strip()
    try:
        raw = re.sub(r"^\d{4}\s+", "", raw).strip()
    except Exception:
        raw = str(name or "").strip()
    if not raw:
        return "Unknown"
    first = raw.split()[0]
    return first.strip(" -_/") or "Unknown"


def cache_thumb_for_tune(tune: TuneFile):
    src = source_thumbnail_path_for_tune(tune.path)
    if not src.exists():
        return
    pix = QPixmap(str(src))
    if pix.isNull():
        return
    THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pix.save(str(thumbnail_cache_path(tune.ordinal)), "PNG")


def load_pixmap_for_tune(tune: TuneFile, max_size=(220, 110)) -> Optional[QPixmap]:
    for p in [thumbnail_cache_path(tune.ordinal), source_thumbnail_path_for_tune(tune.path)]:
        if p.exists():
            pix = QPixmap(str(p))
            if not pix.isNull():
                return pix.scaled(max_size[0], max_size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None


def _safe_unpack(fmt: str, data: bytes, offset: int):
    try:
        size = struct.calcsize(fmt)
        if offset + size > len(data):
            return None
        return struct.unpack_from(fmt, data, offset)[0]
    except Exception:
        return None


def decode_forza_telemetry_packet(data: bytes) -> dict:
    decoded = {
        "received_unix": time.time(),
        "packet_size": len(data),
        "format": "FH6 official 324-byte" if len(data) == 324 else "Unknown/raw",
        "is_race_on": _safe_unpack("<i", data, 0),
        "timestamp_ms": _safe_unpack("<I", data, 4),
        "rpm": _safe_unpack("<f", data, 16),
        "engine_max_rpm": _safe_unpack("<f", data, 8),
        "suspension_fl": _safe_unpack("<f", data, 68),
        "suspension_fr": _safe_unpack("<f", data, 72),
        "suspension_rl": _safe_unpack("<f", data, 76),
        "suspension_rr": _safe_unpack("<f", data, 80),
        "car_ordinal": _safe_unpack("<i", data, 212),
        "pi": _safe_unpack("<i", data, 220),
        "speed_mps": _safe_unpack("<f", data, 256),
        "power_w": _safe_unpack("<f", data, 260),
        "torque_nm": _safe_unpack("<f", data, 264),
        "tyre_temp_fl": _safe_unpack("<f", data, 268),
        "tyre_temp_fr": _safe_unpack("<f", data, 272),
        "tyre_temp_rl": _safe_unpack("<f", data, 276),
        "tyre_temp_rr": _safe_unpack("<f", data, 280),
        # Best-effort lap/race timer fields for the 324-byte FH6 packet.
        "lap_time_current": _safe_unpack("<f", data, 292),
        "lap_time_last": _safe_unpack("<f", data, 296),
        "lap_time_best": _safe_unpack("<f", data, 300),
        "lap_number": _safe_unpack("<h", data, 304),
        "race_position": _safe_unpack("<B", data, 306),
        "throttle_raw": _safe_unpack("<B", data, 315),
        "brake_raw": _safe_unpack("<B", data, 316),
        "gear": _safe_unpack("<B", data, 319),
        "steer": _safe_unpack("<b", data, 320),
        "raw_hex_preview": data[:64].hex(" "),
    }
    speed = decoded.get("speed_mps")
    if isinstance(speed, (int, float)):
        decoded["speed_mph"] = speed * 2.2369362920544
        decoded["speed_kmh"] = speed * 3.6
    power = decoded.get("power_w")
    if isinstance(power, (int, float)):
        decoded["power_kw"] = power / 1000.0
    for raw_key, pct_key in [("throttle_raw", "throttle"), ("brake_raw", "brake")]:
        raw = decoded.get(raw_key)
        if isinstance(raw, int):
            decoded[pct_key] = raw / 255.0 * 100.0
    ordinal = decoded.get("car_ordinal")
    if isinstance(ordinal, int) and ordinal > 0:
        decoded["telemetry_car_name"] = CAR_DB.get(str(ordinal), f"Unknown car #{ordinal}")
    else:
        decoded["telemetry_car_name"] = "--"
    return decoded


def format_lap_time(seconds) -> str:
    try:
        value = float(seconds)
        if not math.isfinite(value) or value <= 0:
            return "--:--.---"
        minutes = int(value // 60)
        rem = value - minutes * 60
        return f"{minutes}:{rem:06.3f}"
    except Exception:
        return "--:--.---"


def seconds_from_lap_text(value) -> float:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        text_value = str(value or "").strip()
        if not text_value or text_value == "--:--.---":
            return 0.0
        if ":" in text_value:
            minutes, rest = text_value.split(":", 1)
            return int(minutes) * 60 + float(rest)
        return float(text_value)
    except Exception:
        return 0.0


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "share")).strip("_") or "share"


def telemetry_samples_for_share(samples, limit=5000):
    cleaned = []
    for sample in list(samples or [])[-limit:]:
        row = {}
        for key, value in sample.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                row[key] = value
        cleaned.append(row)
    return cleaned


def best_lap_from_samples(samples):
    best = 0.0
    last = 0.0
    current = 0.0
    for sample in samples or []:
        try:
            cur = float(sample.get("lap_time_current") or 0.0)
            la = float(sample.get("lap_time_last") or 0.0)
            be = float(sample.get("lap_time_best") or 0.0)
            if cur > 0:
                current = cur
            if la > 0:
                last = la
            if be > 0 and (best <= 0 or be < best):
                best = be
            if la > 0 and (best <= 0 or la < best):
                best = la
        except Exception:
            pass
    return {
        "current_lap_seconds": current,
        "last_lap_seconds": last,
        "best_lap_seconds": best,
    }



THEME_PRESETS = {
    "WN23 Pink/Cyan": {
        "accent": "#ff2f6d",
        "accent2": "#00d4ff",
        "rounded": 14,
    },
    "Horizon Orange": {
        "accent": "#ff6a00",
        "accent2": "#00d4ff",
        "rounded": 10,
    },
    "Midnight Blue": {
        "accent": "#2f80ff",
        "accent2": "#00d4ff",
        "rounded": 14,
    },
    "Festival Purple": {
        "accent": "#8b5cf6",
        "accent2": "#ec4899",
        "rounded": 16,
    },
    "Carbon Green": {
        "accent": "#10b981",
        "accent2": "#38bdf8",
        "rounded": 8,
    },
    "Gold Dark": {
        "accent": "#fbbf24",
        "accent2": "#ff6a00",
        "rounded": 12,
    },
}


def load_config():
    default = {
        "accent": "#ff2f6d",
        "accent2": "#00d4ff",
        "rounded": 14,
        "telemetry_port": 3010,
        "speed_unit": "mph",
        "auto_update_check": False,
        "auto_thumbnail_cache_update": False,
        "auto_load_current_car_tune": True,
        "sidebar_width": 210,
        "thumbnail_cache_branch": DEFAULT_THUMBNAIL_CACHE_BRANCH,
        "thumbnail_cache_path": DEFAULT_THUMBNAIL_CACHE_PATH,
        "first_setup_done": False,
        # The scan folder must stay separate from the last loaded tune file.
        # Older builds accidentally saved an individual Tuning_#### folder here,
        # which made the next launch scan only one tune. v1.3.0 keeps a stable
        # scan root/glob and stores the last selected tune separately.
        "last_tune_folder": DEFAULT_TUNE_FOLDER_GLOB,
        "last_scan_folder": DEFAULT_TUNE_FOLDER_GLOB,
        "last_loaded_tune_file": "",
        "auto_detect_tune_folder": True,
        "dev_mode": False,
        "update_repo_owner": DEFAULT_GITHUB_REPO_OWNER,
        "update_repo_name": DEFAULT_GITHUB_REPO_NAME,
    }
    try:
        if CONFIG_PATH.exists():
            default.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass

    # Migration/fix: older builds stored a single tune's Tuning_#### folder as
    # last_tune_folder after loading tunes. That broke later launches because
    # the app scanned only that one tune folder. Keep scan roots and last file
    # separate from v1.3.0 onward.
    folder_value = str(default.get("last_tune_folder") or DEFAULT_TUNE_FOLDER_GLOB).strip()
    folder_norm = folder_value.replace("\\", "/").lower()
    folder_leaf = folder_norm.rstrip("/").split("/")[-1] if folder_norm else ""
    looks_like_single_tune_folder = folder_leaf.startswith("tuning_") or "/tuning_" in folder_norm
    if looks_like_single_tune_folder:
        default["last_loaded_tune_file"] = str(default.get("last_loaded_tune_file") or "")
        default["last_tune_folder"] = DEFAULT_TUNE_FOLDER_GLOB
        default["last_scan_folder"] = DEFAULT_TUNE_FOLDER_GLOB
        default["auto_detect_tune_folder"] = True
    else:
        default["last_scan_folder"] = str(default.get("last_scan_folder") or folder_value or DEFAULT_TUNE_FOLDER_GLOB)
        default["last_tune_folder"] = str(default.get("last_tune_folder") or default["last_scan_folder"] or DEFAULT_TUNE_FOLDER_GLOB)
    if not default.get("last_scan_folder"):
        default["last_scan_folder"] = DEFAULT_TUNE_FOLDER_GLOB
    if not default.get("last_tune_folder"):
        default["last_tune_folder"] = default["last_scan_folder"]
    return default


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def parse_version_tuple(value: str):
    """Turn tags like v12.4.4, 12.4.4-beta, release-12.4.4 into comparable tuples."""
    text_value = str(value or "").strip().lower()
    match = re.search(r"(\d+(?:\.\d+){0,3})", text_value)
    if not match:
        return ()
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def is_newer_version(latest: str, current: str) -> bool:
    latest_tuple = parse_version_tuple(latest)
    current_tuple = parse_version_tuple(current)
    if not latest_tuple:
        return False
    return latest_tuple > current_tuple


def fetch_latest_github_release(owner: str, repo: str):
    raise RuntimeError("Automatic update checks are disabled in the public build.")



def read_github_json_url(url: str):
    raise RuntimeError("Automatic thumbnail downloads are disabled in the public build.")



def normalise_hex_colour(value: str, fallback: str = "#ff2f6d") -> str:
    try:
        value = str(value).strip()
        colour = QColor(value)
        if colour.isValid():
            return colour.name()
    except Exception:
        pass
    return fallback


def blend_hex(fg: str, bg: str = "#071017", amount: float = 0.25) -> str:
    """Blend fg into bg and return a plain #RRGGBB colour.

    This avoids Qt stylesheet inconsistencies with #RRGGBBAA alpha colours.
    """
    try:
        fg_c = QColor(normalise_hex_colour(fg))
        bg_c = QColor(normalise_hex_colour(bg, "#071017"))
        amount = max(0.0, min(1.0, float(amount)))
        r = round(bg_c.red() + (fg_c.red() - bg_c.red()) * amount)
        g = round(bg_c.green() + (fg_c.green() - bg_c.green()) * amount)
        b = round(bg_c.blue() + (fg_c.blue() - bg_c.blue()) * amount)
        return QColor(r, g, b).name()
    except Exception:
        return bg


class Speedometer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.speed = 0.0
        self.rpm = 0.0
        self.gear = 0
        self.unit = "MPH"
        self.scale = 300.0
        self.accent = QColor("#ff2f6d")
        self.setMinimumHeight(235)

    def set_accent(self, color: str):
        self.accent = QColor(color)
        self.update()

    def set_values(self, speed, rpm=0, gear=0, unit="MPH"):
        try:
            self.speed = max(0.0, float(speed or 0.0))
        except Exception:
            self.speed = 0.0
        try:
            self.rpm = float(rpm or 0.0)
        except Exception:
            self.rpm = 0.0
        try:
            self.gear = int(gear or 0)
        except Exception:
            self.gear = 0
        self.unit = unit
        base = 500 if unit == "KM/H" else 300
        step = 100 if unit == "KM/H" else 50
        self.scale = max(base, math.ceil(max(self.speed, 1) / step) * step)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h - 30
        r = min(w / 2 - 35, h - 45)

        p.setPen(QPen(QColor("#26364a"), 16))
        p.drawArc(QRectF(cx-r, cy-r, r*2, r*2), 30*16, 120*16)
        p.setPen(QPen(self.accent, 7))
        p.drawArc(QRectF(cx-r, cy-r, r*2, r*2), 30*16, 120*16)

        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.setPen(QColor("#a7bad6"))
        for i in range(7):
            frac = i / 6
            deg = math.radians(150 - frac*120)
            x1, y1 = cx + (r-5)*math.cos(deg), cy - (r-5)*math.sin(deg)
            x2, y2 = cx + (r-20)*math.cos(deg), cy - (r-20)*math.sin(deg)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
            label = str(int(round(frac * self.scale)))
            tx, ty = cx + (r-42)*math.cos(deg), cy - (r-42)*math.sin(deg)
            p.drawText(int(tx-18), int(ty-8), 36, 18, Qt.AlignCenter, label)

        frac = min(self.speed, self.scale) / max(self.scale, 1)
        deg = math.radians(150 - frac*120)
        xn, yn = cx + (r-28)*math.cos(deg), cy - (r-28)*math.sin(deg)
        p.setPen(QPen(self.accent, 5))
        p.drawLine(int(cx), int(cy), int(xn), int(yn))
        p.setBrush(QBrush(self.accent))
        p.drawEllipse(QPointF(cx, cy), 7, 7)

        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Segoe UI", 30, QFont.Black))
        p.drawText(QRectF(0, cy-95, w, 45), Qt.AlignCenter, f"{self.speed:.1f}")
        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.setPen(QColor("#a7bad6"))
        p.drawText(QRectF(0, cy-55, w, 24), Qt.AlignCenter, self.unit)
        p.drawText(QRectF(25, cy-15, w/2-30, 24), Qt.AlignLeft, f"GEAR {self.gear}")
        p.drawText(QRectF(w/2, cy-15, w/2-25, 24), Qt.AlignRight, f"{self.rpm:.0f} RPM")


class SteeringWheel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.steer = 0.0
        self.accent = QColor("#ff2f6d")
        self.setMinimumHeight(235)

    def set_accent(self, color: str):
        self.accent = QColor(color)
        self.update()

    def set_value(self, steer):
        try:
            self.steer = max(-127.0, min(127.0, float(steer or 0.0)))
        except Exception:
            self.steer = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 + 50
        r = min(w, h) / 4
        direction = "STRAIGHT"
        if self.steer < -8:
            direction = "LEFT"
        elif self.steer > 8:
            direction = "RIGHT"

        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Segoe UI", 30, QFont.Black))
        p.drawText(QRectF(0, 18, w, 42), Qt.AlignCenter, str(int(round(self.steer))))
        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.setPen(QColor("#a7bad6"))
        p.drawText(QRectF(0, 56, w, 24), Qt.AlignCenter, direction)

        p.setPen(QPen(QColor("#26364a"), 4))
        guide = r + 34
        p.drawArc(QRectF(cx-guide, cy-guide, guide*2, guide*2), 30*16, 120*16)

        rot = math.radians((self.steer / 127.0) * 110.0)
        p.setPen(QPen(self.accent, 8))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(QColor("#ffffff"), 4))
        p.drawEllipse(QPointF(cx, cy), 13, 13)
        for base_deg in [-90, 30, 150]:
            a = math.radians(base_deg) + rot
            x, y = cx + (r-8)*math.cos(a), cy + (r-8)*math.sin(a)
            p.drawLine(QPointF(cx, cy), QPointF(x, y))
        a = math.radians(-90) + rot
        p.setPen(QPen(QColor("#ffffff"), 6))
        p.drawLine(QPointF(cx + (r-18)*math.cos(a), cy + (r-18)*math.sin(a)),
                   QPointF(cx + r*math.cos(a), cy + r*math.sin(a)))


class Tachometer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rpm = 0.0
        self.max_rpm = 8000.0
        self.throttle = 0.0
        self.accent = QColor("#ff2f6d")
        self.setMinimumHeight(235)

    def set_accent(self, color: str):
        self.accent = QColor(color)
        self.update()

    def set_values(self, rpm, max_rpm=8000, throttle=0.0):
        try:
            self.rpm = max(0.0, float(rpm or 0.0))
        except Exception:
            self.rpm = 0.0
        try:
            self.max_rpm = max(1000.0, float(max_rpm or 8000.0))
        except Exception:
            self.max_rpm = 8000.0
        try:
            self.throttle = max(0.0, min(100.0, float(throttle or 0.0)))
        except Exception:
            self.throttle = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h - 32
        r = min(w / 2 - 35, h - 45)

        rect = QRectF(cx-r, cy-r, r*2, r*2)
        start_angle = 30 * 16
        span_angle = 120 * 16
        p.setPen(QPen(QColor('#26364a'), 16))
        p.drawArc(rect, start_angle, span_angle)

        redline_frac = 0.82
        p.setPen(QPen(self.accent, 7))
        p.drawArc(rect, start_angle, int(span_angle * redline_frac))
        p.setPen(QPen(QColor('#ef4444'), 8))
        p.drawArc(rect, start_angle + int(span_angle * redline_frac), int(span_angle * (1 - redline_frac)))

        p.setPen(QColor('#a7bad6'))
        p.setFont(QFont('Segoe UI', 9, QFont.Bold))
        major = 8
        for i in range(major + 1):
            frac = i / major
            deg = math.radians(150 - frac*120)
            outer = r - 4
            inner = r - (24 if i % 2 == 0 else 16)
            x1, y1 = cx + outer*math.cos(deg), cy - outer*math.sin(deg)
            x2, y2 = cx + inner*math.cos(deg), cy - inner*math.sin(deg)
            pen = QPen(QColor('#ef4444') if frac >= redline_frac else QColor('#d8e2ee'), 2)
            p.setPen(pen)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
            label = str(int(round((frac * self.max_rpm) / 1000.0)))
            tx, ty = cx + (r-46)*math.cos(deg), cy - (r-46)*math.sin(deg)
            p.setPen(QColor('#a7bad6'))
            p.drawText(int(tx-16), int(ty-8), 32, 18, Qt.AlignCenter, label)

        frac = max(0.0, min(1.0, self.rpm / max(self.max_rpm, 1.0)))
        deg = math.radians(150 - frac*120)
        xn, yn = cx + (r-26)*math.cos(deg), cy - (r-26)*math.sin(deg)
        p.setPen(QPen(self.accent, 5))
        p.drawLine(int(cx), int(cy), int(xn), int(yn))
        p.setBrush(QBrush(self.accent))
        p.drawEllipse(QPointF(cx, cy), 7, 7)

        p.setPen(QColor('#ffffff'))
        p.setFont(QFont('Segoe UI', 30, QFont.Black))
        p.drawText(QRectF(0, cy-98, w, 42), Qt.AlignCenter, f'{self.rpm:.0f}')
        p.setFont(QFont('Segoe UI', 10, QFont.Bold))
        p.setPen(QColor('#a7bad6'))
        p.drawText(QRectF(0, cy-56, w, 20), Qt.AlignCenter, 'RPM')
        p.drawText(QRectF(0, cy-34, w, 20), Qt.AlignCenter, f'Max {self.max_rpm:.0f}  ·  Throttle {self.throttle:.0f}%')


class TyreStatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.accent = QColor('#ff2f6d')
        self.front_psi = None
        self.rear_psi = None
        self.temps = {'FL': None, 'FR': None, 'RL': None, 'RR': None}
        self.setMinimumHeight(220)

    def set_accent(self, color: str):
        self.accent = QColor(color)
        self.update()

    def set_values(self, temps: dict, front_psi=None, rear_psi=None):
        for key in ['FL', 'FR', 'RL', 'RR']:
            val = temps.get(key) if isinstance(temps, dict) else None
            try:
                self.temps[key] = float(val) if val is not None else None
            except Exception:
                self.temps[key] = None
        self.front_psi = front_psi
        self.rear_psi = rear_psi
        self.update()

    def _temp_colour(self, value):
        if value is None:
            return QColor('#607487')
        # Rough visual bands only: cold / warming / good / hot / overheated.
        if value < 45:
            return QColor('#60a5fa')
        if value < 65:
            return QColor('#38bdf8')
        if value < 90:
            return QColor('#22c55e')
        if value < 105:
            return QColor('#f59e0b')
        return QColor('#ef4444')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        margin = 16
        gap = 14
        box_w = (w - margin*2 - gap) / 2
        box_h = (h - margin*2 - gap - 42) / 2

        layout = [
            ('FL', QRectF(margin, margin, box_w, box_h)),
            ('FR', QRectF(margin + box_w + gap, margin, box_w, box_h)),
            ('RL', QRectF(margin, margin + box_h + gap, box_w, box_h)),
            ('RR', QRectF(margin + box_w + gap, margin + box_h + gap, box_w, box_h)),
        ]
        for key, rect in layout:
            temp = self.temps.get(key)
            fill = self._temp_colour(temp)
            fill_bg = QColor(fill)
            fill_bg.setAlpha(42)
            p.setPen(QPen(QColor('#2d3a49'), 1))
            p.setBrush(QBrush(fill_bg))
            p.drawRoundedRect(rect, 12, 12)

            p.setPen(QColor('#dce7f2'))
            p.setFont(QFont('Segoe UI', 10, QFont.Bold))
            p.drawText(rect.adjusted(12, 10, -12, 0), Qt.AlignLeft | Qt.AlignTop, key)

            p.setPen(fill)
            p.setFont(QFont('Segoe UI', 22, QFont.Black))
            temp_text = '--' if temp is None else f'{temp:.0f}°C'
            p.drawText(rect.adjusted(0, 8, 0, 0), Qt.AlignCenter, temp_text)

            pressure = self.front_psi if key in ('FL', 'FR') else self.rear_psi
            p.setPen(QColor('#a7bad6'))
            p.setFont(QFont('Segoe UI', 9, QFont.Bold))
            pressure_text = '--' if pressure is None else f'Tune {pressure:.1f} PSI'
            p.drawText(rect.adjusted(12, 0, -12, -10), Qt.AlignLeft | Qt.AlignBottom, pressure_text)

        footer = QRectF(margin, h - 34, w - margin*2, 22)
        p.setPen(QColor('#91a4b7'))
        p.setFont(QFont('Segoe UI', 9, QFont.Bold))
        front = '--' if self.front_psi is None else f'{self.front_psi:.1f} PSI'
        rear = '--' if self.rear_psi is None else f'{self.rear_psi:.1f} PSI'
        p.drawText(footer, Qt.AlignCenter, f'Tyre temps are live telemetry · Pressure values use loaded tune targets  ·  Front {front} / Rear {rear}')


class PedalBarsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.throttle = 0.0
        self.brake = 0.0
        self.accent = QColor("#ff2f6d")
        self.setMinimumHeight(220)

    def set_accent(self, color: str):
        self.accent = QColor(color)
        self.update()

    def set_values(self, throttle, brake):
        try:
            self.throttle = max(0.0, min(100.0, float(throttle or 0.0)))
        except Exception:
            self.throttle = 0.0
        try:
            self.brake = max(0.0, min(100.0, float(brake or 0.0)))
        except Exception:
            self.brake = 0.0
        self.update()

    def _bar(self, p, rect, value, label, color):
        p.setPen(QPen(QColor("#2d3a49"), 1))
        p.setBrush(QBrush(QColor("#0b1118")))
        p.drawRoundedRect(rect, 14, 14)

        fill_h = rect.height() * (value / 100.0)
        fill = QRectF(rect.left(), rect.bottom() - fill_h, rect.width(), fill_h)
        glow = QColor(color)
        glow.setAlpha(80)
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(fill, 14, 14)

        p.setPen(QPen(color, 3))
        p.drawRoundedRect(rect, 14, 14)

        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Segoe UI", 20, QFont.Black))
        p.drawText(rect.adjusted(0, 20, 0, -20), Qt.AlignCenter, f"{value:.0f}%")
        p.setPen(QColor("#a7bad6"))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.drawText(rect.adjusted(0, 0, 0, -12), Qt.AlignHCenter | Qt.AlignBottom, label)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QColor("#91a4b7"))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(0, 4, w, 20), Qt.AlignCenter, "LIVE INPUTS")

        margin = 24
        top = 32
        gap = 22
        bar_w = (w - margin*2 - gap) / 2
        bar_h = h - top - 28

        throttle_rect = QRectF(margin, top, bar_w, bar_h)
        brake_rect = QRectF(margin + bar_w + gap, top, bar_w, bar_h)

        self._bar(p, throttle_rect, self.throttle, "THROTTLE", QColor("#22c55e"))
        self._bar(p, brake_rect, self.brake, "BRAKE", QColor("#ef4444"))


class SuspensionTravelWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.accent = QColor("#ff2f6d")
        self.values = {"FL": 0.0, "FR": 0.0, "RL": 0.0, "RR": 0.0}
        self.setMinimumHeight(220)

    def set_accent(self, color: str):
        self.accent = QColor(color)
        self.update()

    def set_values(self, values: dict):
        for key in ["FL", "FR", "RL", "RR"]:
            try:
                self.values[key] = float(values.get(key) or 0.0)
            except Exception:
                self.values[key] = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QColor("#91a4b7"))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(0, 4, w, 20), Qt.AlignCenter, "SUSPENSION TRAVEL")

        # Use relative visual scaling because FH suspension values vary by car.
        vals = [abs(v) for v in self.values.values()]
        max_val = max(vals + [0.01])

        margin = 22
        top = 34
        gap = 14
        cell_w = (w - margin*2 - gap) / 2
        cell_h = (h - top - margin - gap) / 2

        positions = [
            ("FL", QRectF(margin, top, cell_w, cell_h)),
            ("FR", QRectF(margin + cell_w + gap, top, cell_w, cell_h)),
            ("RL", QRectF(margin, top + cell_h + gap, cell_w, cell_h)),
            ("RR", QRectF(margin + cell_w + gap, top + cell_h + gap, cell_w, cell_h)),
        ]

        for key, rect in positions:
            val = self.values.get(key, 0.0)
            frac = max(0.0, min(1.0, abs(val) / max_val))
            p.setPen(QPen(QColor("#2d3a49"), 1))
            p.setBrush(QBrush(QColor("#0b1118")))
            p.drawRoundedRect(rect, 12, 12)

            p.setPen(QColor("#dce7f2"))
            p.setFont(QFont("Segoe UI", 10, QFont.Bold))
            p.drawText(rect.adjusted(10, 6, -10, 0), Qt.AlignLeft | Qt.AlignTop, key)

            travel_rect = rect.adjusted(16, 28, -16, -16)
            center_y = travel_rect.center().y()
            p.setPen(QPen(QColor("#26364a"), 5))
            p.drawLine(QPointF(travel_rect.left(), center_y), QPointF(travel_rect.right(), center_y))

            x = travel_rect.left() + travel_rect.width() * frac
            p.setPen(QPen(self.accent, 6))
            p.drawLine(QPointF(travel_rect.left(), center_y), QPointF(x, center_y))
            p.setBrush(QBrush(self.accent))
            p.drawEllipse(QPointF(x, center_y), 7, 7)

            p.setPen(QColor("#a7bad6"))
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(rect.adjusted(10, 0, -10, -8), Qt.AlignRight | Qt.AlignBottom, f"{val:.3f}")


class TelemetryHudStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.accent = QColor("#ff2f6d")
        self.values = {
            "car": "--",
            "speed": "--",
            "gear": "--",
            "rpm": "--",
            "lap": "--",
            "status": "WAITING",
        }
        self.setMinimumHeight(88)

    def set_accent(self, color: str):
        self.accent = QColor(color)
        self.update()

    def set_values(self, **kwargs):
        self.values.update(kwargs)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(4, 4, w - 8, h - 8)

        bg = QColor("#071017")
        bg.setAlpha(230)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor("#293746"), 1))
        p.drawRoundedRect(rect, 18, 18)

        p.setPen(QPen(self.accent, 3))
        p.drawLine(QPointF(26, h - 12), QPointF(w - 26, h - 12))

        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Segoe UI", 17, QFont.Black))
        p.drawText(QRectF(24, 10, w * 0.42, 32), Qt.AlignLeft | Qt.AlignVCenter, str(self.values.get("car", "--")))

        p.setPen(QColor("#a7bad6"))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(26, 45, w * 0.42, 20), Qt.AlignLeft | Qt.AlignVCenter, str(self.values.get("status", "WAITING")))

        items = [
            ("SPEED", self.values.get("speed", "--")),
            ("GEAR", self.values.get("gear", "--")),
            ("RPM", self.values.get("rpm", "--")),
            ("LAP", self.values.get("lap", "--")),
        ]
        x = w * 0.47
        box_w = (w * 0.50) / 4
        for label, value in items:
            p.setPen(QColor("#91a4b7"))
            p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            p.drawText(QRectF(x, 12, box_w, 16), Qt.AlignCenter, label)
            p.setPen(QColor("#ffffff"))
            p.setFont(QFont("Segoe UI", 16, QFont.Black))
            p.drawText(QRectF(x, 28, box_w, 34), Qt.AlignCenter, str(value))
            x += box_w


class Card(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self.body = layout
        if title:
            lbl = QLabel(title.upper())
            lbl.setObjectName("sectionTitle")
            layout.addWidget(lbl)


class TuneCard(QWidget):
    def __init__(self, tune: TuneFile):
        super().__init__()
        self.tune = tune
        self.is_fe = is_forza_edition_name(tune.car_name)
        self.setObjectName("tuneCardFE" if self.is_fe else "tuneCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        title = QLabel(tune.car_name)
        title.setObjectName("tuneTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        if getattr(tune, "header_name", ""):
            header_name = QLabel(tune.header_name)
            header_name.setObjectName("tuneHeaderName")
            header_name.setWordWrap(True)
            header_name.setToolTip("Tune name auto-loaded from the header file beside Data.")
            layout.addWidget(header_name)

        if self.is_fe:
            badge = QLabel("★ FORZA EDITION")
            badge.setObjectName("feBadge")
            badge.setAlignment(Qt.AlignCenter)
            layout.addWidget(badge)
        img = QLabel("NO THUMB")
        img.setObjectName("thumb")
        img.setAlignment(Qt.AlignCenter)
        pix = load_pixmap_for_tune(tune)
        if pix:
            img.setPixmap(pix)
        layout.addWidget(img)
        meta = QLabel(f"{tune.drivetrain_label} · {tune.active_gear_count} GEARS · #{tune.ordinal}")
        meta.setObjectName("meta")
        layout.addWidget(meta)


# ---------------------------------------------------------------------------
# Car card viewer + tuning assist prototype integration
# ---------------------------------------------------------------------------
CLASS_COLOURS = {
    "X": ("#19d858", "#6eff9b"),
    "R": ("#d61a9c", "#ff70d3"),
    "S2": ("#165edb", "#69a2ff"),
    "S1": ("#b960e8", "#dda2ff"),
    "A": ("#ff1a46", "#ff7f99"),
    "B": ("#ff632c", "#ffac84"),
    "C": ("#ffc533", "#ffe08b"),
    "D": ("#42bdf4", "#a4e6ff"),
}
FORZA_EDITION_GRADIENT = ["#dc3add", "#ca40e1", "#a34dec", "#765ff8", "#436efe"]


def class_from_pi(pi) -> str:
    try:
        pi = int(pi)
    except Exception:
        return "FH6"
    if pi >= 999:
        return "X"
    if pi >= 901:
        return "S2"
    if pi >= 801:
        return "S1"
    if pi >= 701:
        return "A"
    if pi >= 601:
        return "B"
    if pi >= 501:
        return "C"
    return "D"


def clean_forza_edition_name(name: str, is_fe: bool = False) -> str:
    name = str(name or "").strip()
    if not is_fe:
        return name or "Unknown Car"
    for pattern in [r"\s+Forza\s+Edition\b", r"\s+FORZA\s+EDITION\b", r"\s+Forza\s+Ed\.?\b", r"\s+FE\b"]:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
    return re.sub(r"\s{2,}", " ", name).strip(" -_/") or "Unknown Forza Edition Car"


def tune_display_value(tune: TuneFile, field_index: int):
    try:
        field = FIELD_BY_INDEX[field_index]
        return field.raw_to_display(tune.values[field_index])
    except Exception:
        return None


def format_field_display(field_index: int, value) -> str:
    field = FIELD_BY_INDEX.get(field_index)
    if field is None or value is None:
        return "--"
    try:
        return field.format_display(value)
    except Exception:
        return "--"


def telemetry_pi_for_tune(tune: Optional[TuneFile], telemetry: dict):
    if not tune or not telemetry:
        return None
    try:
        if int(telemetry.get("car_ordinal") or -1) != int(tune.ordinal):
            return None
        pi = telemetry.get("pi")
        return int(pi) if pi is not None and int(pi) > 0 else None
    except Exception:
        return None



class CarShowcaseCardWidget(QWidget):
    """
    Main-tuner wrapper around the standalone WN_CarCard_Prototype_v0_5_1 renderer.

    Difference from the standalone prototype:
    - data comes from the currently loaded TuneFile
    - thumbnail comes from thumbnail_cache / share folder, or optional manual image override
    - class/PI are not invented because they are not reliably stored in the tune file
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tune: Optional[TuneFile] = None
        self.show_back = False
        self.accent = QColor("#ff2f6d")
        self.accent2 = QColor("#00d4ff")
        self.manual_image_path = ""
        self.manual_stats = {
            "enabled": False,
            "card_class": "A",
            "pi": 800,
            "power_hp": 276,
            "weight_kg": 1260,
            "top_speed_mph": 156,
            "handling": 7.4,
            "acceleration": 6.8,
            "launch": 7.2,
            "braking": 6.9,
            "force_holographic": False,
        }
        self.logo = QPixmap(str(LOGO_IMAGE_PATH if LOGO_IMAGE_PATH.exists() else LOGO_IMAGE_PATH_ALT))
        self._shine_phase = 0
        self._shine_timer = QTimer(self)
        self._shine_timer.timeout.connect(self._tick_shine)
        self._shine_timer.start(55)
        self.setMinimumSize(540, 780)
        self.setMaximumWidth(590)

    def _tick_shine(self):
        force_holo = bool(self.manual_stats.get("force_holographic"))
        if self.tune and (is_forza_edition_name(self.tune.car_name) or force_holo) and not self.show_back:
            self._shine_phase = (self._shine_phase + 1) % 240
            self.update()

    def set_accent(self, color: str):
        try:
            self.accent = QColor(color)
            if not self.accent.isValid():
                self.accent = QColor("#ff2f6d")
        except Exception:
            self.accent = QColor("#ff2f6d")
        self.update()

    def set_tune(self, tune: Optional[TuneFile], telemetry: Optional[dict] = None):
        # Deliberately tune-only. Telemetry is not used for this card.
        self.tune = tune
        self.update()

    def set_manual_image(self, path: str):
        self.manual_image_path = path or ""
        self.update()

    def clear_manual_image(self):
        self.manual_image_path = ""
        self.update()

    def set_manual_stats(self, **stats):
        self.manual_stats.update(stats)
        self.update()

    def toggle_side(self):
        self.show_back = not self.show_back
        self.update()

    def _rounded_path(self, rect: QRectF, radius: float):
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _draw_badge(self, painter: QPainter, rect: QRectF, text: str, fill, outline: QColor):
        path = self._rounded_path(rect, 18)
        painter.fillPath(path, fill)
        painter.setPen(QPen(outline, 2))
        painter.drawPath(path)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 12 if len(text) > 10 else 14, QFont.Black))
        painter.drawText(rect, Qt.AlignCenter, text)

    def _forza_edition_badge_gradient(self, rect: QRectF) -> QLinearGradient:
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        for i, colour in enumerate(FORZA_EDITION_GRADIENT):
            grad.setColorAt(i / max(1, len(FORZA_EDITION_GRADIENT) - 1), QColor(colour))
        return grad

    def _fit_font_to_rect(self, painter: QPainter, text: str, rect: QRectF, start_size: int, min_size: int = 10):
        size = start_size
        while size > min_size:
            font = QFont("Segoe UI", size, QFont.Black)
            painter.setFont(font)
            if painter.fontMetrics().horizontalAdvance(text) <= rect.width():
                return font
            size -= 1
        font = QFont("Segoe UI", min_size, QFont.Black)
        painter.setFont(font)
        return font

    def _draw_shiny_overlay(self, painter: QPainter, rect: QRectF):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        phase = self._shine_phase
        path = self._rounded_path(rect, 28)

        wash = QLinearGradient(rect.topLeft(), rect.topRight())
        for i, colour in enumerate(FORZA_EDITION_GRADIENT):
            wash.setColorAt(i / max(1, len(FORZA_EDITION_GRADIENT) - 1), QColor(colour))
        painter.setOpacity(0.28)
        painter.fillPath(path, wash)
        painter.setOpacity(1.0)

        sweep_x = rect.left() - rect.width() * 0.45 + (phase / 240.0) * rect.width() * 1.9
        sweep = QLinearGradient(QPointF(sweep_x, rect.top()), QPointF(sweep_x + rect.width() * 0.35, rect.bottom()))
        sweep.setColorAt(0.00, QColor(255, 255, 255, 0))
        sweep.setColorAt(0.42, QColor(255, 255, 255, 0))
        sweep.setColorAt(0.50, QColor(255, 255, 255, 115))
        sweep.setColorAt(0.58, QColor(255, 255, 255, 0))
        sweep.setColorAt(1.00, QColor(255, 255, 255, 0))
        painter.fillPath(path, sweep)

        painter.setPen(QPen(QColor(255, 255, 255, 28), 1.25))
        offset = phase % 42
        x = rect.left() - 160 + offset
        while x < rect.right() + 180:
            painter.drawLine(QPointF(x, rect.bottom()), QPointF(x + 160, rect.top()))
            x += 42

        sparkle_data = [
            (0.15, 0.18, 0),
            (0.74, 0.17, 30),
            (0.28, 0.70, 60),
            (0.82, 0.66, 90),
            (0.52, 0.10, 125),
            (0.60, 0.82, 170),
        ]
        for sx_ratio, sy_ratio, delay in sparkle_data:
            local = ((phase + delay) % 120) / 120.0
            alpha = int(35 + 190 * max(0.0, 1.0 - abs(local - 0.5) * 2.0))
            radius = 2.0 + 4.5 * max(0.0, 1.0 - abs(local - 0.5) * 2.0)
            sx = rect.left() + rect.width() * sx_ratio
            sy = rect.top() + rect.height() * sy_ratio

            painter.setPen(QPen(QColor(255, 255, 255, alpha), 1.5))
            painter.drawLine(QPointF(sx - radius * 2.1, sy), QPointF(sx + radius * 2.1, sy))
            painter.drawLine(QPointF(sx, sy - radius * 2.1), QPointF(sx, sy + radius * 2.1))
            painter.setBrush(QColor(255, 255, 255, min(255, alpha + 30)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(sx, sy), radius, radius)

        painter.restore()

    def _card_pixmap(self, image_rect: QRectF):
        if self.manual_image_path:
            pix = QPixmap(self.manual_image_path)
            if not pix.isNull():
                return pix.scaled(
                    int(image_rect.width() - 28),
                    int(image_rect.height() - 28),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )

        if self.tune:
            return load_pixmap_for_tune(
                self.tune,
                max_size=(int(image_rect.width() - 28), int(image_rect.height() - 28))
            )
        return None

    def _display_value(self, idx: int) -> str:
        if not self.tune:
            return "--"
        value = tune_display_value(self.tune, idx)
        return format_field_display(idx, value)

    def _manual_int(self, key: str, unit: str = "") -> str:
        try:
            value = int(float(self.manual_stats.get(key, 0)))
        except Exception:
            return "--"
        if value <= 0:
            return "--"
        return f"{value} {unit}".strip()

    def _manual_rating(self, key: str) -> str:
        try:
            value = float(self.manual_stats.get(key, 0))
        except Exception:
            return "--"
        if value <= 0:
            return "--"
        return f"{value:.1f}"

    def _paint_back(self, painter: QPainter, outer: QRectF, inner: QRectF):
        frame_grad = QLinearGradient(outer.topLeft(), outer.bottomRight())
        frame_grad.setColorAt(0.0, QColor("#52090f"))
        frame_grad.setColorAt(0.2, QColor("#7e151f"))
        frame_grad.setColorAt(0.5, QColor("#16090c"))
        frame_grad.setColorAt(0.8, QColor("#9b1b29"))
        frame_grad.setColorAt(1.0, QColor("#26070c"))
        painter.fillPath(self._rounded_path(outer, 32), frame_grad)
        painter.setPen(QPen(QColor(255, 96, 96, 110), 1.5))
        painter.drawPath(self._rounded_path(outer, 32))

        bg = QLinearGradient(inner.topLeft(), inner.bottomRight())
        bg.setColorAt(0.0, QColor("#040507"))
        bg.setColorAt(0.38, QColor("#12060b"))
        bg.setColorAt(0.68, QColor("#360910"))
        bg.setColorAt(1.0, QColor("#090a11"))
        inner_path = self._rounded_path(inner, 28)
        painter.fillPath(inner_path, bg)

        radial = QRadialGradient(QPointF(inner.center().x(), inner.center().y() - 40), inner.width() * 0.75)
        radial.setColorAt(0.0, QColor(200, 30, 52, 60))
        radial.setColorAt(0.55, QColor(120, 16, 28, 18))
        radial.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(inner_path, radial)

        gloss = QLinearGradient(QPointF(inner.left(), inner.top()+40), QPointF(inner.right(), inner.bottom()-40))
        gloss.setColorAt(0.0, QColor(255,255,255,10))
        gloss.setColorAt(0.5, QColor(255,255,255,30))
        gloss.setColorAt(1.0, QColor(255,255,255,0))
        painter.setOpacity(0.4)
        painter.fillPath(inner_path, gloss)
        painter.setOpacity(1.0)

        painter.setClipPath(inner_path)
        painter.setPen(QPen(QColor(255, 70, 90, 25), 2))
        x = inner.left() - 120
        while x < inner.right() + 120:
            painter.drawLine(QPointF(x, inner.bottom()), QPointF(x + 160, inner.top()))
            x += 42
        painter.setClipping(False)

        logo_rect = QRectF(inner.left()+70, inner.top()+120, inner.width()-140, 120)
        if not self.logo.isNull():
            scaled = self.logo.scaled(int(logo_rect.width()), int(logo_rect.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = logo_rect.center().x() - scaled.width()/2
            y = logo_rect.center().y() - scaled.height()/2
            painter.drawPixmap(int(x), int(y), scaled)
        else:
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI", 24, QFont.Black))
            painter.drawText(logo_rect, Qt.AlignCenter, "WN FORZA TUNER")

        title_rect = QRectF(inner.left()+50, inner.center().y()-10, inner.width()-100, 90)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 28, QFont.Black, italic=True))
        painter.drawText(QRectF(title_rect.left(), title_rect.top(), title_rect.width(), 40), Qt.AlignCenter, "FORZA HORIZON 6")
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.setPen(QColor(255, 195, 195, 220))
        painter.drawText(QRectF(title_rect.left(), title_rect.top()+42, title_rect.width(), 22), Qt.AlignCenter, "WN Forza Tuner • Reverse Side")

        streak = QRectF(inner.left()+70, inner.center().y()+88, inner.width()-140, 12)
        streak_grad = QLinearGradient(streak.topLeft(), streak.topRight())
        streak_grad.setColorAt(0.0, QColor("#6f0f1b"))
        streak_grad.setColorAt(0.5, QColor("#ff3b4f"))
        streak_grad.setColorAt(1.0, QColor("#4e0d14"))
        painter.fillPath(self._rounded_path(streak, 6), streak_grad)

        footer_box = QRectF(inner.left()+34, inner.bottom()-130, inner.width()-68, 86)
        painter.fillPath(self._rounded_path(footer_box, 20), QColor(255,255,255,12))
        painter.setPen(QPen(QColor(255,255,255,45), 1.2))
        painter.drawPath(self._rounded_path(footer_box, 20))

        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(QRectF(footer_box.left()+20, footer_box.top()+14, footer_box.width()-40, 18), Qt.AlignCenter, 'Click "Flip Card" to return to the front')
        painter.setPen(QColor(255, 215, 215, 210))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(footer_box.left()+20, footer_box.top()+40, footer_box.width()-40, 16), Qt.AlignCenter, "Front: loaded tune card • Back: branding / collectible card reverse")
        painter.drawText(QRectF(footer_box.left()+20, footer_box.top()+58, footer_box.width()-40, 16), Qt.AlignCenter, f"WN Forza Tuner Car View • v{APP_VERSION}")

    def _paint_front(self, painter: QPainter, outer: QRectF, inner: QRectF):
        tune = self.tune
        if not tune:
            bg = QLinearGradient(outer.topLeft(), outer.bottomRight())
            bg.setColorAt(0.0, QColor("#111827"))
            bg.setColorAt(1.0, QColor("#0b1220"))
            painter.fillPath(self._rounded_path(outer, 32), bg)
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI", 22, QFont.Black))
            painter.drawText(outer, Qt.AlignCenter, "Load a tune")
            return

        is_fe = is_forza_edition_name(tune.car_name)
        force_holo = bool(self.manual_stats.get("force_holographic"))
        holo_enabled = is_fe or force_holo
        manual_enabled = bool(self.manual_stats.get("enabled"))
        manual_class = str(self.manual_stats.get("card_class") or "A")

        # Outer gold frame, copied from the standalone v0.5.1 card style.
        gold = QLinearGradient(outer.topLeft(), outer.bottomRight())
        gold.setColorAt(0.0, QColor("#f6e6a8"))
        gold.setColorAt(0.25, QColor("#f2c85f"))
        gold.setColorAt(0.5, QColor("#fff4cb"))
        gold.setColorAt(0.75, QColor("#d6a93b"))
        gold.setColorAt(1.0, QColor("#fff0af"))
        outer_path = self._rounded_path(outer, 32)
        painter.fillPath(outer_path, gold)

        # Main body. When manual card stats are enabled, use the selected class colour
        # just like the standalone card prototype. Otherwise keep the app accent colours.
        if manual_enabled and manual_class in CLASS_COLOURS:
            body_base = QColor(CLASS_COLOURS[manual_class][0])
            body_bright = QColor(CLASS_COLOURS[manual_class][1])
        else:
            body_base = self.accent
            body_bright = self.accent2

        bg = QLinearGradient(inner.topLeft(), inner.bottomRight())
        bg.setColorAt(0.0, body_base.lighter(120))
        bg.setColorAt(0.45, body_base.darker(135))
        bg.setColorAt(1.0, body_bright.darker(150))
        inner_path = self._rounded_path(inner, 28)
        painter.fillPath(inner_path, bg)

        glow = QRadialGradient(inner.center(), inner.width() * 0.6)
        glow.setColorAt(0.0, QColor(255, 255, 255, 42))
        glow.setColorAt(0.4, QColor(255, 255, 255, 16))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(inner_path, glow)

        if holo_enabled:
            self._draw_shiny_overlay(painter, inner)

        # Title strip.
        title_rect = QRectF(inner.left() + 18, inner.top() + 16, inner.width() - 36, 62)
        title_grad = QLinearGradient(title_rect.topLeft(), title_rect.bottomRight())
        title_grad.setColorAt(0.0, QColor(255, 255, 255, 50))
        title_grad.setColorAt(1.0, QColor(0, 0, 0, 45))
        painter.fillPath(self._rounded_path(title_rect, 18), title_grad)
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1.4))
        painter.drawPath(self._rounded_path(title_rect, 18))

        display_name = clean_forza_edition_name(tune.car_name, is_fe)
        painter.setPen(QColor("white"))
        name_rect = QRectF(title_rect.left() + 16, title_rect.top() + 8, title_rect.width() - 32, 46)
        self._fit_font_to_rect(painter, display_name, name_rect, 17, 11)
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, display_name)

        # Prototype badge row. Tune files do not reliably store class/PI, but the
        # manual card stats section can supply display-only class/PI.
        badge_fill = QColor(0, 0, 0, 88)
        class_rect = QRectF(inner.left() + 28, inner.top() + 92, 134, 40)
        try:
            manual_pi = int(self.manual_stats.get("pi", 0))
        except Exception:
            manual_pi = 0
        badge_text = f"{manual_class} {manual_pi}" if manual_enabled and manual_pi > 0 else f"TUNE #{tune.ordinal}"
        self._draw_badge(painter, class_rect, badge_text, badge_fill, QColor(255,255,255,70))

        if is_fe:
            fe_rect = QRectF(class_rect.right() + 12, class_rect.top(), 188, 40)
            self._draw_badge(painter, fe_rect, "FORZA EDITION", self._forza_edition_badge_gradient(fe_rect), QColor(255,255,255,110))

        # Image frame.
        image_rect = QRectF(inner.left() + 28, inner.top() + 144, inner.width() - 56, 324)
        image_grad = QLinearGradient(image_rect.topLeft(), image_rect.bottomRight())
        image_grad.setColorAt(0.0, QColor(255,255,255,26))
        image_grad.setColorAt(1.0, QColor(0,0,0,44))
        painter.fillPath(self._rounded_path(image_rect, 24), image_grad)
        painter.setPen(QPen(QColor(255,255,255,60), 1.5))
        painter.drawPath(self._rounded_path(image_rect, 24))

        car_glow = QRadialGradient(QPointF(image_rect.center().x(), image_rect.center().y() + 10), 180)
        car_glow.setColorAt(0.0, QColor(255,255,255,65))
        car_glow.setColorAt(1.0, QColor(255,255,255,0))
        painter.fillRect(image_rect, car_glow)

        pix = self._card_pixmap(image_rect)
        if pix and not pix.isNull():
            x = image_rect.center().x() - pix.width() / 2
            y = image_rect.center().y() - pix.height() / 2
            painter.drawPixmap(int(x), int(y), pix)
        else:
            painter.setPen(QColor(255,255,255,170))
            painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
            painter.drawText(image_rect, Qt.AlignCenter, "No thumbnail found")

        sub_rect = QRectF(inner.left() + 28, image_rect.bottom() + 12, inner.width() - 56, 42)
        painter.setPen(QColor(255,255,255,230))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        tag_tail = "Manual Card Stats" if manual_enabled else "Loaded Tune"
        tag = f"{tune.drivetrain_label}  •  {tune.active_gear_count} Gears  •  {tag_tail}"
        painter.drawText(sub_rect, Qt.AlignCenter, tag)

        stats_rect = QRectF(inner.left() + 26, inner.bottom() - 194, inner.width() - 52, 170)
        painter.fillPath(self._rounded_path(stats_rect, 22), QColor(8, 10, 18, 112))
        painter.setPen(QPen(QColor(255,255,255,55), 1.2))
        painter.drawPath(self._rounded_path(stats_rect, 22))

        if manual_enabled:
            stats = [
                ("POWER", self._manual_int("power_hp", "HP")),
                ("WEIGHT", self._manual_int("weight_kg", "KG")),
                ("TOP SPEED", self._manual_int("top_speed_mph", "MPH")),
                ("HANDLING", self._manual_rating("handling")),
                ("ACCEL", self._manual_rating("acceleration")),
                ("LAUNCH", self._manual_rating("launch")),
                ("BRAKING", self._manual_rating("braking")),
                ("DRIVETRAIN", tune.drivetrain_label),
            ]
        else:
            stats = [
                ("FINAL", self._display_value(2)),
                ("F TYRE", self._display_value(12)),
                ("R TYRE", self._display_value(23)),
                ("BRAKE", self._display_value(4)),
                ("F ARB", self._display_value(17)),
                ("R ARB", self._display_value(28)),
                ("HASH", tune.md5[:8]),
                ("ORDINAL", f"#{tune.ordinal}"),
            ]

        cols = 2
        card_w = (stats_rect.width() - 18 * 3) / 2
        card_h = 30
        top_y = stats_rect.top() + 16

        for i, (label, value) in enumerate(stats):
            row = i // cols
            col = i % cols
            x = stats_rect.left() + 18 + col * (card_w + 18)
            y = top_y + row * (card_h + 10)
            cell = QRectF(x, y, card_w, card_h)
            painter.fillPath(self._rounded_path(cell, 14), QColor(255,255,255,22))
            painter.setPen(Qt.NoPen)
            painter.drawPath(self._rounded_path(cell, 14))

            painter.setPen(QColor(255, 235, 180))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(QRectF(cell.left() + 10, cell.top(), cell.width() * 0.42, cell.height()),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             label)

            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            painter.drawText(QRectF(cell.left() + cell.width() * 0.42, cell.top(), cell.width() * 0.52 - 6, cell.height()),
                             Qt.AlignVCenter | Qt.AlignRight,
                             value)

        footer_rect = QRectF(inner.left() + 20, inner.bottom() - 30, inner.width() - 40, 18)
        painter.setPen(QColor(255,255,255,160))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(footer_rect, Qt.AlignCenter, f"WN Forza Tuner Car View  •  v{APP_VERSION}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # v0.5.1 ghosting fix from standalone prototype.
        painter.fillRect(self.rect(), QColor("#0b1220"))

        outer = QRectF(18, 18, self.width() - 36, self.height() - 36)
        inner = QRectF(28, 28, self.width() - 56, self.height() - 56)

        if self.show_back:
            self._paint_back(painter, outer, inner)
        else:
            self._paint_front(painter, outer, inner)


@dataclass
class TuneAssistRecommendation:
    priority: str
    field_index: int
    current: float
    suggested: float
    reason: str
    problem: str
    source: str = "Tune"

    @property
    def field(self):
        return FIELD_BY_INDEX[self.field_index]

    @property
    def delta(self):
        return self.suggested - self.current


@dataclass
class TuneAssistInsight:
    priority: str
    title: str
    body: str
    source: str = "Telemetry"


ASSIST_PROBLEMS = [
    "General sanity check",
    "Understeer on corner entry",
    "Understeer mid-corner",
    "Understeer on corner exit",
    "Oversteer on corner entry",
    "Oversteer mid-corner",
    "Oversteer on corner exit",
    "Wheelspin on launch/exit",
    "Unstable braking",
    "Too much body roll",
    "Bottoming out / too low",
    "Bad gearing / top speed",
]


def assist_add_rec(recs: list, tune: TuneFile, idx: int, suggested: float, reason: str, problem: str, priority="Medium", source="Tune"):
    field = FIELD_BY_INDEX.get(idx)
    if not field:
        return
    current = tune_display_value(tune, idx)
    if current is None:
        return
    if hasattr(field, "clamp_display"):
        suggested = field.clamp_display(suggested)
    elif hasattr(field, "clamp"):
        suggested = field.clamp(suggested)
    else:
        lo = min(field.display_min, field.display_max)
        hi = max(field.display_min, field.display_max)
        suggested = max(lo, min(hi, float(suggested)))
    if abs(suggested - current) < max(float(field.step or 0.01), 0.01) * 0.75:
        return
    recs.append(TuneAssistRecommendation(priority, idx, current, suggested, reason, problem, source))


def finite_values(values):
    output = []
    for value in values:
        try:
            v = float(value)
            if math.isfinite(v):
                output.append(v)
        except Exception:
            pass
    return output


def avg_or_none(values):
    vals = finite_values(values)
    return sum(vals) / len(vals) if vals else None


def assist_telemetry_summary(samples: list[dict]) -> dict:
    if not samples:
        return {}
    recent = list(samples[-1500:])
    front_temps, rear_temps, speeds, rpm_ratios, susp_vals = [], [], [], [], []
    low_rpm_high_gear = 0
    brake_steer = 0
    ordinals = {}
    for s in recent:
        fl, fr, rl, rr = s.get("tyre_temp_fl"), s.get("tyre_temp_fr"), s.get("tyre_temp_rl"), s.get("tyre_temp_rr")
        if isinstance(fl, (int, float)) and isinstance(fr, (int, float)):
            front_temps.append((fl + fr) / 2.0)
        if isinstance(rl, (int, float)) and isinstance(rr, (int, float)):
            rear_temps.append((rl + rr) / 2.0)
        spd = s.get("speed_mph")
        if isinstance(spd, (int, float)):
            speeds.append(spd)
        rpm, max_rpm = s.get("rpm"), s.get("engine_max_rpm")
        if isinstance(rpm, (int, float)) and isinstance(max_rpm, (int, float)) and max_rpm > 100:
            ratio = rpm / max_rpm
            rpm_ratios.append(ratio)
            gear = s.get("gear")
            throttle = s.get("throttle")
            if isinstance(gear, int) and isinstance(throttle, (int, float)) and throttle > 75 and gear >= 4 and ratio < 0.68:
                low_rpm_high_gear += 1
        brake, steer = s.get("brake"), s.get("steer")
        if isinstance(brake, (int, float)) and isinstance(steer, (int, float)) and brake > 65 and abs(steer) > 18:
            brake_steer += 1
        ordinal = s.get("car_ordinal")
        if isinstance(ordinal, int) and ordinal > 0:
            ordinals[ordinal] = ordinals.get(ordinal, 0) + 1
        if isinstance(spd, (int, float)) and spd > 45:
            sv = finite_values([s.get("suspension_fl"), s.get("suspension_fr"), s.get("suspension_rl"), s.get("suspension_rr")])
            if sv:
                susp_vals.append(max(abs(v) for v in sv))
    most_common = max(ordinals.items(), key=lambda item: item[1])[0] if ordinals else None
    return {
        "sample_count": len(recent),
        "front_temp_avg": avg_or_none(front_temps),
        "rear_temp_avg": avg_or_none(rear_temps),
        "max_speed_mph": max(speeds) if speeds else None,
        "max_rpm_ratio": max(rpm_ratios) if rpm_ratios else None,
        "low_rpm_high_gear_samples": low_rpm_high_gear,
        "brake_steer_samples": brake_steer,
        "max_suspension_abs": max(susp_vals) if susp_vals else None,
        "most_common_ordinal": most_common,
    }


def run_tuning_assist(tune: TuneFile, problem: str, telemetry_samples: Optional[list] = None):
    recs: list[TuneAssistRecommendation] = []
    insights: list[TuneAssistInsight] = []
    fp, rp = tune_display_value(tune, 12), tune_display_value(tune, 23)
    farb, rarb = tune_display_value(tune, 17), tune_display_value(tune, 28)
    fs, rs = tune_display_value(tune, 16), tune_display_value(tune, 27)
    fcam, rcam = tune_display_value(tune, 13), tune_display_value(tune, 24)
    ftoe, rtoe = tune_display_value(tune, 14), tune_display_value(tune, 25)
    caster = tune_display_value(tune, 15)
    brake_bias, brake_pressure = tune_display_value(tune, 4), tune_display_value(tune, 3)
    fd = tune_display_value(tune, 2)
    front_accel, rear_accel, centre = tune_display_value(tune, 21), tune_display_value(tune, 32), tune_display_value(tune, 6)
    r_bump = tune_display_value(tune, 30)

    if fp is not None and rp is not None:
        if fp > 38:
            assist_add_rec(recs, tune, 12, max(30.0, fp - 2.0), "Front tyre pressure is very high. Lowering it can add front grip and compliance.", problem, "High")
        if rp > 38:
            assist_add_rec(recs, tune, 23, max(30.0, rp - 2.0), "Rear tyre pressure is very high. Lowering it can add rear grip and reduce snap behaviour.", problem, "High")
        if fp < 22:
            assist_add_rec(recs, tune, 12, min(28.0, fp + 1.5), "Front tyre pressure is very low. Raise it slightly if the car feels lazy or vague.", problem)
        if rp < 22:
            assist_add_rec(recs, tune, 23, min(28.0, rp + 1.5), "Rear tyre pressure is very low. Raise it slightly if the rear feels sluggish.", problem)
        if abs(fp - rp) > 4:
            if fp > rp:
                assist_add_rec(recs, tune, 12, fp - min(2.0, abs(fp - rp) / 2), "Front/rear pressure split is large. Bring the front closer to rear for balance.", problem)
            else:
                assist_add_rec(recs, tune, 23, rp - min(2.0, abs(fp - rp) / 2), "Rear/front pressure split is large. Bring the rear closer to front for balance.", problem)

    if farb is not None and rarb is not None:
        if rarb > farb * 1.8 and rarb > 25:
            assist_add_rec(recs, tune, 28, rarb - 6.0, "Rear ARB is very stiff compared with front. This can cause snap oversteer.", problem, "High")
        if farb > rarb * 1.8 and farb > 25:
            assist_add_rec(recs, tune, 17, farb - 6.0, "Front ARB is very stiff compared with rear. This can create heavy understeer.", problem, "High")

    if fs is not None and rs is not None and fs > 0 and rs > 0:
        if rs > fs * 1.9:
            assist_add_rec(recs, tune, 27, rs * 0.90, "Rear springs are much stiffer than front. This can create exit oversteer.", problem)
        if fs > rs * 1.9:
            assist_add_rec(recs, tune, 16, fs * 0.90, "Front springs are much stiffer than rear. This can create strong understeer.", problem)

    if problem == "Understeer on corner entry":
        if farb is not None: assist_add_rec(recs, tune, 17, farb - 4.0, "Softer front ARB should help the front bite on entry.", problem, "High")
        if fcam is not None: assist_add_rec(recs, tune, 13, fcam - 0.3, "More negative front camber can improve front contact patch on turn-in.", problem)
        if ftoe is not None: assist_add_rec(recs, tune, 14, max(-0.2, ftoe - 0.1), "A tiny amount of front toe-out can sharpen initial turn-in.", problem)
        if brake_bias is not None and brake_bias > 52: assist_add_rec(recs, tune, 4, brake_bias - 2.0, "Moving brake bias slightly rearward can help rotation on entry.", problem)
    elif problem == "Understeer mid-corner":
        if farb is not None: assist_add_rec(recs, tune, 17, farb - 5.0, "Reducing front ARB usually adds mid-corner front grip.", problem, "High")
        if rarb is not None: assist_add_rec(recs, tune, 28, rarb + 3.0, "Slightly increasing rear ARB can help the car rotate mid-corner.", problem)
        if fp is not None: assist_add_rec(recs, tune, 12, fp - 1.0, "Lowering front pressure slightly can add front mechanical grip.", problem)
        if caster is not None and caster < 6.0: assist_add_rec(recs, tune, 15, min(7.0, caster + 0.4), "More caster can improve camber gain and front bite.", problem)
    elif problem == "Understeer on corner exit":
        if centre is not None and tune.drivetrain_label == "AWD": assist_add_rec(recs, tune, 6, min(80.0, centre + 5.0), "More rearward centre balance can reduce AWD power-on push.", problem, "High")
        if front_accel is not None and tune.drivetrain_label in {"AWD", "FWD"}: assist_add_rec(recs, tune, 21, max(5.0, front_accel - 8.0), "Reducing front diff accel can reduce power-on push.", problem)
        if rarb is not None: assist_add_rec(recs, tune, 28, rarb + 3.0, "A little more rear ARB can help rotate the car on throttle.", problem)
    elif problem == "Oversteer on corner entry":
        if rarb is not None: assist_add_rec(recs, tune, 28, rarb - 5.0, "Softer rear ARB should calm rotation on entry.", problem, "High")
        if r_bump is not None: assist_add_rec(recs, tune, 30, r_bump - 1.0, "Softer rear bump damping can reduce entry snap over bumps/weight transfer.", problem)
        if brake_bias is not None and brake_bias < 52: assist_add_rec(recs, tune, 4, brake_bias + 2.0, "More front brake bias can stabilise the rear under braking.", problem)
        if rtoe is not None: assist_add_rec(recs, tune, 25, min(0.2, rtoe + 0.1), "A small amount of rear toe-in can improve entry stability.", problem)
    elif problem == "Oversteer mid-corner":
        if rarb is not None: assist_add_rec(recs, tune, 28, rarb - 5.0, "Softer rear ARB usually adds rear grip mid-corner.", problem, "High")
        if rp is not None: assist_add_rec(recs, tune, 23, rp - 1.0, "Lowering rear pressure slightly can add rear grip.", problem)
        if rcam is not None: assist_add_rec(recs, tune, 24, rcam - 0.2, "Slightly more negative rear camber can help rear cornering grip.", problem)
        if rs is not None: assist_add_rec(recs, tune, 27, rs * 0.93, "Softer rear springs can add rear grip and compliance.", problem)
    elif problem == "Oversteer on corner exit":
        if rear_accel is not None and tune.drivetrain_label in {"AWD", "RWD"}: assist_add_rec(recs, tune, 32, max(10.0, rear_accel - 12.0), "Reducing rear diff accel should reduce power-on oversteer.", problem, "High")
        if rarb is not None: assist_add_rec(recs, tune, 28, rarb - 5.0, "Softer rear ARB can add traction on corner exit.", problem, "High")
        if rp is not None: assist_add_rec(recs, tune, 23, rp - 1.0, "Lowering rear pressure slightly can increase rear traction.", problem)
        if centre is not None and tune.drivetrain_label == "AWD" and centre > 65: assist_add_rec(recs, tune, 6, centre - 5.0, "Less rearward centre balance can calm exit oversteer in AWD cars.", problem)
    elif problem == "Wheelspin on launch/exit":
        if rear_accel is not None and tune.drivetrain_label in {"AWD", "RWD"}: assist_add_rec(recs, tune, 32, max(10.0, rear_accel - 10.0), "Lower rear diff accel to smooth throttle application.", problem, "High")
        if front_accel is not None and tune.drivetrain_label == "FWD": assist_add_rec(recs, tune, 21, max(10.0, front_accel - 10.0), "Lower front diff accel to reduce inside-wheel spin.", problem, "High")
        if rp is not None and tune.drivetrain_label in {"AWD", "RWD"}: assist_add_rec(recs, tune, 23, rp - 1.2, "Lower rear pressure slightly for more traction.", problem)
        if fd is not None and fd > 3.2: assist_add_rec(recs, tune, 2, fd - 0.12, "A slightly longer final drive can soften torque delivery.", problem)
    elif problem == "Unstable braking":
        if brake_bias is not None: assist_add_rec(recs, tune, 4, 52.0 if brake_bias < 50 else min(58.0, brake_bias + 2.0), "More front brake bias usually stabilises the car under braking.", problem, "High")
        if brake_pressure is not None and brake_pressure > 130: assist_add_rec(recs, tune, 3, brake_pressure - 10.0, "Lower brake pressure can make braking easier to modulate.", problem)
        if rtoe is not None: assist_add_rec(recs, tune, 25, min(0.2, rtoe + 0.1), "A touch of rear toe-in can improve braking stability.", problem)
    elif problem == "Too much body roll":
        if farb is not None: assist_add_rec(recs, tune, 17, farb + 4.0, "Stiffer front ARB reduces roll, but may add understeer.", problem)
        if rarb is not None: assist_add_rec(recs, tune, 28, rarb + 4.0, "Stiffer rear ARB reduces roll and can help rotation, but may add oversteer.", problem)
        if fs is not None: assist_add_rec(recs, tune, 16, fs * 1.08, "Stiffer front springs reduce roll and pitch.", problem)
        if rs is not None: assist_add_rec(recs, tune, 27, rs * 1.08, "Stiffer rear springs reduce roll and squat.", problem)
    elif problem == "Bottoming out / too low":
        frh, rrh = tune_display_value(tune, 18), tune_display_value(tune, 29)
        if frh is not None: assist_add_rec(recs, tune, 18, frh + 0.5, "Raise front ride height to reduce bottoming.", problem, "High")
        if rrh is not None: assist_add_rec(recs, tune, 29, rrh + 0.5, "Raise rear ride height to reduce bottoming.", problem, "High")
        if fs is not None: assist_add_rec(recs, tune, 16, fs * 1.06, "Slightly stiffer front springs can reduce suspension compression.", problem)
        if rs is not None: assist_add_rec(recs, tune, 27, rs * 1.06, "Slightly stiffer rear springs can reduce suspension compression.", problem)
    elif problem == "Bad gearing / top speed":
        if fd is not None:
            if fd > 4.5: assist_add_rec(recs, tune, 2, fd - 0.20, "Final drive is short. Lengthen it if the car tops out too early.", problem, "High")
            elif fd < 2.6: assist_add_rec(recs, tune, 2, fd + 0.15, "Final drive is long. Shorten it if acceleration feels weak.", problem, "High")
            else: assist_add_rec(recs, tune, 2, fd - 0.08, "Try slightly longer gearing if top speed is the issue.", problem)

    if telemetry_samples:
        ts = assist_telemetry_summary(telemetry_samples)
        count = int(ts.get("sample_count") or 0)
        tel_ordinal = ts.get("most_common_ordinal")
        if tel_ordinal and int(tel_ordinal) != int(tune.ordinal):
            insights.append(TuneAssistInsight("High", "Telemetry car mismatch", f"Telemetry mostly shows ordinal #{tel_ordinal}, but the loaded tune is #{tune.ordinal}. Load the matching tune before trusting telemetry suggestions."))
        if count < 50:
            insights.append(TuneAssistInsight("Medium", "More telemetry needed", f"Only {count} samples are available. Drive for 30–60 seconds, then analyse again."))
        else:
            fta, rta = ts.get("front_temp_avg"), ts.get("rear_temp_avg")
            if fta is not None and rta is not None:
                diff = fta - rta
                if diff > 10 and fp is not None:
                    assist_add_rec(recs, tune, 12, fp - 0.8, f"Telemetry: front tyres average {diff:.1f}° hotter than rear. Lower front pressure slightly.", problem, "High", "Telemetry")
                    if problem.startswith("Understeer") and farb is not None:
                        assist_add_rec(recs, tune, 17, farb - 3.0, "Telemetry: hot front tyres plus understeer suggests reducing front ARB.", problem, "High", "Telemetry")
                elif diff < -10 and rp is not None:
                    assist_add_rec(recs, tune, 23, rp - 0.8, f"Telemetry: rear tyres average {abs(diff):.1f}° hotter than front. Lower rear pressure slightly.", problem, "High", "Telemetry")
                    if problem.startswith("Oversteer") and rarb is not None:
                        assist_add_rec(recs, tune, 28, rarb - 3.0, "Telemetry: hot rear tyres plus oversteer suggests softening rear ARB.", problem, "High", "Telemetry")
            max_rpm_ratio, max_speed = ts.get("max_rpm_ratio"), ts.get("max_speed_mph")
            if fd is not None and max_rpm_ratio is not None and max_speed is not None:
                if max_rpm_ratio > 0.96 and max_speed > 80:
                    assist_add_rec(recs, tune, 2, fd - 0.10, f"Telemetry: engine reached {max_rpm_ratio*100:.0f}% of max RPM. Lengthen final drive if hitting limiter.", problem, "High", "Telemetry")
                elif max_rpm_ratio < 0.78 and max_speed > 80 and problem == "Bad gearing / top speed":
                    assist_add_rec(recs, tune, 2, fd + 0.08, f"Telemetry: engine only reached {max_rpm_ratio*100:.0f}% of max RPM at speed. Shorten final drive if acceleration feels weak.", problem, "Medium", "Telemetry")
            if int(ts.get("brake_steer_samples") or 0) > 25 and brake_bias is not None and problem == "Unstable braking":
                assist_add_rec(recs, tune, 4, min(58.0, brake_bias + 2.0), "Telemetry: heavy braking while steering detected. More front bias may stabilise braking.", problem, "High", "Telemetry")
            if (ts.get("max_suspension_abs") or 0) > 0.16 and problem == "Bottoming out / too low":
                frh, rrh = tune_display_value(tune, 18), tune_display_value(tune, 29)
                if frh is not None: assist_add_rec(recs, tune, 18, frh + 0.3, "Telemetry: high suspension travel detected. Raise front ride height slightly.", problem, "High", "Telemetry")
                if rrh is not None: assist_add_rec(recs, tune, 29, rrh + 0.3, "Telemetry: high suspension travel detected. Raise rear ride height slightly.", problem, "High", "Telemetry")

    if brake_bias is not None and (brake_bias < 45 or brake_bias > 65):
        assist_add_rec(recs, tune, 4, 55.0 if brake_bias < 45 else 58.0, "Brake bias is extreme. This is a safer baseline before fine-tuning.", problem, "High")
    if brake_pressure is not None and brake_pressure > 160:
        assist_add_rec(recs, tune, 3, 130.0, "Brake pressure is very high. Lower it if lockups or instability occur.", problem)

    order = {"High": 0, "Medium": 1, "Low": 2}
    src_order = {"Telemetry": 0, "Tune": 1}
    recs.sort(key=lambda r: (order.get(r.priority, 1), src_order.get(r.source, 2), r.field.section, r.field.label))
    dedup, seen = [], set()
    for r in recs:
        if r.field_index in seen:
            continue
        seen.add(r.field_index)
        dedup.append(r)
    return dedup[:14], insights




ASSIST_TUNE_TYPES = [
    "Balanced",
    "Road / Grip",
    "Race",
    "Drift",
    "Drag",
    "Rally",
    "Off-road",
    "Speed / Highway",
]


def assist_add_map(out: dict, tune: TuneFile, idx: int, suggested: float, reason: str, priority="Medium", source="Tune Type"):
    recs = []
    assist_add_rec(recs, tune, idx, suggested, reason, "General sanity check", priority, source)
    if not recs:
        return
    rec = recs[0]
    existing = out.get(idx)
    order = {"High": 0, "Medium": 1, "Low": 2}
    if existing is None or order.get(rec.priority, 1) < order.get(existing.priority, 1):
        out[idx] = rec


def build_tune_type_suggestion_map(tune: TuneFile, tune_type: str) -> dict[int, TuneAssistRecommendation]:
    out: dict[int, TuneAssistRecommendation] = {}

    # Keep the old general sanity checks, but render them as slider overlays.
    base_recs, _ = run_tuning_assist(tune, "General sanity check", [])
    for rec in base_recs:
        out[rec.field_index] = rec

    def v(idx):
        return tune_display_value(tune, idx)

    fp, rp = v(12), v(23)
    farb, rarb = v(17), v(28)
    fs, rs = v(16), v(27)
    frh, rrh = v(18), v(29)
    fcam, rcam = v(13), v(24)
    ftoe, rtoe = v(14), v(25)
    caster = v(15)
    fd = v(2)
    brake_bias, brake_pressure = v(4), v(3)
    front_accel, rear_accel, centre = v(21), v(32), v(6)
    front_rebound, rear_rebound = v(20), v(31)
    front_bump, rear_bump = v(19), v(30)
    front_aero, rear_aero = v(0), v(1)

    if tune_type in {"Road / Grip", "Race", "Balanced"}:
        if caster is not None and caster < 6.0:
            assist_add_map(out, tune, 15, min(7.0, caster + 0.4), f"{tune_type}: more caster can improve front bite and stability.", "Medium")
        if brake_pressure is not None and brake_pressure < 95:
            assist_add_map(out, tune, 3, 105.0, f"{tune_type}: bring brake pressure closer to a useful baseline.", "Medium")
        if brake_bias is not None and (brake_bias < 48 or brake_bias > 60):
            assist_add_map(out, tune, 4, 54.0, f"{tune_type}: safer brake balance baseline for circuit driving.", "Medium")
        if fp is not None and fp > 32:
            assist_add_map(out, tune, 12, fp - 0.8, f"{tune_type}: slightly lower front pressure for front grip.", "Low")
        if rp is not None and rp > 32:
            assist_add_map(out, tune, 23, rp - 0.8, f"{tune_type}: slightly lower rear pressure for traction.", "Low")

    if tune_type == "Race":
        if farb is not None:
            assist_add_map(out, tune, 17, min(65.0, farb + 2.0), "Race: slightly more front ARB can sharpen response.", "Low")
        if rarb is not None:
            assist_add_map(out, tune, 28, min(65.0, rarb + 2.0), "Race: slightly more rear ARB can reduce roll and help rotation.", "Low")
        if front_aero is not None and front_aero < 35:
            assist_add_map(out, tune, 0, front_aero + 8.0, "Race: more front aero can improve high-speed front grip if aero is fitted.", "Medium")
        if rear_aero is not None and rear_aero < 45:
            assist_add_map(out, tune, 1, rear_aero + 8.0, "Race: more rear aero can stabilise high-speed corners if aero is fitted.", "Medium")

    elif tune_type == "Drift":
        if rear_accel is not None:
            assist_add_map(out, tune, 32, min(100.0, max(78.0, rear_accel + 12.0)), "Drift: more rear diff accel helps hold angle on throttle.", "High")
        if rear_accel is not None and tune.drivetrain_label == "AWD" and centre is not None:
            assist_add_map(out, tune, 6, min(90.0, max(72.0, centre + 10.0)), "Drift: more rearward centre balance helps rotation.", "High")
        if rtoe is not None:
            assist_add_map(out, tune, 25, min(0.6, rtoe + 0.2), "Drift: slight rear toe-in can stabilise the slide.", "Medium")
        if ftoe is not None:
            assist_add_map(out, tune, 14, max(-0.8, ftoe - 0.2), "Drift: small front toe-out can improve steering response.", "Medium")
        if fd is not None and fd < 4.0:
            assist_add_map(out, tune, 2, min(6.1, fd + 0.15), "Drift: shorter final drive can keep the car in the power band.", "Medium")

    elif tune_type == "Drag":
        if fd is not None:
            assist_add_map(out, tune, 2, max(2.0, fd - 0.10), "Drag: slightly longer final drive can reduce wheelspin/limiter hits.", "Medium")
        if tune.drivetrain_label in {"RWD", "AWD"} and rear_accel is not None:
            assist_add_map(out, tune, 32, min(100.0, max(82.0, rear_accel + 8.0)), "Drag: more rear diff lock helps straight-line launch.", "High")
        if rp is not None and tune.drivetrain_label in {"RWD", "AWD"}:
            assist_add_map(out, tune, 23, max(24.0, rp - 1.2), "Drag: lower rear tyre pressure can improve launch traction.", "Medium")
        if rs is not None:
            assist_add_map(out, tune, 27, max(FIELD_BY_INDEX[27].display_min, rs * 0.94), "Drag: slightly softer rear springs can help weight transfer.", "Medium")

    elif tune_type in {"Rally", "Off-road"}:
        if frh is not None:
            assist_add_map(out, tune, 18, frh + 0.5, f"{tune_type}: raise front ride height for clearance.", "High")
        if rrh is not None:
            assist_add_map(out, tune, 29, rrh + 0.5, f"{tune_type}: raise rear ride height for clearance.", "High")
        if fs is not None:
            assist_add_map(out, tune, 16, fs * 0.90, f"{tune_type}: soften front springs for bumps and jumps.", "Medium")
        if rs is not None:
            assist_add_map(out, tune, 27, rs * 0.90, f"{tune_type}: soften rear springs for rough surfaces.", "Medium")
        if front_bump is not None:
            assist_add_map(out, tune, 19, max(1.0, front_bump - 1.2), f"{tune_type}: softer front bump damping improves rough-road compliance.", "Medium")
        if rear_bump is not None:
            assist_add_map(out, tune, 30, max(1.0, rear_bump - 1.2), f"{tune_type}: softer rear bump damping improves rough-road compliance.", "Medium")
        if fp is not None:
            assist_add_map(out, tune, 12, max(24.0, fp - 1.0), f"{tune_type}: lower front pressure can improve loose-surface grip.", "Medium")
        if rp is not None:
            assist_add_map(out, tune, 23, max(24.0, rp - 1.0), f"{tune_type}: lower rear pressure can improve loose-surface grip.", "Medium")

    elif tune_type == "Speed / Highway":
        if fd is not None:
            assist_add_map(out, tune, 2, max(2.0, fd - 0.18), "Speed: longer final drive helps top speed.", "High")
        if front_aero is not None and front_aero > 20:
            assist_add_map(out, tune, 0, max(0.0, front_aero - 10.0), "Speed: lower front aero can reduce drag if stability allows.", "Medium")
        if rear_aero is not None and rear_aero > 25:
            assist_add_map(out, tune, 1, max(0.0, rear_aero - 10.0), "Speed: lower rear aero can reduce drag if stability allows.", "Medium")
        if frh is not None:
            assist_add_map(out, tune, 18, max(FIELD_BY_INDEX[18].display_min, frh - 0.2), "Speed: slightly lower front ride height can reduce drag.", "Low")
        if rrh is not None:
            assist_add_map(out, tune, 29, max(FIELD_BY_INDEX[29].display_min, rrh - 0.2), "Speed: slightly lower rear ride height can reduce drag.", "Low")

    return out


class AssistDualMarkerSlider(QWidget):
    def __init__(self, field: FieldDef, parent=None):
        super().__init__(parent)
        self.field = field
        self.current_value = None
        self.suggested_value = None
        self.setMinimumHeight(30)

    def set_values(self, current, suggested):
        self.current_value = current
        self.suggested_value = suggested
        self.update()

    def _ratio(self, value: float) -> float:
        if self.field.display_max == self.field.display_min:
            return 0.0
        return max(0.0, min(1.0, (float(value) - self.field.display_min) / (self.field.display_max - self.field.display_min)))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(8, 8, -8, -8)
        y = rect.center().y()
        x1, x2 = rect.left(), rect.right()

        p.setPen(QPen(QColor("#07111d"), 8, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(x1, y, x2, y)

        if self.current_value is not None:
            cur_x = x1 + (x2 - x1) * self._ratio(self.current_value)
            grad = QLinearGradient(x1, y, cur_x, y)
            grad.setColorAt(0.0, QColor("#ff2f6d"))
            grad.setColorAt(1.0, QColor("#00d4ff"))
            p.setPen(QPen(QBrush(grad), 8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(x1, y, cur_x, y)

        if self.current_value is not None and self.suggested_value is not None:
            cx = x1 + (x2 - x1) * self._ratio(self.current_value)
            sx = x1 + (x2 - x1) * self._ratio(self.suggested_value)
            p.setPen(QPen(QColor("#ffd84d"), 3, Qt.DashLine, Qt.RoundCap))
            p.drawLine(cx, y, sx, y)

        if self.current_value is not None:
            cx = x1 + (x2 - x1) * self._ratio(self.current_value)
            p.setBrush(QColor("#ffffff"))
            p.setPen(QPen(QColor("#ff2f6d"), 2))
            p.drawRoundedRect(QRectF(cx - 8, y - 10, 16, 20), 7, 7)

        if self.suggested_value is not None:
            sx = x1 + (x2 - x1) * self._ratio(self.suggested_value)
            path = QPainterPath()
            path.moveTo(sx, y - 13)
            path.lineTo(sx + 12, y)
            path.lineTo(sx, y + 13)
            path.lineTo(sx - 12, y)
            path.closeSubpath()
            p.setBrush(QColor("#ffd84d"))
            p.setPen(QPen(QColor("#ff9f1c"), 2))
            p.drawPath(path)


class AssistTuneValueRow(QFrame):
    def __init__(self, field: FieldDef):
        super().__init__()
        self.field = field
        self.setObjectName("assistValueRow")
        self.setMinimumHeight(96)
        grid = QGridLayout(self)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 0)

        left = QVBoxLayout()
        self.title = QLabel(field.label)
        self.title.setObjectName("tuneTitle")
        self.raw = QLabel("raw --")
        self.raw.setObjectName("meta")
        self.note = QLabel(field.note or "Loaded tune value.")
        self.note.setObjectName("meta")
        self.note.setWordWrap(True)
        left.addWidget(self.title)
        left.addWidget(self.raw)
        left.addWidget(self.note)

        self.slider = AssistDualMarkerSlider(field)
        self.current_box = QLabel("--")
        self.current_box.setObjectName("valuePill")
        self.current_box.setAlignment(Qt.AlignCenter)
        self.current_box.setMinimumWidth(116)
        self.suggested_box = QLabel("--")
        self.suggested_box.setObjectName("assistSuggestPill")
        self.suggested_box.setAlignment(Qt.AlignCenter)
        self.suggested_box.setMinimumWidth(128)

        grid.addLayout(left, 0, 0)
        grid.addWidget(self.slider, 0, 1)
        grid.addWidget(self.current_box, 0, 2)
        grid.addWidget(self.suggested_box, 0, 3)

    def set_values(self, tune: Optional[TuneFile], suggestion: Optional[TuneAssistRecommendation]):
        raw = None
        current = None
        if tune and self.field.index < len(tune.values):
            raw = tune.values[self.field.index]
            current = self.field.raw_to_display(raw) if isinstance(raw, (int, float)) else None
        suggested = suggestion.suggested if suggestion else None
        self.slider.set_values(current, suggested)
        self.raw.setText(f"raw {raw:.6f}" if isinstance(raw, (int, float)) and raw >= 0 else "raw --")
        self.current_box.setText(self.field.display_text(raw) if isinstance(raw, (int, float)) else "--")
        if suggestion:
            sign = "+" if suggestion.delta > 0 else ""
            delta_text = f"{sign}{suggestion.delta:.{self.field.decimals}f}{(' ' + self.field.unit) if self.field.unit else ''}"
            self.suggested_box.setText(f"{self.field.format_display(suggestion.suggested)}\n{delta_text}")
            self.suggested_box.setToolTip(suggestion.reason)
            self.note.setText(suggestion.reason)
        else:
            self.suggested_box.setText("--")
            self.suggested_box.setToolTip("")
            self.note.setText(self.field.note or "Loaded tune value.")

class FH6QtApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        # Public release: no background update checks or thumbnail downloads.
        # Existing old config files may still contain these as True, so force them off.
        self.config["auto_update_check"] = False
        self.config["auto_thumbnail_cache_update"] = False
        save_config(self.config)
        for folder in [THUMBNAIL_CACHE_DIR, IMPORTED_SHARE_DIR, SHARED_LAPS_DIR]:
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        try:
            for tmp_file in THUMBNAIL_CACHE_DIR.glob("_tmp_*"):
                tmp_file.unlink(missing_ok=True)
        except Exception:
            pass
        self.tunes = []
        self.current = None
        self.current_section = "Gearing"
        self.telemetry_running = False
        self.telemetry_socket = None
        self.telemetry_thread = None
        self.telemetry_last = {}
        self.telemetry_packets = 0
        self.telemetry_samples = []
        self.race_timer_running = False
        self.race_timer_start_monotonic = 0.0
        self.race_timer_elapsed = 0.0
        self.race_timer_saved_elapsed = 0.0
        self.race_timer_last_timestamp_ms = None
        self.race_timer_last_is_race_on = 0
        self.race_timer_last_packet_unix = 0.0
        self.race_timer_car_name = ""
        self.race_timer_ordinal = None
        self.race_timer_auto_paused = False
        self.race_timer_last_game_current = 0.0
        self.race_timer_last_game_last = 0.0
        self.race_timer_last_game_best = 0.0
        self.race_timer_status_text = "Ready"
        self.shared_laps = []
        self.loaded_shared_lap = None
        self.speed_unit = self.config.get("speed_unit", "mph")
        self.nav_buttons = {}
        self.tune_items = []
        self.current_car_tune_scan_running = False
        self.pending_current_car_tune_load = False
        self.pending_current_car_tune_deadline = 0.0
        self.auto_load_attempted_ordinals = set()

        self.setWindowTitle(APP_NAME)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1480, 900)
        self.setMinimumSize(1120, 720)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar_save_timer = QTimer(self)
        self.sidebar_save_timer.setSingleShot(True)
        self.sidebar_save_timer.timeout.connect(self.save_sidebar_width_now)

        self.sidebar_splitter = QSplitter(Qt.Horizontal)
        self.sidebar_splitter.setObjectName("mainSplitter")
        self.sidebar_splitter.setChildrenCollapsible(False)
        self.sidebar_splitter.setHandleWidth(8)
        root_layout.addWidget(self.sidebar_splitter, 1)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(150)
        self.sidebar.setMaximumWidth(360)
        self.sidebar_splitter.addWidget(self.sidebar)

        self.main = QFrame()
        self.main.setObjectName("main")
        self.sidebar_splitter.addWidget(self.main)

        self.sidebar_splitter.setStretchFactor(0, 0)
        self.sidebar_splitter.setStretchFactor(1, 1)
        self.sidebar_splitter.setSizes([self.clamp_sidebar_width(self.config.get("sidebar_width", 210)), 1200])
        self.sidebar_splitter.splitterMoved.connect(self.queue_sidebar_width_save)

        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(10, 10, 10, 10)
        self.sidebar_layout.setSpacing(8)

        brand = QFrame()
        brand.setObjectName("brand")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(6, 6, 6, 6)
        brand_layout.setSpacing(6)

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo_path = LOGO_IMAGE_PATH if LOGO_IMAGE_PATH.exists() else LOGO_IMAGE_PATH_ALT
        pix = QPixmap(str(logo_path)) if logo_path.exists() else QPixmap()
        if not pix.isNull():
            logo.setPixmap(pix.scaled(178, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo.setContentsMargins(0, 0, 0, 0)
            logo.setMinimumHeight(32)
        else:
            logo.setText("FH6 TUNE EDITOR")
            logo.setObjectName("brandTitle")

        brand_layout.setContentsMargins(6, 6, 6, 6)
        brand_layout.setSpacing(0)
        brand_layout.addWidget(logo)
        self.sidebar_layout.addWidget(brand)

        for page, icon in [("Setup", "◆"), ("Tuning", "⌁"), ("Car View", "▣"), ("Tuning Assist", "🛠"), ("Live Telemetry", "◉"), ("Race Times", "⏱"), ("Shared Lap Times", "≋"), ("Settings", "⚙")]:
            btn = QPushButton(f"{icon}  {page}")
            btn.setObjectName("navButton")
            btn.clicked.connect(lambda checked=False, p=page: self.switch_page(p))
            self.sidebar_layout.addWidget(btn)
            self.nav_buttons[page] = btn

        support_label = QLabel("SUPPORT")
        support_label.setObjectName("sideSectionLabel")
        self.sidebar_layout.addSpacing(8)
        self.sidebar_layout.addWidget(support_label)

        donate_btn = QPushButton("☕  Donate / Ko-fi")
        donate_btn.setObjectName("sideActionButton")
        donate_btn.setMinimumHeight(52)
        donate_btn.setToolTip("Open https://ko-fi.com/wn123")
        if KOFI_ICON_PATH.exists():
            donate_btn.setIcon(QIcon(str(KOFI_ICON_PATH)))
            donate_btn.setIconSize(QSize(24, 24))
        donate_btn.clicked.connect(self.open_kofi)
        self.sidebar_layout.addWidget(donate_btn)

        discord_btn = QPushButton("Discord")
        discord_btn.setObjectName("sideActionButton")
        discord_btn.setMinimumHeight(52)
        if DISCORD_ICON_PATH.exists():
            discord_btn.setIcon(QIcon(str(DISCORD_ICON_PATH)))
            discord_btn.setIconSize(QSize(26, 26))
        discord_btn.clicked.connect(self.open_discord)
        self.sidebar_layout.addWidget(discord_btn)

        self.sidebar_layout.addStretch()

        self.main_layout = QVBoxLayout(self.main)
        self.main_layout.setContentsMargins(24, 18, 24, 18)
        self.main_layout.setSpacing(14)

        self.header = QFrame()
        self.header.setObjectName("header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        self.car_title = QLabel("NO TUNE LOADED")
        self.car_title.setObjectName("bigTitle")
        header_layout.addWidget(self.car_title, 1)
        header_layout.addSpacing(8)
        self.main_layout.addWidget(self.header)

        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack, 1)

        self.build_setup_page()
        self.build_tune_page()
        self.build_car_view_page()
        self.build_tuning_assist_page()
        self.build_telemetry_page()
        self.build_race_times_page()
        self.build_shared_lap_times_page()
        self.build_settings_page()

        self.apply_style()
        self.switch_page("Tuning" if self.config.get("first_setup_done") else "Setup")

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_telemetry_ui)
        self.timer.start(200)


    def clamp_sidebar_width(self, value) -> int:
        try:
            value = int(value)
        except Exception:
            value = 210
        return max(150, min(360, value))

    def apply_sidebar_width(self, value, save: bool = True):
        width = self.clamp_sidebar_width(value)

        if hasattr(self, "sidebar_splitter"):
            sizes = self.sidebar_splitter.sizes()
            total = sum(sizes) if sizes else max(self.width(), 1120)
            main_width = max(650, total - width)
            self.sidebar_splitter.setSizes([width, main_width])
        else:
            self.sidebar.setFixedWidth(width)

        if hasattr(self, "sidebar_width_spin"):
            old_state = self.sidebar_width_spin.blockSignals(True)
            self.sidebar_width_spin.setValue(width)
            self.sidebar_width_spin.blockSignals(old_state)

        self.config["sidebar_width"] = width
        if save:
            self.queue_sidebar_width_save()

    def sidebar_width_from_settings(self, value: int):
        self.apply_sidebar_width(value, save=True)

    def queue_sidebar_width_save(self, *args):
        if hasattr(self, "sidebar"):
            self.config["sidebar_width"] = self.clamp_sidebar_width(self.sidebar.width())

        if hasattr(self, "sidebar_width_spin"):
            old_state = self.sidebar_width_spin.blockSignals(True)
            self.sidebar_width_spin.setValue(self.config["sidebar_width"])
            self.sidebar_width_spin.blockSignals(old_state)

        if hasattr(self, "sidebar_save_timer"):
            self.sidebar_save_timer.start(650)

    def save_sidebar_width_now(self):
        if hasattr(self, "sidebar"):
            self.config["sidebar_width"] = self.clamp_sidebar_width(self.sidebar.width())
        save_config(self.config)

    def apply_style(self):
        accent = normalise_hex_colour(self.config.get("accent", "#ff2f6d"), "#ff2f6d")
        accent2 = normalise_hex_colour(self.config.get("accent2", "#00d4ff"), "#00d4ff")
        rounded = int(self.config.get("rounded", 14))

        # Use pre-blended plain #RRGGBB values so Qt actually paints the selected colours.
        bg = "#071017"
        panel = "#111923"
        card = "#151d27"
        row_bg = "#161d26"
        accent_soft = blend_hex(accent, panel, 0.30)
        accent_med = blend_hex(accent, panel, 0.55)
        accent_dark = blend_hex(accent, bg, 0.38)
        accent2_soft = blend_hex(accent2, panel, 0.28)
        accent2_med = blend_hex(accent2, panel, 0.45)
        header_mid = blend_hex(accent, "#101824", 0.22)
        header_end = blend_hex(accent2, "#101824", 0.22)
        button_start = blend_hex(accent, panel, 0.28)
        button_end = blend_hex(accent2, panel, 0.20)
        card_start = blend_hex(accent, card, 0.22)
        card_end = blend_hex(accent2, card, 0.18)
        row_start = blend_hex(accent, row_bg, 0.20)
        row_end = blend_hex(accent2, row_bg, 0.16)

        self.config["accent"] = accent
        self.config["accent2"] = accent2

        self.speedometer.set_accent(accent)
        self.steering.set_accent(accent)
        if hasattr(self, 'tachometer'):
            self.tachometer.set_accent(accent)
        if hasattr(self, 'tyre_status'):
            self.tyre_status.set_accent(accent)
        if hasattr(self, 'pedal_bars'):
            self.pedal_bars.set_accent(accent)
        if hasattr(self, 'suspension_visual'):
            self.suspension_visual.set_accent(accent)
        if hasattr(self, 'telemetry_hud'):
            self.telemetry_hud.set_accent(accent)
        if hasattr(self, 'car_showcase'):
            self.car_showcase.set_accent(accent)
        self.setStyleSheet(f"""
            QMainWindow, QWidget#main {{
                background: {bg};
                color: #f4f7fb;
                font-family: Segoe UI;
            }}
            QFrame#sidebar {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {blend_hex(accent, "#120913", 0.32)}, stop:0.45 {bg}, stop:1 {blend_hex(accent2, "#04151a", 0.28)});
                border-right: 1px solid #263442;
            }}
            QSplitter#mainSplitter::handle {{
                background: {blend_hex(accent2, bg, 0.18)};
                border-left: 1px solid #263442;
                border-right: 1px solid {blend_hex(accent2, bg, 0.30)};
            }}
            QSplitter#mainSplitter::handle:hover {{
                background: {blend_hex(accent2, bg, 0.38)};
            }}
            QFrame#brand, QFrame#sideCard {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {accent_dark}, stop:1 {accent2_soft});
                border: 1px solid {accent2_med};
                border-radius: {rounded}px;
            }}
            QWidget#tuneCard {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {card_start}, stop:0.55 {card}, stop:1 {card_end});
                border: 1px solid #2d3a49;
                border-radius: {rounded}px;
            }}
            QWidget#tuneCardFE {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #442006, stop:0.34 #7c2d12, stop:0.68 #7e22ce, stop:1 #0891b2);
                border: 1px solid #fbbf24;
                border-radius: {rounded}px;
            }}
            QLabel#feBadge {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #fbbf24, stop:1 #f97316);
                color: #111827;
                border-radius: 8px;
                padding: 4px 8px;
                font-weight: 950;
                font-size: 10px;
            }}
            QLabel#brandTitle {{
                color: #ffffff;
                font-size: 15px;
                font-weight: 900;
            }}
            QLabel#brandSub, QLabel#meta {{
                color: #91a4b7;
                font-size: 11px;
            }}
            QPushButton#navButton {{
                text-align: left;
                padding: 10px;
                border-radius: {rounded}px;
                border: 1px solid #273442;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {button_start}, stop:1 {button_end});
                color: #dce7f2;
                font-weight: 800;
            }}
            QPushButton#navButton:hover {{
                border: 1px solid {accent2};
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent_med}, stop:1 {accent2_med});
            }}
            QPushButton#navButton[active="true"] {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent}, stop:1 {accent2_med});
                border: 1px solid {accent};
                color: white;
            }}
            QLabel#sideSectionLabel {{
                color: #91a4b7;
                font-size: 10px;
                font-weight: 950;
                letter-spacing: 1px;
                padding: 4px 4px 0 4px;
            }}
            QPushButton#sideActionButton {{
                text-align: left;
                padding: 12px 12px;
                min-height: 50px;
                border-radius: {rounded}px;
                border: 1px solid {accent2_med};
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent_dark}, stop:1 {accent2_soft});
                color: #ffffff;
                font-size: 13px;
                font-weight: 950;
            }}
            QPushButton#sideActionButton:hover {{
                border: 1px solid {accent2};
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent}, stop:1 {accent2_med});
            }}
            QFrame#assistValueRow {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {row_start}, stop:0.55 {row_bg}, stop:1 {row_end});
                border: 1px solid #293746;
                border-radius: {rounded}px;
            }}
            QLabel#assistSuggestPill {{
                background: #57491b;
                color: #ffd84d;
                border: 1px solid #d99b00;
                border-radius: 9px;
                padding: 7px;
                font-weight: 950;
            }}
            QTabWidget::pane {{
                border: none;
                background: transparent;
            }}
            QTabBar::tab {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {button_start}, stop:1 {button_end});
                color: white;
                border-radius: 10px;
                min-width: 110px;
                padding: 10px 14px;
                margin: 4px;
                font-weight: 850;
            }}
            QTabBar::tab:selected {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent}, stop:1 {accent2_med});
                border: 1px solid {accent2};
            }}
            QFrame#assistRec {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {row_start}, stop:1 {row_end});
                border: 1px solid #334155;
                border-radius: {rounded}px;
            }}
            QFrame#assistInsight {{
                background: #211607;
                border: 1px solid #f59e0b;
                border-radius: {rounded}px;
            }}
            QLabel#assistRecTitle {{
                color: white;
                font-size: 15px;
                font-weight: 950;
            }}
            QLabel#assistInsightTitle {{
                color: #fbbf24;
                font-size: 14px;
                font-weight: 950;
            }}
            QLabel#assistValue {{
                color: white;
                font-size: 13px;
                font-weight: 900;
            }}
            QLabel#assistBadgeHigh {{
                background: #dc2626;
                color: white;
                border-radius: 9px;
                padding: 4px 9px;
                font-weight: 950;
            }}
            QLabel#assistBadge {{
                background: #475569;
                color: white;
                border-radius: 9px;
                padding: 4px 9px;
                font-weight: 900;
            }}
            QPushButton[sectionActive="true"] {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent}, stop:1 {accent2_med});
                border: 1px solid {accent};
                color: white;
            }}
            QFrame#header {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent_dark}, stop:0.55 {header_mid}, stop:1 {header_end});
                border: 1px solid {accent2_med};
                border-radius: {rounded}px;
            }}
            QFrame#card {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {card_start}, stop:0.55 {panel}, stop:1 {card_end});
                border: 1px solid #293746;
                border-radius: {rounded}px;
            }}
            QFrame#valueRow {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {row_start}, stop:0.55 {row_bg}, stop:1 {row_end});
                border: 1px solid #293746;
                border-radius: {rounded}px;
            }}
            QLabel#bigTitle {{
                color: white;
                font-size: 28px;
                font-weight: 950;
            }}
            QLabel#sectionTitle {{
                color: {accent};
                font-size: 13px;
                font-weight: 900;
            }}
            QLabel#statChip {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {button_start}, stop:1 {button_end});
                border: 1px solid #304050;
                border-radius: 10px;
                padding: 10px 16px;
                color: #ffffff;
                font-weight: 900;
            }}
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {button_start}, stop:1 {button_end});
                border: 1px solid #2d3a49;
                border-radius: 10px;
                padding: 10px 14px;
                color: #f4f7fb;
                font-weight: 800;
            }}
            QPushButton:hover {{
                border: 1px solid {accent2};
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent_med}, stop:1 {accent2_med});
            }}
            QPushButton#primary {{
                background: #0d7a60;
                border: 1px solid #10b981;
            }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {blend_hex(accent, panel, 0.12)};
                border: 1px solid #2d3a49;
                border-radius: 10px;
                color: white;
                padding: 10px;
            }}
            QListWidget, QScrollArea {{
                background: transparent;
                border: none;
                color: white;
            }}
            QLabel#tuneTitle {{
                color: #ffffff;
                font-size: 14px;
                font-weight: 900;
            }}
            QLabel#tuneHeaderName {{
                color: {accent2};
                font-size: 12px;
                font-weight: 900;
                background: {blend_hex(accent2, card, 0.12)};
                border: 1px solid {blend_hex(accent2, card, 0.38)};
                border-radius: 8px;
                padding: 5px 8px;
            }}
            QLabel#thumb {{
                min-height: 96px;
                color: #607487;
            }}
            QLabel#valuePill {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {blend_hex("#fbbf24", row_bg, 0.28)}, stop:1 {blend_hex("#fbbf24", row_bg, 0.14)});
                border: 1px solid #b8861e;
                border-radius: 8px;
                padding: 6px 10px;
                color: #ffd25a;
                font-weight: 900;
            }}
            QLabel#timerBig {{
                color: white;
                font-size: 56px;
                font-weight: 950;
                padding: 22px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent_dark}, stop:1 {accent2_soft});
                border: 1px solid {accent2_med};
                border-radius: {rounded}px;
            }}
            QSlider::groove:horizontal {{
                height: 8px;
                background: #0a1016;
                border: 1px solid #293746;
                border-radius: 4px;
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {accent}, stop:1 {accent2});
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: white;
                border: 2px solid {accent};
                width: 18px;
                margin: -7px 0;
                border-radius: 9px;
            }}
        """)

    def open_discord(self):
        QDesktopServices.openUrl(QUrl(DISCORD_INVITE_URL))

    def open_kofi(self):
        QDesktopServices.openUrl(QUrl(KOFI_URL))

    def switch_page(self, page):
        mapping = {"Setup": 0, "Tuning": 1, "Car View": 2, "Tuning Assist": 3, "Live Telemetry": 4, "Race Times": 5, "Shared Lap Times": 6, "Settings": 7}
        self.stack.setCurrentIndex(mapping.get(page, 0))

        # The Tuning page already has its own car/tune hero card, so the global
        # header card is redundant there. Keep it for the other pages.
        self.header.setVisible(page != "Tuning")

        for name, btn in self.nav_buttons.items():
            btn.setProperty("active", name == page)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if page == "Setup":
            self.car_title.setText("SETUP")
        elif page == "Car View":
            self.car_title.setText("CAR VIEW")
            self.refresh_car_view()
        elif page == "Tuning Assist":
            self.car_title.setText("TUNING ASSIST")
            self.refresh_tuning_assist()
        elif page == "Live Telemetry":
            self.car_title.setText("LIVE TELEMETRY")
        elif page == "Settings":
            self.car_title.setText("SETTINGS")
        elif page == "Race Times":
            self.car_title.setText("RACE TIMES")
        elif page == "Shared Lap Times":
            self.car_title.setText("SHARED LAP TIMES")
        elif self.current:
            self.update_header()
        else:
            self.car_title.setText("NO TUNE LOADED")

    def make_scroll_page(self):
        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        area.setWidget(content)
        return area, content, layout

    def build_setup_page(self):
        area, content, layout = self.make_scroll_page()

        welcome = Card("First-launch setup")
        title = QLabel("FH6 Tune Editor Setup")
        title.setObjectName("bigTitle")
        welcome.body.addWidget(title)

        note = QLabel(
            "Default FH6 tune folder is set for Xbox/Game Pass installs. "
            "You can load it directly or browse to another folder."
        )
        note.setObjectName("meta")
        note.setWordWrap(True)
        welcome.body.addWidget(note)

        folder_grid = QGridLayout()
        self.setup_folder_input = QLineEdit(str(self.config.get("last_scan_folder", self.config.get("last_tune_folder", DEFAULT_TUNE_FOLDER_GLOB))))
        folder_grid.addWidget(QLabel("Default tune folder"), 0, 0)
        folder_grid.addWidget(self.setup_folder_input, 0, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_setup_folder)
        folder_grid.addWidget(browse_btn, 0, 2)

        load_btn = QPushButton("Load Tunes From This Folder")
        load_btn.setObjectName("primary")
        load_btn.clicked.connect(self.load_setup_tune_folder)
        folder_grid.addWidget(load_btn, 1, 1, 1, 2)
        welcome.body.addLayout(folder_grid)

        telemetry_note = QLabel("Telemetry UDP port: 3010. Keep FH6 Data Out pointed at this port.")
        telemetry_note.setObjectName("valuePill")
        telemetry_note.setWordWrap(True)
        welcome.body.addWidget(telemetry_note)

        prefs = QGridLayout()
        self.setup_speed_combo = QComboBox()
        self.setup_speed_combo.addItems(["MPH", "KM/H"])
        self.setup_speed_combo.setCurrentText("KM/H" if self.speed_unit == "kmh" else "MPH")
        prefs.addWidget(QLabel("Speed units"), 0, 0)
        prefs.addWidget(self.setup_speed_combo, 0, 1)

        self.setup_auto_load_current_car = QCheckBox("Auto-load tune when telemetry detects current car")
        self.setup_auto_load_current_car.setChecked(bool(self.config.get("auto_load_current_car_tune", True)))
        prefs.addWidget(self.setup_auto_load_current_car, 1, 0, 1, 2)

        public_note = QLabel("Public release: automatic update checks and automatic thumbnail downloads are disabled.")
        public_note.setObjectName("meta")
        public_note.setWordWrap(True)
        prefs.addWidget(public_note, 2, 0, 1, 2)

        save_btn = QPushButton("Save Setup")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save_setup_settings)
        prefs.addWidget(save_btn, 3, 0, 1, 2)
        welcome.body.addLayout(prefs)
        layout.addWidget(welcome)

        diag = Card("Diagnostics")
        diag_note = QLabel("Useful after converting to EXE too. Exports app version, Python/EXE info, folders, config, tune count, and telemetry status.")
        diag_note.setObjectName("meta")
        diag_note.setWordWrap(True)
        diag.body.addWidget(diag_note)
        diag_btn = QPushButton("Export Diagnostic Report")
        diag_btn.clicked.connect(self.export_diagnostics)
        diag.body.addWidget(diag_btn)
        layout.addWidget(diag)

        self.stack.addWidget(area)

    def browse_setup_folder(self):
        start = self.setup_folder_input.text().replace("*", "") if hasattr(self, "setup_folder_input") else ""
        folder = QFileDialog.getExistingDirectory(self, "Choose FH6 tune folder", start)
        if folder:
            self.setup_folder_input.setText(folder)

    def setup_tune_candidates(self) -> list[Path]:
        pattern = self.setup_folder_input.text().strip() if hasattr(self, "setup_folder_input") else DEFAULT_TUNE_FOLDER_GLOB
        matches = glob.glob(pattern)
        paths = []
        if matches:
            for match in matches:
                paths.extend(discover_tune_files(Path(match)))
        else:
            paths.extend(discover_tune_files(Path(pattern)))
        # de-dupe while preserving order
        seen = set()
        unique = []
        for p in paths:
            key = str(p)
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def load_setup_tune_folder(self):
        paths = self.setup_tune_candidates()
        scan_folder = self.setup_folder_input.text().strip() or DEFAULT_TUNE_FOLDER_GLOB
        self.config["last_tune_folder"] = scan_folder
        self.config["last_scan_folder"] = scan_folder
        self.config["auto_detect_tune_folder"] = (scan_folder == DEFAULT_TUNE_FOLDER_GLOB)
        save_config(self.config)
        if not paths:
            QMessageBox.information(
                self,
                "No tunes found",
                f"No tune files were found under:\n{self.config['last_tune_folder']}",
            )
            return
        self.load_paths(paths)
        self.switch_page("Tuning")

    def save_setup_settings(self):
        scan_folder = self.setup_folder_input.text().strip() or DEFAULT_TUNE_FOLDER_GLOB
        self.config["last_tune_folder"] = scan_folder
        self.config["last_scan_folder"] = scan_folder
        self.config["auto_detect_tune_folder"] = (scan_folder == DEFAULT_TUNE_FOLDER_GLOB)
        self.config["telemetry_port"] = 3010
        self.config["speed_unit"] = "kmh" if self.setup_speed_combo.currentText() == "KM/H" else "mph"
        self.config["auto_update_check"] = False
        self.config["auto_thumbnail_cache_update"] = False
        self.config["auto_load_current_car_tune"] = bool(self.setup_auto_load_current_car.isChecked())
        self.config["first_setup_done"] = True
        save_config(self.config)
        self.speed_unit = self.config["speed_unit"]
        if hasattr(self, "speed_unit_btn"):
            self.speed_unit_btn.setText("Speed: KM/H" if self.speed_unit == "kmh" else "Speed: MPH")
        QMessageBox.information(self, "Setup saved", "Setup saved. Telemetry port is 3010.")
        self.switch_page("Tuning")


    def build_tune_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        hero = Card("Tuning")
        self.hero_title = QLabel("Load a tune folder to begin")
        self.hero_title.setObjectName("bigTitle")
        self.hero_sub = QLabel("FH6 Tune Editor · Qt prototype")
        self.hero_sub.setObjectName("meta")
        hero.body.addWidget(self.hero_title)
        hero.body.addWidget(self.hero_sub)
        outer.addWidget(hero)

        actions = QHBoxLayout()
        for text, fn in [
            ("Open Folder", self.open_folder),
            ("Open File", self.open_file),
            ("Import JSON", self.import_share_json),
            ("Share JSON", self.share_json),
            ("Save Copy", self.save_copy),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            actions.addWidget(btn)
        outer.addLayout(actions)

        body = QHBoxLayout()
        body.setSpacing(14)

        left_panel = Card("Loaded Tunes")
        left_panel.setFixedWidth(370)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search car, tune name or description...")
        self.search.textChanged.connect(self.refresh_tune_list)
        left_panel.body.addWidget(self.search)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Newest first", "Oldest first", "Car name A-Z", "Tune name A-Z"])
        self.sort_combo.currentTextChanged.connect(self.refresh_tune_list)
        left_panel.body.addWidget(self.sort_combo)

        self.brand_filter = QComboBox()
        self.brand_filter.currentTextChanged.connect(self.refresh_tune_list)
        left_panel.body.addWidget(self.brand_filter)

        self.year_filter = QComboBox()
        self.year_filter.currentTextChanged.connect(self.refresh_tune_list)
        left_panel.body.addWidget(self.year_filter)

        self.fe_filter = QComboBox()
        self.fe_filter.addItems(["All cars", "Forza Edition only", "Exclude Forza Edition"])
        self.fe_filter.currentTextChanged.connect(self.refresh_tune_list)
        left_panel.body.addWidget(self.fe_filter)

        self.tune_list = QListWidget()
        self.tune_list.itemClicked.connect(self.on_tune_clicked)
        left_panel.body.addWidget(self.tune_list, 1)
        body.addWidget(left_panel)

        right = QVBoxLayout()
        self.section_bar = QGridLayout()
        self.section_bar.setHorizontalSpacing(8)
        self.section_bar.setVerticalSpacing(8)
        self.section_buttons = {}
        sections = ["Upgrades", "Gearing", "Tyres", "Alignment", "Anti-roll Bars", "Springs", "Damping", "Aero", "Brakes", "Differential", "Raw"]
        for idx, sec in enumerate(sections):
            btn = QPushButton(sec)
            btn.setMinimumWidth(112)
            btn.setMinimumHeight(38)
            btn.clicked.connect(lambda checked=False, s=sec: self.show_tune_section(s))
            self.section_bar.addWidget(btn, idx // 6, idx % 6)
            self.section_buttons[sec] = btn
        self.update_section_button_state()
        right.addLayout(self.section_bar)

        self.tune_section_stack = QStackedWidget()
        placeholder = QLabel("Load and select a tune to view values.")
        placeholder.setAlignment(Qt.AlignCenter)
        self.tune_section_stack.addWidget(placeholder)
        right.addWidget(self.tune_section_stack, 1)

        body.addLayout(right, 1)
        outer.addLayout(body, 1)
        self.stack.addWidget(page)

    def current_tyre_pressure_targets(self):
        if not self.current:
            return None, None
        try:
            front = FIELD_BY_INDEX[12].raw_to_display(self.current.values[12])
        except Exception:
            front = None
        try:
            rear = FIELD_BY_INDEX[23].raw_to_display(self.current.values[23])
        except Exception:
            rear = None
        return front, rear

    def build_car_view_page(self):
        area, content, layout = self.make_scroll_page()

        top = QHBoxLayout()
        card_wrap = Card("Car Card Viewer")
        card_wrap.body.setSpacing(12)
        self.car_showcase = CarShowcaseCardWidget()
        card_wrap.body.addWidget(self.car_showcase, alignment=Qt.AlignHCenter)

        card_actions = QHBoxLayout()
        flip_btn = QPushButton("Flip Card")
        flip_btn.clicked.connect(self.flip_car_card)
        load_img_btn = QPushButton("Load Card Image")
        load_img_btn.clicked.connect(self.load_car_card_image)
        clear_img_btn = QPushButton("Clear Card Image")
        clear_img_btn.clicked.connect(self.clear_car_card_image)
        export_btn = QPushButton("Export Card PNG")
        export_btn.clicked.connect(self.export_car_card_png)
        card_actions.addWidget(flip_btn)
        card_actions.addWidget(load_img_btn)
        card_actions.addWidget(clear_img_btn)
        card_actions.addWidget(export_btn)
        card_actions.addStretch(1)
        card_wrap.body.addLayout(card_actions)
        top.addWidget(card_wrap, 2)

        detail = Card("Loaded Tune Details")
        self.car_view_title = QLabel("No tune selected")
        self.car_view_title.setObjectName("bigTitle")
        self.car_view_title.setWordWrap(True)
        detail.body.addWidget(self.car_view_title)
        self.car_view_meta = QLabel("Load or select a tune to show its car card.")
        self.car_view_meta.setObjectName("meta")
        self.car_view_meta.setWordWrap(True)
        detail.body.addWidget(self.car_view_meta)
        grid = QGridLayout()
        self.car_view_labels = {}
        for i, key in enumerate(["tune_name", "ordinal", "drivetrain", "gears", "forza_edition", "pi", "final_drive", "tyres", "tune_hash", "tune_path"]):
            lbl = QLabel(f"{key.replace('_', ' ').title()}\n--")
            lbl.setObjectName("statChip")
            lbl.setWordWrap(True)
            grid.addWidget(lbl, i // 2, i % 2)
            self.car_view_labels[key] = lbl
        detail.body.addLayout(grid)

        manual_label = QLabel("Manual Card Stats")
        manual_label.setObjectName("sectionTitleSmall")
        detail.body.addWidget(manual_label)

        manual_note = QLabel("Display-only values for the card. These do not edit the tune file.")
        manual_note.setObjectName("meta")
        manual_note.setWordWrap(True)
        detail.body.addWidget(manual_note)

        self.card_manual_enabled = QCheckBox("Use manual stats on card")
        detail.body.addWidget(self.card_manual_enabled)

        self.card_force_holo = QCheckBox("Force holographic effect")
        detail.body.addWidget(self.card_force_holo)

        holo_note = QLabel("Applies the shiny/foil effect to any card. The FORZA EDITION badge still only appears on actual FE cars.")
        holo_note.setObjectName("meta")
        holo_note.setWordWrap(True)
        detail.body.addWidget(holo_note)

        manual_grid = QGridLayout()
        self.card_manual_class = QComboBox()
        self.card_manual_class.addItems(["D", "C", "B", "A", "S1", "S2", "R", "X"])
        self.card_manual_class.setCurrentText("A")

        self.card_manual_pi = QSpinBox()
        self.card_manual_pi.setRange(100, 999)
        self.card_manual_pi.setValue(800)

        self.card_manual_power = QSpinBox()
        self.card_manual_power.setRange(0, 3000)
        self.card_manual_power.setValue(276)

        self.card_manual_weight = QSpinBox()
        self.card_manual_weight.setRange(0, 4000)
        self.card_manual_weight.setValue(1260)

        self.card_manual_top_speed = QSpinBox()
        self.card_manual_top_speed.setRange(0, 400)
        self.card_manual_top_speed.setValue(156)

        self.card_manual_handling = QDoubleSpinBox()
        self.card_manual_handling.setRange(0.0, 10.0)
        self.card_manual_handling.setDecimals(1)
        self.card_manual_handling.setSingleStep(0.1)
        self.card_manual_handling.setValue(7.4)

        self.card_manual_accel = QDoubleSpinBox()
        self.card_manual_accel.setRange(0.0, 10.0)
        self.card_manual_accel.setDecimals(1)
        self.card_manual_accel.setSingleStep(0.1)
        self.card_manual_accel.setValue(6.8)

        self.card_manual_launch = QDoubleSpinBox()
        self.card_manual_launch.setRange(0.0, 10.0)
        self.card_manual_launch.setDecimals(1)
        self.card_manual_launch.setSingleStep(0.1)
        self.card_manual_launch.setValue(7.2)

        self.card_manual_braking = QDoubleSpinBox()
        self.card_manual_braking.setRange(0.0, 10.0)
        self.card_manual_braking.setDecimals(1)
        self.card_manual_braking.setSingleStep(0.1)
        self.card_manual_braking.setValue(6.9)

        manual_fields = [
            ("Class", self.card_manual_class),
            ("PI", self.card_manual_pi),
            ("Power HP", self.card_manual_power),
            ("Weight KG", self.card_manual_weight),
            ("Top Speed MPH", self.card_manual_top_speed),
            ("Handling", self.card_manual_handling),
            ("Acceleration", self.card_manual_accel),
            ("Launch", self.card_manual_launch),
            ("Braking", self.card_manual_braking),
        ]

        for row, (label, widget) in enumerate(manual_fields):
            lbl = QLabel(label)
            lbl.setObjectName("meta")
            manual_grid.addWidget(lbl, row, 0)
            manual_grid.addWidget(widget, row, 1)

        detail.body.addLayout(manual_grid)

        for widget in [
            self.card_manual_enabled, self.card_force_holo, self.card_manual_class, self.card_manual_pi,
            self.card_manual_power, self.card_manual_weight, self.card_manual_top_speed,
            self.card_manual_handling, self.card_manual_accel, self.card_manual_launch,
            self.card_manual_braking,
        ]:
            try:
                widget.toggled.connect(lambda *_: self.update_car_card_manual_stats())
            except Exception:
                pass
            try:
                widget.currentTextChanged.connect(lambda *_: self.update_car_card_manual_stats())
            except Exception:
                pass
            try:
                widget.valueChanged.connect(lambda *_: self.update_car_card_manual_stats())
            except Exception:
                pass

        top.addWidget(detail, 1)
        layout.addLayout(top)

        note = Card("Card notes")
        note_text = QLabel("This now uses the same card-rendering logic as WN_CarCard_Prototype_v0_5_1. It is loaded-tune based, can use cached/local thumbnails, and also lets you manually load a card image if a thumbnail is missing. Power, weight, top speed, class/PI and ratings can be entered manually as display-only card stats. You can also force the holographic effect without showing the Forza Edition badge.")
        note_text.setObjectName("meta")
        note_text.setWordWrap(True)
        note.body.addWidget(note_text)
        layout.addWidget(note)

        self.stack.addWidget(area)

    def flip_car_card(self):
        if hasattr(self, "car_showcase"):
            self.car_showcase.toggle_side()

    def load_car_card_image(self):
        if not hasattr(self, "car_showcase"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose card image / thumbnail",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not path:
            return
        self.car_showcase.set_manual_image(path)

    def clear_car_card_image(self):
        if hasattr(self, "car_showcase"):
            self.car_showcase.clear_manual_image()

    def export_car_card_png(self):
        if not hasattr(self, "car_showcase"):
            return
        default = "car_card.png"
        if self.current:
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", self.current.display_name).strip("_")[:80] or "car_card"
            default = f"{safe_name}_card.png"
        path, _ = QFileDialog.getSaveFileName(self, "Export car card", default, "PNG Image (*.png)")
        if not path:
            return
        pix = self.car_showcase.grab()
        if pix.save(path, "PNG"):
            QMessageBox.information(self, "Export complete", f"Saved car card to:\n{path}")
        else:
            QMessageBox.warning(self, "Export failed", "Could not save the card image.")

    def update_car_card_manual_stats(self):
        if not hasattr(self, "car_showcase") or not hasattr(self, "card_manual_enabled"):
            return
        self.car_showcase.set_manual_stats(
            enabled=self.card_manual_enabled.isChecked(),
            card_class=self.card_manual_class.currentText(),
            pi=self.card_manual_pi.value(),
            power_hp=self.card_manual_power.value(),
            weight_kg=self.card_manual_weight.value(),
            top_speed_mph=self.card_manual_top_speed.value(),
            handling=self.card_manual_handling.value(),
            acceleration=self.card_manual_accel.value(),
            launch=self.card_manual_launch.value(),
            braking=self.card_manual_braking.value(),
            force_holographic=self.card_force_holo.isChecked(),
        )

    def refresh_car_view(self):
        if not hasattr(self, "car_showcase"):
            return
        tune = self.current
        # Car View is loaded-tune based only. Telemetry is used by Live Telemetry
        # and Tuning Assist, not by the card identity/details.
        self.car_showcase.set_tune(tune, {})
        self.car_showcase.set_accent(self.config.get("accent", "#ff2f6d"))
        self.update_car_card_manual_stats()
        if not tune:
            if hasattr(self, "car_view_title"):
                self.car_view_title.setText("No tune selected")
                self.car_view_meta.setText("Load or select a tune to show its car card.")
                for lbl in self.car_view_labels.values():
                    lbl.setText("--")
            return

        self.car_view_title.setText(tune.display_name)
        meta_bits = [tune.drivetrain_label, f"{tune.active_gear_count} gears", f"#{tune.ordinal}"]
        if tune.header_name:
            meta_bits.insert(0, "Header auto-loaded")
        self.car_view_meta.setText(" · ".join(meta_bits))
        values = {
            "tune_name": f"Tune Name\n{tune.header_name or '--'}",
            "ordinal": f"Ordinal\n#{tune.ordinal}",
            "drivetrain": f"Drivetrain\n{tune.drivetrain_label}",
            "gears": f"Gears\n{tune.active_gear_count}",
            "forza_edition": f"Forza Edition\n{'Yes' if is_forza_edition_name(tune.car_name) else 'No'}",
            "pi": "Class / PI\nNot stored in tune",
            "final_drive": f"Final Drive\n{format_field_display(2, tune_display_value(tune, 2))}",
            "tyres": f"Tyres F/R\n{format_field_display(12, tune_display_value(tune, 12))} / {format_field_display(23, tune_display_value(tune, 23))}",
            "tune_hash": f"Tune Hash\n{tune.md5[:12]}",
            "tune_path": f"Tune Path\n{tune.path}",
        }
        for key, value in values.items():
            self.car_view_labels[key].setText(value)

    def build_tuning_assist_page(self):
        area, content, layout = self.make_scroll_page()

        control = Card("Tuning Assist")
        title = QLabel("Tune Assist Preview")
        title.setObjectName("bigTitle")
        control.body.addWidget(title)
        note = QLabel(
            "This uses the currently selected/loaded tune. White markers are current values, gold markers are suggested values. "
            "Suggestions are driven by Tune Type / Goal and are preview-only until we decide how to apply/export them."
        )
        note.setObjectName("meta")
        note.setWordWrap(True)
        control.body.addWidget(note)

        row = QHBoxLayout()
        tune_type_label = QLabel("Tune Type / Goal")
        tune_type_label.setObjectName("sectionTitle")
        self.assist_tune_type_combo = QComboBox()
        self.assist_tune_type_combo.addItems(ASSIST_TUNE_TYPES)
        self.assist_tune_type_combo.currentTextChanged.connect(self.refresh_tuning_assist)
        self.assist_analyse_btn = QPushButton("Analyse Current Tune")
        self.assist_analyse_btn.setObjectName("primary")
        self.assist_analyse_btn.clicked.connect(self.refresh_tuning_assist)
        self.assist_export_btn = QPushButton("Export Suggestions JSON")
        self.assist_export_btn.clicked.connect(self.export_tuning_assist_json)
        self.assist_export_btn.setEnabled(False)
        row.addWidget(tune_type_label)
        row.addWidget(self.assist_tune_type_combo, 2)
        row.addWidget(self.assist_analyse_btn)
        row.addWidget(self.assist_export_btn)
        control.body.addLayout(row)
        layout.addWidget(control)

        summary = Card("Assist Summary")
        self.assist_summary = QLabel("Load or select a tune to begin.")
        self.assist_summary.setObjectName("meta")
        self.assist_summary.setWordWrap(True)
        summary.body.addWidget(self.assist_summary)
        layout.addWidget(summary)

        legend = QLabel("White marker = current loaded tune value   •   Gold marker = suggested value   •   Gold dashed line = previewed change")
        legend.setObjectName("valuePill")
        legend.setWordWrap(True)
        layout.addWidget(legend)

        self.assist_tabs = QTabWidget()
        self.assist_rows = {}
        for section in ["Gearing", "Tyres", "Alignment", "Anti-roll Bars", "Springs", "Damping", "Aero", "Brakes", "Differential"]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            inner = QWidget()
            vbox = QVBoxLayout(inner)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(10)
            title_lbl = QLabel(section.upper())
            title_lbl.setObjectName("sectionTitle")
            vbox.addWidget(title_lbl)
            for field in FIELDS_BY_SECTION.get(section, []):
                row_widget = AssistTuneValueRow(field)
                self.assist_rows[field.index] = row_widget
                vbox.addWidget(row_widget)
            vbox.addStretch(1)
            scroll.setWidget(inner)
            self.assist_tabs.addTab(scroll, section)
        layout.addWidget(self.assist_tabs)

        self.assist_recommendations = []
        self.assist_insights = []
        self.assist_suggestion_map = {}
        self.stack.addWidget(area)

    def refresh_tuning_assist(self, *_args):
        if not hasattr(self, "assist_rows"):
            return

        self.assist_recommendations = []
        self.assist_insights = []
        self.assist_suggestion_map = {}

        if not self.current:
            if hasattr(self, "assist_summary"):
                self.assist_summary.setText("Load or select a tune to begin. Tune Assist always follows the currently viewed tune.")
            for row in self.assist_rows.values():
                row.set_values(None, None)
            if hasattr(self, "assist_export_btn"):
                self.assist_export_btn.setEnabled(False)
            return

        tune_type = self.assist_tune_type_combo.currentText() if hasattr(self, "assist_tune_type_combo") else "Balanced"
        self.assist_suggestion_map = build_tune_type_suggestion_map(self.current, tune_type)
        self.assist_recommendations = list(self.assist_suggestion_map.values())
        self.assist_recommendations.sort(key=lambda r: (r.field.section, r.field.index))

        for idx, row in self.assist_rows.items():
            row.set_values(self.current, self.assist_suggestion_map.get(idx))

        suggested_count = len(self.assist_recommendations)
        self.assist_summary.setText(
            f"Current tune: {self.current.display_name}\n"
            f"Tune type / goal: {tune_type}\n"
            f"Drivetrain: {self.current.drivetrain_label} · Gears: {self.current.active_gear_count} · Ordinal: #{self.current.ordinal}\n"
            f"Suggested value previews: {suggested_count}\n"
            f"Tune path: {self.current.path}"
        )
        self.assist_export_btn.setEnabled(bool(self.assist_recommendations))

    def export_tuning_assist_json(self):
        if not self.current or not getattr(self, "assist_recommendations", None):
            return
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", self.current.display_name).strip("_")[:80] or "tune"
        path, _ = QFileDialog.getSaveFileName(self, "Export tuning assist suggestions", f"{safe_name}_assist_preview.json", "JSON (*.json)")
        if not path:
            return
        tune_type = self.assist_tune_type_combo.currentText() if hasattr(self, "assist_tune_type_combo") else "Balanced"
        payload = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "car": self.current.car_name,
            "tune_name": self.current.header_name,
            "ordinal": self.current.ordinal,
            "drivetrain": self.current.drivetrain_label,
            "gears": self.current.active_gear_count,
            "tune_file": str(self.current.path),
            "tune_hash": self.current.md5,
            "tune_type": tune_type,
            "preview_only": True,
            "recommendations": [
                {
                    "section": rec.field.section,
                    "field": rec.field.label,
                    "index": rec.field_index,
                    "current": rec.current,
                    "suggested": rec.suggested,
                    "unit": rec.field.unit,
                    "delta": rec.delta,
                    "priority": rec.priority,
                    "source": rec.source,
                    "reason": rec.reason,
                }
                for rec in self.assist_recommendations
            ],
        }
        try:
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Export complete", f"Saved suggestions to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def build_telemetry_page(self):
        area, content, layout = self.make_scroll_page()

        controls_card = Card("Forza Data Out Telemetry")
        row = QHBoxLayout()
        self.start_tel_btn = QPushButton("Start Telemetry")
        self.start_tel_btn.setObjectName("primary")
        self.stop_tel_btn = QPushButton("Stop")
        self.clear_tel_btn = QPushButton("Clear Log")
        self.export_tel_btn = QPushButton("Export CSV")
        self.load_current_car_btn = QPushButton("Load Current Car Tune")
        self.speed_unit_btn = QPushButton("Speed: MPH")
        self.start_tel_btn.clicked.connect(self.start_telemetry)
        self.stop_tel_btn.clicked.connect(self.stop_telemetry)
        self.clear_tel_btn.clicked.connect(self.clear_telemetry)
        self.export_tel_btn.clicked.connect(self.export_telemetry_csv)
        self.load_current_car_btn.clicked.connect(lambda: self.load_current_car_tune_from_telemetry(silent=False))
        self.speed_unit_btn.clicked.connect(self.toggle_speed_unit)
        for b in [self.start_tel_btn, self.stop_tel_btn, self.clear_tel_btn, self.export_tel_btn, self.load_current_car_btn, self.speed_unit_btn]:
            row.addWidget(b)
        controls_card.body.addLayout(row)
        self.tel_car = QLabel("Waiting for telemetry packet...")
        self.tel_car.setObjectName("bigTitle")
        controls_card.body.addWidget(self.tel_car)
        tel_note = QLabel("HUD-style telemetry with speedometer, rev meter, steering, pedal inputs, suspension travel, tyre temperatures, and loaded tune pressure targets.")
        tel_note.setObjectName("meta")
        tel_note.setWordWrap(True)
        controls_card.body.addWidget(tel_note)
        layout.addWidget(controls_card)

        hud_card = Card()
        self.telemetry_hud = TelemetryHudStrip()
        hud_card.body.addWidget(self.telemetry_hud)
        layout.addWidget(hud_card)

        top_row = QHBoxLayout()
        speed_card = Card("Speedometer")
        self.speedometer = Speedometer()
        speed_card.body.addWidget(self.speedometer)
        tach_card = Card("Rev Meter")
        self.tachometer = Tachometer()
        tach_card.body.addWidget(self.tachometer)
        steer_card = Card("Steering")
        self.steering = SteeringWheel()
        steer_card.body.addWidget(self.steering)
        top_row.addWidget(speed_card, 2)
        top_row.addWidget(tach_card, 2)
        top_row.addWidget(steer_card, 2)
        layout.addLayout(top_row)

        second_row = QHBoxLayout()
        tyre_card = Card("Tyre Pressures / Temps")
        self.tyre_status = TyreStatusWidget()
        tyre_card.body.addWidget(self.tyre_status)
        second_row.addWidget(tyre_card, 3)

        pedal_card = Card("Pedals")
        self.pedal_bars = PedalBarsWidget()
        pedal_card.body.addWidget(self.pedal_bars)
        second_row.addWidget(pedal_card, 2)

        suspension_card = Card("Suspension")
        self.suspension_visual = SuspensionTravelWidget()
        suspension_card.body.addWidget(self.suspension_visual)
        second_row.addWidget(suspension_card, 3)
        layout.addLayout(second_row)

        dash = Card("Live Dashboard")
        grid = QGridLayout()
        self.tel_labels = {}
        for i, key in enumerate(["speed", "rpm", "gear", "throttle", "brake", "power", "torque", "packets"]):
            lbl = QLabel(f"{key.upper()}\n--")
            lbl.setObjectName("statChip")
            grid.addWidget(lbl, i // 4, i % 4)
            self.tel_labels[key] = lbl
        dash.body.addLayout(grid)
        layout.addWidget(dash)

        self.stack.addWidget(area)

    def current_race_timer_seconds(self) -> float:
        # This timer is now telemetry-clock based, not wall-clock based.
        # It only increases when FH6 telemetry timestamps move forward.
        return float(self.race_timer_elapsed or 0.0)

    def best_available_race_time_seconds(self) -> float:
        saved = float(self.race_timer_saved_elapsed or 0.0)
        if saved > 0:
            return saved
        current = self.current_race_timer_seconds()
        return current if current > 0 else 0.0

    def current_race_car_name(self) -> str:
        if self.race_timer_car_name:
            return self.race_timer_car_name
        data = getattr(self, "telemetry_last", {}) or {}
        car = data.get("telemetry_car_name")
        if car and car != "--":
            return car
        if self.current:
            return self.current.car_name
        return "Unknown car"

    def start_race_timer(self, source: str = "manual"):
        if self.race_timer_running:
            return
        self.race_timer_running = True
        self.race_timer_auto_paused = False
        data = getattr(self, "telemetry_last", {}) or {}
        car = data.get("telemetry_car_name")
        if car and car != "--":
            self.race_timer_car_name = car
            self.race_timer_ordinal = data.get("car_ordinal")
        elif self.current:
            self.race_timer_car_name = self.current.car_name
            self.race_timer_ordinal = self.current.ordinal
        self.race_timer_start_monotonic = time.monotonic()
        self.race_timer_last_packet_unix = time.time()
        ts = data.get("timestamp_ms")
        self.race_timer_last_timestamp_ms = int(ts) if isinstance(ts, (int, float)) else None
        self.race_timer_status_text = f"Running ({source})"
        if hasattr(self, "manual_timer_start_btn"):
            self.manual_timer_start_btn.setEnabled(False)
        if hasattr(self, "manual_timer_stop_btn"):
            self.manual_timer_stop_btn.setEnabled(True)

    def stop_race_timer(self, source: str = "manual"):
        if self.race_timer_elapsed > 0:
            self.race_timer_saved_elapsed = self.race_timer_elapsed
        self.race_timer_running = False
        self.race_timer_auto_paused = False
        self.race_timer_last_timestamp_ms = None
        self.race_timer_status_text = f"Saved ({source})"
        if hasattr(self, "manual_timer_start_btn"):
            self.manual_timer_start_btn.setEnabled(True)
        if hasattr(self, "manual_timer_stop_btn"):
            self.manual_timer_stop_btn.setEnabled(False)
        self.refresh_share_preview()

    def reset_race_timer(self):
        self.race_timer_running = False
        self.race_timer_start_monotonic = 0.0
        self.race_timer_elapsed = 0.0
        self.race_timer_saved_elapsed = 0.0
        self.race_timer_last_timestamp_ms = None
        self.race_timer_last_is_race_on = 0
        self.race_timer_last_packet_unix = 0.0
        self.race_timer_car_name = ""
        self.race_timer_ordinal = None
        self.race_timer_auto_paused = False
        self.race_timer_last_game_current = 0.0
        self.race_timer_last_game_last = 0.0
        self.race_timer_last_game_best = 0.0
        self.race_timer_status_text = "Ready"
        if hasattr(self, "manual_timer_start_btn"):
            self.manual_timer_start_btn.setEnabled(True)
        if hasattr(self, "manual_timer_stop_btn"):
            self.manual_timer_stop_btn.setEnabled(True)
        self.refresh_share_preview()

    def update_app_race_timer_from_telemetry(self, data: dict):
        """Telemetry-clock timer.

        The old version counted wall-clock time, so it kept running if the game was paused or tabbed out.
        This version only adds time when FH6 telemetry timestamp_ms advances.
        """
        game_current = seconds_from_lap_text(data.get("lap_time_current"))
        game_last = seconds_from_lap_text(data.get("lap_time_last"))
        game_best = seconds_from_lap_text(data.get("lap_time_best"))
        is_race_on = int(data.get("is_race_on") or 0)
        ts_raw = data.get("timestamp_ms")
        ts_ms = int(ts_raw) if isinstance(ts_raw, (int, float)) else None
        speed = float(data.get("speed_mph") or 0.0)
        throttle = float(data.get("throttle") or 0.0)
        car = data.get("telemetry_car_name")
        if car and car != "--" and (self.race_timer_running or not self.race_timer_car_name):
            self.race_timer_car_name = car
            self.race_timer_ordinal = data.get("car_ordinal")

        # Auto-start on a real race transition first. Fall back to movement/throttle only when no saved time exists.
        active_signal = (
            is_race_on == 1
            or game_current > 0.2
            or (speed > 8 and throttle > 5 and self.telemetry_packets > 8)
        )
        race_transition_started = self.race_timer_last_is_race_on == 0 and is_race_on == 1

        if not self.race_timer_running and self.race_timer_saved_elapsed <= 0 and (race_transition_started or active_signal):
            self.start_race_timer("auto")
            self.race_timer_last_timestamp_ms = ts_ms

        if self.race_timer_running:
            added = 0.0
            if ts_ms is not None and self.race_timer_last_timestamp_ms is not None:
                delta_ms = ts_ms - self.race_timer_last_timestamp_ms
                # Normal Forza packet delta should be tiny. Ignore huge jumps/resets.
                if 0 < delta_ms <= 2000:
                    added = delta_ms / 1000.0
            elif game_current > self.race_timer_last_game_current:
                delta_raw = game_current - self.race_timer_last_game_current
                if 0 < delta_raw <= 2.0:
                    added = delta_raw

            if active_signal and added > 0:
                self.race_timer_elapsed += added
                self.race_timer_auto_paused = False
            elif not active_signal:
                self.race_timer_auto_paused = True

            self.race_timer_last_packet_unix = time.time()
            if ts_ms is not None:
                self.race_timer_last_timestamp_ms = ts_ms

            # Auto-stop when FH clearly leaves race mode or raw lap fields clearly reset/update.
            finish_by_race_off = (
                self.race_timer_last_is_race_on == 1
                and is_race_on == 0
                and self.race_timer_elapsed > 5
            )
            finish_by_current_reset = (
                self.race_timer_elapsed > 5
                and self.race_timer_last_game_current > 5
                and 0 <= game_current < 0.75
            )
            finish_by_last_update = (
                self.race_timer_elapsed > 5
                and game_last > 5
                and abs(game_last - self.race_timer_last_game_last) > 0.05
            )
            finish_by_best_update = (
                self.race_timer_elapsed > 5
                and game_best > 5
                and abs(game_best - self.race_timer_last_game_best) > 0.05
            )
            if finish_by_race_off or finish_by_current_reset or finish_by_last_update or finish_by_best_update:
                self.stop_race_timer("auto finish")
                # If the game sends a sane lap time close to ours, use it as saved result.
                candidate = game_last if game_last > 5 else game_best
                if candidate and 5 < candidate < 3600 and abs(candidate - self.race_timer_saved_elapsed) < 10:
                    self.race_timer_saved_elapsed = candidate
                    self.race_timer_elapsed = candidate

        self.race_timer_last_is_race_on = is_race_on
        self.race_timer_last_game_current = game_current
        if game_last > 0:
            self.race_timer_last_game_last = game_last
        if game_best > 0:
            self.race_timer_last_game_best = game_best

    def refresh_share_preview(self):
        if not hasattr(self, "share_preview_labels"):
            return
        car = self.current_race_car_name()
        saved = self.race_timer_saved_elapsed
        current = self.current_race_timer_seconds()
        samples = len(self.telemetry_samples or [])
        source = "Saved app timer" if saved > 0 else ("Running app timer" if current > 0 else "No time saved")
        values = {
            "car": f"Car Used\\n{car}",
            "time": f"Share Time\\n{format_lap_time(saved or current)}",
            "source": f"Source\\n{source}",
            "samples": f"Telemetry Samples\\n{samples}",
        }
        for key, value in values.items():
            if key in self.share_preview_labels:
                self.share_preview_labels[key].setText(value)

    def share_current_race_time(self):
        if self.current_race_timer_seconds() <= 0 and self.race_timer_saved_elapsed <= 0:
            QMessageBox.information(
                self,
                "No race time",
                "Start and stop the race timer first, or record telemetry, before sharing.",
            )
            return
        if self.race_timer_running:
            reply = QMessageBox.question(
                self,
                "Timer still running",
                "The timer is still running. Stop and save the current time before sharing?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.stop_race_timer("share")
            else:
                return
        self.refresh_share_preview()
        self.export_current_share_pack()

    def build_race_times_page(self):
        area, content, layout = self.make_scroll_page()

        card = Card("Race Times")
        telemetry_row = QHBoxLayout()
        self.start_race_tel_btn = QPushButton("Start Telemetry")
        self.start_race_tel_btn.setObjectName("primary")
        self.stop_race_tel_btn = QPushButton("Stop Telemetry")
        self.clear_race_tel_btn = QPushButton("Clear Log")
        self.start_race_tel_btn.clicked.connect(self.start_telemetry)
        self.stop_race_tel_btn.clicked.connect(self.stop_telemetry)
        self.clear_race_tel_btn.clicked.connect(self.clear_telemetry)
        for b in [self.start_race_tel_btn, self.stop_race_tel_btn, self.clear_race_tel_btn]:
            telemetry_row.addWidget(b)
        telemetry_row.addStretch(1)
        card.body.addLayout(telemetry_row)

        timer_row = QHBoxLayout()
        self.manual_timer_start_btn = QPushButton("Start Timer")
        self.manual_timer_start_btn.setObjectName("primary")
        self.manual_timer_stop_btn = QPushButton("Stop && Save Time")
        self.manual_timer_reset_btn = QPushButton("Reset Timer")
        self.manual_timer_share_btn = QPushButton("Share This Time")
        self.manual_timer_share_btn.setObjectName("primary")
        self.manual_timer_start_btn.clicked.connect(lambda: self.start_race_timer("manual"))
        self.manual_timer_stop_btn.clicked.connect(lambda: self.stop_race_timer("manual"))
        self.manual_timer_reset_btn.clicked.connect(self.reset_race_timer)
        self.manual_timer_share_btn.clicked.connect(self.share_current_race_time)
        for b in [self.manual_timer_start_btn, self.manual_timer_stop_btn, self.manual_timer_reset_btn, self.manual_timer_share_btn]:
            timer_row.addWidget(b)
        timer_row.addStretch(1)
        card.body.addLayout(timer_row)

        race_intro = QLabel(
            "Timer now uses FH6 telemetry timestamps, so it should pause when the game is paused/tabbed out. "
            "Auto-start/stop is best-effort; Stop && Save Time is still available if FH6 does not send a clean finish signal."
        )
        race_intro.setObjectName("meta")
        race_intro.setWordWrap(True)
        card.body.addWidget(race_intro)

        self.race_timer_big = QLabel("--:--.---")
        self.race_timer_big.setObjectName("timerBig")
        self.race_timer_big.setAlignment(Qt.AlignCenter)
        card.body.addWidget(self.race_timer_big)

        race_grid = QGridLayout()
        self.race_labels = {}
        race_items = [
            ("app_timer", "App Timer"),
            ("saved", "Saved Time"),
            ("status", "Status"),
            ("game_current", "Game Current Raw"),
            ("game_last", "Game Last Raw"),
            ("packets", "Packets"),
        ]
        for i, (key, title) in enumerate(race_items):
            lbl = QLabel(f"{title}\n--")
            lbl.setObjectName("statChip")
            race_grid.addWidget(lbl, i // 3, i % 3)
            self.race_labels[key] = lbl
        card.body.addLayout(race_grid)
        layout.addWidget(card)

        share_card = Card("Share Preview")
        self.share_preview_title = QLabel("Ready to share a clean lap card.")
        self.share_preview_title.setObjectName("bigTitle")
        share_card.body.addWidget(self.share_preview_title)

        preview_grid = QGridLayout()
        self.share_preview_labels = {}
        for i, (key, title) in enumerate([
            ("car", "Car Used"),
            ("time", "Share Time"),
            ("source", "Source"),
            ("samples", "Telemetry Samples"),
        ]):
            lbl = QLabel(f"{title}\n--")
            lbl.setObjectName("statChip")
            preview_grid.addWidget(lbl, i // 2, i % 2)
            self.share_preview_labels[key] = lbl
        share_card.body.addLayout(preview_grid)

        clean_note = QLabel("Share This Time exports a .fh6share pack with the car used during the race, saved time, tune data when selected, and telemetry history.")
        clean_note.setObjectName("meta")
        clean_note.setWordWrap(True)
        share_card.body.addWidget(clean_note)
        layout.addWidget(share_card)

        raw_card = Card("Debug Raw Timer Values")
        self.race_raw = QLabel("Waiting for telemetry packet...")
        self.race_raw.setObjectName("meta")
        self.race_raw.setWordWrap(True)
        raw_card.body.addWidget(self.race_raw)
        layout.addWidget(raw_card)

        self.stack.addWidget(area)
        self.refresh_share_preview()

    def colour_button_style(self, colour: str) -> str:
        return (
            f"background: {normalise_hex_colour(colour)};"
            "border: 1px solid rgba(255,255,255,0.35);"
            "border-radius: 10px;"
            "padding: 10px 14px;"
            "color: white;"
            "font-weight: 900;"
        )

    def refresh_colour_buttons(self):
        if hasattr(self, "accent_button"):
            accent = normalise_hex_colour(self.config.get("accent", "#ff2f6d"), "#ff2f6d")
            self.accent_button.setText(f"Accent: {accent}")
            self.accent_button.setStyleSheet(self.colour_button_style(accent))
        if hasattr(self, "accent2_button"):
            accent2 = normalise_hex_colour(self.config.get("accent2", "#00d4ff"), "#00d4ff")
            self.accent2_button.setText(f"Gradient: {accent2}")
            self.accent2_button.setStyleSheet(self.colour_button_style(accent2))

    def choose_theme_colour(self, key: str):
        current = QColor(normalise_hex_colour(self.config.get(key, "#ff2f6d")))
        colour = QColorDialog.getColor(current, self, "Choose UI colour")
        if not colour.isValid():
            return
        self.config[key] = colour.name()
        save_config(self.config)
        self.apply_style()
        self.refresh_colour_buttons()

    def apply_theme_preset(self, name: str):
        preset = THEME_PRESETS.get(name)
        if not preset:
            return
        self.config.update(preset)
        save_config(self.config)
        if hasattr(self, "rounded_spin"):
            self.rounded_spin.setValue(int(self.config.get("rounded", 14)))
        self.apply_style()
        self.refresh_colour_buttons()

    def open_thumbnail_cache_folder(self):
        try:
            THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(THUMBNAIL_CACHE_DIR))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(THUMBNAIL_CACHE_DIR)))
        except Exception as exc:
            QMessageBox.critical(self, "Open cache folder failed", str(exc))

    def thumbnail_cache_repo_settings(self):
        owner, repo = self.current_update_repo()
        branch = str(self.config.get("thumbnail_cache_branch", DEFAULT_THUMBNAIL_CACHE_BRANCH) or DEFAULT_THUMBNAIL_CACHE_BRANCH).strip()
        folder = str(self.config.get("thumbnail_cache_path", DEFAULT_THUMBNAIL_CACHE_PATH) or DEFAULT_THUMBNAIL_CACHE_PATH).strip().strip("/")
        if self.config.get("dev_mode", False):
            if hasattr(self, "thumb_branch_input"):
                branch = self.thumb_branch_input.text().strip() or DEFAULT_THUMBNAIL_CACHE_BRANCH
            if hasattr(self, "thumb_path_input"):
                folder = self.thumb_path_input.text().strip().strip("/") or DEFAULT_THUMBNAIL_CACHE_PATH
        return owner, repo, branch, folder

    def save_thumbnail_cache_repo_settings(self):
        if not self.config.get("dev_mode", False):
            if hasattr(self, "thumb_status"):
                self.thumb_status.setText("Dev mode is required before thumbnail repo folder settings can be changed.")
            return
        owner, repo, branch, folder = self.thumbnail_cache_repo_settings()
        self.config["thumbnail_cache_branch"] = branch
        self.config["thumbnail_cache_path"] = folder
        save_config(self.config)
        if hasattr(self, "thumb_status"):
            self.thumb_status.setText(f"Thumbnail source saved: {owner}/{repo}/{branch}/{folder}")

    def download_thumbnail_file_to_cache(self, download_url: str, filename: str) -> bool:
        # Public build intentionally does not download thumbnail files.
        return False


    def collect_thumbnail_files_from_github_folder(self, owner: str, repo: str, branch: str, folder: str):
        # Public build intentionally does not read GitHub folder contents for thumbnails.
        return []


    def update_community_thumbnail_cache_from_repo(self, silent: bool = False):
        if not silent:
            QMessageBox.information(
                self,
                "Automatic downloads disabled",
                "This public build does not download thumbnail caches automatically. "
                "Use Settings > Thumbnails > Install Thumbnail Folder instead.",
            )
        if hasattr(self, "thumb_status"):
            self.thumb_status.setText("Automatic thumbnail downloads are disabled. Install a local thumbnail folder instead.")


    def download_thumbnail_cache_from_release(self, silent: bool = False):
        self.update_community_thumbnail_cache_from_repo(silent=silent)


    def find_thumbnail_cache_asset(self, release: dict):
        # Kept for old share/release-cache compatibility, but v1.0.4 now uses the repo folder directly.
        assets = release.get("assets") or []
        preferred_words = ["thumbnail", "thumb", "cache", "car_image", "car-images", "carimages"]
        for asset in assets:
            name = str(asset.get("name", "")).lower()
            if not name.endswith(".zip"):
                continue
            if any(word in name for word in preferred_words):
                return asset
        return None

    def apply_thumbnail_cache_zip(self, zip_path: Path) -> int:
        THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        imported = 0

        with zipfile.ZipFile(zip_path, "r") as z:
            for item in z.infolist():
                if item.is_dir():
                    continue
                name = Path(item.filename).name
                if not name:
                    continue
                lower = name.lower()
                if not lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    continue

                stem = Path(name).stem
                if not stem.isdigit():
                    continue

                data = z.read(item)
                if not data or len(data) < 32:
                    continue

                out = THUMBNAIL_CACHE_DIR / f"{int(stem)}.png"

                if lower.endswith(".png") and data.startswith(b"\x89PNG\r\n\x1a\n"):
                    out.write_bytes(data)
                    imported += 1
                    continue

                image = QImage.fromData(data)
                if image.isNull():
                    continue

                if image.save(str(out), "PNG"):
                    imported += 1

        return imported


    def current_update_repo(self):
        owner = self.config.get("update_repo_owner", DEFAULT_GITHUB_REPO_OWNER)
        repo = self.config.get("update_repo_name", DEFAULT_GITHUB_REPO_NAME)
        if self.config.get("dev_mode", False):
            if hasattr(self, "update_owner_input"):
                owner = self.update_owner_input.text().strip() or DEFAULT_GITHUB_REPO_OWNER
            if hasattr(self, "update_repo_input"):
                repo = self.update_repo_input.text().strip() or DEFAULT_GITHUB_REPO_NAME
        return owner, repo

    def update_dev_mode_visibility(self):
        dev = bool(self.config.get("dev_mode", False))
        for name in [
            "update_owner_label", "update_repo_label", "update_owner_input",
            "update_repo_input", "save_repo_btn", "thumb_branch_label", "thumb_path_label",
            "thumb_branch_input", "thumb_path_input", "save_thumb_source_btn"
        ]:
            widget = getattr(self, name, None)
            if widget:
                widget.setVisible(dev)
        if hasattr(self, "dev_mode_checkbox"):
            self.dev_mode_checkbox.setChecked(dev)

    def toggle_dev_mode(self, state):
        self.config["dev_mode"] = bool(state)
        save_config(self.config)
        self.update_dev_mode_visibility()
        self.set_update_status("Dev mode enabled: update repo editing is visible." if self.config["dev_mode"] else "Dev mode disabled: update repo editing is hidden.")

    def save_update_repo_settings(self):
        if not self.config.get("dev_mode", False):
            self.set_update_status("Dev mode is required before the update repo can be changed.")
            return
        owner, repo = self.current_update_repo()
        self.config["update_repo_owner"] = owner
        self.config["update_repo_name"] = repo
        save_config(self.config)
        self.latest_release_url = github_releases_url(owner, repo)
        self.latest_release_asset_url = ""
        self.latest_release_asset_name = ""
        if hasattr(self, "install_update_button"):
            self.install_update_button.setEnabled(False)
        self.set_update_status(f"Update source saved: {owner}/{repo}")

    def download_file(self, url: str, out_path: Path):
        raise RuntimeError("Network downloads are disabled in the public build.")


    def find_extracted_update_root(self, staging_dir: Path) -> Path:
        dirs = [p for p in staging_dir.iterdir() if p.is_dir()]
        if len(dirs) == 1:
            return dirs[0]
        for p in dirs:
            if (p / "src" / "main.py").exists() or (p / "run-dev.cmd").exists():
                return p
        if (staging_dir / "src" / "main.py").exists() or (staging_dir / "run-dev.cmd").exists():
            return staging_dir
        raise RuntimeError("Could not find extracted app root in update ZIP.")

    def write_and_run_updater(self, new_root: Path):
        raise RuntimeError("In-app updater is disabled in the public build.")


    def download_and_install_update(self):
        QMessageBox.information(
            self,
            "In-app updater removed",
            "The in-app update installer is removed from the public build. "
            "Download updates manually from GitHub Releases.",
        )


    def open_releases_page(self):
        owner, repo = self.current_update_repo()
        QDesktopServices.openUrl(QUrl(github_releases_url(owner, repo)))

    def open_latest_release_page(self):
        owner, repo = self.current_update_repo()
        url = getattr(self, "latest_release_url", None) or github_releases_url(owner, repo)
        QDesktopServices.openUrl(QUrl(url))

    def set_update_status(self, message: str):
        if hasattr(self, "update_status"):
            self.update_status.setText(message)

    def check_for_updates(self):
        self.set_update_status("Automatic update checks are disabled in this public build. Open GitHub Releases manually.")
        QMessageBox.information(
            self,
            "Update checks disabled",
            "Automatic update checks are disabled in this public build. "
            "Use Open GitHub Releases to check for updates manually.",
        )


    def build_shared_lap_times_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        intro = Card("Shared Lap Times")
        note = QLabel("Import .fh6share files to view shared lap records, compare them against your own telemetry, and inspect the included telemetry history.")
        note.setObjectName("meta")
        note.setWordWrap(True)
        intro.body.addWidget(note)

        actions = QHBoxLayout()
        import_btn = QPushButton("Import Share Pack")
        import_btn.clicked.connect(self.import_share_pack)
        export_btn = QPushButton("Export Current Race Pack")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self.export_current_share_pack)
        refresh_btn = QPushButton("Refresh Shared List")
        refresh_btn.clicked.connect(self.load_shared_lap_files)
        actions.addWidget(import_btn)
        actions.addWidget(export_btn)
        actions.addWidget(refresh_btn)
        actions.addStretch(1)
        intro.body.addLayout(actions)
        outer.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(14)

        left = Card("Shared Files")
        left.setFixedWidth(380)
        self.shared_lap_list = QListWidget()
        self.shared_lap_list.itemClicked.connect(self.on_shared_lap_clicked)
        left.body.addWidget(self.shared_lap_list, 1)
        body.addWidget(left)

        right = QVBoxLayout()
        self.shared_compare_card = Card("Compare")
        self.shared_compare_title = QLabel("Import or select a shared lap.")
        self.shared_compare_title.setObjectName("bigTitle")
        self.shared_compare_card.body.addWidget(self.shared_compare_title)

        compare_grid = QGridLayout()
        self.shared_compare_labels = {}
        for i, key in enumerate(["shared_best", "your_best", "gap", "car", "tune_hash", "telemetry_samples"]):
            lbl = QLabel(f"{key.replace('_', ' ').title()}\n--")
            lbl.setObjectName("statChip")
            compare_grid.addWidget(lbl, i // 3, i % 3)
            self.shared_compare_labels[key] = lbl
        self.shared_compare_card.body.addLayout(compare_grid)
        right.addWidget(self.shared_compare_card)

        self.shared_telemetry_card = Card("Shared Telemetry History")
        self.shared_telemetry_summary = QLabel("No shared telemetry loaded.")
        self.shared_telemetry_summary.setObjectName("meta")
        self.shared_telemetry_summary.setWordWrap(True)
        self.shared_telemetry_card.body.addWidget(self.shared_telemetry_summary)

        self.shared_telemetry_table = QListWidget()
        self.shared_telemetry_card.body.addWidget(self.shared_telemetry_table, 1)
        right.addWidget(self.shared_telemetry_card, 1)

        body.addLayout(right, 1)
        outer.addLayout(body, 1)

        self.stack.addWidget(page)
        self.load_shared_lap_files()

    def build_share_pack_payload(self):
        samples = telemetry_samples_for_share(self.telemetry_samples)
        lap_info = best_lap_from_samples(samples)
        app_race_time = self.best_available_race_time_seconds()
        if app_race_time > 0:
            lap_info = {
                "current_lap_seconds": self.current_race_timer_seconds(),
                "last_lap_seconds": app_race_time,
                "best_lap_seconds": app_race_time,
            }
        latest = samples[-1] if samples else {}

        tune_bytes_b64 = ""
        tune_md5 = ""
        tune_name = "No tune selected"
        tune_ordinal = None
        tune_drivetrain = "--"
        active_gears = 0
        thumb_payload = None

        if self.current:
            tune_bytes_b64 = base64.b64encode(self.current.raw_bytes).decode("ascii")
            tune_md5 = hashlib.md5(self.current.raw_bytes).hexdigest()
            tune_name = self.current.car_name
            tune_ordinal = self.current.ordinal
            tune_drivetrain = self.current.drivetrain_label
            active_gears = self.current.active_gear_count

            thumb = thumbnail_cache_path(self.current.ordinal)
            if thumb.exists():
                thumb_payload = {
                    "filename": THUMBNAIL_FILENAME,
                    "format": "png",
                    "image_base64": base64.b64encode(thumb.read_bytes()).decode("ascii"),
                }

        car_name = self.current_race_car_name()
        ordinal = self.race_timer_ordinal or latest.get("car_ordinal") or tune_ordinal

        return {
            "schema": "fh6-share-pack-v1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "app": APP_NAME,
            "version": APP_VERSION,
            "driver": "",
            "event": "",
            "car": {
                "name": car_name,
                "ordinal": ordinal,
                "drivetrain": tune_drivetrain,
                "active_gears": active_gears,
                "forza_edition": is_forza_edition_name(car_name),
            },
            "lap": {
                "current_lap_seconds": lap_info["current_lap_seconds"],
                "last_lap_seconds": lap_info["last_lap_seconds"],
                "best_lap_seconds": lap_info["best_lap_seconds"],
                "best_lap_text": format_lap_time(lap_info["best_lap_seconds"]),
                "source": "telemetry_clock" if app_race_time > 0 else "telemetry_raw",
            },
            "tune": {
                "car_name": tune_name,
                "ordinal": tune_ordinal,
                "md5": tune_md5,
                "size": len(self.current.raw_bytes) if self.current else 0,
                "data_base64": tune_bytes_b64,
                "thumbnail": thumb_payload,
            },
            "telemetry": {
                "sample_count": len(samples),
                "samples": samples,
            },
        }

    def export_current_share_pack(self):
        if not self.current and not self.telemetry_samples and self.best_available_race_time_seconds() <= 0:
            QMessageBox.information(
                self,
                "Nothing to share",
                "Load a tune, record telemetry, or save a race time first, then export a share pack.",
            )
            return

        payload = self.build_share_pack_payload()
        car_name = payload.get("car", {}).get("name") or "FH6"
        lap_text = payload.get("lap", {}).get("best_lap_text") or "lap"
        default_name = safe_filename(f"{car_name}_{lap_text}") + SHARE_PACK_EXTENSION

        out, _ = QFileDialog.getSaveFileName(
            self,
            "Export FH6 share pack",
            default_name,
            f"FH6 Share Pack (*{SHARE_PACK_EXTENSION});;ZIP files (*.zip);;All files (*.*)",
        )
        if not out:
            return
        out_path = Path(out)
        if out_path.suffix.lower() not in [SHARE_PACK_EXTENSION, ".zip"]:
            out_path = out_path.with_suffix(SHARE_PACK_EXTENSION)

        try:
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr("share_info.json", json.dumps(payload, indent=2))
                tune_data = payload.get("tune", {}).get("data_base64")
                if tune_data:
                    z.writestr("tune_data.bin", base64.b64decode(tune_data))
                thumb = payload.get("tune", {}).get("thumbnail")
                if isinstance(thumb, dict) and thumb.get("image_base64"):
                    z.writestr("thumbnail.png", base64.b64decode(thumb["image_base64"]))
                samples = payload.get("telemetry", {}).get("samples", [])
                if samples:
                    keys = sorted({k for sample in samples for k in sample.keys()})
                    csv_lines = [",".join(keys)]
                    for sample in samples:
                        csv_lines.append(",".join(str(sample.get(k, "")).replace(",", " ") for k in keys))
                    z.writestr("telemetry_summary.csv", "\n".join(csv_lines))
            summary = (
                f"Car: {payload.get('car', {}).get('name', 'Unknown car')}\n"
                f"Time: {payload.get('lap', {}).get('best_lap_text', '--:--.---')}\n"
                f"Saved:\n{out_path}"
            )
            QMessageBox.information(self, "Share pack exported", summary)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def read_share_pack(self, path: Path):
        with zipfile.ZipFile(path, "r") as z:
            if "share_info.json" not in z.namelist():
                raise ValueError("Missing share_info.json")
            payload = json.loads(z.read("share_info.json").decode("utf-8", errors="replace"))
        payload["_path"] = str(path)
        payload["_filename"] = path.name
        return payload

    def import_share_pack(self):
        infile, _ = QFileDialog.getOpenFileName(
            self,
            "Import FH6 share pack",
            "",
            f"FH6 Share Pack (*{SHARE_PACK_EXTENSION});;ZIP files (*.zip);;All files (*.*)",
        )
        if not infile:
            return

        try:
            src = Path(infile)
            payload = self.read_share_pack(src)
            SHARED_LAPS_DIR.mkdir(parents=True, exist_ok=True)
            dst = SHARED_LAPS_DIR / src.name
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            self.load_shared_lap_files()
            QMessageBox.information(self, "Imported", f"Imported shared lap:\n{dst.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))

    def load_shared_lap_files(self):
        if not hasattr(self, "shared_lap_list"):
            return
        SHARED_LAPS_DIR.mkdir(parents=True, exist_ok=True)
        self.shared_laps = []
        self.shared_lap_list.clear()

        for path in sorted(SHARED_LAPS_DIR.glob(f"*{SHARE_PACK_EXTENSION}")) + sorted(SHARED_LAPS_DIR.glob("*.zip")):
            try:
                payload = self.read_share_pack(path)
                self.shared_laps.append(payload)
                car = payload.get("car", {}).get("name") or payload.get("tune", {}).get("car_name") or "Unknown car"
                lap = payload.get("lap", {}).get("best_lap_text") or format_lap_time(payload.get("lap", {}).get("best_lap_seconds"))
                samples = payload.get("telemetry", {}).get("sample_count", 0)
                item = QListWidgetItem(f"{car}\nBest: {lap} · Telemetry samples: {samples}\n{path.name}")
                item.setSizeHint(QSize(330, 78))
                self.shared_lap_list.addItem(item)
            except Exception:
                continue

    def on_shared_lap_clicked(self, item):
        row = self.shared_lap_list.row(item)
        if row < 0 or row >= len(self.shared_laps):
            return
        self.loaded_shared_lap = self.shared_laps[row]
        self.render_shared_lap_details(self.loaded_shared_lap)

    def render_shared_lap_details(self, payload):
        car = payload.get("car", {}).get("name") or payload.get("tune", {}).get("car_name") or "Unknown car"
        lap = payload.get("lap", {})
        telemetry = payload.get("telemetry", {})
        samples = telemetry.get("samples") or []
        shared_best = float(lap.get("best_lap_seconds") or 0.0)

        your_info = best_lap_from_samples(self.telemetry_samples)
        your_best = float(your_info.get("best_lap_seconds") or 0.0)
        gap_text = "--"
        if shared_best > 0 and your_best > 0:
            gap = your_best - shared_best
            gap_text = f"{gap:+.3f}s"
        elif shared_best > 0:
            gap_text = "Record your telemetry to compare"

        title = f"{car}"
        if payload.get("car", {}).get("forza_edition"):
            title += "  ★ FE"
        self.shared_compare_title.setText(title)

        values = {
            "shared_best": f"Shared Best\n{format_lap_time(shared_best)}",
            "your_best": f"Your Best\n{format_lap_time(your_best)}",
            "gap": f"Gap\n{gap_text}",
            "car": f"Car\n{car}",
            "tune_hash": f"Tune Hash\n{(payload.get('tune', {}).get('md5') or '--')[:10]}",
            "telemetry_samples": f"Telemetry Samples\n{len(samples)}",
        }
        for key, value in values.items():
            self.shared_compare_labels[key].setText(value)

        if not samples:
            self.shared_telemetry_summary.setText("No telemetry history was included in this share pack.")
            self.shared_telemetry_table.clear()
            return

        speeds = [float(s.get("speed_mph") or 0.0) for s in samples]
        rpms = [float(s.get("rpm") or 0.0) for s in samples]
        throttles = [float(s.get("throttle") or 0.0) for s in samples]
        brakes = [float(s.get("brake") or 0.0) for s in samples]

        summary = (
            f"Samples: {len(samples)} · "
            f"Max speed: {max(speeds):.1f} mph · "
            f"Max RPM: {max(rpms):.0f} · "
            f"Avg throttle: {(sum(throttles)/len(throttles)):.0f}% · "
            f"Avg brake: {(sum(brakes)/len(brakes)):.0f}%"
        )
        self.shared_telemetry_summary.setText(summary)

        self.shared_telemetry_table.clear()
        step = max(1, len(samples) // 200)
        for sample in samples[::step]:
            t = sample.get("received_unix", "")
            speed = float(sample.get("speed_mph") or 0.0)
            rpm = float(sample.get("rpm") or 0.0)
            gear = sample.get("gear", "--")
            throttle = float(sample.get("throttle") or 0.0)
            brake = float(sample.get("brake") or 0.0)
            lap_current = format_lap_time(sample.get("lap_time_current"))
            self.shared_telemetry_table.addItem(
                f"{lap_current} · {speed:.1f} mph · {rpm:.0f} rpm · G{gear} · T {throttle:.0f}% · B {brake:.0f}%"
            )

    def build_settings_page(self):
        area, content, layout = self.make_scroll_page()

        theme = Card("Theme / Visuals")
        theme_note = QLabel("Use the colour buttons to open a colour picker, or apply a premade style.")
        theme_note.setObjectName("meta")
        theme_note.setWordWrap(True)
        theme.body.addWidget(theme_note)

        colour_grid = QGridLayout()
        self.accent_button = QPushButton()
        self.accent_button.clicked.connect(lambda: self.choose_theme_colour("accent"))
        self.accent2_button = QPushButton()
        self.accent2_button.clicked.connect(lambda: self.choose_theme_colour("accent2"))

        colour_grid.addWidget(QLabel("Primary accent"), 0, 0)
        colour_grid.addWidget(self.accent_button, 0, 1)
        colour_grid.addWidget(QLabel("Secondary / gradient"), 1, 0)
        colour_grid.addWidget(self.accent2_button, 1, 1)

        self.rounded_spin = QSpinBox()
        self.rounded_spin.setRange(0, 28)
        self.rounded_spin.setValue(int(self.config.get("rounded", 14)))
        self.rounded_spin.valueChanged.connect(lambda v: self.config.__setitem__("rounded", int(v)))
        colour_grid.addWidget(QLabel("Rounded corners"), 2, 0)
        colour_grid.addWidget(self.rounded_spin, 2, 1)

        self.sidebar_width_spin = QSpinBox()
        self.sidebar_width_spin.setRange(150, 360)
        self.sidebar_width_spin.setSuffix(" px")
        self.sidebar_width_spin.setValue(self.clamp_sidebar_width(self.config.get("sidebar_width", 210)))
        self.sidebar_width_spin.valueChanged.connect(self.sidebar_width_from_settings)
        colour_grid.addWidget(QLabel("Sidebar width"), 3, 0)
        colour_grid.addWidget(self.sidebar_width_spin, 3, 1)

        apply = QPushButton("Apply Current Visual Settings")
        apply.setObjectName("primary")
        apply.clicked.connect(self.apply_theme_settings)
        colour_grid.addWidget(apply, 4, 0, 1, 2)

        theme.body.addLayout(colour_grid)
        if hasattr(self, "refresh_colour_buttons"):
            self.refresh_colour_buttons()
        layout.addWidget(theme)

        presets = Card("Premade Styles")
        preset_grid = QGridLayout()
        for i, name in enumerate(THEME_PRESETS.keys()):
            preset = THEME_PRESETS[name]
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked=False, n=name: self.apply_theme_preset(n))
            btn.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {preset['accent']}, stop:1 {preset['accent2']});"
                "border: 1px solid rgba(255,255,255,0.25);"
                "border-radius: 10px;"
                "padding: 12px;"
                "color: white;"
                "font-weight: 900;"
            )
            preset_grid.addWidget(btn, i // 3, i % 3)
        presets.body.addLayout(preset_grid)
        layout.addWidget(presets)

        release = Card("Public Release")
        release_note = QLabel(
            f"Current version: v{APP_VERSION}. Automatic update checks, in-app update installation, "
            "and automatic thumbnail downloads are disabled in this public build."
        )
        release_note.setObjectName("meta")
        release_note.setWordWrap(True)
        release.body.addWidget(release_note)

        open_releases_btn = QPushButton("Open GitHub Releases")
        open_releases_btn.clicked.connect(self.open_releases_page)
        release.body.addWidget(open_releases_btn)
        layout.addWidget(release)

        diag = Card("Diagnostics")
        diag_note = QLabel("Export a diagnostic report for bug reports. Works in script mode and after EXE conversion.")
        diag_note.setObjectName("meta")
        diag_note.setWordWrap(True)
        diag.body.addWidget(diag_note)
        diag_btn = QPushButton("Export Diagnostic Report")
        diag_btn.clicked.connect(self.export_diagnostics)
        diag.body.addWidget(diag_btn)
        layout.addWidget(diag)

        thumbs = Card("Thumbnails")
        thumb_note = QLabel(
            "Download thumbnails manually from GitHub, then install them from a local folder. Files can be named like 1034.png, 1034_2.png, "
            "or Thumbnail_1034_Big.png. The app copies/converts them into thumbnail_cache as ordinal.png."
        )
        thumb_note.setObjectName("meta")
        thumb_note.setWordWrap(True)
        thumbs.body.addWidget(thumb_note)

        thumb_row = QHBoxLayout()
        for text_label, fn in [
            ("Scan Loaded Tunes", self.scan_thumbnails),
            ("Get Thumbnails on GitHub", self.open_thumbnail_repo_page),
            ("Install Thumbnail Folder", self.install_thumbnail_folder),
            ("Open Cache Folder", self.open_thumbnail_cache_folder),
        ]:
            btn = QPushButton(text_label)
            btn.clicked.connect(fn)
            thumb_row.addWidget(btn)
        thumbs.body.addLayout(thumb_row)

        self.thumb_status = QLabel("Download thumbnails from GitHub manually, then install the local folder here. No automatic downloads.")
        self.thumb_status.setObjectName("meta")
        self.thumb_status.setWordWrap(True)
        thumbs.body.addWidget(self.thumb_status)
        layout.addWidget(thumbs)

        tel = Card("Telemetry")
        self.port_input = QLineEdit(str(self.config.get("telemetry_port", 3010)))
        tel.body.addWidget(QLabel("UDP Port (default/recommended: 3010)"))
        tel.body.addWidget(self.port_input)
        tel_note = QLabel("FH6 Data Out should be pointed at UDP port 3010 unless you intentionally change it.")
        tel_note.setObjectName("meta")
        tel_note.setWordWrap(True)
        tel.body.addWidget(tel_note)

        self.auto_current_car_tune_checkbox = QCheckBox("Auto-load tune when telemetry detects current car")
        self.auto_current_car_tune_checkbox.setChecked(bool(self.config.get("auto_load_current_car_tune", True)))
        tel.body.addWidget(self.auto_current_car_tune_checkbox)

        load_current_btn = QPushButton("Load Current Telemetry Car Tune Now")
        load_current_btn.clicked.connect(lambda: self.load_current_car_tune_from_telemetry(silent=False))
        tel.body.addWidget(load_current_btn)
        layout.addWidget(tel)

        self.stack.addWidget(area)

    def update_header(self):
        if self.stack.currentIndex() == 0:
            self.header.setVisible(False)
        if not self.current:
            self.car_title.setText("NO TUNE LOADED")
            self.hero_title.setText("Load a tune folder to begin")
            return
        title = self.current.display_name
        self.car_title.setText(title)
        self.hero_title.setText(title)
        sub_bits = [self.current.drivetrain_label, f"{self.current.active_gear_count} gears", f"#{self.current.ordinal}"]
        if self.current.header_name:
            sub_bits.insert(0, "header auto-loaded")
        self.hero_sub.setText(" · ".join(sub_bits))

    def open_folder(self):
        dirname = QFileDialog.getExistingDirectory(self, "Open FH6 tune folder")
        if dirname:
            self.config["last_tune_folder"] = dirname
            self.config["last_scan_folder"] = dirname
            self.config["auto_detect_tune_folder"] = False
            save_config(self.config)
            self.load_paths(discover_tune_files(Path(dirname)))

    def open_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open FH6 Data file (header auto-loads from same folder)", "", "FH6 Data files (Data*);;All files (*.*)")
        if filename:
            self.config["last_loaded_tune_file"] = filename
            save_config(self.config)
            self.load_paths([Path(filename)])

    def load_paths(self, paths):
        loaded = []
        errors = []
        for path in paths:
            try:
                tune = parse_tune_file(Path(path))
                cache_thumb_for_tune(tune)
                loaded.append(tune)
            except Exception as exc:
                errors.append(f"{path}: {exc}")
        self.tunes = loaded
        self.current = loaded[0] if loaded else None
        if loaded:
            self.config["last_loaded_tune_file"] = str(loaded[0].path)
            # Do not overwrite last_scan_folder/last_tune_folder with an individual
            # Tuning_#### folder. Those settings are scan roots only.
            save_config(self.config)
        self.refresh_filter_options()
        self.refresh_tune_list()
        self.update_header()
        self.update_section_button_state()
        self.render_tune_values()
        self.refresh_car_view()
        self.refresh_tuning_assist()
        if loaded and len(loaded) == 1 and loaded[0].header_name:
            # Keep this non-invasive: the tune name appearing in the UI is the main indicator.
            # No creator/gamertag/ID is shown.
            pass
        if errors:
            QMessageBox.warning(self, "Some tunes failed", "\n".join(errors[:10]))

    def refresh_filter_options(self):
        if not hasattr(self, "brand_filter") or not hasattr(self, "year_filter"):
            return

        current_brand = self.brand_filter.currentText() if self.brand_filter.count() else "All brands"
        current_year = self.year_filter.currentText() if self.year_filter.count() else "All years"

        brands = sorted({car_brand_from_name(tune.car_name) for tune in self.tunes})
        years = sorted({car_year_from_name(tune.car_name) for tune in self.tunes}, reverse=True)

        self.brand_filter.blockSignals(True)
        self.year_filter.blockSignals(True)

        self.brand_filter.clear()
        self.brand_filter.addItem("All brands")
        self.brand_filter.addItems(brands)

        self.year_filter.clear()
        self.year_filter.addItem("All years")
        self.year_filter.addItems(years)

        if current_brand in ["All brands"] + brands:
            self.brand_filter.setCurrentText(current_brand)
        if current_year in ["All years"] + years:
            self.year_filter.setCurrentText(current_year)

        self.brand_filter.blockSignals(False)
        self.year_filter.blockSignals(False)

    def tune_matches_filters(self, tune: TuneFile) -> bool:
        q = self.search.text().lower() if hasattr(self, "search") else ""
        searchable = " ".join([
            str(tune.car_name),
            str(tune.ordinal),
            str(tune.drivetrain_label),
            str(getattr(tune, "header_name", "")),
            str(getattr(tune, "header_description", "")),
        ]).lower()
        if q and q not in searchable:
            return False

        brand = self.brand_filter.currentText() if hasattr(self, "brand_filter") and self.brand_filter.count() else "All brands"
        if brand and brand != "All brands" and car_brand_from_name(tune.car_name) != brand:
            return False

        year = self.year_filter.currentText() if hasattr(self, "year_filter") and self.year_filter.count() else "All years"
        if year and year != "All years" and car_year_from_name(tune.car_name) != year:
            return False

        fe_mode = self.fe_filter.currentText() if hasattr(self, "fe_filter") else "All cars"
        is_fe = is_forza_edition_name(tune.car_name)
        if fe_mode == "Forza Edition only" and not is_fe:
            return False
        if fe_mode == "Exclude Forza Edition" and is_fe:
            return False

        return True

    def tune_sort_timestamp(self, tune: TuneFile) -> int:
        try:
            header_sort = int(getattr(tune, "header_created_sort", 0) or 0)
            if header_sort:
                return header_sort
        except Exception:
            pass
        try:
            return int(tune.path.stat().st_mtime * 1000)
        except Exception:
            return 0

    def sorted_tunes_for_list(self, tunes: list[TuneFile]) -> list[TuneFile]:
        mode = self.sort_combo.currentText() if hasattr(self, "sort_combo") and self.sort_combo.count() else "Newest first"
        if mode == "Oldest first":
            return sorted(tunes, key=lambda t: (self.tune_sort_timestamp(t), str(t.car_name).lower(), str(getattr(t, "header_name", "")).lower()))
        if mode == "Car name A-Z":
            return sorted(tunes, key=lambda t: (str(t.car_name).lower(), str(getattr(t, "header_name", "")).lower(), -self.tune_sort_timestamp(t)))
        if mode == "Tune name A-Z":
            return sorted(tunes, key=lambda t: (str(getattr(t, "header_name", "") or "").lower(), str(t.car_name).lower(), -self.tune_sort_timestamp(t)))
        return sorted(tunes, key=lambda t: (self.tune_sort_timestamp(t), str(t.car_name).lower(), str(getattr(t, "header_name", "")).lower()), reverse=True)

    def refresh_tune_list(self):
        self.tune_list.clear()
        self.tune_items.clear()

        visible_tunes = [tune for tune in self.tunes if self.tune_matches_filters(tune)]
        for tune in self.sorted_tunes_for_list(visible_tunes):
            item = QListWidgetItem()
            item.setSizeHint(QSize(330, 218 if is_forza_edition_name(tune.car_name) and getattr(tune, "header_name", "") else 204 if getattr(tune, "header_name", "") else 196 if is_forza_edition_name(tune.car_name) else 178))
            widget = TuneCard(tune)
            self.tune_list.addItem(item)
            self.tune_list.setItemWidget(item, widget)
            self.tune_items.append((item, tune))

    def on_tune_clicked(self, item):
        for it, tune in self.tune_items:
            if it is item:
                self.current = tune
                break
        self.update_header()
        self.update_section_button_state()
        self.render_tune_values()
        self.refresh_car_view()
        self.refresh_tuning_assist()

    def show_tune_section(self, section):
        self.current_section = section
        self.update_section_button_state()
        self.render_tune_values()

    def update_section_button_state(self):
        for name, btn in getattr(self, "section_buttons", {}).items():
            btn.setProperty("sectionActive", name == self.current_section)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def debug_section_fields(self, section: str) -> list:
        fields = FIELDS_BY_SECTION.get(section)
        if fields:
            return list(fields)
        wanted = re.sub(r"[^a-z0-9]+", "", section.lower())
        matched = []
        for key, values in FIELDS_BY_SECTION.items():
            if re.sub(r"[^a-z0-9]+", "", key.lower()) == wanted:
                matched.extend(values)
        return matched

    def make_tune_value_row(self, field: FieldDef):
        raw = self.current.values[field.index] if self.current and field.index < len(self.current.values) else None
        display_value = field.raw_to_display(raw) if isinstance(raw, (int, float)) else None

        card = QFrame()
        card.setObjectName("valueRow")
        card.setMinimumHeight(82)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        left = QVBoxLayout()
        name = QLabel(field.label)
        name.setObjectName("tuneTitle")
        left.addWidget(name)

        details = QLabel(f"raw {raw:.6f}" if isinstance(raw, (int, float)) else "raw --")
        details.setObjectName("meta")
        left.addWidget(details)

        if field.note:
            note = QLabel(field.note)
            note.setObjectName("meta")
            note.setWordWrap(True)
            left.addWidget(note)

        row.addLayout(left, 2)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(field.slider_steps)
        slider.setMinimumWidth(260)
        slider.setEnabled(display_value is not None)
        if display_value is not None:
            slider.setValue(field.display_to_slider(display_value))
        row.addWidget(slider, 3)

        spin = QDoubleSpinBox()
        spin.setMinimum(field.display_min)
        spin.setMaximum(field.display_max)
        spin.setDecimals(field.decimals)
        spin.setSingleStep(field.step)
        spin.setEnabled(display_value is not None)
        if display_value is not None:
            spin.setValue(display_value)
        spin.setFixedWidth(120)
        row.addWidget(spin)

        value = QLabel(field.display_text(raw))
        value.setObjectName("valuePill")
        value.setMinimumWidth(92)
        value.setAlignment(Qt.AlignCenter)
        row.addWidget(value)

        updating = {"active": False}

        def update_from_display(v):
            if updating["active"] or not self.current:
                return
            updating["active"] = True
            raw_new = field.display_to_raw(v)
            self.current.values[field.index] = raw_new
            details.setText(f"raw {raw_new:.6f}")
            value.setText(field.display_text(raw_new))
            slider.setValue(field.display_to_slider(v))
            updating["active"] = False

        def update_from_slider(sv):
            if updating["active"]:
                return
            dv = field.slider_to_display(sv)
            spin.setValue(dv)
            update_from_display(dv)

        spin.valueChanged.connect(update_from_display)
        slider.valueChanged.connect(update_from_slider)
        return card

    def export_tune_csv(self):
        if not self.current:
            QMessageBox.information(self, "No tune selected", "Load and select a tune first.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export tune values CSV", f"{self.current.car_name.replace(' ', '_')}_values.csv", "CSV (*.csv)")
        if not out:
            return
        rows = []
        for field in FIELD_DEFS:
            raw = self.current.values[field.index] if field.index < len(self.current.values) else None
            rows.append({
                "section": field.section,
                "index": field.index,
                "label": field.label,
                "raw": raw,
                "display": field.display_text(raw) if isinstance(raw, (int, float)) else "N/A",
                "unit": field.unit,
                "note": field.note,
            })
        for i, raw in enumerate(self.current.values):
            if i not in FIELD_BY_INDEX:
                rows.append({
                    "section": "Raw",
                    "index": i,
                    "label": f"Raw value {i:02d}",
                    "raw": raw,
                    "display": f"{raw:.6f}",
                    "unit": "raw",
                    "note": "",
                })
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["section", "index", "label", "raw", "display", "unit", "note"])
            writer.writeheader()
            writer.writerows(rows)

    def make_upgrade_card(self, upg: UpgradeEntry):
        card = QFrame()
        card.setObjectName("valueRow")
        card.setMinimumHeight(76)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        left = QVBoxLayout()
        title = QLabel(f"Slot {upg.slot_index:02d} · {upgrade_slot_label(upg.slot_index)}")
        title.setObjectName("tuneTitle")
        left.addWidget(title)

        if upg.state == "absent":
            state_text = "Absent"
        else:
            source = "same car" if upg.key == self.current.ordinal else f"source/key {upg.key}"
            state_text = f"Variant {upg.index} · {source}"

        meta = QLabel(state_text)
        meta.setObjectName("meta")
        left.addWidget(meta)

        raw = QLabel(f"raw {upg.raw}")
        raw.setObjectName("meta")
        left.addWidget(raw)

        row.addLayout(left, 1)

        status = QLabel("ABSENT" if upg.state == "absent" else "INSTALLED")
        status.setObjectName("valuePill")
        status.setAlignment(Qt.AlignCenter)
        status.setMinimumWidth(96)
        row.addWidget(status)

        return card

    def make_collapsible_section(self, title: str, count: int, expanded: bool = True):
        wrapper = QFrame()
        wrapper.setObjectName("card")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        header = QPushButton(f"{'▼' if expanded else '▶'}  {title.upper()}  ·  {count}")
        header.setCheckable(True)
        header.setChecked(expanded)
        header.setMinimumHeight(38)
        outer.addWidget(header)

        body = QWidget()
        body_layout = QGridLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setHorizontalSpacing(10)
        body_layout.setVerticalSpacing(10)
        body.setVisible(expanded)
        outer.addWidget(body)

        def toggle(checked):
            body.setVisible(checked)
            header.setText(f"{'▼' if checked else '▶'}  {title.upper()}  ·  {count}")

        header.toggled.connect(toggle)
        return wrapper, body_layout

    def render_upgrades_collapsible(self, layout):
        groups = {}
        for upg in self.current.upgrades:
            groups.setdefault(upgrade_slot_category(upg.slot_index), []).append(upg)

        controls = QHBoxLayout()
        expand_all = QPushButton("Expand All")
        collapse_all = QPushButton("Collapse All")
        controls.addWidget(expand_all)
        controls.addWidget(collapse_all)
        controls.addStretch(1)
        layout.addLayout(controls)

        collapsibles = []

        for category in UPGRADE_CATEGORY_ORDER:
            items = groups.get(category, [])
            if not items:
                continue

            installed = sum(1 for item in items if item.state != "absent")
            wrapper, grid = self.make_collapsible_section(category, f"{installed}/{len(items)} installed", expanded=True)
            collapsibles.append(wrapper)

            for idx, upg in enumerate(items):
                grid.addWidget(self.make_upgrade_card(upg), idx // 2, idx % 2)

            layout.addWidget(wrapper)

        # Any category not in the preferred order still renders.
        for category, items in groups.items():
            if category in UPGRADE_CATEGORY_ORDER:
                continue
            installed = sum(1 for item in items if item.state != "absent")
            wrapper, grid = self.make_collapsible_section(category, f"{installed}/{len(items)} installed", expanded=False)
            collapsibles.append(wrapper)
            for idx, upg in enumerate(items):
                grid.addWidget(self.make_upgrade_card(upg), idx // 2, idx % 2)
            layout.addWidget(wrapper)

        def set_all(open_state: bool):
            for wrapper in collapsibles:
                try:
                    btn = wrapper.findChild(QPushButton)
                    if btn is not None:
                        btn.setChecked(open_state)
                except Exception:
                    pass

        expand_all.clicked.connect(lambda: set_all(True))
        collapse_all.clicked.connect(lambda: set_all(False))

    def render_tune_values(self):
        while self.tune_section_stack.count():
            widget = self.tune_section_stack.widget(0)
            self.tune_section_stack.removeWidget(widget)
            widget.deleteLater()

        if not self.current:
            lbl = QLabel("Load and select a tune to view values.")
            lbl.setAlignment(Qt.AlignCenter)
            self.tune_section_stack.addWidget(lbl)
            self.tune_section_stack.setCurrentWidget(lbl)
            return

        area, content, layout = self.make_scroll_page()
        title = QLabel(self.current_section.upper())
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        try:
            if self.current_section == "Upgrades":
                self.render_upgrades_collapsible(layout)

            elif self.current_section == "Raw":
                for i, raw in enumerate(self.current.values):
                    card = QFrame()
                    card.setObjectName("valueRow")
                    row = QHBoxLayout(card)
                    row.setContentsMargins(14, 10, 14, 10)
                    label = QLabel(f"Raw value {i:02d}")
                    value = QLabel(f"{raw:.6f}")
                    value.setObjectName("valuePill")
                    row.addWidget(label, 1)
                    row.addWidget(value)
                    layout.addWidget(card)

            else:
                fields = self.debug_section_fields(self.current_section)
                if not fields:
                    msg = QLabel(
                        f"No mapped in-game values for {self.current_section} yet.\n\n"
                        f"Known mapped sections: {', '.join(sorted(FIELDS_BY_SECTION.keys()))}"
                    )
                    msg.setAlignment(Qt.AlignCenter)
                    msg.setWordWrap(True)
                    layout.addWidget(msg)
                else:
                    for field in fields:
                        layout.addWidget(self.make_tune_value_row(field))

        except Exception as exc:
            msg = QLabel(f"Could not render {self.current_section} values:\n{exc}\n\nIf this mentions QSlider, the slider import failed.")
            msg.setAlignment(Qt.AlignCenter)
            msg.setWordWrap(True)
            layout.addWidget(msg)

        layout.addStretch(1)
        self.tune_section_stack.addWidget(area)
        self.tune_section_stack.setCurrentWidget(area)

    def save_copy(self):
        if not self.current:
            QMessageBox.information(self, "No tune selected", "Load and select a tune first.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save edited tune copy", str(self.current.path.parent / (self.current.path.name + "_edited")), "FH6 Data file (Data*);;All files (*.*)")
        if out:
            self.current.save_to(Path(out))

    def share_json(self):
        if not self.current:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export share JSON", f"{self.current.car_name.replace(' ', '_')}_share.json", "JSON (*.json)")
        if not out:
            return
        tune_bytes = self.current.raw_bytes
        thumb_payload = None
        thumb = thumbnail_cache_path(self.current.ordinal)
        if thumb.exists():
            thumb_payload = {"filename": THUMBNAIL_FILENAME, "format": "png", "image_base64": base64.b64encode(thumb.read_bytes()).decode("ascii")}
        package = {
            "schema": SHARE_SCHEMA_VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "app": APP_NAME,
            "tune": {
                "car_name": self.current.car_name,
                "ordinal": self.current.ordinal,
                "drivetrain": self.current.drivetrain_label,
                "active_gears": self.current.active_gear_count,
                "original_filename": self.current.path.name,
                "md5": hashlib.md5(tune_bytes).hexdigest(),
                "size": len(tune_bytes),
                "values": [float(v) for v in self.current.values],
                "data_base64": base64.b64encode(tune_bytes).decode("ascii"),
                "thumbnail": thumb_payload,
            },
        }
        Path(out).write_text(json.dumps(package, indent=2), encoding="utf-8")

    def import_share_json(self):
        infile, _ = QFileDialog.getOpenFileName(self, "Import share JSON", "", "JSON (*.json)")
        if not infile:
            return
        try:
            package = json.loads(Path(infile).read_text(encoding="utf-8"))
            if package.get("schema") != SHARE_SCHEMA_VERSION:
                raise ValueError("Unsupported share package")
            tune_info = package["tune"]
            tune_bytes = base64.b64decode(tune_info["data_base64"], validate=True)
            if len(tune_bytes) != TUNE_FILE_SIZE:
                raise ValueError("Tune data size mismatch")
            IMPORTED_SHARE_DIR.mkdir(parents=True, exist_ok=True)
            ordinal = int(tune_info.get("ordinal", 0) or 0)
            out_path = IMPORTED_SHARE_DIR / f"Data_shared_{ordinal}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            out_path.write_bytes(tune_bytes)
            thumb_info = tune_info.get("thumbnail")
            if isinstance(thumb_info, dict) and thumb_info.get("image_base64"):
                (out_path.parent / THUMBNAIL_FILENAME).write_bytes(base64.b64decode(thumb_info["image_base64"]))
            tune = parse_tune_file(out_path)
            cache_thumb_for_tune(tune)
            self.tunes.append(tune)
            self.current = tune
            self.refresh_tune_list()
            self.update_header()
            self.render_tune_values()
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))

    def open_thumbnail_repo_page(self):
        QDesktopServices.openUrl(QUrl(PUBLIC_THUMBNAIL_REPO_URL))

    def install_thumbnail_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder containing thumbnail images", str(BASE_DIR))
        if not folder:
            return

        root = Path(folder)
        if not root.exists():
            QMessageBox.warning(self, "Folder not found", "That folder no longer exists.")
            return

        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        candidates = {}

        scanned = 0
        skipped_no_id = 0
        skipped_invalid = 0

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith("_tmp_"):
                continue
            if path.suffix.lower() not in image_exts:
                continue

            scanned += 1
            ordinal = thumbnail_ordinal_from_filename(path)
            if ordinal is None:
                skipped_no_id += 1
                continue

            image = QImage(str(path))
            if image.isNull():
                skipped_invalid += 1
                continue

            area = int(image.width()) * int(image.height())
            size = path.stat().st_size if path.exists() else 0
            previous = candidates.get(ordinal)
            if previous is None or (area, size) > (previous["area"], previous["size"]):
                candidates[ordinal] = {
                    "path": path,
                    "area": area,
                    "size": size,
                    "width": image.width(),
                    "height": image.height(),
                }

        if not candidates:
            QMessageBox.information(
                self,
                "No thumbnails installed",
                f"No usable thumbnail images with ordinal IDs were found.\n\nScanned images: {scanned}\nSkipped without ID: {skipped_no_id}\nSkipped invalid: {skipped_invalid}",
            )
            return

        THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        installed = 0
        failed = 0

        for ordinal, info in sorted(candidates.items()):
            image = QImage(str(info["path"]))
            if image.isNull():
                failed += 1
                continue
            if image.save(str(thumbnail_cache_path(ordinal)), "PNG"):
                installed += 1
            else:
                failed += 1

        duplicate_count = scanned - skipped_no_id - skipped_invalid - len(candidates)
        message = (
            f"Installed {installed} thumbnails into:\n{THUMBNAIL_CACHE_DIR}\n\n"
            f"Scanned images: {scanned}\n"
            f"Duplicate ordinals handled: {max(0, duplicate_count)}\n"
            f"Skipped without ordinal ID: {skipped_no_id}\n"
            f"Skipped invalid/unreadable: {skipped_invalid}\n"
            f"Failed to save: {failed}"
        )

        if hasattr(self, "thumb_status"):
            self.thumb_status.setText(f"Installed {installed} local thumbnails · skipped {skipped_no_id + skipped_invalid} · failed {failed}")

        self.refresh_tune_list()
        self.refresh_car_view()
        QMessageBox.information(self, "Thumbnail folder installed", message)

    def scan_thumbnails(self):
        good = 0
        missing = 0
        for tune in self.tunes:
            cache_thumb_for_tune(tune)
            if thumbnail_cache_path(tune.ordinal).exists():
                good += 1
            else:
                missing += 1
        self.thumb_status.setText(f"Cached/available: {good} · Missing/broken: {missing}")
        self.refresh_tune_list()

    def assign_thumbnail(self):
        if not self.current:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Assign PNG thumbnail", "", "PNG (*.png)")
        if not filename:
            return
        pix = QPixmap(filename)
        if pix.isNull():
            QMessageBox.warning(self, "Invalid PNG", "That file could not be loaded as a PNG.")
            return
        THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pix.save(str(thumbnail_cache_path(self.current.ordinal)), "PNG")
        self.refresh_tune_list()

    def diagnostic_text(self) -> str:
        try:
            import PySide6
            pyside_version = getattr(PySide6, "__version__", "unknown")
        except Exception:
            pyside_version = "unknown"

        lines = [
            f"FH6 Tune Editor diagnostics",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            f"App version: {APP_VERSION}",
            f"App name: {APP_NAME}",
            f"Python: {sys.version}",
            f"Executable: {sys.executable}",
            f"Frozen/EXE: {bool(getattr(sys, 'frozen', False))}",
            f"PySide6: {pyside_version}",
            "",
            f"Base dir: {BASE_DIR}",
            f"Resource base dir: {RESOURCE_BASE_DIR}",
            f"Data dir: {DATA_DIR}",
            f"Car DB loaded: {len(CAR_DB)} entries",
            f"Drivetrain DB loaded: {len(DT_DB)} entries",
            f"Config path: {CONFIG_PATH}",
            f"Thumbnail cache: {THUMBNAIL_CACHE_DIR}",
            f"Thumbnail cache images: {len([p for p in THUMBNAIL_CACHE_DIR.glob('*.png') if not p.name.startswith('_tmp_')]) if THUMBNAIL_CACHE_DIR.exists() else 0}",
            f"Thumbnail temp files: {len(list(THUMBNAIL_CACHE_DIR.glob('_tmp_*'))) if THUMBNAIL_CACHE_DIR.exists() else 0}",
            f"Auto update checks: disabled in public build",
            f"Automatic thumbnail downloads: disabled in public build",
            f"Shared laps: {SHARED_LAPS_DIR}",
            f"Imported shares: {IMPORTED_SHARE_DIR}",
            "",
            f"Telemetry port: {self.config.get('telemetry_port', 3010)}",
            f"Telemetry running: {self.telemetry_running}",
            f"Telemetry packets: {self.telemetry_packets}",
            f"Last telemetry car: {self.telemetry_last.get('telemetry_car_name', '--') if isinstance(self.telemetry_last, dict) else '--'}",
            f"Speed unit: {self.speed_unit}",
            "",
            f"Loaded tune count: {len(self.tunes)}",
            f"Auto-load current car tune: {self.config.get('auto_load_current_car_tune', True)}",
            f"Pending current car tune load: {self.pending_current_car_tune_load}",
            f"Latest telemetry car ordinal: {self.latest_telemetry_car_data().get('car_ordinal', '--')}",
            f"Auto-load attempted ordinals: {sorted(list(self.auto_load_attempted_ordinals))}",
            f"Current tune: {self.current.car_name if self.current else '--'}",
            f"Current ordinal: {self.current.ordinal if self.current else '--'}",
            f"Current tune path: {self.current.path if self.current else '--'}",
            "",
            "Config:",
            json.dumps(self.config, indent=2),
        ]
        return "\n".join(lines)

    def export_diagnostics(self):
        default = f"FH6_Tune_Editor_Diagnostics_v{APP_VERSION}.txt"
        out, _ = QFileDialog.getSaveFileName(self, "Export Diagnostic Report", default, "Text files (*.txt);;All files (*.*)")
        if not out:
            return
        try:
            Path(out).write_text(self.diagnostic_text(), encoding="utf-8")
            QMessageBox.information(self, "Diagnostics exported", f"Saved:\n{out}")
        except Exception as exc:
            QMessageBox.critical(self, "Diagnostics failed", str(exc))

    def apply_theme_settings(self):
        if hasattr(self, "rounded_spin"):
            self.config["rounded"] = self.rounded_spin.value()
        if hasattr(self, "sidebar_width_spin"):
            self.config["sidebar_width"] = self.clamp_sidebar_width(self.sidebar_width_spin.value())
            self.apply_sidebar_width(self.config["sidebar_width"], save=False)
        try:
            self.config["telemetry_port"] = int(self.port_input.text() or "3010")
        except Exception:
            self.config["telemetry_port"] = 3010
        if hasattr(self, "dev_mode_checkbox"):
            self.config["dev_mode"] = bool(self.dev_mode_checkbox.isChecked())
        self.config["auto_update_check"] = False
        self.config["auto_thumbnail_cache_update"] = False
        if hasattr(self, "auto_current_car_tune_checkbox"):
            self.config["auto_load_current_car_tune"] = bool(self.auto_current_car_tune_checkbox.isChecked())
        save_config(self.config)
        self.apply_style()
        if hasattr(self, "refresh_colour_buttons"):
            self.refresh_colour_buttons()
        if hasattr(self, "update_dev_mode_visibility"):
            self.update_dev_mode_visibility()

    def start_telemetry(self):
        if self.telemetry_running:
            return
        port = int(self.config.get("telemetry_port", 3010))
        try:
            self.telemetry_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.telemetry_socket.bind(("0.0.0.0", port))
            self.telemetry_socket.settimeout(0.5)
        except Exception as exc:
            QMessageBox.critical(self, "Telemetry failed", f"Could not bind UDP port {port}:\n{exc}")
            return
        self.telemetry_running = True
        self.telemetry_thread = threading.Thread(target=self.telemetry_worker, daemon=True)
        self.telemetry_thread.start()

    def stop_telemetry(self):
        self.telemetry_running = False
        try:
            if self.telemetry_socket:
                self.telemetry_socket.close()
        except Exception:
            pass
        self.telemetry_socket = None

    def telemetry_worker(self):
        while self.telemetry_running:
            try:
                data, _ = self.telemetry_socket.recvfrom(2048)
                decoded = decode_forza_telemetry_packet(data)
                self.telemetry_last = decoded
                self.telemetry_packets += 1
                self.telemetry_samples.append(decoded)
                if len(self.telemetry_samples) > 20000:
                    self.telemetry_samples = self.telemetry_samples[-10000:]
            except socket.timeout:
                continue
            except Exception:
                if self.telemetry_running:
                    continue

    def clear_telemetry(self):
        self.telemetry_packets = 0
        self.telemetry_samples.clear()
        self.telemetry_last = {}
        self.refresh_share_preview()

    def toggle_speed_unit(self):
        self.speed_unit = "kmh" if self.speed_unit == "mph" else "mph"
        self.config["speed_unit"] = self.speed_unit
        save_config(self.config)
        self.speed_unit_btn.setText("Speed: KM/H" if self.speed_unit == "kmh" else "Speed: MPH")

    def set_current_tune_and_refresh(self, tune: TuneFile):
        existing_paths = {str(t.path) for t in self.tunes}
        if str(tune.path) not in existing_paths:
            self.tunes.append(tune)
        self.current = tune
        self.config["last_loaded_tune_file"] = str(tune.path)
        # Keep scan root separate from selected tune folder.
        save_config(self.config)
        self.refresh_filter_options()
        self.refresh_tune_list()
        self.update_header()
        self.update_section_button_state()
        self.render_tune_values()
        self.refresh_car_view()
        self.refresh_tuning_assist()

    def newest_loaded_tune_for_ordinal(self, ordinal: int):
        matches = [t for t in self.tunes if int(t.ordinal) == int(ordinal)]
        if not matches:
            return None
        def mtime(t):
            try:
                return t.path.stat().st_mtime
            except Exception:
                return 0
        return max(matches, key=mtime)

    def tune_search_roots_from_config(self) -> list[Path]:
        pattern = str(self.config.get("last_scan_folder") or self.config.get("last_tune_folder") or DEFAULT_TUNE_FOLDER_GLOB).strip()
        pattern_norm = pattern.replace("\\", "/").lower()
        leaf = pattern_norm.rstrip("/").split("/")[-1] if pattern_norm else ""
        if leaf.startswith("tuning_") or "/tuning_" in pattern_norm:
            pattern = DEFAULT_TUNE_FOLDER_GLOB
            self.config["last_scan_folder"] = DEFAULT_TUNE_FOLDER_GLOB
            self.config["last_tune_folder"] = DEFAULT_TUNE_FOLDER_GLOB
            save_config(self.config)
        matches = glob.glob(pattern)
        roots = [Path(m) for m in matches] if matches else [Path(pattern)]
        expanded = []
        seen = set()
        for root in roots:
            for candidate in [root, root.parent if root.name.lower().startswith("tuning_") else None]:
                if candidate is None:
                    continue
                key = str(candidate)
                if key not in seen:
                    seen.add(key)
                    expanded.append(candidate)
        return expanded

    def find_newest_tune_for_ordinal_in_paths(self, ordinal: int):
        candidates = []
        for root in self.tune_search_roots_from_config():
            try:
                for path in discover_tune_files(root):
                    try:
                        tune = parse_tune_file(path)
                        if int(tune.ordinal) == int(ordinal):
                            candidates.append(tune)
                    except Exception:
                        continue
            except Exception:
                continue

        if not candidates:
            return None

        def mtime(t):
            try:
                return t.path.stat().st_mtime
            except Exception:
                return 0

        return max(candidates, key=mtime)

    def latest_telemetry_car_data(self) -> dict:
        """Return the newest telemetry sample with a usable car ordinal."""
        data = dict(self.telemetry_last or {})
        ordinal = data.get("car_ordinal")
        if isinstance(ordinal, int) and ordinal > 0:
            return data

        for sample in reversed(self.telemetry_samples[-250:]):
            ordinal = sample.get("car_ordinal")
            if isinstance(ordinal, int) and ordinal > 0:
                return dict(sample)

        return data

    def wait_for_current_car_tune_packet(self, silent: bool = False):
        if not self.telemetry_running:
            self.start_telemetry()

        self.pending_current_car_tune_load = True
        self.pending_current_car_tune_deadline = time.time() + 8.0

        if hasattr(self, "tel_car"):
            self.tel_car.setText("Waiting for FH telemetry car packet... Make sure Data Out is active and the app telemetry listener is started.")

        if not silent:
            QMessageBox.information(
                self,
                "Waiting for telemetry car",
                "I started/will use telemetry and will wait a few seconds for the current car packet.\n\n"
                "If this times out, make sure FH Data Out is enabled and using the full/Dash telemetry format so car ordinal is included.",
            )

        QTimer.singleShot(500, self.check_pending_current_car_tune_load)

    def check_pending_current_car_tune_load(self):
        if not self.pending_current_car_tune_load:
            return

        data = self.latest_telemetry_car_data()
        ordinal = data.get("car_ordinal")
        if isinstance(ordinal, int) and ordinal > 0:
            self.pending_current_car_tune_load = False
            self.load_current_car_tune_from_telemetry(silent=False, allow_wait=False)
            return

        if time.time() >= self.pending_current_car_tune_deadline:
            self.pending_current_car_tune_load = False
            packet_count = self.telemetry_packets
            packet_size = self.telemetry_last.get("packet_size", "--") if isinstance(self.telemetry_last, dict) else "--"
            QMessageBox.information(
                self,
                "No telemetry car detected",
                "Telemetry did not provide a valid car ordinal within 8 seconds.\n\n"
                f"Packets received: {packet_count}\n"
                f"Last packet size: {packet_size}\n\n"
                "If packets are 0, click Start Telemetry and check FH Data Out IP/port.\n"
                "If packets are arriving but car is not detected, FH may be sending a telemetry format that does not include car ordinal. "
                "Use the full/Dash Data Out format if FH gives you that option.",
            )
            return

        QTimer.singleShot(500, self.check_pending_current_car_tune_load)

    def load_current_car_tune_from_telemetry(self, silent: bool = False, allow_wait: bool = True):
        data = self.latest_telemetry_car_data()
        ordinal = data.get("car_ordinal")
        car_name = data.get("telemetry_car_name") or "--"

        if not isinstance(ordinal, int) or ordinal <= 0:
            if allow_wait:
                self.wait_for_current_car_tune_packet(silent=silent)
            elif not silent:
                QMessageBox.information(
                    self,
                    "No telemetry car detected",
                    "No valid telemetry car ordinal was found yet. Start telemetry and make sure FH Data Out is sending the full/Dash packet.",
                )
            return False

        if self.current and int(self.current.ordinal) == int(ordinal):
            if not silent:
                QMessageBox.information(self, "Already loaded", f"The selected tune already matches:\n{car_name} #{ordinal}")
            return True

        loaded_match = self.newest_loaded_tune_for_ordinal(ordinal)
        if loaded_match:
            self.set_current_tune_and_refresh(loaded_match)
            if not silent:
                QMessageBox.information(self, "Current car tune loaded", f"Selected loaded tune for:\n{loaded_match.car_name}")
            return True

        if self.current_car_tune_scan_running:
            return False

        self.current_car_tune_scan_running = True
        if hasattr(self, "tel_car") and not silent:
            self.tel_car.setText(f"Searching saved tunes for {car_name} #{ordinal}...")

        def worker():
            try:
                found = self.find_newest_tune_for_ordinal_in_paths(ordinal)

                def done():
                    self.current_car_tune_scan_running = False
                    if found:
                        self.set_current_tune_and_refresh(found)
                        msg = f"Loaded newest matching tune for:\n{found.car_name}\n\n{found.path}"
                        if not silent:
                            QMessageBox.information(self, "Current car tune loaded", msg)
                    else:
                        if not silent:
                            QMessageBox.information(
                                self,
                                "No matching tune found",
                                f"No saved tune for current telemetry car was found:\n{car_name} #{ordinal}\n\nSearch folder:\n{self.config.get('last_scan_folder', self.config.get('last_tune_folder', DEFAULT_TUNE_FOLDER_GLOB))}",
                            )

                QTimer.singleShot(0, done)

            except Exception as exc:
                def failed():
                    self.current_car_tune_scan_running = False
                    if not silent:
                        QMessageBox.critical(self, "Current car tune load failed", str(exc))
                QTimer.singleShot(0, failed)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def auto_load_current_car_tune_if_needed(self, data: dict):
        if not bool(self.config.get("auto_load_current_car_tune", True)):
            return
        ordinal = data.get("car_ordinal")
        if not isinstance(ordinal, int) or ordinal <= 0:
            return
        if self.current and int(self.current.ordinal) == int(ordinal):
            return
        if ordinal in self.auto_load_attempted_ordinals:
            return
        self.auto_load_attempted_ordinals.add(ordinal)
        self.load_current_car_tune_from_telemetry(silent=True)

    def refresh_telemetry_ui(self):
        data = dict(self.telemetry_last)
        unit = "KM/H" if self.speed_unit == "kmh" else "MPH"
        speed_key = "speed_kmh" if self.speed_unit == "kmh" else "speed_mph"
        speed = data.get(speed_key, 0.0) or 0.0
        rpm = float(data.get('rpm') or 0.0)
        max_rpm = float(data.get('engine_max_rpm') or 8000.0)
        throttle = float(data.get('throttle') or 0.0)
        brake = float(data.get('brake') or 0.0)
        power_kw = float(data.get('power_kw') or 0.0)
        torque_nm = float(data.get('torque_nm') or 0.0)
        gear = data.get('gear', '--')
        self.speedometer.set_values(speed, rpm, gear, unit)
        self.tachometer.set_values(rpm, max_rpm, throttle)
        self.steering.set_value(data.get('steer', 0))
        self.pedal_bars.set_values(throttle, brake)
        self.suspension_visual.set_values({
            'FL': data.get('suspension_fl'),
            'FR': data.get('suspension_fr'),
            'RL': data.get('suspension_rl'),
            'RR': data.get('suspension_rr'),
        })

        if hasattr(self, "current_tyre_pressure_targets"):
            front_psi, rear_psi = self.current_tyre_pressure_targets()
        else:
            front_psi, rear_psi = None, None
        self.tyre_status.set_values({
            'FL': data.get('tyre_temp_fl'),
            'FR': data.get('tyre_temp_fr'),
            'RL': data.get('tyre_temp_rl'),
            'RR': data.get('tyre_temp_rr'),
        }, front_psi, rear_psi)

        car = data.get("telemetry_car_name") or "--"
        if car != "--":
            self.tel_car.setText(f"{car} · Ordinal #{data.get('car_ordinal', '--')} · Live tyre temps + tune pressure targets")
            if self.pending_current_car_tune_load and isinstance(data.get("car_ordinal"), int) and data.get("car_ordinal") > 0:
                self.pending_current_car_tune_load = False
                self.load_current_car_tune_from_telemetry(silent=False, allow_wait=False)
            self.auto_load_current_car_tune_if_needed(data)
        if hasattr(self, 'telemetry_hud'):
            self.telemetry_hud.set_values(
                car=car,
                speed=f"{float(speed):.1f} {unit}",
                gear=gear,
                rpm=f"{rpm:.0f}",
                lap=format_lap_time(data.get('lap_time_current')),
                status=("LIVE" if self.telemetry_running else "WAITING"),
            )
        labels = {
            "speed": f"SPEED\n{float(speed):.1f} {unit}",
            "rpm": f"RPM\n{rpm:.0f} / {max_rpm:.0f}",
            "gear": f"GEAR\n{gear}",
            "throttle": f"THROTTLE\n{throttle:.0f}%",
            "brake": f"BRAKE\n{brake:.0f}%",
            "power": f"POWER\n{power_kw:.1f} kW",
            "torque": f"TORQUE\n{torque_nm:.0f} Nm",
            "packets": f"PACKETS\n{self.telemetry_packets}",
        }
        for key, value in labels.items():
            self.tel_labels[key].setText(value)

        current_lap = data.get("lap_time_current")
        last_lap = data.get("lap_time_last")
        best_lap = data.get("lap_time_best")
        lap_no = data.get("lap_number")
        race_pos = data.get("race_position")

        self.update_app_race_timer_from_telemetry(data)
        app_time = self.current_race_timer_seconds()
        saved_time = self.race_timer_saved_elapsed

        if hasattr(self, "race_timer_big"):
            self.race_timer_big.setText(format_lap_time(app_time))
        if hasattr(self, "race_labels"):
            status = self.race_timer_status_text
            if self.race_timer_running and self.race_timer_auto_paused:
                status = "Paused/no telemetry clock"
            race_values = {
                "app_timer": f"App Timer\n{format_lap_time(app_time)}",
                "saved": f"Saved Time\n{format_lap_time(saved_time)}",
                "status": f"Status\n{status}",
                "game_current": f"Game Current Raw\n{format_lap_time(current_lap)}",
                "game_last": f"Game Last Raw\n{format_lap_time(last_lap)}",
                "packets": f"Packets\n{self.telemetry_packets}",
            }
            for key, value in race_values.items():
                if key in self.race_labels:
                    self.race_labels[key].setText(value)
        if hasattr(self, "race_raw"):
            self.race_raw.setText(
                f"status={self.race_timer_status_text} · is_race_on={data.get('is_race_on')!r} · "
                f"timestamp_ms={data.get('timestamp_ms')!r} · "
                f"game_current={current_lap!r} · game_last={last_lap!r} · game_best={best_lap!r} · "
                f"lap={lap_no!r} · position={race_pos!r}"
            )
        if hasattr(self, "car_showcase"):
            self.car_showcase.set_tune(self.current, data)
        self.refresh_share_preview()

    def export_telemetry_csv(self):
        if not self.telemetry_samples:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export telemetry CSV", "fh6_telemetry.csv", "CSV (*.csv)")
        if not out:
            return
        keys = sorted({k for sample in self.telemetry_samples for k in sample.keys()})
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.telemetry_samples)


def main():
    app = QApplication(sys.argv)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    win = FH6QtApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
