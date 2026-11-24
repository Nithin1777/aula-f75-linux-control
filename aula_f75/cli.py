"""Command-line interface for AULA F75 configuration on Linux."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .hid_protocol import AulaF75Device, AulaF75Error, find_aula_f75_hidraw
from .layout import (
    EFFECTS_LIST,
    KEYS,
    KEYS_BY_SLOT,
    PER_KEY_PRESETS,
    build_per_key_preset,
    decode_key_entry,
    encode_key_entry,
    format_hex_color,
    parse_hex_color,
    resolve_effect,
    resolve_key_slot,
)
from .mouse_protocol import (
    DPI_VALUES,
    MOUSE_BUTTON_FUNCTIONS,
    MOUSE_BUTTON_SLOTS,
    MOUSE_LED_MODES,
    InstantMouseDevice,
    MouseProtocolError,
    find_instant_mouse_hidraw,
    resolve_mouse_led,
)


def _cmd_status(_args: argparse.Namespace) -> int:
    info = find_aula_f75_hidraw()
    if not info:
        print("AULA F75 (258a:010c) not detected via hidraw. Ensure wired USB connection.", file=sys.stderr)
        return 1

    with AulaF75Device(info["path"]) as dev:
        status = dev.read_status()
        state = dev.get_lighting_state()

    batt_str = f"{status['battery']}%" if status["battery"] is not None else "unknown"
    color_desc = "rainbow (multi-color)" if state["is_rainbow"] else f"slot {state['color_index']} ({state['active_hex']})"
    print(f"Device:     {info['hid_name']} (258a:010c)")
    print(f"HID Node:   {info['path']} ({info['phys']})")
    print(f"Battery:    {batt_str}")
    print(f"Effect:     {state['effect_id']} ({state['effect_slug']} - {state['effect_name']})")
    print(f"Brightness: {state['brightness']}/9")
    print(f"Speed:      {state['speed']}/4")
    print(f"Color:      {color_desc}")
    knob_desc = "media (volume / mute)" if state.get("knob_mode") == "media" else "lighting (brightness / effect)"
    print(f"Knob Mode:  {knob_desc}")
    pal_str = " ".join(format_hex_color(c) for c in state["palette"])
    print(f"Palette:    {pal_str}")
    return 0


def _cmd_effects(_args: argparse.Namespace) -> int:
    print(f"{'ID':>3}  {'Slug':<15}  {'Name':<22}  {'Color':<5}  {'Speed'}")
    print("-" * 60)
    for eff in EFFECTS_LIST:
        c = "yes" if eff.supports_color else "no"
        s = "yes" if eff.supports_speed else "no"
        print(f"{eff.effect_id:>3}  {eff.slug:<15}  {eff.name:<22}  {c:<5}  {s}")
    return 0


def _parse_color_arg(val: str) -> Tuple[Optional[int], Optional[Tuple[int, int, int]]]:
    low = val.strip().lower()
    if low in ("rainbow", "mix", "multi", "7"):
        return 7, None
    if low.isdigit():
        idx = int(low)
        if 0 <= idx <= 7:
            return idx, None
        raise ValueError("Color index must be 0..7 or 'rainbow' or '#RRGGBB'")
    rgb = parse_hex_color(val)
    return 0, rgb


def _cmd_effect(args: argparse.Namespace) -> int:
    eff = resolve_effect(args.name)
    color_idx: Optional[int] = None
    custom_rgb: Optional[Tuple[int, int, int]] = None
    if args.color is not None:
        color_idx, custom_rgb = _parse_color_arg(args.color)

    with AulaF75Device() as dev:
        state = dev.set_effect(
            eff.effect_id,
            brightness=args.brightness,
            speed=args.speed,
            color_index=color_idx,
            custom_rgb=custom_rgb,
        )
    print(
        f"Applied effect {state['effect_id']} ({state['effect_slug']}) | "
        f"brightness={state['brightness']}/9 speed={state['speed']}/4 color={state['active_hex']}"
    )
    return 0


def _cmd_color(args: argparse.Namespace) -> int:
    rgb = parse_hex_color(args.hex_color)
    with AulaF75Device() as dev:
        state = dev.set_effect(
            1,  # static
            brightness=args.brightness,
            speed=0,
            color_index=0,
            custom_rgb=rgb,
        )
    print(
        f"Applied static color {format_hex_color(rgb)} | "
        f"brightness={state['brightness']}/9"
    )
    return 0


def _cmd_off(_args: argparse.Namespace) -> int:
    with AulaF75Device() as dev:
        dev.set_effect(0)
    print("Backlight turned off (effect 0).")
    return 0


def _cmd_perkey(args: argparse.Namespace) -> int:
    with AulaF75Device() as dev:
        if args.preset:
            slot_rgb = build_per_key_preset(args.preset)
        else:
            slot_rgb = dev.read_per_key_rgb()

        if args.all:
            rgb = parse_hex_color(args.all)
            for k in KEYS:
                if not k.is_knob:
                    slot_rgb[k.slot] = rgb

        for item in args.set_key or []:
            if "=" not in item:
                raise ValueError(f"Expected KEY=#RRGGBB, got {item!r}")
            key_tok, hex_tok = item.split("=", 1)
            slot = resolve_key_slot(key_tok)
            slot_rgb[slot] = parse_hex_color(hex_tok)

        dev.set_per_key_colors(
            slot_rgb,
            activate_custom=not args.no_activate,
            brightness=args.brightness,
        )

    active_msg = "and activated Custom mode (21)" if not args.no_activate else "(saved without switching effect)"
    print(f"Updated per-key RGB {active_msg}.")
    return 0


def _cmd_keymap(args: argparse.Namespace) -> int:
    layer = 0 if args.layer == "base" else 1
    with AulaF75Device() as dev:
        km = dev.read_keymap(layer=layer)
        if args.km_action == "show":
            print(f"Keymap layer: {args.layer} (sub={layer})")
            for k in KEYS:
                off = k.slot * 4
                entry = bytes(km[off : off + 4])
                decoded = decode_key_entry(entry)
                print(f"  slot {k.slot:3d}  {k.label:<7}  {entry.hex()}  ->  {decoded}")
            return 0

        if args.km_action == "set":
            slot = resolve_key_slot(args.key)
            new_entry = encode_key_entry(args.binding)
            off = slot * 4
            old_entry = bytes(km[off : off + 4])
            km[off : off + 4] = new_entry
            dev.write_keymap(km, layer=layer, allow_remove_fn=args.force)
            key_label = KEYS_BY_SLOT[slot].label if slot in KEYS_BY_SLOT else f"slot {slot}"
            print(
                f"Updated {args.layer} slot {slot} ({key_label}): "
                f"{decode_key_entry(old_entry)} [{old_entry.hex()}] -> "
                f"{decode_key_entry(new_entry)} [{new_entry.hex()}]"
            )
            return 0
    return 1


def _cmd_backup(args: argparse.Namespace) -> int:
    out_path = Path(args.path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with AulaF75Device() as dev:
        data = dev.export_backup()
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved full keyboard backup to {out_path}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    in_path = Path(args.path).expanduser()
    data = json.loads(in_path.read_text(encoding="utf-8"))
    with AulaF75Device() as dev:
        dev.import_backup(
            data,
            restore_keymaps=not args.lighting_only,
            allow_remove_fn=args.force,
        )
    print(f"Restored backup from {in_path}")
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    with AulaF75Device() as dev:
        prev = bytes(dev.read_config())
        print("Watching 128-byte config block (0x84). Press Fn+... shortcuts on keyboard; Ctrl+C to stop.")
        while True:
            time.sleep(args.interval)
            cur = bytes(dev.read_config())
            diffs = [
                f"[{i}]=0x{prev[i]:02x}->0x{cur[i]:02x}"
                for i in range(len(cur))
                if cur[i] != prev[i]
            ]
            if diffs:
                print(time.strftime("%H:%M:%S"), " ".join(diffs))
                prev = cur
    return 0


def _cmd_knob(args: argparse.Namespace) -> int:
    with AulaF75Device() as dev:
        mode = dev.set_knob_mode(args.mode)
    desc = "media (turn = volume, press = mute)" if mode == "media" else "lighting (turn = brightness, press = cycle effect)"
    print(f"Knob mode set to {desc}.")
    return 0


# ---------------- Mouse CLI Handlers ----------------
def _resolve_mouse_button_slot(token: str) -> int:
    s = token.strip().lower()
    if s.isdigit():
        slot = int(s)
        if slot in {sl for sl, _ in MOUSE_BUTTON_SLOTS}:
            return slot
        raise ValueError(f"Unsupported button slot: {slot}")
    aliases = {
        "left": 0,
        "middle": 1,
        "wheel": 1,
        "right": 2,
        "back": 3,
        "rear": 3,
        "forward": 4,
        "front": 4,
        "top1": 5,
        "led": 5,
        "top2": 7,
        "dpi": 7,
    }
    if s in aliases:
        return aliases[s]
    for sl, label in MOUSE_BUTTON_SLOTS:
        if s == label.lower():
            return sl
    raise ValueError(f"Unknown mouse button: {token!r} (try: left, middle, right, back, forward, top1, top2)")


def _resolve_mouse_func(token: str) -> int:
    s = token.strip().lower()
    if s.startswith("0x"):
        return int(s, 16)
    aliases = {
        "left": 0x21,
        "left-click": 0x21,
        "middle": 0x22,
        "middle-click": 0x22,
        "right": 0x23,
        "right-click": 0x23,
        "back": 0x24,
        "forward": 0x25,
        "dpi-loop": 0x26,
        "dpi": 0x26,
        "dpi+": 0x2B,
        "dpi-up": 0x2B,
        "dpi-": 0x2C,
        "dpi-down": 0x2C,
        "led": 0x35,
        "led-loop": 0x35,
        "double": 0x28,
        "double-click": 0x28,
        "fire": 0x29,
        "rapid-fire": 0x29,
        "desktop": 0x27,
        "show-desktop": 0x27,
        "fn": 0x34,
        "disabled": 0x00,
        "off": 0x00,
    }
    if s in aliases:
        return aliases[s]
    for code, name in MOUSE_BUTTON_FUNCTIONS:
        if s == name.lower():
            return code
    raise ValueError(f"Unknown button function: {token!r}")


def _cmd_mouse_status(_args: argparse.Namespace) -> int:
    info = find_instant_mouse_hidraw()
    if not info:
        print("Instant A825 mouse (30fa:1440) not detected via hidraw.", file=sys.stderr)
        return 1
    with InstantMouseDevice(info["path"]) as dev:
        st = dev.read_state()
    print(f"Mouse:      {info['model_name']} ({info['vid_pid']})")
    print(f"HID Name:   {info['hid_name']}")
    print(f"HID Node:   {info['path']} ({info['phys']})")
    print(f"LED Mode:   {st['led_mode_id']} ({st['led_mode_slug']} - {st['led_mode_name']}) | speed={st['led_speed']}/5")
    print(f"Active DPI: Stage {st['active_stage']} -> {st['active_dpi']} DPI | color={st['active_color_hex']}")
    print("DPI Stages:")
    for s in st["stages"]:
        mark = "*" if s["active"] else " "
        en = "on " if s["enabled"] else "off"
        print(f"  {mark} Stage {s['stage']}: {s['dpi']:>5} DPI  [{en}]  {s['hex']}")
    print("Buttons:")
    for b in st["buttons"]:
        print(f"  slot {b['slot']} ({b['label']:<22}): {b['function']} [0x{b['code']:02x}]")
    return 0


def _cmd_mouse_modes(_args: argparse.Namespace) -> int:
    print(f"{'ID':>3}  {'Slug':<16}  {'Name':<18}  {'Color'}")
    print("-" * 48)
    for m in MOUSE_LED_MODES:
        print(f"{m.mode_id:>3}  {m.slug:<16}  {m.name:<18}  {'yes' if m.uses_color else 'no'}")
    return 0


def _cmd_mouse_led(args: argparse.Namespace) -> int:
    mode = resolve_mouse_led(args.mode)
    rgb = parse_hex_color(args.color) if args.color else None
    with InstantMouseDevice() as dev:
        if args.live:
            spd = 2 if args.speed is None else args.speed
            dev.set_live_lighting(mode.mode_id, speed=spd, brightness=args.brightness, rgb=rgb)
            print(f"Applied live RAM lighting: {mode.mode_id} ({mode.slug}), brightness={args.brightness}/4")
        else:
            st = dev.set_led(mode.mode_id, speed=args.speed, rgb=rgb)
            print(
                f"Saved mouse LED: {st['led_mode_id']} ({st['led_mode_slug']}) | "
                f"speed={st['led_speed']}/5 active_color={st['active_color_hex']}"
            )
    return 0


def _cmd_mouse_color(args: argparse.Namespace) -> int:
    rgb = parse_hex_color(args.hex_color)
    stage = (args.stage - 1) if args.stage is not None else None
    with InstantMouseDevice() as dev:
        st = dev.set_led(2, rgb=rgb, stage=stage)
    print(
        f"Saved static mouse color {format_hex_color(rgb)} "
        f"(stage {args.stage if args.stage else st['active_stage']})"
    )
    return 0


def _cmd_mouse_off(_args: argparse.Namespace) -> int:
    with InstantMouseDevice() as dev:
        st = dev.set_led(13)
    print(f"Mouse LEDs turned off (mode {st['led_mode_id']}).")
    return 0


def _cmd_mouse_dpi(args: argparse.Namespace) -> int:
    with InstantMouseDevice() as dev:
        _, orig = dev.read_header_and_config()
        cfg = orig.copy()
        for item in args.set_stage or []:
            if "=" not in item:
                raise ValueError(f"Expected STAGE=DPI, got {item!r}")
            st_s, dpi_s = item.split("=", 1)
            st_idx = int(st_s) - 1
            cfg.set_dpi(st_idx, int(dpi_s))
        for item in args.color_stage or []:
            if "=" not in item:
                raise ValueError(f"Expected STAGE=#RRGGBB, got {item!r}")
            st_s, hex_s = item.split("=", 1)
            st_idx = int(st_s) - 1
            cfg.set_stage_color(st_idx, parse_hex_color(hex_s))
        if args.enable:
            mask = 0
            for part in args.enable.split(","):
                idx = int(part.strip()) - 1
                if not (0 <= idx < 6):
                    raise ValueError(f"Stage out of range 1..6: {part}")
                mask |= 1 << idx
            cfg.set_dpi_enabled_mask(mask)
        if args.active is not None:
            cfg.set_active_dpi_stage(args.active - 1)
        changed = dev.save_config(cfg, original_cfg=orig)
        st = dev.read_state()
    print(f"Updated DPI config (blocks {[hex(b) for b in changed]}). Active: Stage {st['active_stage']} -> {st['active_dpi']} DPI")
    return 0


def _cmd_mouse_button(args: argparse.Namespace) -> int:
    slot = _resolve_mouse_button_slot(args.button)
    code = _resolve_mouse_func(args.function)
    with InstantMouseDevice() as dev:
        _, orig = dev.read_header_and_config()
        cfg = orig.copy()
        cfg.set_button(slot, code)
        dev.save_config(cfg, original_cfg=orig, allow_remove_left=args.force)
        st = dev.read_state()
    b_info = next(b for b in st["buttons"] if b["slot"] == slot)
    print(f"Saved mouse button slot {slot} ({b_info['label']}): {b_info['function']} [0x{code:02x}]")
    return 0


def _cmd_mouse_backup(args: argparse.Namespace) -> int:
    out_path = Path(args.path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with InstantMouseDevice() as dev:
        data = dev.export_backup()
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved mouse backup to {out_path}")
    return 0


def _cmd_mouse_restore(args: argparse.Namespace) -> int:
    in_path = Path(args.path).expanduser()
    data = json.loads(in_path.read_text(encoding="utf-8"))
    with InstantMouseDevice() as dev:
        changed = dev.import_backup(data, allow_remove_left=args.force)
    print(f"Restored mouse backup from {in_path} (blocks updated: {[hex(b) for b in changed]})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aula-f75",
        description="Native Linux configurator for the AULA F75 mechanical keyboard (258a:010c).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Show connection, battery, and active lighting state")
    p_status.set_defaults(func=_cmd_status)

    p_effs = sub.add_parser("effects", help="List supported built-in lighting effect IDs")
    p_effs.set_defaults(func=_cmd_effects)

    p_eff = sub.add_parser("effect", help="Set lighting effect, brightness, speed, and color")
    p_eff.add_argument("name", help="Effect ID (e.g. 1, 11) or slug (e.g. static, stream, breathing)")
    p_eff.add_argument("-b", "--brightness", type=int, choices=range(0, 10), metavar="0..9")
    p_eff.add_argument("-s", "--speed", type=int, choices=range(0, 5), metavar="0..4")
    p_eff.add_argument("-c", "--color", help="Palette index 0..6, 'rainbow', or '#RRGGBB'")
    p_eff.set_defaults(func=_cmd_effect)

    p_col = sub.add_parser("color", help="Set solid static custom RGB color")
    p_col.add_argument("hex_color", help="Hex color like '#00ffff' or 'ff3300'")
    p_col.add_argument("-b", "--brightness", type=int, choices=range(0, 10), metavar="0..9")
    p_col.set_defaults(func=_cmd_color)

    p_off = sub.add_parser("off", help="Turn off keyboard backlight")
    p_off.set_defaults(func=_cmd_off)

    p_pk = sub.add_parser("perkey", help="Configure per-key RGB colors")
    p_pk.add_argument("--preset", choices=PER_KEY_PRESETS, help="Apply a built-in per-key preset")
    p_pk.add_argument("--all", help="Fill all keys with '#RRGGBB'")
    p_pk.add_argument("--set", dest="set_key", action="append", help="Set KEY=#RRGGBB (repeatable)")
    p_pk.add_argument("-b", "--brightness", type=int, choices=range(0, 10), metavar="0..9")
    p_pk.add_argument("--no-activate", action="store_true", help="Save per-key map without switching to effect 21")
    p_pk.set_defaults(func=_cmd_perkey)

    p_km = sub.add_parser("keymap", help="Inspect or remap keys on Base or Fn layer")
    km_sub = p_km.add_subparsers(dest="km_action", required=True)
    p_km_show = km_sub.add_parser("show", help="Print decoded keymap slots")
    p_km_show.add_argument("--layer", choices=["base", "fn"], default="base")
    p_km_show.set_defaults(func=_cmd_keymap)

    p_km_set = km_sub.add_parser("set", help="Remap a key slot")
    p_km_set.add_argument("key", help="Key label (e.g. Caps, RShift) or numeric slot 0..125")
    p_km_set.add_argument("binding", help="New binding (e.g. Esc, LCtrl+C, Fn, Disabled)")
    p_km_set.add_argument("--layer", choices=["base", "fn"], default="base")
    p_km_set.add_argument("--force", action="store_true", help="Allow writing base keymap without Fn key")
    p_km_set.set_defaults(func=_cmd_keymap)

    p_bk = sub.add_parser("backup", help="Export full keyboard config/lighting/keymap JSON backup")
    p_bk.add_argument("path", help="Output JSON file path")
    p_bk.set_defaults(func=_cmd_backup)

    p_rs = sub.add_parser("restore", help="Restore keyboard from a JSON backup")
    p_rs.add_argument("path", help="Input JSON file path")
    p_rs.add_argument("--lighting-only", action="store_true", help="Only restore lighting/config, skip keymaps")
    p_rs.add_argument("--force", action="store_true", help="Allow restoring base keymap without Fn key")
    p_rs.set_defaults(func=_cmd_restore)

    p_watch = sub.add_parser("watch", help="Live-monitor config block changes as you press Fn combos")
    p_watch.add_argument("--interval", type=float, default=0.3, help="Polling interval in seconds")
    p_watch.set_defaults(func=_cmd_watch)

    p_knob = sub.add_parser("knob", help="Set rotary knob mode (media volume/mute vs lighting brightness/effect)")
    p_knob.add_argument("mode", choices=["media", "lighting"], help="Target knob behavior")
    p_knob.set_defaults(func=_cmd_knob)

    # Mouse subcommand group
    p_mouse = sub.add_parser("mouse", help="Configure connected Ant Esports GM320 / Instant A825 mouse (30fa:1440)")
    m_sub = p_mouse.add_subparsers(dest="mouse_cmd", required=True)

    pm_st = m_sub.add_parser("status", help="Show mouse DPI stages, colors, LED mode, and buttons")
    pm_st.set_defaults(func=_cmd_mouse_status)

    pm_md = m_sub.add_parser("modes", help="List supported mouse LED lighting modes")
    pm_md.set_defaults(func=_cmd_mouse_modes)

    pm_led = m_sub.add_parser("led", help="Set mouse LED mode (saved to flash, or --live for RAM-only)")
    pm_led.add_argument("mode", help="Mode ID (0..13) or slug (e.g. light-on, flowing-water, neon, click-response, off)")
    pm_led.add_argument("-s", "--speed", type=int, choices=range(0, 6), metavar="0..5")
    pm_led.add_argument("-c", "--color", help="Hex RGB color '#RRGGBB'")
    pm_led.add_argument("--live", action="store_true", help="Apply to RAM only via 0x13/0x14 (no flash wear)")
    pm_led.add_argument("-b", "--brightness", type=int, choices=range(0, 5), default=4, metavar="0..4", help="Brightness for --live")
    pm_led.set_defaults(func=_cmd_mouse_led)

    pm_col = m_sub.add_parser("color", help="Set solid static mouse LED color")
    pm_col.add_argument("hex_color", help="Hex color '#RRGGBB'")
    pm_col.add_argument("--stage", type=int, choices=range(1, 7), help="DPI stage 1..6 to update (default: active)")
    pm_col.set_defaults(func=_cmd_mouse_color)

    pm_off = m_sub.add_parser("off", help="Turn off mouse LEDs")
    pm_off.set_defaults(func=_cmd_mouse_off)

    pm_dpi = m_sub.add_parser("dpi", help="Configure mouse DPI stages, active stage, and stage colors")
    pm_dpi.add_argument("--active", type=int, choices=range(1, 7), help="Set active stage (1..6)")
    pm_dpi.add_argument("--set", dest="set_stage", action="append", help=f"Set STAGE=DPI (repeatable; valid: {DPI_VALUES})")
    pm_dpi.add_argument("--color", dest="color_stage", action="append", help="Set STAGE=#RRGGBB (repeatable)")
    pm_dpi.add_argument("--enable", help="Comma-separated enabled stages, e.g. 1,2,3,4")
    pm_dpi.set_defaults(func=_cmd_mouse_dpi)

    pm_btn = m_sub.add_parser("button", help="Remap a mouse button")
    pm_btn.add_argument("button", help="Button (left, middle, right, back, forward, top1, top2, or slot)")
    pm_btn.add_argument("function", help="Function (left, middle, right, back, forward, dpi-loop, dpi+, dpi-, led-loop, double-click, fire, desktop, disabled)")
    pm_btn.add_argument("--force", action="store_true", help="Allow removing Left Click")
    pm_btn.set_defaults(func=_cmd_mouse_button)

    pm_bk = m_sub.add_parser("backup", help="Save mouse flash backup JSON (0x00..0x3f)")
    pm_bk.add_argument("path", help="Output JSON file path")
    pm_bk.set_defaults(func=_cmd_mouse_backup)

    pm_rs = m_sub.add_parser("restore", help="Restore mouse settings from backup JSON (never touches 0x00..0x07)")
    pm_rs.add_argument("path", help="Input JSON file path")
    pm_rs.add_argument("--force", action="store_true", help="Allow restoring without Left Click")
    pm_rs.set_defaults(func=_cmd_mouse_restore)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (AulaF75Error, MouseProtocolError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130
