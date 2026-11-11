"""One color per method, shared by every E07 figure, video and the report.

The eight methods shown in the trace plots and videos each own one hue of the validated
categorical palette, in fixed order; every other method is grey. Color follows the method, never
its position in a list, so a method looks the same in the bars, the traces, the box plot and the
video panels.
"""

TRUTH = "#0b0b0b"  # OpenCap
OTHER = "#b5b4ae"  # methods not featured in the traces and videos

FEATURED = {
    "aligned_trunk_upper_watch": "#2a78d6",  # blue
    "wearmocap_watch": "#eb6834",  # orange
    "opensense_trunk_upper_watch_phone": "#1baf7a",  # aqua
    "constraint_watch_swing": "#eda100",  # yellow
    "own_gru_allsensors_personal": "#e87ba4",  # magenta
    "mobileposer_rw_rp_h": "#008300",  # green
    "own_gru_watch_xplayer": "#6250d6",  # violet
    "imucoco_rw_rp_h": "#e34948",  # red
}


def color(name):
    """Hex color of a method."""
    return FEATURED.get(name, OTHER)


def bgr(name_or_hex):
    """OpenCV BGR tuple of a method (or of a hex string)."""
    h = name_or_hex if name_or_hex.startswith("#") else color(name_or_hex)
    r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
    return (b, g, r)
