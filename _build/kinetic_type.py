"""
Kinetic Typography Video Generator
Style: D2D / Brutalist - black bg, bold text, hard cuts, subtext
"""

from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy import ImageSequenceClip, concatenate_videoclips
import os
from pathlib import Path

# Config - reduced for memory
WIDTH, HEIGHT = 1280, 720
FPS = 24

# Colors
BLACK = (0, 0, 0)
WHITE = (230, 230, 230)
GRAY = (120, 120, 120)
GOLD = (212, 175, 55)

# Configurable output directory
OUTPUT_DIR = os.environ.get(
    'FORTUNE0_VIDEO_OUTPUT',
    str(Path.home() / 'fortune0-videos')
)

def ensure_output_dir(path=None):
    """Create output directory if it doesn't exist"""
    target = path or OUTPUT_DIR
    Path(target).mkdir(parents=True, exist_ok=True)
    return target

def find_font(preferred_names, fallback_names):
    """Find first available font from preference list"""
    import platform

    # macOS font paths
    if platform.system() == 'Darwin':
        search_paths = [
            Path.home() / 'Library/Fonts',
            Path('/Library/Fonts'),
            Path('/System/Library/Fonts'),
        ]

        # Try preferred fonts first
        for font_name in preferred_names:
            for base_path in search_paths:
                for ext in ['.ttf', '.ttc', '.otf']:
                    font_path = base_path / f"{font_name}{ext}"
                    if font_path.exists():
                        return str(font_path)

        # Try fallback fonts
        for font_name in fallback_names:
            for base_path in search_paths:
                for ext in ['.ttf', '.ttc', '.otf']:
                    font_path = base_path / f"{font_name}{ext}"
                    if font_path.exists():
                        return str(font_path)

    # Linux font paths
    else:
        search_paths = ['/usr/share/fonts/truetype', '/usr/share/fonts/opentype']
        for font_name in preferred_names + fallback_names:
            for base_path in search_paths:
                for root, dirs, files in os.walk(base_path):
                    for f in files:
                        if font_name.lower() in f.lower() and f.endswith(('.ttf', '.otf')):
                            return os.path.join(root, f)

    return None

# Detect fonts at module load
FONT_BOLD = find_font(
    preferred_names=['Poppins-Bold', 'Helvetica-Bold', 'Arial-Bold'],
    fallback_names=['DejaVuSans-Bold', 'LiberationSans-Bold', 'Helvetica', 'Arial']
)

FONT_CONDENSED = find_font(
    preferred_names=['Poppins-Medium', 'HelveticaNeue-Medium', 'Arial-Narrow'],
    fallback_names=['DejaVuSansCondensed-Bold', 'LiberationSans-Narrow-Bold']
)

def get_font(size, condensed=False):
    """Get font at specified size with error handling"""
    target_font = FONT_CONDENSED if condensed else FONT_BOLD
    if target_font:
        try:
            return ImageFont.truetype(target_font, size)
        except Exception as e:
            print(f"Warning: Failed to load font {target_font}: {e}")

    print("Warning: Using default font (may not render properly)")
    return ImageFont.load_default()

def draw_centered_text(draw, text, y, font, color, outline=False):
    """Draw text centered horizontally, handles multiline"""
    lines = text.split('\n')
    line_height = font.size + 10

    total_height = len(lines) * line_height
    start_y = y - total_height // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (WIDTH - text_width) // 2
        line_y = start_y + i * line_height

        if outline:
            # Draw outline text (stroke effect)
            for offset in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                draw.text((x + offset[0], line_y + offset[1]), line, fill=BLACK, font=font)
            draw.text((x, line_y), line, fill=GRAY, font=font)
        else:
            draw.text((x, line_y), line, fill=color, font=font)

def create_slide(headline, subtext=None, duration=1.5, headline_color=WHITE,
                 headline_size=160, outline_headline=False, subtext_color=GRAY):
    """Create a single slide with headline and optional subtext"""
    frames = []
    total_frames = int(FPS * duration)

    # Fonts
    headline_font = get_font(headline_size, condensed=True)
    subtext_font = get_font(32, condensed=False)

    for i in range(total_frames):
        img = Image.new('RGB', (WIDTH, HEIGHT), BLACK)
        draw = ImageDraw.Draw(img)

        t = i / total_frames

        # Quick fade in for first 10% of duration
        fade = min(1, t / 0.1) if t < 0.1 else 1

        # Headline
        headline_y = HEIGHT // 2 - 60
        if subtext:
            headline_y = HEIGHT // 2 - 80

        h_color = tuple(int(c * fade) for c in headline_color)
        draw_centered_text(draw, headline.upper(), headline_y, headline_font,
                          h_color, outline=outline_headline)

        # Subtext
        if subtext:
            s_color = tuple(int(c * fade) for c in subtext_color)
            subtext_y = HEIGHT // 2 + 80
            draw_centered_text(draw, subtext.upper(), subtext_y, subtext_font, s_color)

        frames.append(np.array(img))

    return frames

def create_transition(duration=0.1):
    """Create a quick black frame transition"""
    frames = []
    total_frames = max(1, int(FPS * duration))

    for _ in range(total_frames):
        img = Image.new('RGB', (WIDTH, HEIGHT), BLACK)
        frames.append(np.array(img))

    return frames

def create_video_from_script(script, output_path):
    """
    Create video from a script.

    Script format:
    [
        {"headline": "TEXT", "subtext": "optional", "duration": 1.5, "outline": False},
        ...
    ]
    """
    all_frames = []

    for i, slide in enumerate(script):
        print(f"  Creating slide {i+1}/{len(script)}: {slide['headline'][:30]}...")

        headline = slide.get('headline', '')
        subtext = slide.get('subtext', None)
        duration = slide.get('duration', 1.5)
        outline = slide.get('outline', False)
        color = slide.get('color', WHITE)
        size = slide.get('size', 160)

        frames = create_slide(
            headline,
            subtext,
            duration,
            headline_color=color,
            headline_size=size,
            outline_headline=outline
        )
        all_frames.extend(frames)

        # Add transition between slides
        if i < len(script) - 1:
            all_frames.extend(create_transition(0.08))

    print(f"Total frames: {len(all_frames)}")
    print("Creating video clip...")

    try:
        # Check disk space
        import shutil
        stat = shutil.disk_usage(os.path.dirname(output_path) or '.')
        required_space = len(all_frames) * WIDTH * HEIGHT * 3
        if stat.free < required_space * 1.2:
            raise IOError(f"Insufficient disk space. Need ~{required_space // 1024 // 1024}MB")

        clip = ImageSequenceClip(all_frames, fps=FPS)

        print(f"Writing to {output_path}...")
        clip.write_videofile(
            output_path,
            fps=FPS,
            codec='libx264',
            audio=False,
            preset='medium',
            logger='bar'
        )

        # Validate output
        if not os.path.exists(output_path):
            raise IOError(f"Rendering failed - output file not created: {output_path}")

        file_size = os.path.getsize(output_path)
        if file_size < 1024:
            raise IOError(f"Output file suspiciously small: {file_size} bytes")

        print(f"✓ Done: {output_path} ({file_size // 1024}KB)")
        return output_path

    except KeyboardInterrupt:
        print("\n✗ Rendering cancelled by user")
        if os.path.exists(output_path):
            os.remove(output_path)
        raise

    except Exception as e:
        print(f"\n✗ Rendering failed: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        raise

# ============================================
# FORTUNE0 EXPLAINER SCRIPT
# ============================================

FORTUNE0_SCRIPT = [
    # Opening
    {"headline": "fortune0", "duration": 1.2, "size": 140, "color": GOLD},

    # The problem
    {"headline": "SAFE", "subtext": "Simple Agreement for Future Equity", "duration": 1.5, "outline": True, "size": 120},
    {"headline": "ACCREDITED\nINVESTORS", "subtext": "Net worth > $1M or Income > $200K", "duration": 1.8, "size": 100},
    {"headline": "99%\nEXCLUDED", "subtext": "From early-stage opportunity", "duration": 1.5, "size": 120},

    # The shift
    {"headline": "WHAT IF", "duration": 0.8, "size": 140},
    {"headline": "ANYONE", "subtext": "Could participate", "duration": 1.2, "color": GOLD, "size": 140},

    # The model
    {"headline": "SPONSORSHIP", "subtext": "$1 keeps a domain alive for 28 days", "duration": 2.0, "size": 100},
    {"headline": "230\nDOMAINS", "subtext": "Ideas waiting for builders", "duration": 1.5, "size": 120},
    {"headline": "1 SUBSCRIBER\n= 1 DOMAIN", "subtext": "Permissionless participation", "duration": 1.8, "color": GOLD, "size": 90},

    # Beyond sponsorship
    {"headline": "MENTORSHIP", "subtext": "Give time, not money", "duration": 1.5, "size": 100},
    {"headline": "PARTNERSHIP", "subtext": "Build it yourself", "duration": 1.5, "size": 100},

    # The difference
    {"headline": "NO LAWYERS", "duration": 1.0, "size": 120},
    {"headline": "NO MINIMUMS", "duration": 1.0, "size": 120},
    {"headline": "NO GATEKEEPERS", "duration": 1.0, "size": 110},

    # Close
    {"headline": "$1", "subtext": "Per 28 days", "duration": 1.5, "size": 180, "color": GOLD},
    {"headline": "fortune0.com", "duration": 2.0, "size": 100},
]

def main():
    import sys

    try:
        output_dir = ensure_output_dir()
        print(f"Output directory: {output_dir}")
        print(f"Using font: {FONT_BOLD or 'default'}")

        output_path = os.path.join(output_dir, "fortune0-explainer.mp4")

        print("\nGenerating fortune0 explainer video...")
        create_video_from_script(FORTUNE0_SCRIPT, output_path)

        print(f"\n✓ Video rendered successfully!")

        # Also create a GIF version (smaller) - optional
        print("\nCreating web GIF version...")
        gif_path = os.path.join(output_dir, "fortune0-explainer-web.gif")
        result = os.system(f'ffmpeg -i "{output_path}" -vf "scale=640:-1:flags=lanczos,fps=12" -loop 0 "{gif_path}" -y 2>/dev/null')
        if result == 0:
            print(f"✓ GIF: {gif_path}")
        else:
            print("Note: GIF conversion skipped (ffmpeg not available)")

    except ModuleNotFoundError as e:
        print(f"\n✗ Missing dependency: {e}")
        print("\nInstall: pip3 install moviepy pillow numpy")
        print("System: brew install ffmpeg (macOS) or sudo apt-get install ffmpeg (Linux)")
        sys.exit(1)

    except IOError as e:
        print(f"\n✗ File I/O error: {e}")
        sys.exit(1)

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
