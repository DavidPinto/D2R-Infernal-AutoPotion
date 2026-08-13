"""Reusable CustomTkinter widgets used across the app tabs."""

from __future__ import annotations

import customtkinter as ctk

# Shared palette (dark theme accent).
ACCENT = "#2f80ed"
ACCENT_HOVER = "#1c5fbf"
DANGER = "#eb5757"
GOOD = "#27ae60"
WARN = "#f2994a"
MERC = "#bb6bd9"


def heading(parent, text: str) -> ctk.CTkLabel:
    """A bold section heading label."""
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=15, weight="bold"))


def hint(parent, text: str) -> ctk.CTkLabel:
    """A muted, wrapping helper-text label."""
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=11),
                        text_color="gray60", justify="left", wraplength=420)


def labeled_slider(parent, label: str, minimum: float, maximum: float,
                   value: float, command, step: float = 1.0, fmt: str = "{:.0f}"):
    """Return (frame, value_label) for an integer/float slider with a live readout."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    top = ctk.CTkFrame(frame, fg_color="transparent")
    top.pack(fill="x")
    ctk.CTkLabel(top, text=label, font=ctk.CTkFont(size=12)).pack(side="left")
    val_label = ctk.CTkLabel(top, text=fmt.format(value), font=ctk.CTkFont(size=12, weight="bold"),
                             text_color=ACCENT, width=48)
    val_label.pack(side="right")

    steps = int(round((maximum - minimum) / step))
    slider = ctk.CTkSlider(frame, from_=minimum, to=maximum, number_of_steps=steps,
                           command=lambda v: _on_slide(v, val_label, command, fmt))
    slider.set(value)
    slider.pack(fill="x", pady=(2, 0))

    def set_value(v):
        slider.set(v)
        val_label.configure(text=fmt.format(v))

    frame.set_value = set_value  # type: ignore[attr-defined]
    return frame, val_label


def _on_slide(value, val_label, command, fmt):
    """Slider callback: refresh the readout and forward the value."""
    val_label.configure(text=fmt.format(value))
    command(value)


def stat_bar(parent, label: str, color: str) -> tuple[ctk.CTkLabel, ctk.CTkProgressBar, ctk.CTkLabel]:
    """A labeled progress bar with a numeric readout on the right."""
    top = ctk.CTkFrame(parent, fg_color="transparent")
    top.pack(fill="x")
    name = ctk.CTkLabel(top, text=label, font=ctk.CTkFont(size=13, weight="bold"))
    name.pack(side="left")
    readout = ctk.CTkLabel(top, text="--", font=ctk.CTkFont(size=12))
    readout.pack(side="right")

    bar = ctk.CTkProgressBar(parent, height=20, corner_radius=6)
    bar.configure(progress_color=color)
    bar.set(0)
    bar.pack(fill="x", pady=(2, 8))
    return name, bar, readout


def append_log(textbox, line: str) -> None:
    """Append a line to a disabled Text widget, keeping it scrolled to the end."""
    textbox.configure(state="normal")
    textbox.insert("end", line + "\n")
    textbox.see("end")
    textbox.configure(state="disabled")


def color_for_percent(pct: int, merc: bool = False) -> str:
    """Traffic-light colour for a percentage (merc bars use a fixed purple)."""
    if merc:
        return MERC
    if pct <= 25:
        return DANGER
    if pct <= 50:
        return WARN
    return GOOD
