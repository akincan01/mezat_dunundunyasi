from flask import Flask, request, jsonify
import openai
import base64
import os
import json
import re
from PIL import Image
import io
from datetime import datetime
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__)

# Configure Flask for file uploads
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['UPLOAD_FOLDER'] = '/tmp'

openai.api_key = os.getenv("OPENAI_API_KEY")

def resize_image_for_openai(image_bytes, max_size=1600, quality=85, target_file_size=2*1024*1024):
    """Resize image for OpenAI API with aggressive compression for large files"""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        original_width, original_height = image.size
        original_size = len(image_bytes)
        
        print(f"🔍 Original: {original_width}x{original_height}px, {original_size:,} bytes")
        
        # If already small enough, return as-is
        if original_size <= target_file_size and max(original_width, original_height) <= max_size:
            print(f"✅ Image already optimal")
            return image_bytes
        
        # Convert to RGB if needed
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        
        # Calculate new dimensions
        if original_width > original_height:
            new_width = min(original_width, max_size)
            new_height = int((original_height * new_width) / original_width)
        else:
            new_height = min(original_height, max_size)
            new_width = int((original_width * new_height) / original_height)
        
        # Resize image
        resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Try different quality levels to hit target file size
        for attempt_quality in [quality, 75, 60, 50, 40]:
            output = io.BytesIO()
            resized_image.save(output, format="JPEG", quality=attempt_quality, optimize=True)
            compressed_bytes = output.getvalue()
            compressed_size = len(compressed_bytes)
            
            print(f"🔄 Attempt: {new_width}x{new_height}px, quality={attempt_quality}%, size={compressed_size:,} bytes")
            
            # If we hit our target size, use this version
            if compressed_size <= target_file_size:
                print(f"✅ Success: {compressed_size:,} bytes (was {original_size:,} bytes)")
                return compressed_bytes
            
            # If this is our last attempt, use it anyway
            if attempt_quality == 40:
                print(f"⚠️ Using lowest quality: {compressed_size:,} bytes")
                return compressed_bytes
        
        # Fallback - return the compressed version even if large
        return compressed_bytes
        
    except Exception as e:
        print(f"❌ Error resizing image: {e}")
        return image_bytes

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "Flask app is running - Hybrid Solution Ready", 
        "endpoints": ["/extract", "/extract-hybrid", "/health"],
        "version": "2.0 - Hybrid Support"
    })

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy", 
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "max_file_size": "50MB",
        "supported_formats": ["jpeg", "jpg", "png", "webp", "gif"]
    })

@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return jsonify({
        "error": "File too large",
        "message": "Please use images smaller than 50MB. For best results, compress images to under 5MB.",
        "max_size": "50MB",
        "suggestion": "Use client-side compression or resize images before uploading"
    }), 413

@app.route("/extract", methods=["POST", "OPTIONS"])
def extract_product_info():
    """Original endpoint - maintains backward compatibility"""
    return process_images(return_format="original")

@app.route("/extract-hybrid", methods=["POST", "OPTIONS"])
def extract_product_info_hybrid():
    """New hybrid endpoint - optimized for web app integration"""
    return process_images(return_format="hybrid")

def process_images(return_format="original"):
    """Main image processing function - supports both original and hybrid formats"""
    
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
        print(f"🔍 Return format: {return_format}")
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
        
        # Add processing metadata
        product_data["processingInfo"] = {
            "timestamp": datetime.now().isoformat(),
            "api_version": "2.0-hybrid",
            "total_images": total_images,
            "ai_processed_images": len(image_data_urls),
            "return_format": return_format
        }

        # Return different formats based on endpoint
        if return_format == "hybrid":
            # Format for hybrid web app
            return jsonify({
                "success": True,
                "data": product_data,
                "metadata": {
                    "total_images": total_images,
                    "processed_images": len(image_data_urls),
                    "api_version": "2.0-hybrid"
                }
            })
        else:
            # Original format for backward compatibility
            return jsonify(product_data)

    except RequestEntityTooLarge:
        return jsonify({
            "error": "File too large",
            "message": "Please use images smaller than 50MB. Consider using client-side compression.",
            "max_size": "50MB",
            "suggestion": "Compress images to under 5MB for best performance"
        }), 413
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