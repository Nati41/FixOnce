#!/usr/bin/env python3
"""
Create FixOnce icons for Windows (.ico) and Mac (.icns)
Design: Blue circle with white brain/memory symbol
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import struct
import io

FIXONCE_DIR = Path(__file__).parent.parent

# Colors
BLUE = (66, 133, 244)      # Google Blue
DARK_BLUE = (25, 103, 210)  # Darker blue for depth
WHITE = (255, 255, 255)

def create_brain_icon(size: int) -> Image.Image:
    """Create a brain/memory icon at given size."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw circular background with gradient effect
    padding = size // 16

    # Main circle (blue)
    draw.ellipse(
        [padding, padding, size - padding, size - padding],
        fill=BLUE
    )

    # Inner circle for depth (slightly darker)
    inner_pad = padding + size // 20
    draw.ellipse(
        [inner_pad, inner_pad, size - inner_pad, size - inner_pad],
        fill=BLUE
    )

    # Draw stylized brain/memory symbol (simplified as "FO" or infinity-like shape)
    center_x = size // 2
    center_y = size // 2
    symbol_size = size // 3

    # Draw infinity symbol (represents "never forget")
    line_width = max(2, size // 20)

    # Left loop of infinity
    left_center = (center_x - symbol_size // 3, center_y)
    loop_radius = symbol_size // 3

    draw.ellipse(
        [left_center[0] - loop_radius, left_center[1] - loop_radius,
         left_center[0] + loop_radius, left_center[1] + loop_radius],
        outline=WHITE,
        width=line_width
    )

    # Right loop of infinity
    right_center = (center_x + symbol_size // 3, center_y)
    draw.ellipse(
        [right_center[0] - loop_radius, right_center[1] - loop_radius,
         right_center[0] + loop_radius, right_center[1] + loop_radius],
        outline=WHITE,
        width=line_width
    )

    # Small dot in center (memory point)
    dot_radius = max(2, size // 25)
    draw.ellipse(
        [center_x - dot_radius, center_y - dot_radius,
         center_x + dot_radius, center_y + dot_radius],
        fill=WHITE
    )

    return img


def create_text_icon(size: int, text: str = "FO") -> Image.Image:
    """Create a simple text-based icon."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw circular background
    padding = size // 16
    draw.ellipse(
        [padding, padding, size - padding, size - padding],
        fill=BLUE
    )

    # Try to use a nice font, fallback to default
    font_size = size // 2
    try:
        # Try common fonts
        for font_name in ['Arial Bold', 'Helvetica Bold', 'Arial', 'Helvetica']:
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except:
                continue
        else:
            font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()

    # Draw text centered
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (size - text_width) // 2
    y = (size - text_height) // 2 - bbox[1]

    draw.text((x, y), text, fill=WHITE, font=font)

    return img


def create_ico(images: list, output_path: Path):
    """Create Windows .ico file from list of PIL images."""
    # ICO format: multiple sizes bundled together
    # Common sizes: 16, 32, 48, 64, 128, 256

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save as ICO using PIL
    # PIL can save ICO directly
    images[0].save(
        str(output_path),
        format='ICO',
        sizes=[(img.size[0], img.size[1]) for img in images]
    )


def create_icns(images: dict, output_path: Path):
    """Create Mac .icns file from dict of size->image."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ICNS format is complex, use iconutil if available (Mac only)
    # For now, save as PNG and provide instructions

    # Save largest as PNG (Mac can use PNG icons too)
    largest = max(images.keys())
    png_path = output_path.with_suffix('.png')
    images[largest].save(str(png_path), 'PNG')

    # Try to create .icns using iconutil (Mac only)
    import subprocess
    import tempfile
    import shutil

    try:
        # Create iconset directory
        with tempfile.TemporaryDirectory() as tmpdir:
            iconset_path = Path(tmpdir) / "FixOnce.iconset"
            iconset_path.mkdir()

            # Save all required sizes
            size_names = {
                16: 'icon_16x16.png',
                32: 'icon_16x16@2x.png',
                32: 'icon_32x32.png',
                64: 'icon_32x32@2x.png',
                128: 'icon_128x128.png',
                256: 'icon_128x128@2x.png',
                256: 'icon_256x256.png',
                512: 'icon_256x256@2x.png',
                512: 'icon_512x512.png',
                1024: 'icon_512x512@2x.png',
            }

            for size, name in size_names.items():
                if size in images:
                    images[size].save(str(iconset_path / name), 'PNG')
                else:
                    # Resize from largest available
                    resized = images[largest].resize((size, size), Image.LANCZOS)
                    resized.save(str(iconset_path / name), 'PNG')

            # Run iconutil
            result = subprocess.run(
                ['iconutil', '-c', 'icns', str(iconset_path), '-o', str(output_path)],
                capture_output=True
            )

            if result.returncode == 0:
                print(f"  Created: {output_path}")
                return True
    except Exception as e:
        print(f"  Note: Could not create .icns (iconutil not available)")

    print(f"  Created PNG: {png_path}")
    return False


def main():
    print("Creating FixOnce icons...")

    # Generate icons at various sizes
    sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    images = {}

    for size in sizes:
        images[size] = create_brain_icon(size)
        print(f"  Generated {size}x{size}")

    # Save Windows .ico
    ico_path = FIXONCE_DIR / "assets" / "FixOnce.ico"
    try:
        # PIL ICO save needs specific format
        ico_images = [images[s] for s in [256, 128, 64, 48, 32, 16] if s in images]
        ico_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to format PIL can save as ICO
        ico_images[0].save(
            str(ico_path),
            format='ICO',
            sizes=[(img.size[0], img.size[1]) for img in ico_images],
            append_images=ico_images[1:]
        )
        print(f"  Windows: {ico_path}")
    except Exception as e:
        print(f"  Windows ICO error: {e}")
        # Fallback: save as PNG
        png_path = FIXONCE_DIR / "assets" / "FixOnce.png"
        images[256].save(str(png_path), 'PNG')
        print(f"  Saved PNG instead: {png_path}")

    # Save Mac .icns
    icns_path = FIXONCE_DIR / "assets" / "FixOnce.icns"
    create_icns(images, icns_path)

    # Also save a preview PNG
    preview_path = FIXONCE_DIR / "assets" / "FixOnce-preview.png"
    images[256].save(str(preview_path), 'PNG')
    print(f"  Preview: {preview_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
