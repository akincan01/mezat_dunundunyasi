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
        # ✅ Get image from form-data (key: 'image')
        if 'image' not in request.files:
            return jsonify({"error": "Görsel yüklenmedi. 'image' anahtarı eksik."}), 400

        image_file = request.files['image']
        mime_type = image_file.mimetype
        image_bytes = image_file.read()

        # ✅ Supported formats
        if mime_type not in ['image/jpeg', 'image/png', 'image/webp', 'image/gif']:
            return jsonify({"error": f"Desteklenmeyen görsel formatı: {mime_type}"}), 400

        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:{mime_type};base64,{base64_image}"

        # ✅ Prompt
        prompt = """
        Bu görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve JSON formatında döndür:
        - Ürün Adı
        - Kategori (yalnızca şu seçeneklerden biri olmalı: Kitap, Obje, Efemera, Plak, Tablo, Mobilya)
        - Ölçü veya boyut (mutlaka santimetre cinsinden belirt)
        - Marka / Yayınevi / Plak Şirketi (eğer varsa)
        - Model / Plak Baskı Kodu / Seri No (eğer varsa)
        - Tarih / Dönem (fotograftan bulunabiliyorsa, yoksa tahmin et)
        - Malzeme (objeler ve mobilyalar için tahmin et)
        - Adet (fotoğrafta birden fazla ürün varsa adedini yaz)
        - Kondisyon (Ürünün kondisyonunu 1’den 10’a kadar puanla. Kusurları varsa belirt)
        - Etiket (örnek: #ElvisPresley #Müzik)
        - Tarz / Tür (örnek: pop art, mid-century, roman, şiir, caz vs.)
        - Notlar (ürünün tarihi, ilginç bilgi, kimin kullandığı vs. kısa ve değerli notlar)
        - Sosyal Medya / Arama Motoru Etiketleri (virgülle ayır)
        - Kitap Adı / Albüm Adı / Tablo Adı
        - Yazar / Sanatçı Adı

        Sadece Türkçe, geçerli bir JSON formatı döndür. Örnek:
        {
          "itemName": "Elvis - The Moviestar",
          "category": "Plak",
          "size": "31x31 cm",
          "brand": "RCA Records",
          "model": "APL1-2566",
          "period": "1977",
          "material": "",
          "quantity": "1",
          "condition": "8/10 - Kapakta küçük yıpranma",
          "tags": "#ElvisPresley, #Müzik",
          "style": "Rock",
          "notes": "Bu plak Elvis’in sinema kariyerine adanmış nadir baskılardan biridir.",
          "seoKeywords": "elvis, plak, vintage, müzik, rock",
          "title": "The Moviestar",
          "author": "Elvis Presley"
        }
        """

        # ✅ OpenAI call
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bir ürün tanımlama asistanısın."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]}
            ],
            max_tokens=1000
        )

        raw = response.choices[0].message.content.strip()

        # 🧹 Remove markdown code blocks
        cleaned = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()

        # ✅ Return actual JSON object
        return jsonify(json.loads(cleaned))

    except Exception as e:
        print("❌ Error:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
