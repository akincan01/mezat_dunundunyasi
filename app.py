from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import base64
import os
import json
import re
from PIL import Image
import io
import concurrent.futures
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for faster requests

# Load environment variables
openai.api_key = os.getenv("OPENAI_API_KEY")

def resize_image_optimized(image_bytes, max_size=1800, quality=85):
    """SPEED OPTIMIZED: Smaller images, lower quality for faster processing"""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        
        # SPEED OPTIMIZATION: More aggressive resizing
        if max(width, height) <= max_size:
            # Still resize slightly for consistency
            max_size = min(max_size, max(width, height) * 0.9)
        
        if width > height:
            new_width = min(width, max_size)
            new_height = int((height * new_width) / width)
        else:
            new_height = min(height, max_size)
            new_width = int((width * new_height) / height)
        
        # SPEED OPTIMIZATION: Faster resampling method
        resized_image = image.resize((new_width, new_height), Image.Resampling.BILINEAR)
        
        if resized_image.mode in ("RGBA", "P"):
            resized_image = resized_image.convert("RGB")
        
        output = io.BytesIO()
        resized_image.save(output, format="JPEG", quality=quality, optimize=False)  # No optimization for speed
        resized_bytes = output.getvalue()
        
        print(f"⚡ Fast resize: {len(image_bytes)} -> {len(resized_bytes)} bytes")
        return resized_bytes
        
    except Exception as e:
        print(f"❌ Error resizing: {e}")
        return image_bytes

def process_single_image(image_file, index):
    """SPEED OPTIMIZATION: Process images in parallel"""
    try:
        original_bytes = image_file.read()
        resized_bytes = resize_image_optimized(original_bytes, max_size=1800, quality=85)
        base64_resized = base64.b64encode(resized_bytes).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{base64_resized}"
        
        return {"type": "image_url", "image_url": {"url": image_url}}
    except Exception as e:
        print(f"❌ Error processing image {index}: {e}")
        return None

@app.route("/extract", methods=["POST"])
def extract_product_info():
    start_time = time.time()
    
    try:
        # SPEED OPTIMIZATION: Quick file collection
        uploaded_files = []
        
        if 'images' in request.files:
            uploaded_files.extend(request.files.getlist('images'))
        
        # Check for additional images quickly
        for i in range(1, 5):  # Reduced range for speed
            key = f'images_{i}'
            if key in request.files:
                uploaded_files.extend(request.files.getlist(key))
        
        if 'image' in request.files:
            uploaded_files.append(request.files['image'])
        
        if not uploaded_files:
            return jsonify({"error": "Hiç görsel yüklenmedi."}), 400

        total_images = len(uploaded_files)
        ai_images = min(3, total_images)
        
        print(f"⚡ SPEED MODE: {ai_images} images for AI, {total_images} total")

        # SPEED OPTIMIZATION: Parallel image processing
        image_data_urls = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for i in range(ai_images):
                future = executor.submit(process_single_image, uploaded_files[i], i)
                futures.append(future)
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    image_data_urls.append(result)
        
        print(f"⚡ Images processed in parallel: {len(image_data_urls)}")

        # SPEED OPTIMIZATION: Streamlined storage processing
        all_images_for_storage = []
        for i, image_file in enumerate(uploaded_files):
            image_file.seek(0)
            original_bytes = image_file.read()
            base64_original = base64.b64encode(original_bytes).decode("utf-8")
            
            all_images_for_storage.append({
                "filename": image_file.filename or f"img_{i+1}",
                "mime_type": image_file.mimetype,
                "size_bytes": len(original_bytes),
                "base64": base64_original,
                "used_for_ai": i < ai_images
            })

        # SAME PROMPT - NO CHANGES (as requested)
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

        print(f"⚡ Calling OpenAI with {len(image_data_urls)} images...")

        # SPEED OPTIMIZATION: Faster OpenAI call
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Sen hızlı ve doğru ürün tanımlama uzmanısın."},
                {"role": "user", "content": message_content}
            ],
            max_tokens=1800,  # Reduced for speed
            temperature=0.1,  # Lower for faster, more consistent responses
            timeout=30  # 30 second timeout
        )

        print("⚡ OpenAI response received")

        # SPEED OPTIMIZATION: Fast JSON parsing
        raw = response.choices[0].message.content.strip()
        cleaned = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        product_data = json.loads(cleaned)
        
        # Add metadata
        product_data["totalImageCount"] = total_images
        product_data["aiAnalysisImageCount"] = ai_images
        product_data["imageFilenames"] = [img["filename"] for img in all_images_for_storage]
        product_data["images"] = all_images_for_storage
        product_data["processingTime"] = round(time.time() - start_time, 2)

        print(f"⚡ TOTAL PROCESSING TIME: {product_data['processingTime']} seconds")
        return jsonify(product_data)

    except json.JSONDecodeError as e:
        print(f"❌ JSON Error: {e}")
        return jsonify({"error": f"JSON formatı hatası: {str(e)}"}), 500
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

# SPEED OPTIMIZATION: Add endpoint for health check (wakeup)
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ready", "timestamp": time.time()})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)  # Debug=False for speed