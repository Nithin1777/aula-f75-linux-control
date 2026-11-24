"""Safe Linux hidraw driver for Instant Microelectronics A825 mice (e.g. Ant Esports GM320, 30fa:1440)."""

from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .layout import format_hex_color, parse_hex_color

MOUSE_VENDOR_ID = "000030FA"
MOUSE_PRODUCT_IDS = ("00001440", "00001040")
REPORT_ID = 0x07
REPORT_LEN = 8

CFG_START = 0x08
CFG_LEN = 0x38  # 0x08..0x3f
WRITABLE_BLOCKS = frozenset({0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38})

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "aula-f75-control"
MOUSE_INITIAL_BACKUP_PATH = DEFAULT_DATA_DIR / "mouse_initial_backup.json"


class MouseProtocolError(RuntimeError):
    """Raised when mouse HID communication or safety validation fails."""


# DPI code <-> DPI mapping (Instant A825; code 11 unused)
DPI_BY_CODE: Dict[int, int] = {c: c * 200 for c in range(1, 11)}
DPI_BY_CODE.update(
    {
        12: 2400,
        13: 3200,
        14: 4000,
        15: 4800,
        16: 5600,
        17: 6400,
        18: 7200,
        19: 8000,
        20: 8800,
        21: 9600,
        22: 10400,
        23: 11200,
        24: 12800,
    }
)
CODE_BY_DPI: Dict[int, int] = {v: k for k, v in DPI_BY_CODE.items()}
DPI_VALUES: List[int] = sorted(CODE_BY_DPI)


@dataclass(frozen=True)
class MouseLedMode:
    mode_id: int
    slug: str
    name: str
    uses_color: bool


MOUSE_LED_MODES: List[MouseLedMode] = [
    MouseLedMode(0, "dpi-breathing", "DPI Breathing", True),
    MouseLedMode(1, "cycle-breathing", "Cycle Breathing", False),
    MouseLedMode(2, "light-on", "Static (Light On)", True),
    MouseLedMode(3, "flowing-water", "Flowing Water", False),
    MouseLedMode(4, "mono-water", "Mono Water", True),
    MouseLedMode(5, "comet-streak", "Comet Streak", False),
    MouseLedMode(6, "neon", "Neon Wave", False),
    MouseLedMode(7, "ambilight", "Ambilight", False),
    MouseLedMode(8, "flicker", "Rhythmic Flicker", False),
    MouseLedMode(9, "star-trek", "Star Trek", False),
    MouseLedMode(10, "ripple", "Water Ripple", False),
    MouseLedMode(11, "enraptured", "Enraptured", False),
    MouseLedMode(12, "click-response", "Click Response", False),
    MouseLedMode(13, "off", "Off", False),
]

MOUSE_LED_BY_ID: Dict[int, MouseLedMode] = {m.mode_id: m for m in MOUSE_LED_MODES}
MOUSE_LED_BY_SLUG: Dict[str, MouseLedMode] = {m.slug: m for m in MOUSE_LED_MODES}
MOUSE_LED_ALIASES: Dict[str, int] = {
    "static": 2,
    "solid": 2,
    "breathing": 1,
    "wave": 6,
    "neon-wave": 6,
    "click": 12,
    "reactive": 12,
}


def resolve_mouse_led(value: str | int) -> MouseLedMode:
    if isinstance(value, int):
        if value in MOUSE_LED_BY_ID:
            return MOUSE_LED_BY_ID[value]
        raise ValueError(f"Unknown mouse LED mode ID: {value} (expected 0..13)")
    s = str(value).strip().lower().replace("_", "-")
    if s.isdigit():
        return resolve_mouse_led(int(s))
    if s in MOUSE_LED_BY_SLUG:
        return MOUSE_LED_BY_SLUG[s]
    if s in MOUSE_LED_ALIASES:
        return MOUSE_LED_BY_ID[MOUSE_LED_ALIASES[s]]
    for m in MOUSE_LED_MODES:
        if s == m.name.lower():
            return m
    raise ValueError(f"Unknown mouse LED mode: {value!r}")


# Physical button slots in 0x08..0x0f (slot 6 unused on 7-button GM320)
MOUSE_BUTTON_SLOTS: List[Tuple[int, str]] = [
    (0, "Left Click"),
    (2, "Right Click"),
    (1, "Middle Click"),
    (3, "Side Back"),
    (4, "Side Forward"),
    (5, "Top Button 1 (LED/DPI)"),
    (7, "Top Button 2 (DPI/LED)"),
]

MOUSE_BUTTON_FUNCTIONS: List[Tuple[int, str]] = [
    (0x21, "Left Click"),
    (0x23, "Right Click"),
    (0x22, "Middle Click"),
    (0x24, "Back"),
    (0x25, "Forward"),
    (0x26, "DPI Loop"),
    (0x2B, "DPI +"),
    (0x2C, "DPI -"),
    (0x35, "LED Mode Loop"),
    (0x28, "Double Click"),
    (0x29, "Rapid Fire"),
    (0x27, "Show Desktop"),
    (0x34, "Fn"),
    (0x00, "Disabled"),
]

FUNC_NAME_BY_CODE: Dict[int, str] = {code: name for code, name in MOUSE_BUTTON_FUNCTIONS}
LEFT_CLICK_CODE = 0x21

MOUSE_QUICK_PRESETS: List[Tuple[str, int, int, Optional[Tuple[int, int, int]]]] = [
    ("Static Cyan", 2, 2, (0, 220, 255)),
    ("Static Red", 2, 2, (255, 20, 40)),
    ("Static Purple", 2, 2, (170, 40, 255)),
    ("Static White", 2, 2, (255, 255, 255)),
    ("Flowing Water", 3, 2, None),
    ("Neon Wave", 6, 3, None),
    ("Click Response", 12, 3, None),
    ("Off", 13, 0, None),
]


def _ioc(nr: int, length: int) -> int:
    return (3 << 30) | (length << 16) | (0x48 << 8) | nr


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def find_instant_mouse_hidraw() -> Optional[Dict[str, Any]]:
    """Locate the connected Instant Microelectronics mouse vendor hidraw node."""
    sys_hidraw = Path("/sys/class/hidraw")
    if not sys_hidraw.exists():
        return None

    candidates: List[Dict[str, Any]] = []
    for entry in sorted(sys_hidraw.iterdir()):
        uevent = _read_text(entry / "device" / "uevent")
        if not uevent:
            continue
        props: Dict[str, str] = {}
        for line in uevent.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()

        hid_id = props.get("HID_ID", "").upper()
        if MOUSE_VENDOR_ID not in hid_id:
            continue
        matched_pid = next((pid for pid in MOUSE_PRODUCT_IDS if pid in hid_id), None)
        if not matched_pid:
            continue

        rdesc = _read_bytes(entry / "device" / "report_descriptor")
        has_vendor_feature = (b"\x06\x01\xff" in rdesc) and (b"\x85\x07" in rdesc)
        if not has_vendor_feature:
            continue

        dev_path = f"/dev/{entry.name}"
        vid_pid = f"30fa:{matched_pid[-4:].lower()}"
        candidates.append(
            {
                "path": dev_path,
                "hid_name": props.get("HID_NAME", "INSTANT USB GAMING MOUSE").strip(),
                "phys": props.get("HID_PHYS", ""),
                "hid_id": hid_id,
                "vid_pid": vid_pid,
                "model_name": "Ant Esports GM320 / Instant A825" if matched_pid == "00001440" else "Instant A825 Mouse",
                "readable": os.access(dev_path, os.R_OK),
                "writable": os.access(dev_path, os.W_OK),
            }
        )

    return candidates[0] if candidates else None


class InstantMouseConfig:
    """Field-level model of flash addresses 0x08..0x3f (56 bytes)."""

    def __init__(self, region: bytes | bytearray) -> None:
        if len(region) != CFG_LEN:
            raise MouseProtocolError(f"Expected {CFG_LEN} config bytes (0x08..0x3f), got {len(region)}")
        self.r = bytearray(region)

    def copy(self) -> "InstantMouseConfig":
        return InstantMouseConfig(self.r)

    def _b(self, addr: int) -> int:
        return self.r[addr - CFG_START]

    def _s(self, addr: int, val: int) -> None:
        self.r[addr - CFG_START] = val & 0xFF

    # ---- Buttons (0x08..0x0f) ----
    def get_button(self, slot: int) -> int:
        if not (0 <= slot <= 7):
            raise ValueError(f"Button slot out of range (0..7): {slot}")
        return self._b(0x08 + slot)

    def set_button(self, slot: int, code: int) -> None:
        if not (0 <= slot <= 7):
            raise ValueError(f"Button slot out of range (0..7): {slot}")
        self._s(0x08 + slot, code)

    # ---- DPI stages (0..5) ----
    def get_dpi_code(self, stage: int) -> int:
        if not (0 <= stage < 6):
            raise ValueError(f"DPI stage out of range (0..5): {stage}")
        hi = (self._b(0x13) >> stage) & 1
        pair = self._b(0x15 + stage // 2)
        lo = (pair >> 4) if stage % 2 == 0 else (pair & 0x0F)
        return lo | (hi << 4)

    def get_dpi(self, stage: int) -> int:
        code = self.get_dpi_code(stage)
        return DPI_BY_CODE.get(code, code * 200)

    def set_dpi(self, stage: int, dpi_value: int) -> None:
        if not (0 <= stage < 6):
            raise ValueError(f"DPI stage out of range (0..5): {stage}")
        if dpi_value not in CODE_BY_DPI:
            raise ValueError(f"Unsupported DPI {dpi_value}. Valid: {DPI_VALUES}")
        code = CODE_BY_DPI[dpi_value]
        self._s(0x13, (self._b(0x13) & ~(1 << stage)) | (((code >> 4) & 1) << stage))
        addr = 0x15 + stage // 2
        pair = self._b(addr)
        if stage % 2 == 0:
            self._s(addr, (pair & 0x0F) | ((code & 0x0F) << 4))
        else:
            self._s(addr, (pair & 0xF0) | (code & 0x0F))

    def get_active_dpi_stage(self) -> int:
        return self._b(0x18) & 0x07

    def set_active_dpi_stage(self, stage: int) -> None:
        if not (0 <= stage < 6):
            raise ValueError(f"Active DPI stage out of range (0..5): {stage}")
        self._s(0x18, (self._b(0x18) & 0xF8) | (stage & 0x07))

    def get_dpi_enabled_mask(self) -> int:
        return self._b(0x19) & 0x3F

    def set_dpi_enabled_mask(self, mask: int) -> None:
        mask &= 0x3F
        if mask == 0:
            raise ValueError("At least one DPI stage must remain enabled")
        self._s(0x19, (self._b(0x19) & 0xC0) | mask)

    # ---- Stage RGB Colors (0x20..0x31, inverted 255 - channel) ----
    def get_stage_color(self, stage: int) -> Tuple[int, int, int]:
        if not (0 <= stage < 6):
            raise ValueError(f"DPI stage out of range (0..5): {stage}")
        base = 0x20 + stage * 3
        return (255 - self._b(base), 255 - self._b(base + 1), 255 - self._b(base + 2))

    def set_stage_color(self, stage: int, rgb: Tuple[int, int, int]) -> None:
        if not (0 <= stage < 6):
            raise ValueError(f"DPI stage out of range (0..5): {stage}")
        base = 0x20 + stage * 3
        r, g, b = rgb
        self._s(base, 255 - max(0, min(255, int(r))))
        self._s(base + 1, 255 - max(0, min(255, int(g))))
        self._s(base + 2, 255 - max(0, min(255, int(b))))

    # ---- LED Mode & Speed (0x1c + 0x33 bit 7) ----
    def get_led_mode(self) -> Tuple[int, int]:
        b1c = self._b(0x1C)
        speed = b1c & 0x07
        if speed == 7:
            return (13, 2)  # Off
        if b1c & 0x08:
            return (12, min(5, speed))  # Click Response
        mode = ((b1c >> 4) & 0x07) | (8 if (self._b(0x33) & 0x80) else 0)
        return (mode, min(5, speed))

    def set_led_mode(self, mode_id: int, speed: Optional[int] = None) -> None:
        if not (0 <= mode_id <= 13):
            raise ValueError(f"Mouse LED mode out of range (0..13): {mode_id}")
        cur_mode, cur_speed = self.get_led_mode()
        spd = cur_speed if speed is None else max(0, min(5, int(speed)))
        b1c = self._b(0x1C)
        b33 = self._b(0x33)

        if mode_id == 13:
            self._s(0x1C, 0x80 | (b1c & 0x70) | 7)
        elif mode_id == 12:
            self._s(0x1C, 0x80 | 0x10 | 0x08 | (spd & 0x07))
            self._s(0x33, b33 & 0x7F)
        else:
            self._s(0x1C, 0x80 | ((mode_id & 0x07) << 4) | (spd & 0x07))
            self._s(0x33, (b33 & 0x7F) | (0x80 if (mode_id & 0x08) else 0x00))

    # ---- Rapid fire interval ----
    def get_fire_ms(self) -> int:
        return (self._b(0x1A) | (self._b(0x1B) << 8)) * 8

    def blocks(self) -> Dict[int, bytes]:
        return {CFG_START + off: bytes(self.r[off : off + 8]) for off in range(0, CFG_LEN, 8)}

    def diff_blocks(self, original: "InstantMouseConfig") -> Dict[int, bytes]:
        old_blocks = original.blocks()
        new_blocks = self.blocks()
        return {
            addr: data
            for addr, data in new_blocks.items()
            if data != old_blocks[addr]
        }

    def validate(self, allow_remove_left: bool = False) -> None:
        if not allow_remove_left:
            has_left = any(self.get_button(slot) == LEFT_CLICK_CODE for slot, _ in MOUSE_BUTTON_SLOTS)
            if not has_left:
                raise MouseProtocolError(
                    "Safety guard: refusing to save button map without Left Click (0x21) assigned."
                )
        mask = self.get_dpi_enabled_mask()
        if mask == 0:
            raise MouseProtocolError("At least one DPI stage must be enabled")
        active = self.get_active_dpi_stage()
        if not ((mask >> active) & 1):
            raise MouseProtocolError(f"Active DPI stage {active + 1} is disabled in mask 0x{mask:02x}")


class InstantMouseDevice:
    """Context-managed hidraw interface to Instant A825 gaming mice (30fa:1440)."""

    def __init__(self, device_path: Optional[str] = None) -> None:
        self.device_info = find_instant_mouse_hidraw() if device_path is None else {"path": device_path}
        if not self.device_info:
            raise MouseProtocolError(
                "Instant A825 gaming mouse (30fa:1440) not found on /sys/class/hidraw."
            )
        self.path: str = self.device_info["path"]
        self._fd: Optional[int] = None

    def open(self) -> "InstantMouseDevice":
        if self._fd is not None:
            return self
        try:
            self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as exc:
            raise MouseProtocolError(f"Permission denied opening {self.path}: {exc}") from exc
        except OSError as exc:
            raise MouseProtocolError(f"Failed to open {self.path}: {exc}") from exc
        return self

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def __enter__(self) -> "InstantMouseDevice":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _ensure_open(self) -> int:
        if self._fd is None:
            self.open()
        assert self._fd is not None
        return self._fd

    def _set_feature(self, pkt: List[int] | bytes | bytearray) -> None:
        if len(pkt) != REPORT_LEN or pkt[0] != REPORT_ID:
            raise MouseProtocolError(f"Invalid 8-byte feature packet: {bytes(pkt).hex()}")
        fd = self._ensure_open()
        try:
            fcntl.ioctl(fd, _ioc(0x06, REPORT_LEN), bytearray(pkt))
        except OSError as exc:
            raise MouseProtocolError(f"Mouse HID SET_FEATURE failed: {exc}") from exc

    def _get_feature(self) -> bytes:
        fd = self._ensure_open()
        buf = bytearray([REPORT_ID] + [0] * (REPORT_LEN - 1))
        try:
            fcntl.ioctl(fd, _ioc(0x07, REPORT_LEN), buf)
        except OSError as exc:
            raise MouseProtocolError(f"Mouse HID GET_FEATURE failed: {exc}") from exc
        return bytes(buf)

    @staticmethod
    def _flash_pkt(sub: int, idx: int = 0, addr: int = 0, data: int = 0, last: int = 0) -> List[int]:
        if sub not in (0x00, 0x03, 0x05, 0x09, 0x10):
            raise MouseProtocolError(f"Unsupported 0x18 sub-op: 0x{sub:02x}")
        return [REPORT_ID, 0x18, sub, idx & 0xFF, addr & 0xFF, (addr >> 8) & 0xFF, data & 0xFF, last & 0xFF]

    def read_block(self, addr: int, n: int = 8) -> bytes:
        lo, hi = addr & 0xFF, (addr >> 8) & 0xFF
        for i in range(n):
            self._set_feature(self._flash_pkt(0x03, i, addr, 0, n - 1))
            time.sleep(0.002)
        time.sleep(0.002)
        self._set_feature(self._flash_pkt(0x00, 0, addr))
        out = bytearray()
        for i in range(n):
            self._set_feature(self._flash_pkt(0x05, i, addr, 0, n - 1))
            time.sleep(0.002)
            out.append(self._get_feature()[1])
        time.sleep(0.002)
        self._set_feature(self._flash_pkt(0x00))
        return bytes(out)

    def read_range(self, start: int, length: int) -> bytes:
        out = bytearray()
        for addr in range(start, start + length, 8):
            out += self.read_block(addr, min(8, start + length - addr))
        return bytes(out)

    def write_block(self, addr: int, data: bytes) -> None:
        if len(data) != 8 or addr % 8 != 0:
            raise MouseProtocolError(f"Flash writes must be 8-byte aligned (addr=0x{addr:02x}, len={len(data)})")
        if addr < 0x08:
            raise MouseProtocolError("HARD GUARD: Flash header 0x00..0x07 (USB VID/PID) must NEVER be written!")
        if addr not in WRITABLE_BLOCKS:
            raise MouseProtocolError(f"HARD GUARD: Block 0x{addr:02x} is not in WRITABLE_BLOCKS")

        for i, byte_val in enumerate(data):
            self._set_feature(self._flash_pkt(0x03, i, addr, byte_val, 7))
        time.sleep(0.004)
        self._set_feature(self._flash_pkt(0x09, 0, addr, 0, 7))
        time.sleep(0.002)
        self._set_feature(self._flash_pkt(0x00, 0, addr))
        time.sleep(0.002)

        verify = self.read_block(addr, 8)
        if verify != bytes(data):
            raise MouseProtocolError(
                f"Flash write verification failed at 0x{addr:02x}: wrote {bytes(data).hex()}, read {verify.hex()}"
            )

    def apply(self) -> None:
        self._set_feature(self._flash_pkt(0x10))
        time.sleep(0.005)
        self._set_feature(self._flash_pkt(0x00))

    def read_header_and_config(self) -> Tuple[bytes, InstantMouseConfig]:
        raw = self.read_range(0x00, 0x40)
        hdr, cfg_bytes = raw[:8], raw[8:0x40]
        if hdr[0] != 0x5A or hdr[2] != 0xA5:
            raise MouseProtocolError(f"Unexpected mouse flash header: {hdr.hex()} (expected 5a ?? a5 ...)")
        return hdr, InstantMouseConfig(cfg_bytes)

    def ensure_initial_backup(self, path: Path = MOUSE_INITIAL_BACKUP_PATH) -> Optional[Path]:
        if path.exists():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.export_backup()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def save_config(
        self,
        new_cfg: InstantMouseConfig,
        original_cfg: Optional[InstantMouseConfig] = None,
        allow_remove_left: bool = False,
    ) -> List[int]:
        new_cfg.validate(allow_remove_left=allow_remove_left)
        self.ensure_initial_backup()
        if original_cfg is None:
            _, original_cfg = self.read_header_and_config()

        changed = new_cfg.diff_blocks(original_cfg)
        if not changed:
            return []

        for addr in sorted(changed):
            self.write_block(addr, changed[addr])
        self.apply()
        return sorted(changed)

    def set_live_lighting(
        self,
        mode_id: int,
        speed: int = 2,
        brightness: int = 4,
        rgb: Optional[Tuple[int, int, int]] = None,
    ) -> None:
        """Apply volatile RAM lighting immediately via 0x13/0x14 (zero flash wear)."""
        if not (0 <= mode_id <= 13):
            raise MouseProtocolError(f"LED mode out of range (0..13): {mode_id}")
        spd = max(0, min(5, int(speed)))
        bright = max(0, min(4, int(brightness)))
        is_single = mode_id in (2, 4, 13)
        pkt = [
            REPORT_ID,
            0x13,
            0x80 if is_single else 0xFF,
            0x80 | ((mode_id & 0x07) << 4) | (spd & 0x07),
            0x1B,
            bright & 0x07,
            0x80 if mode_id >= 8 else 0x00,
            0x02,
        ]
        if rgb is not None:
            r4 = max(0, min(15, round(rgb[0] / 17.0)))
            g4 = max(0, min(15, round(rgb[1] / 17.0)))
            b4 = max(0, min(15, round(rgb[2] / 17.0)))
            for zone in range(8):
                self._set_feature([REPORT_ID, 0x14, (zone << 5) | g4, (r4 << 4) | b4, 0, 0, 0, 0])
        self._set_feature(pkt)
        if rgb is not None:
            for zone in range(8):
                self._set_feature([REPORT_ID, 0x14, (zone << 5) | g4, (r4 << 4) | b4, 0, 0, 0, 0])
        time.sleep(0.005)
        self.apply()

    def read_state(self) -> Dict[str, Any]:
        hdr, cfg = self.read_header_and_config()
        mode_id, speed = cfg.get_led_mode()
        mode_spec = MOUSE_LED_BY_ID.get(mode_id)
        active = cfg.get_active_dpi_stage()
        mask = cfg.get_dpi_enabled_mask()
        stages = []
        for i in range(6):
            rgb = cfg.get_stage_color(i)
            stages.append(
                {
                    "stage": i + 1,
                    "dpi": cfg.get_dpi(i),
                    "enabled": bool((mask >> i) & 1),
                    "active": i == active,
                    "rgb": rgb,
                    "hex": format_hex_color(rgb),
                }
            )
        buttons = []
        for slot, label in MOUSE_BUTTON_SLOTS:
            code = cfg.get_button(slot)
            buttons.append(
                {
                    "slot": slot,
                    "label": label,
                    "code": code,
                    "function": FUNC_NAME_BY_CODE.get(code, f"Raw(0x{code:02x})"),
                }
            )
        return {
            "header_hex": hdr.hex(),
            "config_hex": bytes(cfg.r).hex(),
            "led_mode_id": mode_id,
            "led_mode_slug": mode_spec.slug if mode_spec else f"mode-{mode_id}",
            "led_mode_name": mode_spec.name if mode_spec else f"Mode {mode_id}",
            "led_speed": speed,
            "active_stage": active + 1,
            "active_dpi": cfg.get_dpi(active),
            "active_color": cfg.get_stage_color(active),
            "active_color_hex": format_hex_color(cfg.get_stage_color(active)),
            "stages": stages,
            "buttons": buttons,
            "fire_ms": cfg.get_fire_ms(),
        }

    def set_led(
        self,
        mode_id: int,
        speed: Optional[int] = None,
        rgb: Optional[Tuple[int, int, int]] = None,
        stage: Optional[int] = None,
    ) -> Dict[str, Any]:
        _, orig = self.read_header_and_config()
        cfg = orig.copy()
        cfg.set_led_mode(mode_id, speed=speed)
        if rgb is not None:
            target = cfg.get_active_dpi_stage() if stage is None else stage
            cfg.set_stage_color(target, rgb)
        self.save_config(cfg, original_cfg=orig)
        return self.read_state()

    def export_backup(self) -> Dict[str, Any]:
        hdr, cfg = self.read_header_and_config()
        return {
            "format": "instant-a825-backup-v1",
            "vid_pid": self.device_info.get("vid_pid", "30fa:1440"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "header_hex": hdr.hex(),
            "config_0x08_0x3f_hex": bytes(cfg.r).hex(),
        }

    def import_backup(self, data: Dict[str, Any], allow_remove_left: bool = False) -> List[int]:
        if data.get("format") != "instant-a825-backup-v1":
            raise MouseProtocolError("Unsupported mouse backup format")
        cfg_bytes = bytes.fromhex(data["config_0x08_0x3f_hex"])
        new_cfg = InstantMouseConfig(cfg_bytes)
        _, orig = self.read_header_and_config()
        return self.save_config(new_cfg, original_cfg=orig, allow_remove_left=allow_remove_left)
