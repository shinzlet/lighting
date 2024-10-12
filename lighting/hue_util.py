from typing import Tuple

from .kelvin import k_to_rgb

def rgb_to_hue_and_saturation(r: int, g: int, b: int) -> Tuple[float, float]:
    # Normalize RGB values to [0, 1] range
    r_normalized = r / 255.0
    g_normalized = g / 255.0
    b_normalized = b / 255.0

    # Find max and min values among the normalized RGB
    max_val = max(r_normalized, g_normalized, b_normalized)
    min_val = min(r_normalized, g_normalized, b_normalized)

    # Calculate Lightness (L) as the midpoint between max and min
    lightness = (max_val + min_val) / 2

    # Calculate Delta (the difference between max and min)
    delta = max_val - min_val

    # Calculate Hue
    if delta == 0:
        hue = 0  # When delta is 0, hue is undefined, so we set it to 0
    elif max_val == r_normalized:
        hue = (60 * (((g_normalized - b_normalized) / delta) % 6))
    elif max_val == g_normalized:
        hue = (60 * (((b_normalized - r_normalized) / delta) + 2))
    elif max_val == b_normalized:
        hue = (60 * (((r_normalized - g_normalized) / delta) + 4))

    # Ensure hue is positive
    if hue < 0:
        hue += 360

    # Calculate Saturation
    if delta == 0:
        saturation = 0  # No saturation when the color is grayscale (delta = 0)
    else:
        if lightness <= 0.5:
            saturation = delta / (max_val + min_val)
        else:
            saturation = delta / (2.0 - max_val - min_val)

    return hue, saturation

def k_to_hue_and_saturation(kelvin: int) -> Tuple[float, float]:
    # Use the provided k_to_rgb function to get the RGB values
    r, g, b = k_to_rgb(kelvin)
    
    # Convert the RGB values to hue and saturation components of HSL
    return rgb_to_hue_and_saturation(r, g, b)