"""
Domain Trailer Generator
Glitchy, hard cuts, scanlines, chromatic aberration.
Reusable for any fortune0 domain.
"""

from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy import ImageSequenceClip
import math
import random
import os

# Config
WIDTH, HEIGHT = 1280, 720
FPS = 30

# Colors
BLACK = (0, 0, 0)
GOLD = (212, 175, 55)
BRIGHT_GOLD = (255, 215, 0)
WHITE = (255, 255, 255)
RED = (255, 50, 50)
CYAN = (50, 255, 255)

# Font
FONT_BOLD = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def get_font(size):
    try:
        return ImageFont.truetype(FONT_BOLD, size)
    except:
        return ImageFont.truetype(FONT_FALLBACK, size)

def add_scanlines(img, intensity=0.1, spacing=3):
    """CRT scanlines"""
    draw = ImageDraw.Draw(img)
    for y in range(0, HEIGHT, spacing):
        color = (int(20 * intensity), int(20 * intensity), int(20 * intensity))
        draw.line([(0, y), (WIDTH, y)], fill=color, width=1)
    return img

def add_chromatic_aberration(img, offset=3):
    """RGB channel split"""
    if offset <= 0:
        return img
    arr = np.array(img)
    result = np.zeros_like(arr)
    result[:, :offset, 0] = arr[:, :offset, 0]
    result[:, offset:, 0] = arr[:, :-offset, 0]
    result[:, :, 1] = arr[:, :, 1]
    result[:, -offset:, 2] = arr[:, -offset:, 2]
    result[:, :-offset, 2] = arr[:, offset:, 2]
    return Image.fromarray(result)

def add_noise(img, amount=0.03):
    """Film grain"""
    arr = np.array(img).astype(float)
    noise = np.random.normal(0, 255 * amount, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)

def add_glitch_slice(img, num_slices=3):
    """Horizontal slice displacement"""
    arr = np.array(img)
    for _ in range(num_slices):
        y = random.randint(0, HEIGHT - 20)
        h = random.randint(5, 30)
        offset = random.randint(-30, 30)
        if y + h < HEIGHT:
            slice_data = arr[y:y+h, :, :].copy()
            arr[y:y+h, :, :] = np.roll(slice_data, offset, axis=1)
    return Image.fromarray(arr)

def flash_frame(intensity=1.0, color=WHITE):
    """White/colored flash"""
    c = tuple(int(v * intensity) for v in color)
    return Image.new('RGB', (WIDTH, HEIGHT), c)

def black_frame():
    return Image.new('RGB', (WIDTH, HEIGHT), BLACK)

def draw_text_centered(draw, text, y, font, color):
    """Draw centered text"""
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    x = (WIDTH - w) // 2
    draw.text((x, y), text, fill=color, font=font)

def draw_ring(draw, cx, cy, outer_r, inner_r, color, progress=1.0):
    """Draw the fortune0 zero mark"""
    if progress <= 0:
        return

    angle = int(360 * progress)

    # Outer edge
    for i in range(3):
        r = outer_r - i
        bbox = [cx-r, cy-r, cx+r, cy+r]
        draw.arc(bbox, -90, -90 + angle, fill=WHITE, width=2)

    # Gold fill
    for r in range(inner_r + 4, outer_r - 4):
        bbox = [cx-r, cy-r, cx+r, cy+r]
        draw.arc(bbox, -90, -90 + angle, fill=color, width=2)

    # Inner cutout
    bbox = [cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r]
    draw.ellipse(bbox, fill=BLACK)

def ease_out_expo(t):
    return 1 if t >= 1 else 1 - pow(2, -10 * t)

def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


class TrailerGenerator:
    def __init__(self, seed=42):
        random.seed(seed)
        self.frames = []

    def add_black(self, duration=0.5):
        """Add black frames"""
        for _ in range(int(FPS * duration)):
            img = black_frame()
            img = add_noise(img, 0.02)
            self.frames.append(np.array(img))

    def add_flash(self, duration=0.1, color=WHITE):
        """Add flash transition"""
        total = int(FPS * duration)
        for i in range(total):
            t = i / total
            intensity = 1 - t  # Fade out
            img = flash_frame(intensity, color)
            self.frames.append(np.array(img))

    def add_text_slam(self, text, duration=1.5, size=120, color=WHITE, subtext=None, subtext_size=28):
        """Text slams in from right"""
        total = int(FPS * duration)
        font = get_font(size)
        sub_font = get_font(subtext_size) if subtext else None

        for i in range(total):
            t = i / total
            img = Image.new('RGB', (WIDTH, HEIGHT), BLACK)
            draw = ImageDraw.Draw(img)

            # Text animation
            if t < 0.2:
                # Slam in
                ease_t = ease_out_back(t / 0.2)
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                x_start = WIDTH + 50
                x_end = (WIDTH - text_w) // 2
                x = int(x_start + (x_end - x_start) * ease_t)
                y = HEIGHT // 2 - size // 2
                draw.text((x, y), text, fill=color, font=font)

                # Glitch on impact
                if t < 0.1 and random.random() < 0.5:
                    img = add_glitch_slice(img, 5)
                    img = add_chromatic_aberration(img, random.randint(5, 15))
            else:
                # Hold
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                x = (WIDTH - text_w) // 2
                y = HEIGHT // 2 - size // 2
                draw.text((x, y), text, fill=color, font=font)

                # Subtext fades in
                if subtext and t > 0.3:
                    sub_t = min(1, (t - 0.3) / 0.2)
                    sub_color = tuple(int(120 * sub_t) for _ in range(3))
                    bbox_sub = draw.textbbox((0, 0), subtext, font=sub_font)
                    sub_w = bbox_sub[2] - bbox_sub[0]
                    sub_x = (WIDTH - sub_w) // 2
                    sub_y = HEIGHT // 2 + size // 2 + 20
                    draw.text((sub_x, sub_y), subtext.upper(), fill=sub_color, font=sub_font)

            img = add_scanlines(img, 0.06)
            img = add_noise(img, 0.02)

            # Random glitch frames
            if random.random() < 0.03:
                img = add_chromatic_aberration(img, random.randint(3, 8))

            self.frames.append(np.array(img))

    def add_ring_reveal(self, duration=2.0, text_after=None, text_size=48):
        """The fortune0 zero mark reveals and fills with gold"""
        total = int(FPS * duration)
        cx, cy = WIDTH // 2, HEIGHT // 2
        outer_r = 100
        inner_r = 60

        for i in range(total):
            t = i / total
            img = Image.new('RGB', (WIDTH, HEIGHT), BLACK)
            draw = ImageDraw.Draw(img)

            if t < 0.4:
                # Ring draws
                progress = ease_out_expo(t / 0.4)
                draw_ring(draw, cx, cy, outer_r, inner_r, BLACK, progress)
                # Just white outline during draw
                for j in range(3):
                    r = outer_r - j
                    bbox = [cx-r, cy-r, cx+r, cy+r]
                    angle = int(360 * progress)
                    draw.arc(bbox, -90, -90 + angle, fill=WHITE, width=2)
                bbox = [cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r]
                draw.ellipse(bbox, fill=BLACK)
            else:
                # Gold fills
                fill_t = ease_out_expo((t - 0.4) / 0.4)
                draw_ring(draw, cx, cy, outer_r, inner_r, GOLD, 1.0)
                # Redraw gold portion
                angle = int(360 * fill_t)
                for r in range(inner_r + 4, outer_r - 4):
                    bbox = [cx-r, cy-r, cx+r, cy+r]
                    draw.arc(bbox, -90, -90 + angle, fill=GOLD, width=2)
                bbox = [cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r]
                draw.ellipse(bbox, fill=BLACK)
                # White outline
                for j in range(3):
                    r = outer_r - j
                    bbox = [cx-r, cy-r, cx+r, cy+r]
                    draw.arc(bbox, 0, 360, fill=WHITE, width=2)

                # Text below
                if text_after and t > 0.7:
                    text_t = min(1, (t - 0.7) / 0.2)
                    font = get_font(text_size)
                    bbox_t = draw.textbbox((0, 0), text_after, font=font)
                    tw = bbox_t[2] - bbox_t[0]
                    tx = (WIDTH - tw) // 2
                    ty = cy + outer_r + 30 + int(20 * (1 - text_t))
                    color = tuple(int(255 * text_t) for _ in range(3))
                    draw.text((tx, ty), text_after, fill=color, font=font)

            img = add_scanlines(img, 0.05)
            img = add_noise(img, 0.015)

            if random.random() < 0.05:
                img = add_chromatic_aberration(img, 4)

            self.frames.append(np.array(img))

    def add_domain_intro(self, domain, tagline=None, duration=2.5, color=WHITE):
        """Domain name with optional tagline"""
        # Flash in
        self.add_flash(0.08, GOLD)

        total = int(FPS * duration)
        font_big = get_font(90)
        font_small = get_font(24)

        for i in range(total):
            t = i / total
            img = Image.new('RGB', (WIDTH, HEIGHT), BLACK)
            draw = ImageDraw.Draw(img)

            # Domain name
            bbox = draw.textbbox((0, 0), domain, font=font_big)
            dw = bbox[2] - bbox[0]
            dx = (WIDTH - dw) // 2
            dy = HEIGHT // 2 - 50

            if t < 0.15:
                # Glitch in
                glitch_x = int((1 - t/0.15) * random.randint(-50, 50))
                draw.text((dx + glitch_x, dy), domain, fill=color, font=font_big)
                img = add_chromatic_aberration(img, int((1 - t/0.15) * 15))
                img = add_glitch_slice(img, 4)
            else:
                draw.text((dx, dy), domain, fill=color, font=font_big)

            # Tagline
            if tagline and t > 0.25:
                tag_t = min(1, (t - 0.25) / 0.2)
                tag_color = (int(100 * tag_t), int(100 * tag_t), int(100 * tag_t))
                bbox_tag = draw.textbbox((0, 0), tagline.upper(), font=font_small)
                tw = bbox_tag[2] - bbox_tag[0]
                tx = (WIDTH - tw) // 2
                ty = HEIGHT // 2 + 50
                draw.text((tx, ty), tagline.upper(), fill=tag_color, font=font_small)

            img = add_scanlines(img, 0.05)
            img = add_noise(img, 0.02)

            self.frames.append(np.array(img))

    def render(self, output_path):
        """Render to MP4"""
        print(f"Rendering {len(self.frames)} frames...")
        clip = ImageSequenceClip(self.frames, fps=FPS)
        clip.write_videofile(output_path, fps=FPS, codec='libx264', audio=False)
        print(f"Done: {output_path}")
        return output_path


# ============================================
# TRAILER DEFINITIONS
# ============================================

def make_fortune0_trailer():
    """Extended fortune0 trailer - ~25 seconds"""
    t = TrailerGenerator(seed=42)

    # Opening
    t.add_black(0.5)
    t.add_ring_reveal(2.5, text_after="fortune0")
    t.add_flash(0.1, GOLD)

    # The pitch
    t.add_text_slam("OPEN", duration=1.0, size=140, color=WHITE)
    t.add_flash(0.08)
    t.add_text_slam("INCUBATOR", duration=1.2, size=100, color=GOLD)
    t.add_black(0.3)

    # The model
    t.add_text_slam("$1", duration=1.0, size=180, color=GOLD, subtext="per 28 days")
    t.add_flash(0.08)
    t.add_text_slam("230", duration=1.0, size=160, color=WHITE, subtext="domains")
    t.add_flash(0.08)
    t.add_text_slam("BUILD", duration=1.2, size=120, color=GOLD)
    t.add_flash(0.08)
    t.add_text_slam("OWN", duration=1.2, size=120, color=GOLD)
    t.add_black(0.3)

    # Anti-SAFE
    t.add_text_slam("NO SAFE", duration=1.0, size=100, color=WHITE)
    t.add_flash(0.06)
    t.add_text_slam("NO VC", duration=1.0, size=100, color=WHITE)
    t.add_flash(0.06)
    t.add_text_slam("NO GATE", duration=1.0, size=100, color=WHITE)
    t.add_black(0.3)

    # Close
    t.add_ring_reveal(2.0, text_after="fortune0.com")
    t.add_black(1.0)

    output = "/sessions/friendly-nice-rubin/mnt/fortune0.com/brand/fortune0-trailer-extended.mp4"
    return t.render(output)

def make_death2data_trailer():
    """death2data trailer"""
    t = TrailerGenerator(seed=123)

    t.add_black(0.3)
    t.add_domain_intro("death2data", tagline="your data dies with you", color=WHITE)
    t.add_flash(0.1)

    t.add_text_slam("PRIVACY", duration=1.2, size=120, color=WHITE)
    t.add_flash(0.08)
    t.add_text_slam("LOCAL", duration=1.0, size=120, color=WHITE, subtext="first")
    t.add_flash(0.08)
    t.add_text_slam("$1", duration=1.2, size=160, color=GOLD, subtext="notebooks")
    t.add_black(0.3)

    t.add_domain_intro("death2data.com", color=GOLD)
    t.add_black(0.8)

    output = "/sessions/friendly-nice-rubin/mnt/fortune0.com/brand/death2data-trailer.mp4"
    return t.render(output)

def make_domain_trailer(domain, tagline, concepts, color=WHITE):
    """Generic domain trailer"""
    t = TrailerGenerator(seed=hash(domain) % 10000)

    t.add_black(0.3)
    t.add_domain_intro(domain, tagline=tagline, color=color)
    t.add_flash(0.1)

    for concept in concepts[:4]:  # Max 4 concepts
        t.add_text_slam(concept.upper(), duration=1.0, size=100, color=WHITE)
        t.add_flash(0.06)

    t.add_black(0.2)
    t.add_domain_intro(f"{domain}", color=GOLD)
    t.add_black(0.6)

    safe_name = domain.replace(".", "-")
    output = f"/sessions/friendly-nice-rubin/mnt/fortune0.com/brand/{safe_name}-trailer.mp4"
    return t.render(output)


if __name__ == "__main__":
    os.makedirs("/sessions/friendly-nice-rubin/mnt/fortune0.com/brand", exist_ok=True)

    print("=== FORTUNE0 EXTENDED ===")
    make_fortune0_trailer()

    print("\n=== DEATH2DATA ===")
    make_death2data_trailer()

    print("\nDone!")
