"""sRGB <-> OKLab conversions and helpers for blending colours perceptually."""
import numpy as np


def hex_to_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def rgb_to_hex(rgb):
    rgb = np.clip(rgb, 0, 1)
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def _to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])


def rgb_to_oklab(rgb):
    lms = _M1 @ _to_linear(np.asarray(rgb, float))
    return _M2 @ np.cbrt(lms)


def oklab_to_rgb(lab):
    lms = np.linalg.solve(_M2, np.asarray(lab, float)) ** 3
    return _to_srgb(np.linalg.solve(_M1, lms))


def hex_to_oklab(h):
    return rgb_to_oklab(hex_to_rgb(h))


def oklab_to_hex(lab):
    return rgb_to_hex(oklab_to_rgb(lab))
