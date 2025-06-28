from flask import Flask, request, jsonify
from flask.cli import load_dotenv
import openai
import base64
import os
import re
import json

app = Flask(__name__)

load_dotenv()  # 🔑 Load variables from .env
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/extract", methods=["POST"])
def extract_product_info():
    try:
        # Get the image file from the request
        image_file = request.files["image"]
        image_bytes = image_file.read()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        # Turkish prompt for item extraction
        prompt = """
        Bu görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve JSON formatında döndür:
        - Ürün Adı
        - Kategori (yalnızca şu seçeneklerden biri olmalı: Kitap, Obje, Efemera, Plak, Tablo, Mobilya)
        - Ölçü veya boyut (mutlaka santimetre cinsinden belirt)

        Sadece Türkçe JSON döndür. Örnek:
        {
          "itemName": "Beyaz Tişört",
          "category": "Kıyafet",
          "size": "30x40 cm"
        }
        """

        # Send image + prompt to OpenAI
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bir ürün tanımlama asistanısın."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            max_tokens=500
        )

        raw = response.choices[0].message.content.strip()

        # ✅ Clean the triple-backtick code formatting if present
        cleaned = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()

        try:
            data = json.loads(cleaned)
            return jsonify(data)
        except json.JSONDecodeError:
            return jsonify({"error": "OpenAI response could not be parsed as JSON.", "raw": raw}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
