"""
Kinetic Typography Video Generator
Style: D2D / Brutalist - black bg, bold text, hard cuts, subtext
"""

from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy import ImageSequenceClip, concatenate_videoclips
import os

# Config - reduced for memory
WIDTH, HEIGHT = 1280, 720
FPS = 24

# Colors
BLACK = (0, 0, 0)
WHITE = (230, 230, 230)
GRAY = (120, 120, 120)
GOLD = (212, 175, 55)

# Fonts - try to match the condensed bold style
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_CONDENSED = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"

def get_font(size, condensed=False):
    """Get font at specified size"""
    try:
        path = FONT_CONDENSED if condensed else FONT_BOLD
        return ImageFont.truetype(path, size)
    except:
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

    clip = ImageSequenceClip(all_frames, fps=FPS)

    print(f"Writing to {output_path}...")
    clip.write_videofile(output_path, fps=FPS, codec='libx264', audio=False)

    return output_path

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
    output_dir = "/sessions/friendly-nice-rubin/mnt/fortune0.com/brand"
    os.makedirs(output_dir, exist_ok=True)

    output_path = f"{output_dir}/fortune0-explainer.mp4"

    print("Generating fortune0 explainer video...")
    create_video_from_script(FORTUNE0_SCRIPT, output_path)

    print(f"\nDone! Output: {output_path}")

    # Also create a GIF version (smaller)
    print("\nCreating web GIF version...")
    gif_path = f"{output_dir}/fortune0-explainer-web.gif"
    os.system(f'ffmpeg -i "{output_path}" -vf "scale=640:-1:flags=lanczos,fps=12" -loop 0 "{gif_path}" -y 2>/dev/null')
    print(f"GIF: {gif_path}")

if __name__ == "__main__":
    main()
