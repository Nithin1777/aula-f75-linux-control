"""Linux hidraw HID feature-report transport and configuration manager for AULA F75."""

from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .layout import EFFECTS_BY_ID, format_hex_color

VENDOR_ID = "0000258A"
PRODUCT_ID = "0000010C"
REPORT_ID = 0x06
REPORT_SIZE = 520

CMD_WRITE_KEYMAP = 0x03
CMD_READ_KEYMAP = 0x83
CMD_WRITE_CONFIG = 0x04
CMD_READ_CONFIG = 0x84
CMD_WRITE_PERKEY = 0x06
CMD_READ_PERKEY = 0x86
CMD_READ_STATUS = 0x87
CMD_WRITE_PALETTE = 0x0A
CMD_READ_PALETTE = 0x8A

CONFIG_LEN = 128
PALETTE_LEN = 512
KEYMAP_LEN = 512
LEGACY_KEYMAP_LEN = 504
PERKEY_LEN = 378
CUSTOM_EFFECT_ID = 21
MAGIC_TRAILER = b"\x5a\xa5"

READ_DELAY_SEC = 0.025
WRITE_SETTLE_SEC = 0.40

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "aula-f75-control"
INITIAL_BACKUP_PATH = DEFAULT_DATA_DIR / "initial_backup.json"


class AulaF75Error(RuntimeError):
    """Raised when communicating with or validating the AULA F75 fails."""


def _hidiocsfeature(length: int) -> int:
    return (3 << 30) | (length << 16) | (0x48 << 8) | 0x06


def _hidiocgfeature(length: int) -> int:
    return (3 << 30) | (length << 16) | (0x48 << 8) | 0x07


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


def find_aula_f75_hidraw() -> Optional[Dict[str, Any]]:
    """Locate the wired AULA F75 vendor configuration hidraw device node."""
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
        if VENDOR_ID not in hid_id or PRODUCT_ID not in hid_id:
            continue

        dev_path = f"/dev/{entry.name}"
        rdesc = _read_bytes(entry / "device" / "report_descriptor")
        has_vendor_feature = (b"\x85\x06" in rdesc) and (b"\x96\x07\x02\xb1\x02" in rdesc)
        phys = props.get("HID_PHYS", "")
        is_input1 = phys.endswith("/input1")

        candidates.append(
            {
                "path": dev_path,
                "hid_name": props.get("HID_NAME", "AULA F75"),
                "phys": phys,
                "hid_id": hid_id,
                "has_vendor_feature": has_vendor_feature,
                "is_input1": is_input1,
                "readable": os.access(dev_path, os.R_OK),
                "writable": os.access(dev_path, os.W_OK),
            }
        )

    if not candidates:
        return None

    candidates.sort(key=lambda c: (not c["has_vendor_feature"], not c["is_input1"], c["path"]))
    return candidates[0]


def normalize_keymap_bytes(keymap: bytes | bytearray) -> bytearray:
    """Normalize a 504B legacy keymap or 512B signed keymap to 512B ending with 5a a5 at [510:512]."""
    if len(keymap) == LEGACY_KEYMAP_LEN:
        buf = bytearray(KEYMAP_LEN)
        buf[:LEGACY_KEYMAP_LEN] = keymap
        buf[510:512] = MAGIC_TRAILER
        return buf
    if len(keymap) == KEYMAP_LEN:
        return bytearray(keymap)
    raise AulaF75Error(f"Keymap must be {KEYMAP_LEN} bytes (or legacy {LEGACY_KEYMAP_LEN}), got {len(keymap)}")


class AulaF75Device:
    """Context-managed HID raw interface to an AULA F75 keyboard."""

    def __init__(self, device_path: Optional[str] = None) -> None:
        self.device_info = find_aula_f75_hidraw() if device_path is None else {"path": device_path}
        if not self.device_info:
            raise AulaF75Error(
                "AULA F75 (USB 258a:010c) not found on /sys/class/hidraw. "
                "Make sure the keyboard is connected via USB cable (wired mode)."
            )
        self.path: str = self.device_info["path"]
        self._fd: Optional[int] = None

    def open(self) -> "AulaF75Device":
        if self._fd is not None:
            return self
        try:
            self._fd = os.open(self.path, os.O_RDWR)
        except PermissionError as exc:
            raise AulaF75Error(
                f"Permission denied opening {self.path}. Add a udev rule for 258a:010c and replug."
            ) from exc
        except OSError as exc:
            raise AulaF75Error(f"Failed to open {self.path}: {exc}") from exc
        return self

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def __enter__(self) -> "AulaF75Device":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _ensure_open(self) -> int:
        if self._fd is None:
            self.open()
        assert self._fd is not None
        return self._fd

    def _build_packet(self, cmd: int, sub: int, length: int, payload: bytes = b"") -> bytearray:
        if len(payload) > 512:
            raise AulaF75Error(f"Payload too large ({len(payload)} > 512)")
        pkt = bytearray(REPORT_SIZE)
        pkt[0] = REPORT_ID
        pkt[1] = cmd & 0xFF
        pkt[2] = sub & 0xFF
        pkt[3] = 0x00
        pkt[4] = 0x01
        pkt[5] = 0x00
        pkt[6] = length & 0xFF
        pkt[7] = (length >> 8) & 0xFF
        if payload:
            pkt[8 : 8 + len(payload)] = payload
        return pkt

    def read_block(
        self,
        cmd: int,
        sub: int = 0,
        length: int = 512,
        magic_offset: Optional[int] = None,
    ) -> bytes:
        fd = self._ensure_open()
        req = self._build_packet(cmd, sub, length)
        expected_hdr = bytes(req[:8])

        last_err: Optional[str] = None
        for attempt in range(3):
            resp = bytearray(REPORT_SIZE)
            resp[0] = REPORT_ID
            try:
                fcntl.ioctl(fd, _hidiocsfeature(REPORT_SIZE), bytearray(req))
                time.sleep(READ_DELAY_SEC)
                fcntl.ioctl(fd, _hidiocgfeature(REPORT_SIZE), resp)
            except OSError as exc:
                last_err = f"HID read failed (cmd=0x{cmd:02x}, sub={sub}): {exc}"
                time.sleep(0.1)
                continue

            if bytes(resp[:8]) != expected_hdr:
                last_err = f"Unexpected HID read header: {bytes(resp[:8]).hex()} (expected {expected_hdr.hex()})"
                time.sleep(0.1)
                continue

            payload = bytes(resp[8 : 8 + length])
            if magic_offset is not None and payload[magic_offset : magic_offset + 2] != MAGIC_TRAILER:
                last_err = (
                    f"Missing 5aa5 signature at offset {magic_offset} for cmd=0x{cmd:02x}: "
                    f"{payload[magic_offset : magic_offset + 2].hex()}"
                )
                time.sleep(0.1)
                continue

            return payload

        raise AulaF75Error(last_err or f"HID read failed after retries (cmd=0x{cmd:02x}, sub={sub})")

    def write_block(self, cmd: int, payload: bytes, sub: int = 0, length: Optional[int] = None) -> None:
        fd = self._ensure_open()
        if length is None:
            length = len(payload)
        pkt = self._build_packet(cmd, sub, length, payload)
        try:
            fcntl.ioctl(fd, _hidiocsfeature(REPORT_SIZE), pkt)
        except OSError as exc:
            raise AulaF75Error(f"HID write failed (cmd=0x{cmd:02x}, sub={sub}): {exc}") from exc
        time.sleep(WRITE_SETTLE_SEC)

    def read_config(self) -> bytearray:
        data = bytearray(self.read_block(CMD_READ_CONFIG, sub=0, length=CONFIG_LEN, magic_offset=126))
        if len(data) != CONFIG_LEN:
            raise AulaF75Error(f"Unexpected config block length: {len(data)}")
        return data

    def write_config(self, cfg: bytes | bytearray) -> None:
        if len(cfg) != CONFIG_LEN:
            raise AulaF75Error(f"Config block must be {CONFIG_LEN} bytes, got {len(cfg)}")
        if bytes(cfg[126:128]) != MAGIC_TRAILER:
            raise AulaF75Error("Refusing to write config without 5aa5 sentinel at [126:128]")
        raw = bytes(cfg)
        self.write_block(CMD_WRITE_CONFIG, raw, sub=0, length=CONFIG_LEN)
        verify = bytes(self.read_config())
        if verify != raw:
            raise AulaF75Error("Config write verification failed (keyboard read-back differs)")

    def read_palette(self) -> bytearray:
        data = bytearray(self.read_block(CMD_READ_PALETTE, sub=0, length=PALETTE_LEN, magic_offset=506))
        if len(data) != PALETTE_LEN:
            raise AulaF75Error(f"Unexpected palette block length: {len(data)}")
        return data

    def write_palette(self, palette: bytes | bytearray) -> None:
        if len(palette) != PALETTE_LEN:
            raise AulaF75Error(f"Palette block must be {PALETTE_LEN} bytes, got {len(palette)}")
        if bytes(palette[506:508]) != MAGIC_TRAILER:
            raise AulaF75Error("Refusing to write palette without 5aa5 sentinel at [506:508]")
        raw = bytes(palette)
        self.write_block(CMD_WRITE_PALETTE, raw, sub=0, length=PALETTE_LEN)
        verify = bytes(self.read_palette())
        if verify != raw:
            raise AulaF75Error("Palette write verification failed (keyboard read-back differs)")

    def read_per_key_rgb(self) -> Dict[int, Tuple[int, int, int]]:
        raw = self.read_block(CMD_READ_PERKEY, sub=0, length=PERKEY_LEN)
        return {i: (raw[i], raw[126 + i], raw[252 + i]) for i in range(126)}

    def write_per_key_rgb(self, slot_rgb: Dict[int, Tuple[int, int, int]]) -> None:
        buf = bytearray(PERKEY_LEN)
        for slot, rgb in slot_rgb.items():
            if not (0 <= slot < 126):
                raise AulaF75Error(f"Per-key slot out of range: {slot}")
            r, g, b = rgb
            buf[slot] = max(0, min(255, int(r)))
            buf[126 + slot] = max(0, min(255, int(g)))
            buf[252 + slot] = max(0, min(255, int(b)))
        raw = bytes(buf)
        self.write_block(CMD_WRITE_PERKEY, raw, sub=0, length=PERKEY_LEN)
        verify = self.read_block(CMD_READ_PERKEY, sub=0, length=PERKEY_LEN)
        if verify != raw:
            raise AulaF75Error("Per-key RGB write verification failed (keyboard read-back differs)")

    def read_keymap(self, layer: int = 0) -> bytearray:
        if layer not in (0, 1):
            raise AulaF75Error(f"Layer must be 0 (base) or 1 (fn), got {layer}")
        return bytearray(self.read_block(CMD_READ_KEYMAP, sub=layer, length=KEYMAP_LEN, magic_offset=510))

    def write_keymap(
        self,
        keymap: bytes | bytearray,
        layer: int = 0,
        allow_remove_fn: bool = False,
    ) -> None:
        if layer not in (0, 1):
            raise AulaF75Error(f"Layer must be 0 (base) or 1 (fn), got {layer}")
        buf = normalize_keymap_bytes(keymap)
        if bytes(buf[510:512]) != MAGIC_TRAILER:
            raise AulaF75Error("Refusing to write keymap without 5aa5 signature at [510:512]")
        if not any(buf[:LEGACY_KEYMAP_LEN]):
            raise AulaF75Error("Refusing to write an all-zero keymap")
        if layer == 0 and not allow_remove_fn:
            has_fn = any(buf[i : i + 4] == b"\x0d\x00\x00\x00" for i in range(0, LEGACY_KEYMAP_LEN, 4))
            if not has_fn:
                raise AulaF75Error(
                    "Safety guard: refusing to write base keymap without an Fn key (0d000000). "
                    "Use --force / allow_remove_fn=True if you really intend this."
                )
        raw = bytes(buf)
        self.write_block(CMD_WRITE_KEYMAP, raw, sub=layer, length=KEYMAP_LEN)
        verify = bytes(self.read_keymap(layer=layer))
        if verify != raw:
            raise AulaF75Error(f"Keymap layer {layer} write verification failed (keyboard read-back differs)")

    def read_status(self) -> Dict[str, Any]:
        raw = self.read_block(CMD_READ_STATUS, sub=0, length=CONFIG_LEN)
        battery = raw[0] if raw[0] <= 100 else None
        return {"battery": battery, "raw": raw}

    def get_lighting_state(self) -> Dict[str, Any]:
        cfg = self.read_config()
        palette = self.read_palette()
        effect_id = cfg[10]
        spec = EFFECTS_BY_ID.get(effect_id)

        if 1 <= effect_id <= 18:
            slot_off = 56 + effect_id * 2
            brightness = cfg[slot_off]
            packed = cfg[slot_off + 1]
            speed = (packed >> 4) & 0x0F
            color_index = packed & 0x0F
            pal_off = effect_id * 21
            colors = [
                (
                    palette[pal_off + i * 3],
                    palette[pal_off + i * 3 + 1],
                    palette[pal_off + i * 3 + 2],
                )
                for i in range(7)
            ]
        else:
            brightness = cfg[14]
            speed = 0
            color_index = 7
            colors = [
                (
                    palette[21 + i * 3],
                    palette[21 + i * 3 + 1],
                    palette[21 + i * 3 + 2],
                )
                for i in range(7)
            ]

        is_rainbow = color_index >= 7
        active_rgb = None if is_rainbow else colors[color_index]
        return {
            "effect_id": effect_id,
            "effect_slug": spec.slug if spec else f"effect-{effect_id}",
            "effect_name": spec.name if spec else f"Effect {effect_id}",
            "brightness": brightness,
            "speed": speed,
            "color_index": color_index,
            "is_rainbow": is_rainbow,
            "active_rgb": active_rgb,
            "active_hex": format_hex_color(active_rgb) if active_rgb else "rainbow",
            "palette": colors,
            "raw_config": bytes(cfg),
        }

    def ensure_initial_backup(self, path: Path = INITIAL_BACKUP_PATH) -> Optional[Path]:
        if path.exists():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.export_backup()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def set_effect(
        self,
        effect_id: int,
        brightness: Optional[int] = None,
        speed: Optional[int] = None,
        color_index: Optional[int] = None,
        custom_rgb: Optional[Tuple[int, int, int]] = None,
    ) -> Dict[str, Any]:
        if effect_id == 32:
            effect_id = CUSTOM_EFFECT_ID
        if not (0 <= effect_id <= 255):
            raise AulaF75Error(f"effect_id out of range: {effect_id}")
        self.ensure_initial_backup()

        if custom_rgb is not None and 1 <= effect_id <= 18:
            if color_index is None or color_index >= 7:
                color_index = 0
            palette = self.read_palette()
            off = effect_id * 21 + color_index * 3
            r, g, b = custom_rgb
            palette[off] = max(0, min(255, int(r)))
            palette[off + 1] = max(0, min(255, int(g)))
            palette[off + 2] = max(0, min(255, int(b)))
            self.write_palette(palette)

        cfg = self.read_config()
        cfg[9] = 1 if effect_id == CUSTOM_EFFECT_ID else 0
        cfg[10] = effect_id

        if effect_id == CUSTOM_EFFECT_ID:
            cfg[11] = 0x20
        elif 1 <= effect_id <= 18:
            slot_off = 56 + effect_id * 2
            cur_bright = cfg[slot_off]
            cur_packed = cfg[slot_off + 1]
            cur_speed = (cur_packed >> 4) & 0x0F
            cur_color = cur_packed & 0x0F

            new_bright = cur_bright if brightness is None else max(0, min(9, int(brightness)))
            if effect_id == 1:
                new_speed = cur_speed
            else:
                new_speed = cur_speed if speed is None else max(0, min(4, int(speed)))

            spec = EFFECTS_BY_ID.get(effect_id)
            if spec and not spec.supports_color:
                new_color = cur_color
            else:
                new_color = cur_color if color_index is None else max(0, min(7, int(color_index)))

            cfg[slot_off] = new_bright
            cfg[slot_off + 1] = ((new_speed & 0x0F) << 4) | (new_color & 0x0F)

        self.write_config(cfg)
        return self.get_lighting_state()

    def set_per_key_colors(
        self,
        slot_rgb: Dict[int, Tuple[int, int, int]],
        activate_custom: bool = True,
        brightness: Optional[int] = None,
    ) -> None:
        self.ensure_initial_backup()
        self.write_per_key_rgb(slot_rgb)
        if activate_custom or brightness is not None:
            cfg = self.read_config()
            if activate_custom:
                cfg[9] = 1
                cfg[10] = CUSTOM_EFFECT_ID
                cfg[11] = 0x20
            if brightness is not None:
                cfg[14] = max(0, min(9, int(brightness)))
            self.write_config(cfg)

    def export_backup(self) -> Dict[str, Any]:
        cfg = self.read_config()
        palette = self.read_palette()
        per_key = self.read_block(CMD_READ_PERKEY, sub=0, length=PERKEY_LEN)
        base_km = self.read_keymap(0)
        fn_km = self.read_keymap(1)
        return {
            "format": "aula-f75-backup-v1",
            "vid_pid": "258a:010c",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "config_hex": bytes(cfg).hex(),
            "palette_hex": bytes(palette).hex(),
            "per_key_hex": bytes(per_key).hex(),
            "keymap_base_hex": bytes(base_km).hex(),
            "keymap_fn_hex": bytes(fn_km).hex(),
        }

    def import_backup(
        self,
        data: Dict[str, Any],
        restore_keymaps: bool = True,
        allow_remove_fn: bool = False,
    ) -> None:
        if data.get("format") != "aula-f75-backup-v1":
            raise AulaF75Error("Unsupported backup format")
        cfg = bytes.fromhex(data["config_hex"])
        palette = bytes.fromhex(data["palette_hex"])
        per_key = bytes.fromhex(data["per_key_hex"])
        if len(cfg) != CONFIG_LEN or cfg[126:128] != MAGIC_TRAILER:
            raise AulaF75Error("Backup config_hex is invalid")
        if len(palette) != PALETTE_LEN or palette[506:508] != MAGIC_TRAILER:
            raise AulaF75Error("Backup palette_hex is invalid")
        if len(per_key) != PERKEY_LEN:
            raise AulaF75Error("Backup per_key_hex is invalid")

        self.ensure_initial_backup()
        self.write_palette(palette)
        self.write_block(CMD_WRITE_PERKEY, per_key, sub=0, length=PERKEY_LEN)
        verify_pk = self.read_block(CMD_READ_PERKEY, sub=0, length=PERKEY_LEN)
        if verify_pk != per_key:
            raise AulaF75Error("Per-key RGB restore verification failed")
        self.write_config(cfg)

        if restore_keymaps:
            if "keymap_base_hex" in data:
                base_km = bytes.fromhex(data["keymap_base_hex"])
                self.write_keymap(base_km, layer=0, allow_remove_fn=allow_remove_fn)
            if "keymap_fn_hex" in data:
                fn_km = bytes.fromhex(data["keymap_fn_hex"])
                self.write_keymap(fn_km, layer=1, allow_remove_fn=True)
