"""Unit tests for AULA F75 and Instant A825 mouse protocols, framing, and safety guards."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aula_f75.hid_protocol import (
    CONFIG_LEN,
    CUSTOM_EFFECT_ID,
    KEYMAP_LEN,
    LEGACY_KEYMAP_LEN,
    MAGIC_TRAILER,
    PERKEY_LEN,
    AulaF75Device,
    AulaF75Error,
)
from aula_f75.layout import (
    build_per_key_preset,
    decode_key_entry,
    encode_key_entry,
    format_hex_color,
    parse_hex_color,
    resolve_effect,
    resolve_key_slot,
)
from aula_f75.mouse_protocol import (
    InstantMouseConfig,
    InstantMouseDevice,
    MouseProtocolError,
    resolve_mouse_led,
)

# Real 0x00..0x3f flash dump captured from the connected 30fa:1440 mouse
REAL_MOUSE_DUMP_00_3F = bytes.fromhex(
    "5a03a54014fa3010"  # 0x00..0x07 header
    "2122232425350026"  # 0x08..0x0f buttons
    "2f0000300878de03"  # 0x10..0x17 dpi high bits + nibbles
    "093f1100b1ff0000"  # 0x18..0x1f active dpi, mask, fire, led mode
    "0010fff0800f00ff"  # 0x20..0x27 colors 0,1,2..
    "80ff00bb00ffffff"  # 0x28..0x2f colors ..2,3,4,5..
    "0000ff3f00000000"  # 0x30..0x37 color 5 + led mask + mode bit3
    "00002b0000018f00"  # 0x38..0x3f
)


class DummyDevice(AulaF75Device):
    """In-memory mock subclass to test packet framing and safety checks without touching hardware."""

    def __init__(self) -> None:
        self.device_info = {"path": "/dev/null"}
        self.path = "/dev/null"
        self._fd = -1
        self.writes = []
        self.cfg = bytearray(CONFIG_LEN)
        self.cfg[126:128] = MAGIC_TRAILER
        self.keymaps = {0: bytearray(KEYMAP_LEN), 1: bytearray(KEYMAP_LEN)}
        self.per_key = bytearray(PERKEY_LEN)

    def read_block(self, cmd: int, sub: int = 0, length: int = 512, magic_offset=None) -> bytes:
        if cmd == 0x84:
            return bytes(self.cfg)
        if cmd == 0x83:
            return bytes(self.keymaps[sub])
        if cmd == 0x86:
            return bytes(self.per_key)
        return bytes(length)

    def write_block(self, cmd: int, payload: bytes, sub: int = 0, length=None) -> None:
        self.writes.append((cmd, sub, length if length is not None else len(payload), bytes(payload)))
        if cmd == 0x04:
            self.cfg = bytearray(payload)
        elif cmd == 0x03:
            self.keymaps[sub] = bytearray(payload)
        elif cmd == 0x06:
            self.per_key = bytearray(payload)


class DummyMouseDevice(InstantMouseDevice):
    """In-memory mock subclass for mouse safety checks."""

    def __init__(self) -> None:
        self.device_info = {"path": "/dev/null", "vid_pid": "30fa:1440"}
        self.path = "/dev/null"
        self._fd = -1


class TestProtocol(unittest.TestCase):
    def test_packet_framing_headers(self) -> None:
        dev = DummyDevice()
        pkt = dev._build_packet(0x84, sub=1, length=0x01F8, payload=b"\xaa\xbb")
        self.assertEqual(len(pkt), 520)
        self.assertEqual(bytes(pkt[:8]), bytes([0x06, 0x84, 0x01, 0x00, 0x01, 0x00, 0xF8, 0x01]))
        self.assertEqual(bytes(pkt[8:10]), b"\xaa\xbb")

    def test_planar_per_key_rgb_encoding(self) -> None:
        dev = DummyDevice()
        dev.write_per_key_rgb({0: (0x11, 0x22, 0x33), 89: (0xFE, 0x00, 0x7F)})
        cmd, sub, length, payload = dev.writes[-1]
        self.assertEqual(cmd, 0x06)
        self.assertEqual(sub, 0)
        self.assertEqual(length, PERKEY_LEN)
        self.assertEqual((payload[0], payload[126], payload[252]), (0x11, 0x22, 0x33))
        self.assertEqual((payload[89], payload[126 + 89], payload[252 + 89]), (0xFE, 0x00, 0x7F))

    def test_palette_and_config_sentinel_guards(self) -> None:
        dev = DummyDevice()
        bad_cfg = bytearray(128)
        with self.assertRaises(AulaF75Error):
            dev.write_config(bad_cfg)
        bad_pal = bytearray(512)
        with self.assertRaises(AulaF75Error):
            dev.write_palette(bad_pal)

    def test_keymap_fn_safety_guard(self) -> None:
        dev = DummyDevice()
        self.assertEqual(KEYMAP_LEN, 512)
        km = bytearray(KEYMAP_LEN)
        km[0:4] = encode_key_entry("Esc")
        # Missing 5aa5 signature at [510:512] must fail
        with self.assertRaises(AulaF75Error):
            dev.write_keymap(km, layer=0, allow_remove_fn=True)
        km[510:512] = MAGIC_TRAILER
        # Missing Fn key on base layer must fail
        with self.assertRaises(AulaF75Error):
            dev.write_keymap(km, layer=0, allow_remove_fn=False)
        # Adding Fn key allows 512B write
        km[53 * 4 : 53 * 4 + 4] = encode_key_entry("Fn")
        dev.write_keymap(km, layer=0, allow_remove_fn=False)
        self.assertEqual(dev.writes[-1][0], 0x03)
        self.assertEqual(dev.writes[-1][2], 512)
        # Legacy 504B buffer auto-upgrades with 5aa5 trailer
        legacy = bytearray(LEGACY_KEYMAP_LEN)
        legacy[53 * 4 : 53 * 4 + 4] = encode_key_entry("Fn")
        dev.write_keymap(legacy, layer=0, allow_remove_fn=False)
        self.assertEqual(dev.writes[-1][2], 512)
        self.assertEqual(dev.writes[-1][3][510:512], MAGIC_TRAILER)

    def test_custom_per_key_mode_uses_effect_21_and_flag_9(self) -> None:
        dev = DummyDevice()
        dev.ensure_initial_backup = lambda *a, **kw: None  # skip disk in unit test
        dev.set_per_key_colors({0: (255, 0, 0)}, activate_custom=True)
        self.assertEqual(dev.cfg[9], 1)
        self.assertEqual(dev.cfg[10], CUSTOM_EFFECT_ID)
        self.assertEqual(dev.cfg[11], 0x20)

    def test_keycode_roundtrip(self) -> None:
        for spec in ("Esc", "A", "Space", "LCtrl+C", "Fn", "Disabled"):
            encoded = encode_key_entry(spec)
            self.assertEqual(len(encoded), 4)
            self.assertEqual(decode_key_entry(encoded), spec)

    def test_effects_colors_and_presets(self) -> None:
        self.assertEqual(resolve_effect("static").effect_id, 1)
        self.assertEqual(resolve_effect("custom").effect_id, 21)
        self.assertEqual(resolve_effect(32).effect_id, 21)
        self.assertEqual(resolve_effect("11").slug, "stream")
        self.assertEqual(resolve_key_slot("W"), 14)
        self.assertEqual(format_hex_color(parse_hex_color("#00Ff80")), "#00ff80")
        fps = build_per_key_preset("fps")
        self.assertEqual(fps[14], (255, 30, 30))


class TestMouseProtocol(unittest.TestCase):
    def test_header_write_is_hard_blocked(self) -> None:
        m = DummyMouseDevice()
        with self.assertRaises(MouseProtocolError):
            m.write_block(0x00, b"\x00" * 8)
        with self.assertRaises(MouseProtocolError):
            m.write_block(0x40, b"\x00" * 8)

    def test_decode_real_mouse_dump(self) -> None:
        cfg = InstantMouseConfig(REAL_MOUSE_DUMP_00_3F[8:0x40])
        self.assertEqual(cfg.get_active_dpi_stage(), 1)  # 0x09 & 7 == 1 (Stage 2)
        self.assertEqual(cfg.get_dpi_enabled_mask(), 0x3F)
        self.assertEqual([cfg.get_dpi(i) for i in range(6)], [1400, 1600, 3200, 4000, 5600, 8000])
        self.assertEqual(cfg.get_led_mode(), (3, 1))  # Flowing Water, speed 1
        self.assertEqual(cfg.get_stage_color(0), (255, 239, 0))
        self.assertEqual(cfg.get_stage_color(1), (15, 127, 240))
        self.assertEqual(cfg.get_button(0), 0x21)  # Left Click

    def test_dpi_color_and_led_roundtrip_preserves_unknown_bits(self) -> None:
        orig = InstantMouseConfig(REAL_MOUSE_DUMP_00_3F[8:0x40])
        cfg = orig.copy()
        cfg.set_dpi(0, 800)
        cfg.set_dpi(5, 12800)
        cfg.set_active_dpi_stage(0)
        cfg.set_stage_color(0, (0, 220, 255))
        cfg.set_led_mode(10, speed=4)  # mode >= 8 sets bit 7 of 0x33
        self.assertEqual(cfg.get_dpi(0), 800)
        self.assertEqual(cfg.get_dpi(5), 12800)
        self.assertEqual(cfg.get_stage_color(0), (0, 220, 255))
        self.assertEqual(cfg.get_led_mode(), (10, 4))
        self.assertEqual(cfg._b(0x18) & 0xF8, 0x08)  # unknown upper bits preserved
        self.assertEqual(cfg._b(0x33) & 0x7F, 0x3F)  # lower 7 bits preserved
        self.assertEqual(resolve_mouse_led("static").mode_id, 2)

    def test_left_click_safety_guard(self) -> None:
        cfg = InstantMouseConfig(REAL_MOUSE_DUMP_00_3F[8:0x40])
        cfg.set_button(0, 0x22)
        with self.assertRaises(MouseProtocolError):
            cfg.validate(allow_remove_left=False)
        cfg.validate(allow_remove_left=True)


if __name__ == "__main__":
    unittest.main()
