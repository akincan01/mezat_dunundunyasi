from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import base64
import os
import json
import re
from PIL import Image
import io

app = Flask(__name__)
CORS(app)  # This helps with browser requests

openai.api_key = os.getenv("OPENAI_API_KEY")

def resize_image_for_openai(image_bytes, max_size=2000, quality=95):
    """HIGH QUALITY resize - same as your working version"""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        
        if max(width, height) <= max_size:
            print(f"✅ Image already optimal: {width}x{height}px, {len(image_bytes)} bytes")
            return image_bytes
        
        print(f"🔄 Resizing: {len(image_bytes)} bytes, {width}x{height}px -> max {max_size}px")
        
        if width > height:
            new_width = min(width, max_size)
            new_height = int((height * new_width) / width)
        else:
            new_height = min(height, max_size)
            new_width = int((width * new_height) / height)
        
        # HIGH QUALITY resampling
        resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        if resized_image.mode in ("RGBA", "P"):
            resized_image = resized_image.convert("RGB")
        
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
        # Handle multiple images - your proven method
        uploaded_files = []
        
        if 'images' in request.files:
            uploaded_files.extend(request.files.getlist('images'))
            print(f"✅ Found {len(request.files.getlist('images'))} images in 'images' key")
        
        # Handle additional images from Google Apps Script
        for i in range(1, 10):
            key = f'images_{i}'
            if key in request.files:
                uploaded_files.extend(request.files.getlist(key))
                print(f"✅ Found images in '{key}' key")
        
        if 'image' in request.files:
            uploaded_files.append(request.files['image'])
            print("✅ Found 1 image in 'image' key")
        
        if not uploaded_files:
            print("❌ No images found")
            return jsonify({"error": "Hiç görsel yüklenmedi."}), 400

        total_images = len(uploaded_files)
        ai_images = min(3, total_images)
        
        print(f"📸 Total images: {total_images}")
        print(f"🤖 Using {ai_images} images for AI analysis")

        # Process AI images with HIGH QUALITY
        image_data_urls = []
        
        for i in range(ai_images):
            image_file = uploaded_files[i]
            print(f"Processing AI image {i+1}: {image_file.filename}")
            
            mime_type = image_file.mimetype
            if mime_type not in ['image/jpeg', 'image/png', 'image/webp', 'image/gif']:
                return jsonify({"error": f"Desteklenmeyen format: {mime_type}"}), 400

            original_bytes = image_file.read()
            print(f"Original size: {len(original_bytes)} bytes")
            
            # HIGH QUALITY processing
            resized_bytes = resize_image_for_openai(original_bytes, max_size=2000, quality=95)
            base64_resized = base64.b64encode(resized_bytes).decode("utf-8")
            image_url = f"data:image/jpeg;base64,{base64_resized}"
            
            image_data_urls.append({"type": "image_url", "image_url": {"url": image_url}})
            print(f"✅ AI image {i+1} processed")

        # Process all images for storage
        all_images_for_storage = []
        
        for i, image_file in enumerate(uploaded_files):
            print(f"Processing storage image {i+1}: {image_file.filename}")
            
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

        # Your PROVEN prompt - exactly the same
        prompt = f"""
        Bu {ai_images} görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve JSON formatında döndür.
        (Toplam {total_images} fotoğraf yüklendi, ilk {ai_images} tanesi analiz ediliyor)

        3 FOTOĞRAFTAN ELDE EDİLEN TÜM BİLGİLERİ BİRLEŞTİR:
        - Her fotoğraftaki tüm metinleri oku
        - Farklı açılardan görünen detayları birleştir  
        - En doğru ve eksiksiz bilgileri çıkar

        Çıkaracağın bilgiler:
        - Ürün Adı (en net görünen isim)
        - Kategori (Kitap, Obje, Efemera, Plak, Tablo, Mobilya)
        - Ölçü/boyut (santimetre cinsinden)
        - Marka/Yayınevi/Şirket (fotoğraflarda görünen)
        - Model/Seri/Baskı kodu
        - Tarih/Dönem (yazıyorsa, yoksa tahmin et)
        - Malzeme (ne yapıldığını tahmin et)
        - Adet (kaç tane ürün var)
        - Kondisyon (1-10 arası puan ve açıklama)
        - Etiketler (hashtag formatında)
        - Tarz/Tür (kategori, dönem, stil)
        - Başlık/Albüm adı (tam isim)
        - Yazar/Sanatçı (tam isim)
        - Notlar (önemli detaylar, tarihçe, özellikler)
        - SEO anahtar kelimeleri (virgülle ayır)

        ÖNEMLI: 3 fotoğraftaki TÜM yazıları dikkatli oku. Çok detaylı ve eksiksiz analiz yap.
        Sadece Türkçe, geçerli JSON formatı döndür.

        Örnek format:
        {{
          "itemName": "Suç ve Ceza - Fyodor Dostoyevski",
          "category": "Kitap", 
          "size": "19x12x2 cm",
          "brand": "Yapı Kredi Yayınları",
          "model": "YKY-2021-455",
          "period": "2021",
          "material": "Kağıt, karton kapak",
          "quantity": "1",
          "condition": "9/10 - Çok iyi durumda, hafif köşe kırıkları",
          "tags": "#klasik #edebiyat #dostoyevski #roman #yky",
          "style": "Klasik Edebiyat",
          "notes": "Dostoyevski'nin ünlü eseri. Türkçe çeviri. 3. baskı. Sayfa kenarları temiz.",
          "seoKeywords": "suç ve ceza, dostoyevski, klasik roman, yky yayınları",
          "title": "Suç ve Ceza",
          "author": "Fyodor Dostoyevski"
        }}
        """

        message_content = [{"type": "text", "text": prompt}]
        message_content.extend(image_data_urls)

        print(f"🤖 Sending {len(image_data_urls)} images to OpenAI...")

        # PROVEN OpenAI call settings
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Sen bir ürün tanımlama uzmanısın. 3 fotoğrafı birlikte analiz edip en doğru bilgileri çıkarıyorsun."},
                {"role": "user", "content": message_content}
            ],
            max_tokens=2000,
            temperature=0.3  # Good balance of creativity and consistency
        )

        print("✅ OpenAI response received")

        # Parse response - your proven method
        raw = response.choices[0].message.content.strip()
        cleaned = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        product_data = json.loads(cleaned)
        
        # Add metadata
        product_data["totalImageCount"] = total_images
        product_data["aiAnalysisImageCount"] = ai_images
        product_data["imageFilenames"] = [img["filename"] for img in all_images_for_storage]
        product_data["images"] = all_images_for_storage

        print(f"✅ Analysis complete: {ai_images} images analyzed")
        return jsonify(product_data)

    except json.JSONDecodeError as e:
        print(f"❌ JSON Error: {e}")
        return jsonify({"error": f"JSON formatı hatası: {str(e)}"}), 500
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

# Simple health check
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ready", "version": "proven"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)