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
        image_bytes = request.get_data()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

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

        raw = response.choices[0].message.content.strip()

        # 🛠️ Debug log
        print("🔍 RAW GPT RESPONSE:")
        print(raw)

        # Clean markdown ```json
        json_text = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()

        parsed = json.loads(json_text)

        return jsonify(parsed)

    except Exception as e:
        print("❌ Error parsing GPT response:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
