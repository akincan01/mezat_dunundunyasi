from flask import Flask, request, jsonify
import openai
import base64
import os
import json
import re
from PIL import Image
import io

app = Flask(__name__)

# Configure Flask for file uploads
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['UPLOAD_FOLDER'] = '/tmp'

openai.api_key = os.getenv("OPENAI_API_KEY")

def resize_image_for_openai(image_bytes, max_size=2000, quality=95):
    """Resize image for OpenAI API - ultra high quality for text readability"""
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

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Flask app is running", "endpoints": ["/extract", "/health"]})

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "openai_key_set": bool(os.getenv("OPENAI_API_KEY"))})

@app.route("/extract", methods=["POST", "OPTIONS"])
def extract_product_info():
    # Handle CORS preflight
    if request.method == "OPTIONS":
        response = jsonify({"status": "ok"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type")
        response.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
        return response
    
    try:
        print(f"🔍 Request method: {request.method}")
        print(f"🔍 Content-Type: {request.content_type}")
        print(f"🔍 Content-Length: {request.content_length}")
        print(f"🔍 Files keys: {list(request.files.keys())}")
        print(f"🔍 Form keys: {list(request.form.keys())}")
        
        # Check if request has files
        if not request.files:
            return jsonify({
                "error": "No files in request",
                "debug": {
                    "content_type": request.content_type,
                    "content_length": request.content_length,
                    "has_files": bool(request.files),
                    "files_keys": list(request.files.keys()),
                    "suggestion": "Make sure you're using 'form-data' in Postman, not 'raw' or 'x-www-form-urlencoded'"
                }
            }), 400

        # Get uploaded files - try multiple possible keys
        uploaded_files = []
        possible_keys = ['images', 'image', 'file', 'files']
        
        for key in possible_keys:
            if key in request.files:
                files = request.files.getlist(key)
                uploaded_files.extend(files)
                print(f"✅ Found {len(files)} files with key '{key}'")
                break
        
        # If no files found with standard keys, try all keys
        if not uploaded_files:
            for key in request.files.keys():
                files = request.files.getlist(key)
                uploaded_files.extend(files)
                print(f"✅ Found {len(files)} files with key '{key}'")

        if not uploaded_files:
            return jsonify({
                "error": "No valid files uploaded",
                "debug": {
                    "available_keys": list(request.files.keys()),
                    "suggestion": "Check your form field name in Postman"
                }
            }), 400

        # Filter out empty files
        valid_files = [f for f in uploaded_files if f and f.filename and f.filename.strip()]
        
        if not valid_files:
            return jsonify({
                "error": "No valid files with names found",
                "debug": {
                    "total_files": len(uploaded_files),
                    "files_info": [{"filename": f.filename, "has_content": bool(f.read(1))} for f in uploaded_files]
                }
            }), 400

        # Reset file pointers
        for f in valid_files:
            f.seek(0)

        total_images = len(valid_files)
        ai_images = min(3, total_images)
        
        print(f"📸 Processing {total_images} images, analyzing {ai_images}")

        # Process images for AI
        image_data_urls = []
        
        for i in range(ai_images):
            image_file = valid_files[i]
            print(f"Processing image {i+1}: {image_file.filename}")
            
            # Read file content
            image_file.seek(0)
            original_bytes = image_file.read()
            
            if len(original_bytes) == 0:
                continue
            
            # Detect mime type
            mime_type = image_file.mimetype
            if not mime_type:
                # Try to detect from filename
                filename = image_file.filename.lower()
                if filename.endswith(('.jpg', '.jpeg')):
                    mime_type = 'image/jpeg'
                elif filename.endswith('.png'):
                    mime_type = 'image/png'
                elif filename.endswith('.webp'):
                    mime_type = 'image/webp'
                else:
                    mime_type = 'image/jpeg'  # default
            
            print(f"MIME type: {mime_type}")
            
            if mime_type not in ['image/jpeg', 'image/png', 'image/webp', 'image/gif']:
                print(f"⚠️ Unsupported format {mime_type}, trying anyway...")
            
            try:
                resized_bytes = resize_image_for_openai(original_bytes, max_size=2000, quality=95)
                base64_resized = base64.b64encode(resized_bytes).decode("utf-8")
                image_url = f"data:image/jpeg;base64,{base64_resized}"
                
                image_data_urls.append({"type": "image_url", "image_url": {"url": image_url}})
                print(f"✅ Image {i+1} processed successfully")
                
            except Exception as e:
                print(f"❌ Error processing image {i+1}: {e}")
                continue

        if not image_data_urls:
            return jsonify({"error": "No images could be processed"}), 400

        # Process all images for storage
        all_images_for_storage = []
        
        for i, image_file in enumerate(valid_files):
            image_file.seek(0)
            original_bytes = image_file.read()
            base64_original = base64.b64encode(original_bytes).decode("utf-8")
            
            all_images_for_storage.append({
                "filename": image_file.filename,
                "mime_type": image_file.mimetype or 'image/jpeg',
                "size_bytes": len(original_bytes),
                "base64": base64_original,
                "used_for_ai": i < ai_images
            })

        # Create prompt
        prompt = f"""
        Bu {len(image_data_urls)} görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve JSON formatında döndür.
        (Toplam {total_images} fotoğraf yüklendi, ilk {len(image_data_urls)} tanesi analiz ediliyor)

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
        Sadece Türkçe içerikli ama İngilizce anahtarlı JSON formatı döndür. Anahtarlar tam olarak aşağıdaki örnekteki gibi olmalı.

        ZORUNLU: Döndürülen JSON'daki anahtarlar (keys) mutlaka İngilizce olmalı, değerler (values) Türkçe olabilir.

        Örnek format - AYNI ANAHTARLARI KULLAN:
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

        # Call OpenAI
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

        # Parse response
        raw = response.choices[0].message.content.strip()
        cleaned = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        product_data = json.loads(cleaned)
        
        # Add image info
        product_data["totalImageCount"] = total_images
        product_data["aiAnalysisImageCount"] = len(image_data_urls)
        product_data["imageFilenames"] = [img["filename"] for img in all_images_for_storage]
        product_data["images"] = all_images_for_storage

        return jsonify(product_data)

    except json.JSONDecodeError as e:
        print(f"❌ JSON Error: {e}")
        return jsonify({"error": f"JSON formatı hatası: {str(e)}"}), 500
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "type": type(e).__name__}), 500

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)