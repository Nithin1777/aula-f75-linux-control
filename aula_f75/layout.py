"""Physical layout, lighting effects, per-key presets, and HID keycode tables for AULA F75."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class EffectSpec:
    effect_id: int
    slug: str
    name: str
    supports_color: bool
    supports_speed: bool


EFFECTS_LIST: List[EffectSpec] = [
    EffectSpec(0, "off", "Off", False, False),
    EffectSpec(1, "static", "Static (Always On)", True, False),
    EffectSpec(2, "breathing", "Breathing", True, True),
    EffectSpec(3, "spectrum", "Spectrum Cycle", False, True),
    EffectSpec(4, "ripple-row", "Ripple Row", True, True),
    EffectSpec(5, "raindrops", "Raindrops", True, True),
    EffectSpec(6, "wave", "Wave", True, True),
    EffectSpec(7, "ripple", "Reactive Ripple", True, True),
    EffectSpec(8, "twinkle", "Twinkle / Stars", True, True),
    EffectSpec(9, "sine-wave", "Sine Wave", True, True),
    EffectSpec(10, "snake", "Snake / Marquee", True, True),
    EffectSpec(11, "stream", "Stream / Flowing", True, True),
    EffectSpec(12, "reactive", "Reactive Key", True, True),
    EffectSpec(13, "center-wave", "Center Wave", True, True),
    EffectSpec(14, "neon-flow", "Neon Flow", True, True),
    EffectSpec(15, "rainbow-wheel", "Rainbow Wheel", False, True),
    EffectSpec(16, "waterfall", "Waterfall", True, True),
    EffectSpec(17, "center-flash", "Center Flash", True, True),
    EffectSpec(18, "aurora", "Effect 18", True, True),
    EffectSpec(21, "custom", "Custom Per-Key RGB", False, False),
]

EFFECTS_BY_ID: Dict[int, EffectSpec] = {e.effect_id: e for e in EFFECTS_LIST}
EFFECTS_BY_SLUG: Dict[str, EffectSpec] = {e.slug: e for e in EFFECTS_LIST}


def resolve_effect(value: str | int) -> EffectSpec:
    """Resolve an effect ID or slug (case-insensitive) to an EffectSpec."""
    if isinstance(value, int):
        if value == 32:
            return EFFECTS_BY_ID[21]
        if value in EFFECTS_BY_ID:
            return EFFECTS_BY_ID[value]
        return EffectSpec(value, f"effect-{value}", f"Effect {value}", True, True)

    s = str(value).strip().lower()
    if s.isdigit():
        num = int(s)
        return resolve_effect(num)
    if s.startswith("0x"):
        num = int(s, 16)
        return resolve_effect(num)
    if s in EFFECTS_BY_SLUG:
        return EFFECTS_BY_SLUG[s]
    # Fuzzy match by name/slug substring
    for eff in EFFECTS_LIST:
        if s == eff.name.lower() or s.replace("_", "-") == eff.slug:
            return eff
    raise ValueError(f"Unknown lighting effect: {value!r}")


@dataclass(frozen=True)
class KeySpec:
    slot: int
    label: str
    row: int
    x: float
    width: float = 1.0
    is_knob: bool = False


# Exact 80-key + knob ANSI AULA F75 matrix layout matching 0x83 and 0x86 slots.
KEYS: List[KeySpec] = [
    # Row 0 (Function row + Esc + Knob)
    KeySpec(0, "Esc", 0, 0.0, 1.0),
    KeySpec(12, "F1", 0, 1.5, 1.0),
    KeySpec(18, "F2", 0, 2.5, 1.0),
    KeySpec(24, "F3", 0, 3.5, 1.0),
    KeySpec(30, "F4", 0, 4.5, 1.0),
    KeySpec(36, "F5", 0, 5.75, 1.0),
    KeySpec(42, "F6", 0, 6.75, 1.0),
    KeySpec(48, "F7", 0, 7.75, 1.0),
    KeySpec(54, "F8", 0, 8.75, 1.0),
    KeySpec(60, "F9", 0, 10.0, 1.0),
    KeySpec(66, "F10", 0, 11.0, 1.0),
    KeySpec(72, "F11", 0, 12.0, 1.0),
    KeySpec(78, "F12", 0, 13.0, 1.0),
    KeySpec(84, "Knob", 0, 14.5, 1.0, is_knob=True),
    # Row 1 (Number row)
    KeySpec(1, "`", 1, 0.0, 1.0),
    KeySpec(7, "1", 1, 1.0, 1.0),
    KeySpec(13, "2", 1, 2.0, 1.0),
    KeySpec(19, "3", 1, 3.0, 1.0),
    KeySpec(25, "4", 1, 4.0, 1.0),
    KeySpec(31, "5", 1, 5.0, 1.0),
    KeySpec(37, "6", 1, 6.0, 1.0),
    KeySpec(43, "7", 1, 7.0, 1.0),
    KeySpec(49, "8", 1, 8.0, 1.0),
    KeySpec(55, "9", 1, 9.0, 1.0),
    KeySpec(61, "0", 1, 10.0, 1.0),
    KeySpec(67, "-", 1, 11.0, 1.0),
    KeySpec(73, "=", 1, 12.0, 1.0),
    KeySpec(79, "Bksp", 1, 13.0, 2.0),
    KeySpec(85, "Del", 1, 15.25, 1.0),
    # Row 2 (QWERTY)
    KeySpec(2, "Tab", 2, 0.0, 1.5),
    KeySpec(8, "Q", 2, 1.5, 1.0),
    KeySpec(14, "W", 2, 2.5, 1.0),
    KeySpec(20, "E", 2, 3.5, 1.0),
    KeySpec(26, "R", 2, 4.5, 1.0),
    KeySpec(32, "T", 2, 5.5, 1.0),
    KeySpec(38, "Y", 2, 6.5, 1.0),
    KeySpec(44, "U", 2, 7.5, 1.0),
    KeySpec(50, "I", 2, 8.5, 1.0),
    KeySpec(56, "O", 2, 9.5, 1.0),
    KeySpec(62, "P", 2, 10.5, 1.0),
    KeySpec(68, "[", 2, 11.5, 1.0),
    KeySpec(74, "]", 2, 12.5, 1.0),
    KeySpec(80, "\\", 2, 13.5, 1.5),
    KeySpec(86, "PgUp", 2, 15.25, 1.0),
    # Row 3 (Home row)
    KeySpec(3, "Caps", 3, 0.0, 1.75),
    KeySpec(9, "A", 3, 1.75, 1.0),
    KeySpec(15, "S", 3, 2.75, 1.0),
    KeySpec(21, "D", 3, 3.75, 1.0),
    KeySpec(27, "F", 3, 4.75, 1.0),
    KeySpec(33, "G", 3, 5.75, 1.0),
    KeySpec(39, "H", 3, 6.75, 1.0),
    KeySpec(45, "J", 3, 7.75, 1.0),
    KeySpec(51, "K", 3, 8.75, 1.0),
    KeySpec(57, "L", 3, 9.75, 1.0),
    KeySpec(63, ";", 3, 10.75, 1.0),
    KeySpec(69, "'", 3, 11.75, 1.0),
    KeySpec(81, "Enter", 3, 12.75, 2.25),
    KeySpec(87, "PgDn", 3, 15.25, 1.0),
    # Row 4 (Bottom alpha + Up + End)
    KeySpec(4, "LShift", 4, 0.0, 2.25),
    KeySpec(10, "Z", 4, 2.25, 1.0),
    KeySpec(16, "X", 4, 3.25, 1.0),
    KeySpec(22, "C", 4, 4.25, 1.0),
    KeySpec(28, "V", 4, 5.25, 1.0),
    KeySpec(34, "B", 4, 6.25, 1.0),
    KeySpec(40, "N", 4, 7.25, 1.0),
    KeySpec(46, "M", 4, 8.25, 1.0),
    KeySpec(52, ",", 4, 9.25, 1.0),
    KeySpec(58, ".", 4, 10.25, 1.0),
    KeySpec(64, "/", 4, 11.25, 1.0),
    KeySpec(70, "RShift", 4, 12.25, 1.75),
    KeySpec(82, "Up", 4, 14.125, 1.0),
    KeySpec(88, "End", 4, 15.25, 1.0),
    # Row 5 (Modifiers + Space + Arrows)
    KeySpec(5, "LCtrl", 5, 0.0, 1.25),
    KeySpec(11, "LWin", 5, 1.25, 1.25),
    KeySpec(17, "LAlt", 5, 2.5, 1.25),
    KeySpec(35, "Space", 5, 3.75, 6.25),
    KeySpec(53, "Fn", 5, 10.0, 1.0),
    KeySpec(59, "RCtrl", 5, 11.0, 1.0),
    KeySpec(77, "Left", 5, 13.125, 1.0),
    KeySpec(83, "Down", 5, 14.125, 1.0),
    KeySpec(89, "Right", 5, 15.25, 1.0),
]

KEYS_BY_SLOT: Dict[int, KeySpec] = {k.slot: k for k in KEYS}

KEY_ALIASES: Dict[str, int] = {}
for _k in KEYS:
    KEY_ALIASES[_k.label.lower()] = _k.slot
KEY_ALIASES.update(
    {
        "escape": 0,
        "grave": 1,
        "tilde": 1,
        "backspace": 79,
        "delete": 85,
        "capslock": 3,
        "caps_lock": 3,
        "return": 81,
        "lctrl": 5,
        "lwin": 11,
        "super": 11,
        "lalt": 17,
        "spacebar": 35,
        "rctrl": 59,
        "lshift": 4,
        "rshift": 70,
        "pageup": 86,
        "pagedown": 87,
        "backslash": 80,
        "comma": 52,
        "period": 58,
        "slash": 64,
        "semicolon": 63,
        "quote": 69,
        "minus": 67,
        "equal": 73,
        "equals": 73,
    }
)


def resolve_key_slot(token: str | int) -> int:
    """Resolve a key name (e.g. 'W', 'Esc', 'Space') or numeric slot to a slot index (0..125)."""
    if isinstance(token, int):
        if 0 <= token < 126:
            return token
        raise ValueError(f"Slot out of range (0..125): {token}")
    s = str(token).strip()
    if s.isdigit():
        slot = int(s)
        if 0 <= slot < 126:
            return slot
        raise ValueError(f"Slot out of range (0..125): {slot}")
    low = s.lower()
    if low in KEY_ALIASES:
        return KEY_ALIASES[low]
    raise ValueError(f"Unknown key name or slot: {token!r}")


# Standard USB HID Usage IDs (Page 0x07)
HID_KEYCODES: Dict[int, str] = {
    0x04: "A",
    0x05: "B",
    0x06: "C",
    0x07: "D",
    0x08: "E",
    0x09: "F",
    0x0A: "G",
    0x0B: "H",
    0x0C: "I",
    0x0D: "J",
    0x0E: "K",
    0x0F: "L",
    0x10: "M",
    0x11: "N",
    0x12: "O",
    0x13: "P",
    0x14: "Q",
    0x15: "R",
    0x16: "S",
    0x17: "T",
    0x18: "U",
    0x19: "V",
    0x1A: "W",
    0x1B: "X",
    0x1C: "Y",
    0x1D: "Z",
    0x1E: "1",
    0x1F: "2",
    0x20: "3",
    0x21: "4",
    0x22: "5",
    0x23: "6",
    0x24: "7",
    0x25: "8",
    0x26: "9",
    0x27: "0",
    0x28: "Enter",
    0x29: "Esc",
    0x2A: "Backspace",
    0x2B: "Tab",
    0x2C: "Space",
    0x2D: "-",
    0x2E: "=",
    0x2F: "[",
    0x30: "]",
    0x31: "\\",
    0x32: "NonUS#",
    0x33: ";",
    0x34: "'",
    0x35: "`",
    0x36: ",",
    0x37: ".",
    0x38: "/",
    0x39: "CapsLock",
    0x3A: "F1",
    0x3B: "F2",
    0x3C: "F3",
    0x3D: "F4",
    0x3E: "F5",
    0x3F: "F6",
    0x40: "F7",
    0x41: "F8",
    0x42: "F9",
    0x43: "F10",
    0x44: "F11",
    0x45: "F12",
    0x46: "PrintScreen",
    0x47: "ScrollLock",
    0x48: "Pause",
    0x49: "Insert",
    0x4A: "Home",
    0x4B: "PageUp",
    0x4C: "Delete",
    0x4D: "End",
    0x4E: "PageDown",
    0x4F: "Right",
    0x50: "Left",
    0x51: "Down",
    0x52: "Up",
    0x53: "NumLock",
    0x54: "KP/",
    0x55: "KP*",
    0x56: "KP-",
    0x57: "KP+",
    0x58: "KPEnter",
    0x59: "KP1",
    0x5A: "KP2",
    0x5B: "KP3",
    0x5C: "KP4",
    0x5D: "KP5",
    0x5E: "KP6",
    0x5F: "KP7",
    0x60: "KP8",
    0x61: "KP9",
    0x62: "KP0",
    0x63: "KP.",
    0x64: "NonUS\\",
    0x65: "Menu",
    0x68: "F13",
    0x69: "F14",
    0x6A: "F15",
    0x6B: "F16",
    0x6C: "F17",
    0x6D: "F18",
    0x6E: "F19",
    0x6F: "F20",
    0x70: "F21",
    0x71: "F22",
    0x72: "F23",
    0x73: "F24",
    0x7F: "Mute",
    0x80: "VolUp",
    0x81: "VolDown",
}

MODIFIER_BITS: Dict[int, str] = {
    0x01: "LCtrl",
    0x02: "LShift",
    0x04: "LAlt",
    0x08: "LWin",
    0x10: "RCtrl",
    0x20: "RShift",
    0x40: "RAlt",
    0x80: "RWin",
}

NAME_TO_HID: Dict[str, int] = {v.lower(): k for k, v in HID_KEYCODES.items()}
NAME_TO_HID.update(
    {
        "escape": 0x29,
        "return": 0x28,
        "bksp": 0x2A,
        "del": 0x4C,
        "pgup": 0x4B,
        "pgdn": 0x4E,
        "caps": 0x39,
        "ins": 0x49,
        "prtsc": 0x46,
        "app": 0x65,
    }
)

NAME_TO_MOD: Dict[str, int] = {v.lower(): k for k, v in MODIFIER_BITS.items()}
NAME_TO_MOD.update(
    {
        "ctrl": 0x01,
        "shift": 0x02,
        "alt": 0x04,
        "win": 0x08,
        "super": 0x08,
        "lsuper": 0x08,
        "rsuper": 0x80,
    }
)


def decode_key_entry(entry: bytes) -> str:
    """Decode a 4-byte AULA F75 keymap entry [type, mod, hi, lo] into a readable string."""
    if len(entry) != 4:
        return entry.hex()
    ktype, mod, hi, lo = entry
    if ktype == 0 and mod == 0 and hi == 0 and lo == 0:
        return "Disabled"
    if ktype == 0x0D and mod == 0 and hi == 0 and lo == 0:
        return "Fn"
    if ktype == 0x00:
        parts: List[str] = []
        for bit, mname in MODIFIER_BITS.items():
            if mod & bit:
                parts.append(mname)
        if lo:
            kname = HID_KEYCODES.get(lo, f"HID_0x{lo:02X}")
            parts.append(kname)
        elif hi:
            parts.append(f"Ext_0x{hi:02X}")
        return "+".join(parts) if parts else "Disabled"
    if ktype == 0x07:
        return f"Special(0x{mod:02X},0x{hi:02X},0x{lo:02X})"
    if ktype == 0x08:
        return f"Media(0x{mod:02X},0x{hi:02X},0x{lo:02X})"
    return f"Raw({entry.hex()})"


def encode_key_entry(spec: str) -> bytes:
    """Encode a binding string (e.g. 'A', 'LCtrl+C', 'Fn', 'Disabled', 'raw:00000004') to 4 bytes."""
    s = spec.strip()
    low = s.lower()
    if low in ("disabled", "none", "off"):
        return b"\x00\x00\x00\x00"
    if low == "fn":
        return b"\x0d\x00\x00\x00"
    if low.startswith("raw:"):
        raw_hex = low[4:].replace(" ", "")
        data = bytes.fromhex(raw_hex)
        if len(data) != 4:
            raise ValueError("raw: binding must be exactly 4 bytes (8 hex chars)")
        return data

    parts = [p.strip() for p in s.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Empty key binding: {spec!r}")

    mod_mask = 0
    key_code = 0
    for idx, part in enumerate(parts):
        plow = part.lower()
        if plow in NAME_TO_MOD and (len(parts) == 1 or idx < len(parts) - 1):
            mod_mask |= NAME_TO_MOD[plow]
        elif plow in NAME_TO_HID:
            if key_code != 0:
                raise ValueError(f"Multiple non-modifier keys in binding: {spec!r}")
            key_code = NAME_TO_HID[plow]
        elif plow in NAME_TO_MOD:
            mod_mask |= NAME_TO_MOD[plow]
        elif plow.startswith("0x") or plow.startswith("hid_0x"):
            hex_part = plow.replace("hid_", "")
            val = int(hex_part, 16)
            if not (0 <= val <= 0xFF):
                raise ValueError(f"HID code out of range: {part!r}")
            key_code = val
        else:
            raise ValueError(f"Unknown key token {part!r} in binding {spec!r}")

    return bytes([0x00, mod_mask, 0x00, key_code])


def parse_hex_color(value: str) -> Tuple[int, int, int]:
    """Parse '#RRGGBB' or 'RRGGBB' into (r, g, b)."""
    s = value.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"Expected #RRGGBB hex color, got {value!r}")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return (r, g, b)


def format_hex_color(rgb: Tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def build_per_key_preset(name: str) -> Dict[int, Tuple[int, int, int]]:
    """Build a 126-slot per-key RGB mapping for a named preset."""
    low = name.strip().lower()
    result: Dict[int, Tuple[int, int, int]] = {i: (0, 0, 0) for i in range(126)}

    if low == "clear":
        return result

    if low == "fps":
        # WASD + Arrows bright red, Esc amber, Space/Modifiers cyan, numbers dim blue
        for slot in (14, 9, 15, 21, 82, 77, 83, 89):
            result[slot] = (255, 30, 30)
        result[0] = (255, 160, 0)
        for slot in (4, 5, 17, 35):
            result[slot] = (0, 200, 255)
        for slot in (7, 13, 19, 25, 31):
            result[slot] = (40, 90, 255)
        return result

    if low == "coding":
        # Soft cyan alphas, violet modifiers, green Enter/Esc, amber arrows
        mods = {0, 2, 3, 4, 5, 11, 17, 53, 59, 70, 79, 85, 86, 87, 88}
        arrows = {77, 82, 83, 89}
        for k in KEYS:
            if k.is_knob:
                continue
            if k.slot == 81:
                result[k.slot] = (0, 230, 120)
            elif k.slot in arrows:
                result[k.slot] = (255, 170, 0)
            elif k.slot in mods:
                result[k.slot] = (150, 60, 255)
            else:
                result[k.slot] = (0, 200, 255)
        return result

    if low == "cyberpunk":
        for k in KEYS:
            if k.is_knob:
                continue
            if k.x < 7.5:
                result[k.slot] = (255, 0, 140)
            else:
                result[k.slot] = (0, 240, 255)
        result[35] = (180, 0, 255)
        result[81] = (255, 220, 0)
        return result

    if low == "rainbow-rows":
        row_colors = [
            (255, 40, 40),
            (255, 150, 0),
            (220, 240, 0),
            (0, 230, 100),
            (0, 170, 255),
            (170, 60, 255),
        ]
        for k in KEYS:
            if not k.is_knob:
                result[k.slot] = row_colors[k.row % len(row_colors)]
        return result

    raise ValueError(f"Unknown per-key preset: {name!r} (valid: fps, coding, cyberpunk, rainbow-rows, clear)")


PER_KEY_PRESETS = ["fps", "coding", "cyberpunk", "rainbow-rows", "clear"]

QUICK_LIGHTING_PRESETS: List[Tuple[str, int, int, int, int, Optional[Tuple[int, int, int]]]] = [
    ("Ice Cyan", 1, 8, 2, 0, (0, 220, 255)),
    ("Pure White", 1, 8, 2, 0, (255, 255, 255)),
    ("Crimson", 1, 8, 2, 0, (255, 25, 45)),
    ("Emerald", 1, 8, 2, 0, (0, 235, 110)),
    ("Purple Glow", 2, 8, 2, 0, (175, 45, 255)),
    ("Warm Amber", 1, 8, 2, 0, (255, 145, 15)),
    ("Rainbow Stream", 11, 7, 3, 7, None),
    ("Rainbow Wave", 6, 7, 3, 7, None),
    ("Off", 0, 0, 0, 0, None),
]

BINDABLE_KEY_CHOICES: List[str] = (
    ["Esc", "Tab", "CapsLock", "Backspace", "Enter", "Space", "Delete", "Insert", "Home", "End", "PageUp", "PageDown"]
    + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(n) for n in range(0, 10)]
    + [f"F{n}" for n in range(1, 13)]
    + ["Up", "Down", "Left", "Right", "`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/"]
    + ["LCtrl", "LShift", "LAlt", "LWin", "RCtrl", "RShift", "RAlt", "Fn"]
    + ["Mute", "VolUp", "VolDown", "PrintScreen", "Pause", "Menu", "Disabled"]
)
