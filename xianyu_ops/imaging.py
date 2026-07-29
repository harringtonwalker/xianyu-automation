from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1080
HEIGHT = 1080
PALETTES = [
    ("#141B2D", "#F6C768", "#F7F3EA"),
    ("#123C49", "#F27C5D", "#F7F4EC"),
    ("#2A2343", "#9DDBAD", "#FAF6EE"),
]


def font_path() -> str:
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("未找到支持中文的系统字体")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path(), size=size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textlength(candidate, font=font_obj) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def gradient_image(top: str, bottom: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), top)
    top_rgb = Image.new("RGB", (1, 1), top).getpixel((0, 0))
    bottom_rgb = Image.new("RGB", (1, 1), bottom).getpixel((0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top_rgb, bottom_rgb))
        draw.line((0, y, WIDTH, y), fill=color)
    return image


def add_watermark(image: Image.Image, text: str) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    tile_font = font(32)
    label_font = font(30)
    for y in range(-100, HEIGHT + 200, 180):
        for x in range(-200, WIDTH + 200, 360):
            draw.text((x, y), text, font=tile_font, fill=(255, 255, 255, 22))
    label_box = (52, HEIGHT - 98, WIDTH - 52, HEIGHT - 42)
    draw.rounded_rectangle(label_box, radius=20, fill=(0, 0, 0, 120))
    draw.text((76, HEIGHT - 86), text, font=label_font, fill=(255, 255, 255, 225))
    image.paste(overlay, (0, 0), overlay)


def _draw_heading(draw: ImageDraw.ImageDraw, heading: str, accent: str, foreground: str) -> int:
    draw.rounded_rectangle((64, 64, 308, 126), radius=31, fill=accent)
    draw.text((92, 77), heading, font=font(30), fill="#151923")
    return 172


def render_listing_images(
    source: dict[str, Any],
    output_dir: Path,
    watermark_text: str,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir.parent, 0o700)
    os.chmod(output_dir, 0o700)
    outputs: list[str] = []
    facts = list(source["facts"].items())
    titles = ["商品主图", "核心信息", "交易说明"]
    for index, palette in enumerate(PALETTES):
        background, accent, foreground = palette
        image = gradient_image(background, "#202A40" if index == 0 else background)
        draw = ImageDraw.Draw(image)
        y = _draw_heading(draw, titles[index], accent, foreground)
        if index == 0:
            title_font = font(72)
            for line in wrap(draw, source["title"], title_font, 920)[:4]:
                draw.text((64, y), line, font=title_font, fill=foreground)
                y += 100
            price_label = f"¥ {source['price']}"
            draw.rounded_rectangle((64, 720, 520, 866), radius=34, fill=accent)
            draw.text((96, 748), price_label, font=font(70), fill="#151923")
            draw.text((64, 900), "自有 / 已授权商品资料生成", font=font(30), fill="#D9DDEA")
        elif index == 1:
            draw.text((64, y), "真实信息，一页看清", font=font(62), fill=foreground)
            y += 112
            for key, value in facts[:4]:
                draw.rounded_rectangle((64, y, 1016, y + 142), radius=26, fill="#173D46", outline=accent, width=3)
                draw.text((94, y + 24), str(key)[:18], font=font(34), fill=accent)
                value_lines = wrap(draw, str(value), font(30), 670)[:2]
                for line_index, line in enumerate(value_lines):
                    draw.text((310, y + 24 + line_index * 42), line, font=font(30), fill=foreground)
                y += 164
        else:
            draw.text((64, y), "下单前请确认", font=font(62), fill=foreground)
            y += 116
            notes = [
                f"交易方式：{source['delivery']}",
                f"价格：¥{source['price']}",
                "交付范围、时间与适配条件以下单前沟通为准",
                "平台风控或页面异常时，系统会停止而不是绕过",
            ]
            for number, note in enumerate(notes, 1):
                draw.ellipse((68, y + 8, 116, y + 56), fill=accent)
                draw.text((82, y + 12), str(number), font=font(24), fill="#151923")
                for line_index, line in enumerate(wrap(draw, note, font(36), 830)[:2]):
                    draw.text((142, y + line_index * 50), line, font=font(36), fill=foreground)
                y += 142
        add_watermark(image, watermark_text)
        output_path = output_dir / f"{index + 1:02d}-{['cover', 'facts', 'terms'][index]}.png"
        image.save(output_path, format="PNG", optimize=True)
        os.chmod(output_path, 0o600)
        outputs.append(str(output_path))
    return outputs
