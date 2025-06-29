from flask import Flask, request, jsonify
from flask.cli import load_dotenv
import openai
import base64
import os
import json
import re

app = Flask(__name__)
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/extract", methods=["POST"])
def extract_product_info():
    try:
        # 📥 Step 1: Get image in base64 format
        if request.is_json:
            # Request is from Google Apps Script
            data = request.get_json()
            data_url = data.get("image_base64", "")
            if "," in data_url:
                base64_image = data_url.split(",")[1]
            else:
                return jsonify({"error": "No valid base64 image found"}), 400
        else:
            # Request is raw binary (e.g. from Postman)
            image_bytes = request.get_data()
            base64_image = base64.b64encode(image_bytes).decode("utf-8")

        # 🧠 Prompt for GPT-4o (in Turkish)
        prompt = """
        Bu görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve JSON formatında döndür:
        - Ürün Adı
        - Kategori (yalnızca şu seçeneklerden biri olmalı: Kitap, Obje, Efemera, Plak, Tablo, Mobilya)
        - Ölçü veya boyut (santimetre cinsinden belirt)
        - Marka / Yayınevi / Plak Şirketi (eğer varsa)
        - Model / Plak Baskı Kodu / Seri No (eğer varsa)
        - Tarih / Dönem (fotoğraftan bulunabiliyorsa, yoksa tahmin et)
        - Malzeme (tahmin et)
        - Adet (birden fazlaysa belirt)
        - Kondisyon (1-10, varsa kusur yaz)
        - Etiket (örn: #ElvisPresley)
        - Tarz / Tür (örn: rock, roman, art deco)
        - Notlar (ürünün kısa hikayesi veya bilgisi)
        - SEO Etiketleri (virgülle ayır)
        - Kitap/Albüm/Tablo Adı
        - Yazar / Sanatçı Adı

        Sadece geçerli bir JSON döndür.
        """

        # 🧠 Call OpenAI API
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bir ürün tanımlama asistanısın."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            max_tokens=800
        )

        raw_response = response.choices[0].message.content.strip()

        # 🧹 Clean ```json code block
        cleaned = re.sub(r"^```json|```$", "", raw_response, flags=re.MULTILINE).strip()

        # 🛠 Debugging log
        print("📦 GPT response:", raw_response)

        # ✅ Return both raw and cleaned JSON
        return jsonify({
            "result": raw_response,
            "cleaned": cleaned
        })

    except Exception as e:
        print("❌ Error:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
