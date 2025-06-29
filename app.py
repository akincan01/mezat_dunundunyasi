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

        prompt = """
        Bu görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve sadece Türkçe JSON formatında döndür:

        - Ürün Adı
        - Kategori (yalnızca şu seçeneklerden biri olmalı: Kitap, Obje, Efemera, Plak, Tablo, Mobilya)
        - Ölçü veya Boyut (mutlaka santimetre cinsinden belirt)
        - Marka / Yayınevi / Plak Şirketi (eğer varsa)
        - Model / Plak Baskı Kodu / Seri No (eğer varsa)
        - Tarih / Dönem (fotoğraftan bulunabiliyorsa, yoksa tahmin et)
        - Malzeme (obje ve mobilyalar için tahmin et)
        - Adet (fotoğrafta birden fazla ürün varsa adedini belirt)
        - Kondisyon (ürünün kondisyonunu 1’den 10’a kadar puanla. Belirtilmesi gereken arıza veya kusurları yanında belirt)
        - Etiketler (örn: Elvis Presley plakası ise, #ElvisPresley, #Müzik gibi uygun etiketleri öner)
        - Tarz / Tür (örn: Pop art, mid-century, art deco, gotik, rustik, rock, pop, caz, best of, karışık, sanat, fotoğraf, tarih, ansiklopedi, roman, şiir, spor vb.)
        - Notlar (ürünün kullanıldığı roman, film, koleksiyon; ürünün markasının, modelinin ya da üretici firmanın dikkat çekici bir geçmişi varsa detaylıca ama kısa ve öz şekilde belirt. Maksimum 3-4 cümle.)
        - Sosyal Medya / Arama Motoru Etiketleri (ürün sosyal medyada veya Google'da nasıl aranır? Anahtar kelimeleri aralarına virgül koyarak yaz)
        - Kitap Adı / Albüm Adı / Tablo Adı (eğer ürün bir kitap, albüm veya tablo ise adını belirt)
        - Yazar / Sanatçı Adı (varsa)

        Yalnızca geçerli bir JSON nesnesi döndür. Örnek:

        {
        "itemName": "Elvis - The Moviestar",
        "category": "Plak",
        "size": "31x31 cm",
        "brand": "RCA",
        "model": "LPM-1234",
        "period": "1970'ler",
        "material": "Vinil",
        "quantity": 1,
        "condition": "8/10 - Kapakta hafif yıpranma",
        "tags": ["#ElvisPresley", "#Müzik"],
        "style": "Rock",
        "notes": "Elvis Presley'in bu albümü, 1970'lerde sinema kariyerine yaptığı göndermelerle dikkat çeker. Albüm, plak koleksiyoncuları arasında nadir bulunan baskılardan biridir. RCA şirketi tarafından sınırlı sayıda üretilmiştir.",
        "seoKeywords": "elvis plak, vintage rock albüm, elvis vinil, RCA plak",
        "title": "The Moviestar",
        "author": "Elvis Presley"
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
