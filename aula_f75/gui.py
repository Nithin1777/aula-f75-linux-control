"""Native GTK4 + Libadwaita GUI for AULA F75 configuration on Linux."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .hid_protocol import (  # noqa: E402
    INITIAL_BACKUP_PATH,
    AulaF75Device,
    AulaF75Error,
    find_aula_f75_hidraw,
)
from .mouse_protocol import (  # noqa: E402
    DPI_VALUES,
    MOUSE_BUTTON_FUNCTIONS,
    MOUSE_BUTTON_SLOTS,
    MOUSE_INITIAL_BACKUP_PATH,
    MOUSE_LED_MODES,
    MOUSE_QUICK_PRESETS,
    InstantMouseDevice,
    MouseProtocolError,
    find_instant_mouse_hidraw,
)
from .layout import (  # noqa: E402
    BINDABLE_KEY_CHOICES,
    EFFECTS_BY_ID,
    EFFECTS_LIST,
    KEYS,
    KEYS_BY_SLOT,
    PER_KEY_PRESETS,
    QUICK_LIGHTING_PRESETS,
    KeySpec,
    build_per_key_preset,
    decode_key_entry,
    encode_key_entry,
    format_hex_color,
    parse_hex_color,
)


def _rgba_from_rgb(rgb: Tuple[int, int, int]) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red = rgb[0] / 255.0
    c.green = rgb[1] / 255.0
    c.blue = rgb[2] / 255.0
    c.alpha = 1.0
    return c


def _rgb_from_rgba(rgba: Gdk.RGBA) -> Tuple[int, int, int]:
    return (
        max(0, min(255, int(round(rgba.red * 255)))),
        max(0, min(255, int(round(rgba.green * 255)))),
        max(0, min(255, int(round(rgba.blue * 255)))),
    )


class KeyboardCanvas(Gtk.DrawingArea):
    """Interactive visual AULA F75 canvas used for both Per-Key RGB painting and Keymap selection."""

    def __init__(self, mode: str = "rgb") -> None:
        super().__init__()
        self.mode = mode  # "rgb" or "keymap"
        self.set_content_width(860)
        self.set_content_height(315)
        self.set_hexpand(True)
        self.set_vexpand(False)

        self.slot_colors: Dict[int, Tuple[int, int, int]] = {k.slot: (0, 200, 255) for k in KEYS}
        self.keymap_labels: Dict[int, str] = {}
        self.selected_slot: Optional[int] = 0
        self.hover_slot: Optional[int] = None
        self.paint_rgb: Tuple[int, int, int] = (0, 220, 255)
        self.eraser_active: bool = False
        self._dragging: bool = False
        self._key_rects: List[Tuple[KeySpec, float, float, float, float]] = []

        self.on_key_painted = None
        self.on_key_selected = None

        self.set_draw_func(self._on_draw)

        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_pressed)
        click.connect("released", self._on_released)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def _compute_geometry(self, width: int, height: int) -> Tuple[float, float, float]:
        # Total logical grid: 16.25 units wide x 6 rows (+ small gap below row 0)
        unit = min((width - 24) / 16.25, (height - 24) / 6.35)
        unit = max(24.0, unit)
        x0 = (width - unit * 16.25) / 2.0
        y0 = (height - unit * 6.35) / 2.0
        return unit, x0, y0

    def _hit_test(self, px: float, py: float) -> Optional[KeySpec]:
        for k, rx, ry, rw, rh in self._key_rects:
            if rx <= px <= rx + rw and ry <= py <= ry + rh:
                return k
        return None

    def _on_pressed(self, _gesture, _n_press: int, x: float, y: float) -> None:
        self._dragging = True
        k = self._hit_test(x, y)
        if k is None:
            return
        if self.mode == "rgb":
            if not k.is_knob:
                self._paint_key(k)
        else:
            self.selected_slot = k.slot
            self.queue_draw()
            if self.on_key_selected:
                self.on_key_selected(k.slot)

    def _on_released(self, _gesture, _n_press: int, _x: float, _y: float) -> None:
        self._dragging = False

    def _on_motion(self, _ctrl, x: float, y: float) -> None:
        k = self._hit_test(x, y)
        new_hover = k.slot if k else None
        if new_hover != self.hover_slot:
            self.hover_slot = new_hover
            self.queue_draw()
        if self._dragging and self.mode == "rgb" and k is not None and not k.is_knob:
            self._paint_key(k)

    def _on_leave(self, _ctrl) -> None:
        self.hover_slot = None
        self.queue_draw()

    def _paint_key(self, k: KeySpec) -> None:
        rgb = (0, 0, 0) if self.eraser_active else self.paint_rgb
        if self.slot_colors.get(k.slot) != rgb:
            self.slot_colors[k.slot] = rgb
            self.queue_draw()
            if self.on_key_painted:
                self.on_key_painted(k.slot, rgb)

    def _rounded_rect(self, cr, x: float, y: float, w: float, h: float, r: float) -> None:
        import math

        r = min(r, w / 2.0, h / 2.0)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _on_draw(self, _area, cr, width: int, height: int) -> None:
        import math

        # Case background
        self._rounded_rect(cr, 2, 2, width - 4, height - 4, 14)
        cr.set_source_rgb(0.11, 0.12, 0.14)
        cr.fill_preserve()
        cr.set_source_rgb(0.24, 0.26, 0.30)
        cr.set_line_width(1.5)
        cr.stroke()

        unit, x0, y0 = self._compute_geometry(width, height)
        gap = max(2.0, unit * 0.08)
        self._key_rects = []

        for k in KEYS:
            row_offset = 0.35 if k.row > 0 else 0.0
            rx = x0 + k.x * unit + gap / 2.0
            ry = y0 + (k.row + row_offset) * unit + gap / 2.0
            rw = k.width * unit - gap
            rh = unit - gap
            self._key_rects.append((k, rx, ry, rw, rh))

            if k.is_knob:
                cx = rx + rw / 2.0
                cy = ry + rh / 2.0
                rad = min(rw, rh) * 0.44
                cr.arc(cx, cy, rad, 0, 2 * math.pi)
                cr.set_source_rgb(0.20, 0.22, 0.26)
                cr.fill_preserve()
                if self.mode == "keymap" and self.selected_slot == k.slot:
                    cr.set_source_rgb(0.30, 0.72, 1.0)
                    cr.set_line_width(2.4)
                else:
                    cr.set_source_rgb(0.45, 0.48, 0.54)
                    cr.set_line_width(1.4)
                cr.stroke()
                cr.set_source_rgb(0.88, 0.90, 0.94)
                cr.set_font_size(max(8.5, unit * 0.22))
                label = self.keymap_labels.get(k.slot, k.label) if self.mode == "keymap" else "Knob"
                ext = cr.text_extents(label)
                cr.move_to(cx - ext.width / 2.0, cy + ext.height / 2.0)
                cr.show_text(label)
                continue

            r, g, b = self.slot_colors.get(k.slot, (0, 0, 0))
            self._rounded_rect(cr, rx, ry, rw, rh, 6)

            if self.mode == "rgb":
                lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                if r == 0 and g == 0 and b == 0:
                    cr.set_source_rgb(0.16, 0.17, 0.20)
                else:
                    cr.set_source_rgba(r / 255.0, g / 255.0, b / 255.0, 0.28)
                cr.fill_preserve()
                if self.hover_slot == k.slot:
                    cr.set_source_rgb(1.0, 1.0, 1.0)
                    cr.set_line_width(2.2)
                elif r == 0 and g == 0 and b == 0:
                    cr.set_source_rgb(0.30, 0.32, 0.36)
                    cr.set_line_width(1.2)
                else:
                    cr.set_source_rgb(r / 255.0, g / 255.0, b / 255.0)
                    cr.set_line_width(2.0)
                cr.stroke()
                text_color = (0.95, 0.96, 0.98) if lum < 0.72 else (0.98, 0.99, 1.0)
            else:
                is_sel = self.selected_slot == k.slot
                is_hov = self.hover_slot == k.slot
                if is_sel:
                    cr.set_source_rgb(0.16, 0.36, 0.58)
                elif is_hov:
                    cr.set_source_rgb(0.24, 0.27, 0.33)
                else:
                    cr.set_source_rgb(0.18, 0.20, 0.24)
                cr.fill_preserve()
                if is_sel:
                    cr.set_source_rgb(0.38, 0.78, 1.0)
                    cr.set_line_width(2.2)
                else:
                    cr.set_source_rgb(0.34, 0.36, 0.42)
                    cr.set_line_width(1.2)
                cr.stroke()
                text_color = (0.95, 0.96, 0.98)

            label = k.label
            if self.mode == "keymap":
                bound = self.keymap_labels.get(k.slot, k.label)
                label = bound if len(bound) <= 6 else bound[:5] + "…"
            cr.set_source_rgb(*text_color)
            cr.set_font_size(max(8.5, unit * (0.25 if len(label) <= 2 else 0.21)))
            ext = cr.text_extents(label)
            cr.move_to(rx + (rw - ext.width) / 2.0, ry + (rh + ext.height) / 2.0 - 1.0)
            cr.show_text(label)


class AulaF75Window(Adw.ApplicationWindow):
    """Main Libadwaita window for controlling the AULA F75 keyboard and Instant A825 mouse."""

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="AULA F75 & Mouse Control")
        self.set_default_size(1060, 740)

        self._updating_ui = False
        self._palette_colors: List[Tuple[int, int, int]] = [(255, 0, 0)] * 7
        self._selected_palette_slot: int = 0
        self._custom_rgb: Tuple[int, int, int] = (0, 220, 255)
        self._current_layer: int = 0
        self._keymap_buf: bytearray = bytearray(512)
        self._watch_source_id: Optional[int] = None
        self._last_cfg_snapshot: Optional[bytes] = None
        self._mouse_color_rgb: Tuple[int, int, int] = (0, 220, 255)
        self._mouse_stage_colors: List[Tuple[int, int, int]] = [(255, 0, 0)] * 6

        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(root_box)

        # Header bar with ViewSwitcher
        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        self.status_pill = Gtk.Label(label="Checking...")
        self.status_pill.add_css_class("caption")
        self.status_pill.add_css_class("dim-label")
        header.pack_start(self.status_pill)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh state from devices")
        refresh_btn.connect("clicked", lambda *_: self.refresh_all())
        header.pack_end(refresh_btn)

        root_box.append(header)
        root_box.append(self.view_stack)
        self.view_stack.set_vexpand(True)

        self.view_stack.add_titled_with_icon(
            self._build_lighting_page(), "lighting", "Lighting", "weather-clear-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_perkey_page(), "perkey", "Per-Key RGB", "applications-graphics-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_keymap_page(), "keymap", "Keymap", "input-keyboard-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_mouse_page(), "mouse", "Mouse", "input-mouse-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_device_page(), "device", "Device & Backup", "preferences-system-symbolic"
        )

    def _toast(self, msg: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(msg))

    # ---------------- Lighting Page ----------------
    def _build_lighting_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        clamp = Adw.Clamp(maximum_size=880, margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(box)

        # Quick presets group
        preset_group = Adw.PreferencesGroup(title="Quick Presets", description="One-click lighting profiles")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=5, column_spacing=8, row_spacing=8)
        for label, eff_id, bright, spd, col_idx, rgb in QUICK_LIGHTING_PRESETS:
            btn = Gtk.Button(label=label)
            btn.connect(
                "clicked",
                lambda _b, e=eff_id, br=bright, sp=spd, ci=col_idx, c=rgb: self._apply_quick_preset(e, br, sp, ci, c),
            )
            flow.insert(btn, -1)
        preset_group.add(flow)
        box.append(preset_group)

        # Effect controls group
        ctrl_group = Adw.PreferencesGroup(title="Effect &amp; Parameters", description="Configure built-in hardware shader")

        effect_names = [f"{e.effect_id}: {e.name}" for e in EFFECTS_LIST]
        self.effect_model = Gtk.StringList.new(effect_names)
        self.effect_row = Adw.ComboRow(title="Lighting Effect", model=self.effect_model)
        self.effect_row.connect("notify::selected", self._on_effect_combo_changed)
        ctrl_group.add(self.effect_row)

        # Brightness slider row
        bright_row = Adw.ActionRow(title="Brightness", subtitle="Hardware intensity (0 = off, 9 = max)")
        self.bright_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 9, 1)
        self.bright_scale.set_size_request(240, -1)
        self.bright_scale.set_draw_value(True)
        self.bright_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.bright_scale.set_digits(0)
        bright_row.add_suffix(self.bright_scale)
        ctrl_group.add(bright_row)

        # Speed slider row
        speed_row = Adw.ActionRow(title="Animation Speed", subtitle="Hardware speed step (0 = slow, 4 = fast)")
        self.speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 4, 1)
        self.speed_scale.set_size_request(240, -1)
        self.speed_scale.set_draw_value(True)
        self.speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.speed_scale.set_digits(0)
        speed_row.add_suffix(self.speed_scale)
        ctrl_group.add(speed_row)

        # Rainbow toggle
        self.rainbow_row = Adw.SwitchRow(
            title="Rainbow / Multi-Color Mode",
            subtitle="Disable to lock the effect to a single RGB color below",
        )
        self.rainbow_row.connect("notify::active", lambda *_: self._sync_color_sensitivity())
        ctrl_group.add(self.rainbow_row)

        # Color picker row
        color_row = Adw.ActionRow(
            title="Custom Single Color",
            subtitle="Any 24-bit RGB color (saved into selected palette slot)",
        )
        color_suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER)

        self.hex_entry = Gtk.Entry(width_chars=8, text="#00dcff")
        self.hex_entry.set_tooltip_text("Hex RGB color (#RRGGBB)")
        self.hex_entry.connect("activate", self._on_hex_entry_activate)

        self.color_btn = self._make_color_button(self._custom_rgb, self._on_main_color_picked)
        color_suffix.append(self.hex_entry)
        color_suffix.append(self.color_btn)
        color_row.add_suffix(color_suffix)
        ctrl_group.add(color_row)

        # 7 palette slots row
        pal_row = Adw.ActionRow(
            title="Effect Palette Slots (0–6)",
            subtitle="Click a slot to use it; editing the color above updates that slot",
        )
        pal_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
        self.palette_buttons: List[Gtk.ToggleButton] = []
        for idx in range(7):
            tb = Gtk.ToggleButton(label=str(idx))
            tb.set_size_request(36, 32)
            tb.connect("toggled", self._on_palette_slot_toggled, idx)
            pal_box.append(tb)
            self.palette_buttons.append(tb)
        pal_row.add_suffix(pal_box)
        ctrl_group.add(pal_row)

        box.append(ctrl_group)

        # Apply button bar
        apply_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.END)
        apply_btn = Gtk.Button(label="Apply Lighting to Keyboard")
        apply_btn.add_css_class("suggested-action")
        apply_btn.add_css_class("pill")
        apply_btn.connect("clicked", lambda *_: self._on_apply_lighting())
        apply_box.append(apply_btn)
        box.append(apply_box)

        return scroll

    def _make_color_button(self, initial_rgb: Tuple[int, int, int], callback):
        if hasattr(Gtk, "ColorDialog") and hasattr(Gtk, "ColorDialogButton"):
            dlg = Gtk.ColorDialog()
            dlg.set_with_alpha(False)
            btn = Gtk.ColorDialogButton.new(dlg)
            btn.set_rgba(_rgba_from_rgb(initial_rgb))
            btn.connect("notify::rgba", lambda b, _p: callback(_rgb_from_rgba(b.get_rgba())))
            return btn
        btn = Gtk.ColorButton.new_with_rgba(_rgba_from_rgb(initial_rgb))
        btn.connect("color-set", lambda b: callback(_rgb_from_rgba(b.get_rgba())))
        return btn

    def _set_color_button_rgb(self, btn, rgb: Tuple[int, int, int]) -> None:
        btn.set_rgba(_rgba_from_rgb(rgb))

    def _on_main_color_picked(self, rgb: Tuple[int, int, int]) -> None:
        if self._updating_ui:
            return
        self._custom_rgb = rgb
        self.hex_entry.set_text(format_hex_color(rgb))
        self._palette_colors[self._selected_palette_slot] = rgb
        self._refresh_palette_swatches()

    def _on_hex_entry_activate(self, entry: Gtk.Entry) -> None:
        try:
            rgb = parse_hex_color(entry.get_text())
        except ValueError as exc:
            self._toast(str(exc))
            return
        self._custom_rgb = rgb
        self._updating_ui = True
        try:
            self._set_color_button_rgb(self.color_btn, rgb)
        finally:
            self._updating_ui = False
        self._palette_colors[self._selected_palette_slot] = rgb
        self._refresh_palette_swatches()

    def _on_palette_slot_toggled(self, btn: Gtk.ToggleButton, idx: int) -> None:
        if self._updating_ui or not btn.get_active():
            return
        self._updating_ui = True
        try:
            for i, other in enumerate(self.palette_buttons):
                if i != idx and other.get_active():
                    other.set_active(False)
            self._selected_palette_slot = idx
            rgb = self._palette_colors[idx]
            self._custom_rgb = rgb
            self.hex_entry.set_text(format_hex_color(rgb))
            self._set_color_button_rgb(self.color_btn, rgb)
            self.rainbow_row.set_active(False)
        finally:
            self._updating_ui = False
        self._sync_color_sensitivity()

    def _refresh_palette_swatches(self) -> None:
        css_lines: List[str] = []
        for idx, btn in enumerate(self.palette_buttons):
            cname = f"aula-pal-{idx}"
            if not btn.has_css_class(cname):
                btn.add_css_class(cname)
            r, g, b = self._palette_colors[idx]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            fg = "#111111" if lum > 140 else "#ffffff"
            css_lines.append(
                f"button.{cname} {{ background: rgb({r},{g},{b}); color: {fg}; border-radius: 6px; }}"
            )
        provider = getattr(self, "_pal_css", None)
        if provider is None:
            provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            self._pal_css = provider
        provider.load_from_string("\n".join(css_lines))

    def _on_effect_combo_changed(self, *_args) -> None:
        self._sync_color_sensitivity()

    def _sync_color_sensitivity(self) -> None:
        idx = self.effect_row.get_selected()
        if idx < 0 or idx >= len(EFFECTS_LIST):
            return
        eff = EFFECTS_LIST[idx]
        self.bright_scale.set_sensitive(eff.effect_id != 0)
        self.speed_scale.set_sensitive(eff.supports_speed)
        self.rainbow_row.set_sensitive(eff.supports_color)
        single_active = eff.supports_color and not self.rainbow_row.get_active()
        self.color_btn.set_sensitive(single_active)
        self.hex_entry.set_sensitive(single_active)

    def _apply_quick_preset(
        self,
        eff_id: int,
        bright: int,
        spd: int,
        col_idx: int,
        rgb: Optional[Tuple[int, int, int]],
    ) -> None:
        try:
            with AulaF75Device() as dev:
                dev.set_effect(eff_id, brightness=bright, speed=spd, color_index=col_idx, custom_rgb=rgb)
            self.refresh_all()
            self._toast("Preset applied")
        except (AulaF75Error, ValueError) as exc:
            self._toast(f"Error: {exc}")

    def _on_apply_lighting(self) -> None:
        idx = self.effect_row.get_selected()
        if idx < 0 or idx >= len(EFFECTS_LIST):
            return
        eff = EFFECTS_LIST[idx]
        bright = int(round(self.bright_scale.get_value()))
        spd = int(round(self.speed_scale.get_value()))
        is_rainbow = self.rainbow_row.get_active()

        custom_rgb: Optional[Tuple[int, int, int]] = None
        if eff.supports_color and not is_rainbow:
            try:
                custom_rgb = parse_hex_color(self.hex_entry.get_text())
            except ValueError as exc:
                self._toast(str(exc))
                return
            col_idx = self._selected_palette_slot
        else:
            col_idx = 7 if eff.supports_color else 0

        try:
            with AulaF75Device() as dev:
                dev.set_effect(
                    eff.effect_id,
                    brightness=bright,
                    speed=spd,
                    color_index=col_idx,
                    custom_rgb=custom_rgb,
                )
            self.refresh_all()
            self._toast(f"Applied {eff.name}")
        except AulaF75Error as exc:
            self._toast(f"Error: {exc}")

    # ---------------- Per-Key RGB Page ----------------
    def _build_perkey_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=14, margin_bottom=14, margin_start=16, margin_end=16)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.append(Gtk.Label(label="Brush:"))
        self.pk_color_btn = self._make_color_button((0, 220, 255), self._on_pk_brush_picked)
        toolbar.append(self.pk_color_btn)

        self.pk_hex_entry = Gtk.Entry(width_chars=8, text="#00dcff")
        self.pk_hex_entry.connect("activate", self._on_pk_hex_activate)
        toolbar.append(self.pk_hex_entry)

        self.pk_eraser_btn = Gtk.ToggleButton(label="Eraser (Off)")
        self.pk_eraser_btn.connect("toggled", lambda b: setattr(self.pk_canvas, "eraser_active", b.get_active()))
        toolbar.append(self.pk_eraser_btn)

        fill_btn = Gtk.Button(label="Fill All")
        fill_btn.connect("clicked", self._on_pk_fill_all)
        toolbar.append(fill_btn)

        spacer = Gtk.Box(hexpand=True)
        toolbar.append(spacer)

        for preset in PER_KEY_PRESETS:
            pbtn = Gtk.Button(label=preset.title())
            pbtn.connect("clicked", lambda _b, p=preset: self._on_pk_preset(p))
            toolbar.append(pbtn)

        box.append(toolbar)

        self.pk_canvas = KeyboardCanvas(mode="rgb")
        self.pk_canvas.set_vexpand(True)
        box.append(self.pk_canvas)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hint = Gtk.Label(label="Click or drag across keys to paint. Click Apply to save and activate Custom Per-Key mode (21).")
        hint.add_css_class("dim-label")
        hint.set_hexpand(True)
        hint.set_xalign(0.0)
        bottom.append(hint)

        reload_pk_btn = Gtk.Button(label="Reload from Keyboard")
        reload_pk_btn.connect("clicked", lambda *_: self._reload_perkey())
        bottom.append(reload_pk_btn)

        apply_pk_btn = Gtk.Button(label="Apply Per-Key RGB")
        apply_pk_btn.add_css_class("suggested-action")
        apply_pk_btn.add_css_class("pill")
        apply_pk_btn.connect("clicked", lambda *_: self._on_apply_perkey())
        bottom.append(apply_pk_btn)
        box.append(bottom)

        return box

    def _on_pk_brush_picked(self, rgb: Tuple[int, int, int]) -> None:
        self.pk_canvas.paint_rgb = rgb
        self.pk_eraser_btn.set_active(False)
        self.pk_hex_entry.set_text(format_hex_color(rgb))

    def _on_pk_hex_activate(self, entry: Gtk.Entry) -> None:
        try:
            rgb = parse_hex_color(entry.get_text())
        except ValueError as exc:
            self._toast(str(exc))
            return
        self.pk_canvas.paint_rgb = rgb
        self.pk_eraser_btn.set_active(False)
        self._set_color_button_rgb(self.pk_color_btn, rgb)

    def _on_pk_fill_all(self, *_args) -> None:
        rgb = (0, 0, 0) if self.pk_eraser_btn.get_active() else self.pk_canvas.paint_rgb
        for k in KEYS:
            if not k.is_knob:
                self.pk_canvas.slot_colors[k.slot] = rgb
        self.pk_canvas.queue_draw()

    def _on_pk_preset(self, preset: str) -> None:
        self.pk_canvas.slot_colors = build_per_key_preset(preset)
        self.pk_canvas.queue_draw()

    def _reload_perkey(self) -> None:
        try:
            with AulaF75Device() as dev:
                self.pk_canvas.slot_colors = dev.read_per_key_rgb()
            self.pk_canvas.queue_draw()
            self._toast("Reloaded per-key colors")
        except AulaF75Error as exc:
            self._toast(f"Error: {exc}")

    def _on_apply_perkey(self) -> None:
        try:
            with AulaF75Device() as dev:
                dev.set_per_key_colors(self.pk_canvas.slot_colors, activate_custom=True)
            self.refresh_all()
            self._toast("Per-key RGB applied (Custom mode active)")
        except AulaF75Error as exc:
            self._toast(f"Error: {exc}")

    # ---------------- Keymap Page ----------------
    def _build_keymap_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=14, margin_bottom=14, margin_start=16, margin_end=16)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.append(Gtk.Label(label="Layer:"))
        self.layer_base_btn = Gtk.ToggleButton(label="Base Layer", active=True)
        self.layer_fn_btn = Gtk.ToggleButton(label="Fn Layer")
        self.layer_base_btn.connect("toggled", self._on_layer_toggled, 0)
        self.layer_fn_btn.connect("toggled", self._on_layer_toggled, 1)
        top.append(self.layer_base_btn)
        top.append(self.layer_fn_btn)

        spacer = Gtk.Box(hexpand=True)
        top.append(spacer)

        reload_km_btn = Gtk.Button(label="Reload Layer")
        reload_km_btn.connect("clicked", lambda *_: self._reload_keymap())
        top.append(reload_km_btn)

        write_km_btn = Gtk.Button(label="Write Layer to Keyboard")
        write_km_btn.add_css_class("suggested-action")
        write_km_btn.connect("clicked", lambda *_: self._on_write_keymap())
        top.append(write_km_btn)
        box.append(top)

        self.km_canvas = KeyboardCanvas(mode="keymap")
        self.km_canvas.set_vexpand(True)
        self.km_canvas.on_key_selected = self._on_km_key_selected
        box.append(self.km_canvas)

        editor_group = Adw.PreferencesGroup(title="Selected Key Binding")
        self.km_info_row = Adw.ActionRow(title="Slot 0 (Esc)", subtitle="Current: Esc [00000029]")
        editor_group.add(self.km_info_row)

        assign_row = Adw.ActionRow(title="New Binding", subtitle="Choose a standard key or enter combo like LCtrl+C")
        assign_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER)

        self.km_combo = Gtk.DropDown.new_from_strings(BINDABLE_KEY_CHOICES)
        self.km_combo.set_enable_search(True)
        self.km_combo.connect("notify::selected", self._on_km_combo_changed)
        assign_box.append(self.km_combo)

        self.km_custom_entry = Gtk.Entry(width_chars=16, placeholder_text="e.g. LCtrl+C or Esc")
        assign_box.append(self.km_custom_entry)

        assign_btn = Gtk.Button(label="Set in Buffer")
        assign_btn.connect("clicked", lambda *_: self._on_km_assign_slot())
        assign_box.append(assign_btn)

        assign_row.add_suffix(assign_box)
        editor_group.add(assign_row)
        box.append(editor_group)

        return box

    def _on_layer_toggled(self, btn: Gtk.ToggleButton, layer: int) -> None:
        if self._updating_ui or not btn.get_active():
            return
        self._updating_ui = True
        try:
            (self.layer_fn_btn if layer == 0 else self.layer_base_btn).set_active(False)
            self._current_layer = layer
        finally:
            self._updating_ui = False
        self._reload_keymap()

    def _reload_keymap(self) -> None:
        try:
            with AulaF75Device() as dev:
                self._keymap_buf = dev.read_keymap(layer=self._current_layer)
            self._refresh_km_labels()
            if self.km_canvas.selected_slot is not None:
                self._on_km_key_selected(self.km_canvas.selected_slot)
        except AulaF75Error as exc:
            self._toast(f"Error: {exc}")

    def _refresh_km_labels(self) -> None:
        labels: Dict[int, str] = {}
        for k in KEYS:
            off = k.slot * 4
            labels[k.slot] = decode_key_entry(bytes(self._keymap_buf[off : off + 4]))
        self.km_canvas.keymap_labels = labels
        self.km_canvas.queue_draw()

    def _on_km_key_selected(self, slot: int) -> None:
        k = KEYS_BY_SLOT.get(slot)
        key_name = k.label if k else f"Slot {slot}"
        off = slot * 4
        raw = bytes(self._keymap_buf[off : off + 4])
        decoded = decode_key_entry(raw)
        self.km_info_row.set_title(f"Slot {slot} ({key_name})")
        self.km_info_row.set_subtitle(f"Current: {decoded} [{raw.hex()}]")
        self.km_custom_entry.set_text(decoded if not decoded.startswith(("Special(", "Media(", "Raw(")) else f"raw:{raw.hex()}")

    def _on_km_combo_changed(self, *_args) -> None:
        idx = self.km_combo.get_selected()
        if 0 <= idx < len(BINDABLE_KEY_CHOICES):
            self.km_custom_entry.set_text(BINDABLE_KEY_CHOICES[idx])

    def _on_km_assign_slot(self) -> None:
        slot = self.km_canvas.selected_slot
        if slot is None:
            return
        spec = self.km_custom_entry.get_text().strip()
        try:
            encoded = encode_key_entry(spec)
        except ValueError as exc:
            self._toast(str(exc))
            return
        off = slot * 4
        self._keymap_buf[off : off + 4] = encoded
        self._refresh_km_labels()
        self._on_km_key_selected(slot)
        self._toast("Updated in buffer — click 'Write Layer to Keyboard' to flash")

    def _on_write_keymap(self) -> None:
        try:
            with AulaF75Device() as dev:
                dev.write_keymap(self._keymap_buf, layer=self._current_layer, allow_remove_fn=False)
            self._toast(f"Saved {'Base' if self._current_layer == 0 else 'Fn'} keymap to keyboard")
        except AulaF75Error as exc:
            self._toast(f"Error: {exc}")

    # ---------------- Device & Backup Page ----------------
    def _build_device_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        clamp = Adw.Clamp(maximum_size=880, margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(box)

        info_group = Adw.PreferencesGroup(title="Connected Hardware")
        self.dev_name_row = Adw.ActionRow(title="Device", subtitle="Not connected")
        self.dev_node_row = Adw.ActionRow(title="HID Node", subtitle="—")
        self.dev_batt_row = Adw.ActionRow(title="Battery", subtitle="—")
        info_group.add(self.dev_name_row)
        info_group.add(self.dev_node_row)
        info_group.add(self.dev_batt_row)
        box.append(info_group)

        bk_group = Adw.PreferencesGroup(
            title="Backup &amp; Restore",
            description="Full snapshot of config, palette, per-key RGB, and both keymap layers",
        )
        bk_row = Adw.ActionRow(title="Export or Restore Snapshot")
        bk_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER)
        export_btn = Gtk.Button(label="Export JSON…")
        export_btn.connect("clicked", lambda *_: self._on_export_backup())
        import_btn = Gtk.Button(label="Restore JSON…")
        import_btn.connect("clicked", lambda *_: self._on_import_backup())
        restore_init_btn = Gtk.Button(label="Restore Initial Backup")
        restore_init_btn.add_css_class("destructive-action")
        restore_init_btn.connect("clicked", lambda *_: self._on_restore_initial_backup())
        bk_btns.append(export_btn)
        bk_btns.append(import_btn)
        bk_btns.append(restore_init_btn)
        bk_row.add_suffix(bk_btns)
        bk_group.add(bk_row)
        box.append(bk_group)

        insp_group = Adw.PreferencesGroup(
            title="Config Block Inspector (0x84)",
            description="Toggle Watch to see which bytes change when pressing Fn shortcuts on the keyboard",
        )
        watch_row = Adw.SwitchRow(title="Watch Live Changes (every 300ms)")
        watch_row.connect("notify::active", self._on_watch_toggled)
        insp_group.add(watch_row)

        self.hex_view = Gtk.TextView(editable=False, monospace=True)
        self.hex_view.set_top_margin(8)
        self.hex_view.set_bottom_margin(8)
        self.hex_view.set_left_margin(8)
        self.hex_view.set_right_margin(8)
        frame = Gtk.Frame(child=self.hex_view)
        insp_group.add(frame)

        self.watch_diff_label = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.watch_diff_label.add_css_class("monospace")
        insp_group.add(self.watch_diff_label)
        box.append(insp_group)

        udev_group = Adw.PreferencesGroup(
            title="Permissions / udev Rule (Optional)",
            description="Bazzite already grants user ACL access to /dev/hidraw*; use this on other distros if needed:",
        )
        udev_label = Gtk.Label(
            label='SUBSYSTEM=="hidraw", ATTRS{idVendor}=="258a", ATTRS{idProduct}=="010c", MODE="0660", TAG+="uaccess"',
            selectable=True,
            xalign=0.0,
            wrap=True,
        )
        udev_label.add_css_class("monospace")
        udev_group.add(udev_label)
        box.append(udev_group)

        return scroll

    def _on_export_backup(self) -> None:
        dlg = Gtk.FileDialog(title="Export AULA F75 Backup", initial_name="aula-f75-backup.json")
        dlg.save(self, None, self._finish_export_backup)

    def _finish_export_backup(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            gfile = dlg.save_finish(res)
        except GLib.Error:
            return
        path = Path(gfile.get_path())
        try:
            with AulaF75Device() as dev:
                data = dev.export_backup()
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._toast(f"Exported backup to {path.name}")
        except (AulaF75Error, OSError) as exc:
            self._toast(f"Export failed: {exc}")

    def _on_import_backup(self) -> None:
        dlg = Gtk.FileDialog(title="Restore AULA F75 Backup")
        dlg.open(self, None, self._finish_import_backup)

    def _finish_import_backup(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            gfile = dlg.open_finish(res)
        except GLib.Error:
            return
        path = Path(gfile.get_path())
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            with AulaF75Device() as dev:
                dev.import_backup(data)
            self.refresh_all()
            self._toast(f"Restored {path.name}")
        except (AulaF75Error, OSError, json.JSONDecodeError) as exc:
            self._toast(f"Restore failed: {exc}")

    def _on_restore_initial_backup(self) -> None:
        if not INITIAL_BACKUP_PATH.exists():
            self._toast("No initial safety backup saved yet")
            return
        try:
            data = json.loads(INITIAL_BACKUP_PATH.read_text(encoding="utf-8"))
            with AulaF75Device() as dev:
                dev.import_backup(data)
            self.refresh_all()
            self._toast("Restored initial safety backup")
        except (AulaF75Error, OSError, json.JSONDecodeError) as exc:
            self._toast(f"Restore failed: {exc}")

    def _on_watch_toggled(self, row: Adw.SwitchRow, _pspec) -> None:
        if row.get_active():
            if self._watch_source_id is None:
                self._watch_source_id = GLib.timeout_add(300, self._poll_watch)
        else:
            if self._watch_source_id is not None:
                GLib.source_remove(self._watch_source_id)
                self._watch_source_id = None

    def _poll_watch(self) -> bool:
        try:
            with AulaF75Device() as dev:
                cur = bytes(dev.read_config())
        except AulaF75Error:
            return True
        if self._last_cfg_snapshot is not None and cur != self._last_cfg_snapshot:
            diffs = [
                f"[{i}]=0x{self._last_cfg_snapshot[i]:02x}->0x{cur[i]:02x}"
                for i in range(len(cur))
                if cur[i] != self._last_cfg_snapshot[i]
            ]
            self.watch_diff_label.set_text("Changed: " + "  ".join(diffs))
            self._render_cfg_hex(cur)
        self._last_cfg_snapshot = cur
        return True

    def _render_cfg_hex(self, cfg: bytes) -> None:
        lines = []
        for i in range(0, len(cfg), 16):
            chunk = cfg[i : i + 16]
            hex_s = " ".join(f"{b:02x}" for b in chunk)
            lines.append(f"{i:04x}: {hex_s}")
        self.hex_view.get_buffer().set_text("\n".join(lines))

    # ---------------- Mouse Page ----------------
    def _build_mouse_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        clamp = Adw.Clamp(maximum_size=900, margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(box)

        # Mouse Status Group
        status_group = Adw.PreferencesGroup(title="Connected Mouse")
        self.mouse_model_row = Adw.ActionRow(title="Model", subtitle="Checking...")
        self.mouse_node_row = Adw.ActionRow(title="HID Node", subtitle="—")
        self.mouse_summary_row = Adw.ActionRow(title="Active Profile", subtitle="—")
        status_group.add(self.mouse_model_row)
        status_group.add(self.mouse_node_row)
        status_group.add(self.mouse_summary_row)
        box.append(status_group)

        # Mouse Quick Presets
        preset_group = Adw.PreferencesGroup(
            title="Mouse Quick Presets",
            description="Applies lighting mode and color directly to mouse flash",
        )
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=8, row_spacing=8)
        for label, m_id, spd, rgb in MOUSE_QUICK_PRESETS:
            btn = Gtk.Button(label=label)
            btn.connect(
                "clicked",
                lambda _b, mid=m_id, sp=spd, c=rgb: self._on_mouse_quick_preset(mid, sp, c),
            )
            flow.insert(btn, -1)
        preset_group.add(flow)
        box.append(preset_group)

        # Mouse Lighting Group
        led_group = Adw.PreferencesGroup(title="Mouse Lighting")
        mode_names = [f"{m.mode_id}: {m.name}" for m in MOUSE_LED_MODES]
        self.mouse_mode_row = Adw.ComboRow(title="Lighting Mode", model=Gtk.StringList.new(mode_names))
        led_group.add(self.mouse_mode_row)

        m_spd_row = Adw.ActionRow(title="Animation Speed", subtitle="0 = slowest, 5 = fastest")
        self.mouse_speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 5, 1)
        self.mouse_speed_scale.set_size_request(220, -1)
        self.mouse_speed_scale.set_draw_value(True)
        self.mouse_speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.mouse_speed_scale.set_digits(0)
        m_spd_row.add_suffix(self.mouse_speed_scale)
        led_group.add(m_spd_row)

        m_br_row = Adw.ActionRow(title="Live Preview Brightness", subtitle="Used for Live Preview (RAM) mode (0..4)")
        self.mouse_bright_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 4, 1)
        self.mouse_bright_scale.set_size_request(220, -1)
        self.mouse_bright_scale.set_draw_value(True)
        self.mouse_bright_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.mouse_bright_scale.set_digits(0)
        self.mouse_bright_scale.set_value(4)
        m_br_row.add_suffix(self.mouse_bright_scale)
        led_group.add(m_br_row)

        m_col_row = Adw.ActionRow(
            title="Active Stage / Static Color",
            subtitle="Sets bottom RGB strip color for Static, Mono Water, and DPI Breathing",
        )
        m_col_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER)
        self.mouse_hex_entry = Gtk.Entry(width_chars=8, text="#00dcff")
        self.mouse_hex_entry.connect("activate", self._on_mouse_hex_activate)
        self.mouse_color_btn = self._make_color_button(self._mouse_color_rgb, self._on_mouse_color_picked)
        m_col_box.append(self.mouse_hex_entry)
        m_col_box.append(self.mouse_color_btn)
        m_col_row.add_suffix(m_col_box)
        led_group.add(m_col_row)
        box.append(led_group)

        led_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.END)
        live_btn = Gtk.Button(label="Live Preview (RAM)")
        live_btn.connect("clicked", lambda *_: self._on_apply_mouse_lighting(live=True))
        save_led_btn = Gtk.Button(label="Save Lighting to Flash")
        save_led_btn.add_css_class("suggested-action")
        save_led_btn.add_css_class("pill")
        save_led_btn.connect("clicked", lambda *_: self._on_apply_mouse_lighting(live=False))
        led_actions.append(live_btn)
        led_actions.append(save_led_btn)
        box.append(led_actions)

        # DPI Stages Group
        dpi_group = Adw.PreferencesGroup(
            title="DPI Stages (1–6) &amp; Stage Colors",
            description="Configure active stage, enabled stages, DPI levels (200–12800), and per-stage RGB color",
        )
        dpi_str_list = [f"{v} DPI" for v in DPI_VALUES]
        self.mouse_stage_active_btns: List[Gtk.ToggleButton] = []
        self.mouse_stage_enable_chks: List[Gtk.CheckButton] = []
        self.mouse_stage_dpi_drops: List[Gtk.DropDown] = []
        self.mouse_stage_color_btns = []

        for idx in range(6):
            row = Adw.ActionRow(title=f"Stage {idx + 1}")
            ctl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER)

            act_btn = Gtk.ToggleButton(label="Active")
            act_btn.connect("toggled", self._on_mouse_stage_active_toggled, idx)
            self.mouse_stage_active_btns.append(act_btn)
            ctl.append(act_btn)

            en_chk = Gtk.CheckButton(label="Enabled", active=True)
            self.mouse_stage_enable_chks.append(en_chk)
            ctl.append(en_chk)

            drop = Gtk.DropDown.new_from_strings(dpi_str_list)
            self.mouse_stage_dpi_drops.append(drop)
            ctl.append(drop)

            cbtn = self._make_color_button((255, 0, 0), lambda rgb, s=idx: self._on_mouse_stage_color_picked(s, rgb))
            self.mouse_stage_color_btns.append(cbtn)
            ctl.append(cbtn)

            row.add_suffix(ctl)
            dpi_group.add(row)
        box.append(dpi_group)

        dpi_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.END)
        save_dpi_btn = Gtk.Button(label="Save DPI & Colors")
        save_dpi_btn.add_css_class("suggested-action")
        save_dpi_btn.add_css_class("pill")
        save_dpi_btn.connect("clicked", lambda *_: self._on_save_mouse_dpi())
        dpi_actions.append(save_dpi_btn)
        box.append(dpi_actions)

        # Mouse Buttons Group
        btn_group = Adw.PreferencesGroup(
            title="Mouse Button Remapping",
            description="At least one button must remain assigned to Left Click",
        )
        func_labels = [f"{name} (0x{code:02x})" for code, name in MOUSE_BUTTON_FUNCTIONS]
        self.mouse_btn_drops: Dict[int, Gtk.DropDown] = {}
        for slot, label in MOUSE_BUTTON_SLOTS:
            row = Adw.ActionRow(title=label, subtitle=f"Flash slot {slot}")
            drop = Gtk.DropDown.new_from_strings(func_labels)
            self.mouse_btn_drops[slot] = drop
            row.add_suffix(drop)
            btn_group.add(row)
        box.append(btn_group)

        btn_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.END)
        save_btns_btn = Gtk.Button(label="Save Mouse Buttons")
        save_btns_btn.add_css_class("suggested-action")
        save_btns_btn.connect("clicked", lambda *_: self._on_save_mouse_buttons())
        btn_actions.append(save_btns_btn)
        box.append(btn_actions)

        # Mouse Backup Group
        mbk_group = Adw.PreferencesGroup(
            title="Mouse Backup &amp; Restore",
            description="Safely snapshots 0x08..0x3f (USB VID/PID header 0x00..0x07 is never written)",
        )
        mbk_row = Adw.ActionRow(title="Mouse Flash Snapshot")
        mbk_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER)
        m_exp_btn = Gtk.Button(label="Export JSON…")
        m_exp_btn.connect("clicked", lambda *_: self._on_mouse_export_backup())
        m_imp_btn = Gtk.Button(label="Restore JSON…")
        m_imp_btn.connect("clicked", lambda *_: self._on_mouse_import_backup())
        m_init_btn = Gtk.Button(label="Restore Initial Backup")
        m_init_btn.add_css_class("destructive-action")
        m_init_btn.connect("clicked", lambda *_: self._on_mouse_restore_initial())
        mbk_box.append(m_exp_btn)
        mbk_box.append(m_imp_btn)
        mbk_box.append(m_init_btn)
        mbk_row.add_suffix(mbk_box)
        mbk_group.add(mbk_row)
        box.append(mbk_group)

        return scroll

    def _on_mouse_color_picked(self, rgb: Tuple[int, int, int]) -> None:
        if self._updating_ui:
            return
        self._mouse_color_rgb = rgb
        self.mouse_hex_entry.set_text(format_hex_color(rgb))

    def _on_mouse_hex_activate(self, entry: Gtk.Entry) -> None:
        try:
            rgb = parse_hex_color(entry.get_text())
        except ValueError as exc:
            self._toast(str(exc))
            return
        self._mouse_color_rgb = rgb
        self._updating_ui = True
        try:
            self._set_color_button_rgb(self.mouse_color_btn, rgb)
        finally:
            self._updating_ui = False

    def _on_mouse_stage_active_toggled(self, btn: Gtk.ToggleButton, idx: int) -> None:
        if self._updating_ui or not btn.get_active():
            return
        self._updating_ui = True
        try:
            for i, other in enumerate(self.mouse_stage_active_btns):
                if i != idx and other.get_active():
                    other.set_active(False)
        finally:
            self._updating_ui = False

    def _on_mouse_stage_color_picked(self, stage: int, rgb: Tuple[int, int, int]) -> None:
        if self._updating_ui:
            return
        self._mouse_stage_colors[stage] = rgb

    def _on_mouse_quick_preset(self, mode_id: int, speed: int, rgb: Optional[Tuple[int, int, int]]) -> None:
        try:
            with InstantMouseDevice() as dev:
                dev.set_led(mode_id, speed=speed, rgb=rgb)
            self.refresh_all()
            self._toast("Mouse preset saved")
        except (MouseProtocolError, ValueError) as exc:
            self._toast(f"Mouse error: {exc}")

    def _on_apply_mouse_lighting(self, live: bool = False) -> None:
        idx = self.mouse_mode_row.get_selected()
        if idx < 0 or idx >= len(MOUSE_LED_MODES):
            return
        mode = MOUSE_LED_MODES[idx]
        speed = int(round(self.mouse_speed_scale.get_value()))
        bright = int(round(self.mouse_bright_scale.get_value()))
        try:
            rgb = parse_hex_color(self.mouse_hex_entry.get_text()) if mode.uses_color else None
        except ValueError as exc:
            self._toast(str(exc))
            return
        try:
            with InstantMouseDevice() as dev:
                if live:
                    dev.set_live_lighting(mode.mode_id, speed=speed, brightness=bright, rgb=rgb)
                    self._toast(f"Live mouse preview: {mode.name}")
                else:
                    dev.set_led(mode.mode_id, speed=speed, rgb=rgb)
                    self.refresh_all()
                    self._toast(f"Saved mouse lighting: {mode.name}")
        except MouseProtocolError as exc:
            self._toast(f"Mouse error: {exc}")

    def _on_save_mouse_dpi(self) -> None:
        try:
            with InstantMouseDevice() as dev:
                _, orig = dev.read_header_and_config()
                cfg = orig.copy()
                active_stage = 0
                mask = 0
                for idx in range(6):
                    if self.mouse_stage_active_btns[idx].get_active():
                        active_stage = idx
                    if self.mouse_stage_enable_chks[idx].get_active():
                        mask |= 1 << idx
                    dpi_idx = self.mouse_stage_dpi_drops[idx].get_selected()
                    if 0 <= dpi_idx < len(DPI_VALUES):
                        cfg.set_dpi(idx, DPI_VALUES[dpi_idx])
                    cfg.set_stage_color(idx, self._mouse_stage_colors[idx])
                cfg.set_dpi_enabled_mask(mask)
                cfg.set_active_dpi_stage(active_stage)
                dev.save_config(cfg, original_cfg=orig)
            self.refresh_all()
            self._toast("Mouse DPI stages & colors saved")
        except (MouseProtocolError, ValueError) as exc:
            self._toast(f"Mouse error: {exc}")

    def _on_save_mouse_buttons(self) -> None:
        try:
            with InstantMouseDevice() as dev:
                _, orig = dev.read_header_and_config()
                cfg = orig.copy()
                for slot, drop in self.mouse_btn_drops.items():
                    fidx = drop.get_selected()
                    if 0 <= fidx < len(MOUSE_BUTTON_FUNCTIONS):
                        cfg.set_button(slot, MOUSE_BUTTON_FUNCTIONS[fidx][0])
                dev.save_config(cfg, original_cfg=orig, allow_remove_left=False)
            self.refresh_all()
            self._toast("Mouse button mapping saved")
        except (MouseProtocolError, ValueError) as exc:
            self._toast(f"Mouse error: {exc}")

    def _on_mouse_export_backup(self) -> None:
        dlg = Gtk.FileDialog(title="Export Mouse Backup", initial_name="ant-gm320-mouse-backup.json")
        dlg.save(self, None, self._finish_mouse_export)

    def _finish_mouse_export(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            gfile = dlg.save_finish(res)
        except GLib.Error:
            return
        path = Path(gfile.get_path())
        try:
            with InstantMouseDevice() as dev:
                data = dev.export_backup()
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._toast(f"Exported mouse backup to {path.name}")
        except (MouseProtocolError, OSError) as exc:
            self._toast(f"Export failed: {exc}")

    def _on_mouse_import_backup(self) -> None:
        dlg = Gtk.FileDialog(title="Restore Mouse Backup")
        dlg.open(self, None, self._finish_mouse_import)

    def _finish_mouse_import(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            gfile = dlg.open_finish(res)
        except GLib.Error:
            return
        path = Path(gfile.get_path())
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            with InstantMouseDevice() as dev:
                dev.import_backup(data)
            self.refresh_all()
            self._toast(f"Restored mouse backup {path.name}")
        except (MouseProtocolError, OSError, json.JSONDecodeError) as exc:
            self._toast(f"Restore failed: {exc}")

    def _on_mouse_restore_initial(self) -> None:
        if not MOUSE_INITIAL_BACKUP_PATH.exists():
            self._toast("No initial mouse backup saved yet")
            return
        try:
            data = json.loads(MOUSE_INITIAL_BACKUP_PATH.read_text(encoding="utf-8"))
            with InstantMouseDevice() as dev:
                dev.import_backup(data)
            self.refresh_all()
            self._toast("Restored initial mouse backup")
        except (MouseProtocolError, OSError, json.JSONDecodeError) as exc:
            self._toast(f"Restore failed: {exc}")

    # ---------------- Global Refresh ----------------
    def refresh_all(self) -> None:
        kb_pill = "KB: Off"
        mouse_pill = "Mouse: Off"

        info = find_aula_f75_hidraw()
        if not info:
            self.dev_name_row.set_subtitle("AULA F75 (258a:010c) not found")
            self.dev_node_row.set_subtitle("Connect keyboard via USB cable")
            self.dev_batt_row.set_subtitle("—")
        else:
            try:
                with AulaF75Device(info["path"]) as dev:
                    status = dev.read_status()
                    state = dev.get_lighting_state()
                    per_key = dev.read_per_key_rgb()
                    km = dev.read_keymap(layer=self._current_layer)

                batt_txt = f"{status['battery']}%" if status["battery"] is not None else "Wired"
                kb_pill = f"KB {batt_txt}"
                self.dev_name_row.set_subtitle(f"{info['hid_name']} (258a:010c)")
                self.dev_node_row.set_subtitle(f"{info['path']} ({info['phys']})")
                self.dev_batt_row.set_subtitle(batt_txt)

                self._updating_ui = True
                try:
                    eff_id = state["effect_id"]
                    for i, e in enumerate(EFFECTS_LIST):
                        if e.effect_id == eff_id:
                            self.effect_row.set_selected(i)
                            break
                    self.bright_scale.set_value(state["brightness"])
                    self.speed_scale.set_value(state["speed"])
                    self.rainbow_row.set_active(state["is_rainbow"])

                    self._palette_colors = list(state["palette"])
                    if not state["is_rainbow"] and state["color_index"] < 7:
                        self._selected_palette_slot = state["color_index"]
                    self.palette_buttons[self._selected_palette_slot].set_active(True)
                    for idx, tb in enumerate(self.palette_buttons):
                        if idx != self._selected_palette_slot:
                            tb.set_active(False)

                    rgb = self._palette_colors[self._selected_palette_slot]
                    self._custom_rgb = rgb
                    self.hex_entry.set_text(format_hex_color(rgb))
                    self._set_color_button_rgb(self.color_btn, rgb)
                    self._refresh_palette_swatches()
                finally:
                    self._updating_ui = False

                self._sync_color_sensitivity()

                self.pk_canvas.slot_colors = per_key
                self.pk_canvas.queue_draw()

                self._keymap_buf = km
                self._refresh_km_labels()
                if self.km_canvas.selected_slot is not None:
                    self._on_km_key_selected(self.km_canvas.selected_slot)

                self._last_cfg_snapshot = state["raw_config"]
                self._render_cfg_hex(state["raw_config"])
            except AulaF75Error as exc:
                kb_pill = "KB Err"
                self._toast(str(exc))

        mouse_pill = self._refresh_mouse()
        self.status_pill.set_text(f"{kb_pill} • {mouse_pill}")

    def _refresh_mouse(self) -> str:
        minfo = find_instant_mouse_hidraw()
        if not minfo:
            self.mouse_model_row.set_subtitle("Instant A825 mouse (30fa:1440) not found")
            self.mouse_node_row.set_subtitle("—")
            self.mouse_summary_row.set_subtitle("—")
            return "Mouse: Off"

        try:
            with InstantMouseDevice(minfo["path"]) as dev:
                st = dev.read_state()
        except MouseProtocolError as exc:
            self.mouse_model_row.set_subtitle(f"{minfo['model_name']} ({minfo['vid_pid']})")
            self.mouse_node_row.set_subtitle(minfo["path"])
            self.mouse_summary_row.set_subtitle(f"Error: {exc}")
            return "Mouse Err"

        self.mouse_model_row.set_subtitle(f"{minfo['model_name']} ({minfo['vid_pid']})")
        self.mouse_node_row.set_subtitle(f"{minfo['path']} ({minfo['phys']})")
        self.mouse_summary_row.set_subtitle(
            f"Stage {st['active_stage']} ({st['active_dpi']} DPI) • {st['led_mode_name']}"
        )

        self._updating_ui = True
        try:
            for i, m in enumerate(MOUSE_LED_MODES):
                if m.mode_id == st["led_mode_id"]:
                    self.mouse_mode_row.set_selected(i)
                    break
            self.mouse_speed_scale.set_value(st["led_speed"])
            self._mouse_color_rgb = st["active_color"]
            self.mouse_hex_entry.set_text(st["active_color_hex"])
            self._set_color_button_rgb(self.mouse_color_btn, st["active_color"])

            for idx, s in enumerate(st["stages"]):
                self.mouse_stage_active_btns[idx].set_active(s["active"])
                self.mouse_stage_enable_chks[idx].set_active(s["enabled"])
                if s["dpi"] in DPI_VALUES:
                    self.mouse_stage_dpi_drops[idx].set_selected(DPI_VALUES.index(s["dpi"]))
                self._mouse_stage_colors[idx] = s["rgb"]
                self._set_color_button_rgb(self.mouse_stage_color_btns[idx], s["rgb"])

            func_codes = [c for c, _ in MOUSE_BUTTON_FUNCTIONS]
            for b in st["buttons"]:
                drop = self.mouse_btn_drops.get(b["slot"])
                if drop is not None and b["code"] in func_codes:
                    drop.set_selected(func_codes.index(b["code"]))
        finally:
            self._updating_ui = False

        return f"Mouse {st['active_dpi']} DPI"


class AulaF75App(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="io.github.aulaf75.Control")

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = AulaF75Window(self)
        win.present()


def main(argv: Optional[List[str]] = None) -> int:
    Adw.init()
    app = AulaF75App()
    return app.run(argv if argv is not None else sys.argv)
