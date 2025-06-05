from flask import Flask, request, send_file, jsonify, abort, Response
from PIL import Image, ImageDraw, ImageFont
import requests
import time
import uuid
from io import BytesIO

app = Flask(__name__)

###############################################
# НАСТРОЙКИ (можно менять)
###############################################

DEFAULT_LOGO_URL = "https://ai.ls/assets/openai-logos/PNGs/openai-white-lockup.png"

TITLE_FONT_PATH = "InterTight-Regular.ttf"
DESC_FONT_PATH = "InterTight-Regular.ttf"

TITLE_FONT_SIZE = 78
DESC_FONT_SIZE = 40

SIDE_PADDING = 80
BOTTOM_PADDING = 60

MAX_LOGO_HEIGHT = 60

GRADIENT_HEIGHT_RATIO = 0.55
GRADIENT_OPACITY = 255

LOGO_TEXT_SPACING = 50

###############################################
# ОПАСНАЯ ЗОНА (не рекомендуется изменять)
###############################################

EPHEMERAL_STORE = {}
IMAGE_LIFETIME = 60

def wrap_text(draw, text, font, max_width):
    words = text.split()
    if not words:
        return [""]
    lines, current_line = [], words[0]
    for word in words[1:]:
        test_line = current_line + " " + word
        w, _ = draw.textbbox((0, 0), test_line, font=font)[2:]
        if w <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines

def calculate_logo_position(position, img, logo, text_top, text_bottom):
    iw, ih = img.size
    lw, lh = logo.size

    if position == "top_right":
        return iw - lw - SIDE_PADDING, SIDE_PADDING
    if position == "bottom_right":
        return iw - lw - SIDE_PADDING, ih - lh - SIDE_PADDING
    if position == "above_text":
        y = text_top - LOGO_TEXT_SPACING - lh
        return SIDE_PADDING, max(0, y)
    if position == "below_text":
        y = text_bottom + LOGO_TEXT_SPACING
        return SIDE_PADDING, min(ih - lh, y)
    return SIDE_PADDING, SIDE_PADDING  # default (top_left)

@app.route('/')
def home():
    return "Flask Image Editor is running!"

@app.route('/edit_image', methods=['POST'])
def edit_image():
    try:
        image_url = request.form.get("image_url")
        title = request.form.get("title", "Your Title").strip()
        description = request.form.get("description", "Your description here.").strip()
        logo_url = request.form.get("logo_url", DEFAULT_LOGO_URL)
        logo_position = request.form.get("logo_position", "top_left").strip()

        image_file = request.files.get("image_file")
        if image_file:
            img = Image.open(image_file.stream).convert("RGBA")
        elif image_url:
            response = requests.get(image_url)
            img = Image.open(BytesIO(response.content)).convert("RGBA")
        else:
            return jsonify({"error": "Image required (via image_file or image_url)"}), 400

        # Центрированный кроп
        width, height = img.size
        new_size = 1080
        if width < new_size or height < new_size:
            scale = max(new_size / width, new_size / height)
            img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
            width, height = img.size
        left = (width - new_size) // 2
        top = (height - new_size) // 2
        img = img.crop((left, top, left + new_size, top + new_size))

        # Лого
        logo_file = request.files.get("logo_file")
        if logo_file:
            logo = Image.open(logo_file.stream).convert("RGBA")
        elif logo_url:
            logo_response = requests.get(logo_url)
            logo = Image.open(BytesIO(logo_response.content)).convert("RGBA")
        else:
            return jsonify({"error": "Logo required (via logo_file or logo_url)"}), 400

        ratio = MAX_LOGO_HEIGHT / logo.height
        logo = logo.resize((int(logo.width * ratio), int(logo.height * ratio)), Image.LANCZOS)

        # Шрифты и текст
        draw = ImageDraw.Draw(img)
        title_font = ImageFont.truetype(TITLE_FONT_PATH, size=TITLE_FONT_SIZE)
        desc_font = ImageFont.truetype(DESC_FONT_PATH, size=DESC_FONT_SIZE)
        max_text_width = img.width - 2 * SIDE_PADDING

        title_lines = wrap_text(draw, title, title_font, max_text_width)
        desc_lines = wrap_text(draw, description, desc_font, max_text_width)

        title_height = draw.textbbox((0, 0), "Ay", font=title_font)[3]
        desc_height = draw.textbbox((0, 0), "Ay", font=desc_font)[3]
        base_text_height = title_height * len(title_lines) + desc_height * len(desc_lines) + 20

        # Если логотип под текстом — добавляем extra_space
        extra_space = LOGO_TEXT_SPACING + logo.height if logo_position == "below_text" else 0
        base_text_height_with_logo = base_text_height + extra_space

        # Градиент
        total_gradient_height = int(img.height * GRADIENT_HEIGHT_RATIO)
        gradient_img = Image.new('L', (1, total_gradient_height), color=0xFF)
        for y in range(total_gradient_height):
            opacity = int(GRADIENT_OPACITY * (y / total_gradient_height))
            gradient_img.putpixel((0, y), min(opacity, 255))
        gradient_alpha = gradient_img.resize((img.width, total_gradient_height))
        gradient_overlay = Image.new("RGBA", (img.width, total_gradient_height), (0, 0, 0, 0))
        gradient_overlay.putalpha(gradient_alpha)
        gradient_start_y = img.height - total_gradient_height
        img.paste(gradient_overlay, (0, gradient_start_y), gradient_overlay)

        # Текст
        text_start_y = img.height - base_text_height_with_logo - BOTTOM_PADDING
        y = text_start_y
        for line in title_lines:
            draw.text((SIDE_PADDING, y), line, font=title_font, fill=(255, 255, 255, 255))
            y += title_height
        y += 20
        for line in desc_lines:
            draw.text((SIDE_PADDING, y), line, font=desc_font, fill=(255, 255, 255, 255))
            y += desc_height

        # Логотип (после текста)
        logo_x, logo_y = calculate_logo_position(logo_position, img, logo, text_start_y, y)
        img.paste(logo, (logo_x, logo_y), logo)

        # Сохранение
        output = BytesIO()
        img.convert("RGB").save(output, format="JPEG", quality=90)
        output.seek(0)

        image_id = str(uuid.uuid4())
        EPHEMERAL_STORE[image_id] = {
            "data": output.getvalue(),
            "expires_at": time.time() + IMAGE_LIFETIME
        }

        temp_url = request.host_url.rstrip("/") + "/temp_image/" + image_id
        return Response(temp_url.strip(), mimetype="text/plain")

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/temp_image/<image_id>', methods=['GET'])
def temp_image(image_id):
    cleanup_ephemeral_store()
    if image_id not in EPHEMERAL_STORE:
        abort(404, description="Image not found or expired")
    image_entry = EPHEMERAL_STORE[image_id]
    if time.time() > image_entry["expires_at"]:
        EPHEMERAL_STORE.pop(image_id, None)
        abort(404, description="Image has expired")
    return send_file(BytesIO(image_entry["data"]), mimetype='image/jpeg')

def cleanup_ephemeral_store():
    now = time.time()
    expired = [k for k, v in EPHEMERAL_STORE.items() if now > v["expires_at"]]
    for k in expired:
        EPHEMERAL_STORE.pop(k, None)

if __name__ == '__main__':
    app.run(debug=True, port=10000)
