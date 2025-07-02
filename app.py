from flask import Flask, request, jsonify
import openai
import base64
import os
import json
import re
from PIL import Image
import io

app = Flask(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")

def resize_image_for_openai(image_bytes, max_size=2000, quality=95):
    """Resize image for OpenAI API - ultra high quality for text readability"""
    try:
        # Open image to check dimensions
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        
        # Only resize if image is larger than max_size
        if max(width, height) <= max_size:
            print(f"✅ Image already optimal: {width}x{height}px, {len(image_bytes)} bytes")
            return image_bytes
        
        print(f"🔄 Resizing: {len(image_bytes)} bytes, {width}x{height}px -> max {max_size}px")
        
        # Calculate new size maintaining aspect ratio
        if width > height:
            new_width = min(width, max_size)
            new_height = int((height * new_width) / width)
        else:
            new_height = min(height, max_size)
            new_width = int((width * new_height) / height)
        
        # Resize image with best quality algorithm
        resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Convert to RGB if necessary (for JPEG)
        if resized_image.mode in ("RGBA", "P"):
            resized_image = resized_image.convert("RGB")
        
        # Save with highest quality
        output = io.BytesIO()
        resized_image.save(output, format="JPEG", quality=quality, optimize=True)
        resized_bytes = output.getvalue()
        
        print(f"✅ Resized to: {len(resized_bytes)} bytes, {new_width}x{new_height}px")
        return resized_bytes
        
    except Exception as e:
        print(f"❌ Error resizing image: {e}")
        return image_bytes

@app.route("/extract", methods=["POST"])
def extract_product_info():
    try:
        # ✅ Handle both single and multiple images
        uploaded_files = []
        
        if 'images' in request.files:
            uploaded_files = request.files.getlist('images')
            print(f"✅ Found {len(uploaded_files)} images in 'images' key")
        elif 'image' in request.files:
            uploaded_files = [request.files['image']]
            print("✅ Found 1 image in 'image' key")
        else:
            print("❌ No images found")
            return jsonify({"error": "Hiç görsel yüklenmedi."}), 400

        if not uploaded_files:
            return jsonify({"error": "Hiç görsel yüklenmedi."}), 400

        total_images = len(uploaded_files)
        ai_images = min(3, total_images)  # Changed to 3 images for AI analysis
        
        print(f"📸 Total images: {total_images}")
        print(f"🤖 Using {ai_images} images for AI analysis")
        print(f"💾 Saving {total_images} images for storage")

        # ✅ Process first 3 images for AI analysis
        image_data_urls = []
        
        for i in range(ai_images):
            image_file = uploaded_files[i]
            print(f"Processing AI image {i+1}: {image_file.filename}")
            
            # Check format
            mime_type = image_file.mimetype
            if mime_type not in ['image/jpeg', 'image/png', 'image/webp', 'image/gif']:
                return jsonify({"error": f"Desteklenmeyen format: {mime_type}"}), 400

            # Read and resize for AI
            original_bytes = image_file.read()
            print(f"Original size: {len(original_bytes)} bytes")
            
            resized_bytes = resize_image_for_openai(original_bytes, max_size=2000, quality=95)
            base64_resized = base64.b64encode(resized_bytes).decode("utf-8")
            image_url = f"data:image/jpeg;base64,{base64_resized}"
            
            image_data_urls.append({"type": "image_url", "image_url": {"url": image_url}})
            print(f"✅ AI image {i+1} processed")

        # ✅ Process ALL images for storage
        all_images_for_storage = []
        
        for i, image_file in enumerate(uploaded_files):
            print(f"Processing storage image {i+1}: {image_file.filename}")
            
            # Reset file pointer and read original
            image_file.seek(0)
            original_bytes = image_file.read()
            base64_original = base64.b64encode(original_bytes).decode("utf-8")
            
            all_images_for_storage.append({
                "filename": image_file.filename or f"image_{i+1}",
                "mime_type": image_file.mimetype,
                "size_bytes": len(original_bytes),
                "base64": base64_original,
                "used_for_ai": i < ai_images
            })
            print(f"✅ Storage image {i+1} processed")

        # ✅ Create detailed prompt
        prompt = f"""
        Bu {ai_images} görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve JSON formatında döndür.
        (Toplam {total_images} fotoğraf yüklendi, ilk {ai_images} tanesi analiz ediliyor)

        Görsellerdeki tüm metinleri çok dikkatli oku ve en doğru bilgiyi çıkar:

        - Ürün Adı
        - Kategori (yalnızca şu seçeneklerden biri olmalı: Kitap, Obje, Efemera, Plak, Tablo, Mobilya)
        - Ölçü veya boyut (mutlaka santimetre cinsinden belirt)
        - Marka / Yayınevi / Plak Şirketi (eğer varsa)
        - Model / Plak Baskı Kodu / Seri No (eğer varsa)
        - Tarih / Dönem (fotograftan bulunabiliyorsa, yoksa tahmin et)
        - Malzeme (objeler ve mobilyalar için tahmin et)
        - Adet (fotoğrafta birden fazla ürün varsa adedini yaz)
        - Kondisyon (Ürünün kondisyonunu 1'den 10'a kadar puanla. Kusurları varsa belirt)
        - Etiket (örnek: #ElvisPresley #Müzik)
        - Tarz / Tür (örnek: pop art, mid-century, roman, şiir, caz vs.)
        - Notlar (ürünün tarihi, ilginç bilgi, kimin kullandığı vs. kısa ve değerli notlar)
        - Sosyal Medya / Arama Motoru Etiketleri (virgülle ayır)
        - Kitap Adı / Albüm Adı / Tablo Adı
        - Yazar / Sanatçı Adı

        ÖNEMLI: Görsellerdeki yazıları çok dikkatli oku. Yayınevi adlarını, kitap başlıklarını tam olarak yazmaya özen göster.
        Sadece Türkçe, geçerli bir JSON formatı döndür.

        Örnek format:
        {{
          "itemName": "Suç ve Ceza",
          "category": "Kitap",
          "size": "19x12 cm",
          "brand": "Yapı Kredi Yayınları",
          "model": "YKY-2021-455",
          "period": "2021",
          "material": "Kağıt",
          "quantity": "1",
          "condition": "9/10 - Çok iyi durumda",
          "tags": "#klasik #edebiyat #dostoyevski",
          "style": "Klasik Edebiyat",
          "notes": "Dostoyevski'nin ünlü eseri, Türkçe çeviri",
          "seoKeywords": "suç ve ceza, dostoyevski, klasik, roman, edebiyat",
          "title": "Suç ve Ceza",
          "author": "Fyodor Dostoyevski"
        }}
        """

        # ✅ Call OpenAI
        message_content = [{"type": "text", "text": prompt}]
        message_content.extend(image_data_urls)

        print(f"🤖 Sending {len(image_data_urls)} images to OpenAI...")

        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Ürün tanımlama asistanısın. Metinleri dikkatli oku."},
                {"role": "user", "content": message_content}
            ],
            max_tokens=1500
        )

        print("✅ OpenAI response received")

        # ✅ Parse response
        raw = response.choices[0].message.content.strip()
        cleaned = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        product_data = json.loads(cleaned)
        
        # ✅ Add image info
        product_data["totalImageCount"] = total_images
        product_data["aiAnalysisImageCount"] = ai_images
        product_data["imageFilenames"] = [img["filename"] for img in all_images_for_storage]
        product_data["images"] = all_images_for_storage

        return jsonify(product_data)

    except json.JSONDecodeError as e:
        print(f"❌ JSON Error: {e}")
        return jsonify({"error": f"JSON formatı hatası: {str(e)}"}), 500
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)