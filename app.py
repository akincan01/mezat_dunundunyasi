from flask import Flask, request, jsonify
from flask.cli import load_dotenv
import openai
import base64
import os
import json
import re
from PIL import Image
import io

app = Flask(__name__)
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def resize_image_for_openai(image_bytes, max_size=800, quality=60, max_file_size=1024*1024):
    """Resize image aggressively for OpenAI API - smaller size for multiple images"""
    try:
        # Open image to check dimensions
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        max_dimension = max(width, height)
        
        # Check if image needs resizing (ALWAYS resize for multiple images)
        needs_resize = True  # Always resize for better OpenAI compatibility
        
        if not needs_resize:
            print(f"✅ Image OK: {len(image_bytes)} bytes, {width}x{height}px")
            return image_bytes, False
        
        print(f"🔄 Resizing: {len(image_bytes)} bytes, {width}x{height}px -> max {max_size}px")
        
        # Calculate new size maintaining aspect ratio
        if width > height:
            new_width = min(width, max_size)
            new_height = int((height * new_width) / width)
        else:
            new_height = min(height, max_size)
            new_width = int((width * new_height) / height)
        
        # Resize image
        resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Convert to RGB if necessary (for JPEG)
        if resized_image.mode in ("RGBA", "P"):
            resized_image = resized_image.convert("RGB")
        
        # Save to bytes
        output = io.BytesIO()
        resized_image.save(output, format="JPEG", quality=quality, optimize=True)
        resized_bytes = output.getvalue()
        
        print(f"✅ Resized to: {len(resized_bytes)} bytes, {new_width}x{new_height}px")
        return resized_bytes, True
        
    except Exception as e:
        print(f"❌ Error resizing image: {e}")
        return image_bytes, False

@app.route("/extract", methods=["POST"])
def extract_product_info():
    try:
        # ✅ Handle both single and multiple images (backwards compatible)
        uploaded_files = []
        
        # Try multiple images first
        if 'images' in request.files:
            uploaded_files = request.files.getlist('images')
            print(f"✅ Found {len(uploaded_files)} images in 'images' key")
        # Fallback to single image (original format)
        elif 'image' in request.files:
            uploaded_files = [request.files['image']]
            print("✅ Found 1 image in 'image' key")
        else:
            print("❌ No 'images' or 'image' key found in request.files")
            print("Available keys:", list(request.files.keys()))
        
        if not uploaded_files or len(uploaded_files) == 0:
            return jsonify({"error": "Hiç görsel yüklenmedi. En az 1 görsel gerekli."}), 400

        print(f"📸 Processing {len(uploaded_files)} images...")

        # ✅ Process ALL images for AI analysis

        # ✅ Process images for AI analysis (max 3)
        processed_images = []
        image_data_urls = []
        
        for i, image_file in enumerate(uploaded_files):  # Process ALL images
            try:
                print(f"Processing image {i+1}: {image_file.filename}")
                
                mime_type = image_file.mimetype
                print(f"MIME type: {mime_type}")
                
                # Read the original image bytes
                original_image_bytes = image_file.read()
                print(f"Original image size: {len(original_image_bytes)} bytes")

                # ✅ Supported formats
                if mime_type not in ['image/jpeg', 'image/png', 'image/webp', 'image/gif']:
                    return jsonify({"error": f"Desteklenmeyen görsel formatı: {mime_type}"}), 400

                # ✅ Resize for OpenAI (ALWAYS resize aggressively for multiple images)
                processed_image_bytes, was_resized = resize_image_for_openai(
                    original_image_bytes, 
                    max_size=800,      # Much smaller
                    quality=60,        # Lower quality
                    max_file_size=512*1024  # 512KB limit
                )
                
                print(f"Processed image size: {len(processed_image_bytes)} bytes")
                
                # Create base64 for OpenAI (using processed/resized image)
                base64_for_openai = base64.b64encode(processed_image_bytes).decode("utf-8")
                if was_resized:
                    image_url = f"data:image/jpeg;base64,{base64_for_openai}"
                else:
                    image_url = f"data:{mime_type};base64,{base64_for_openai}"
                
                # Store original image data for Google Drive storage
                base64_original = base64.b64encode(original_image_bytes).decode("utf-8")
                
                processed_images.append({
                    "filename": image_file.filename or f"image_{i+1}",
                    "mime_type": mime_type,
                    "size_bytes": len(original_image_bytes),
                    "base64": base64_original,  # Always store original
                    "was_resized_for_ai": was_resized
                })
                
                image_data_urls.append({"type": "image_url", "image_url": {"url": image_url}})
                print(f"✅ Successfully processed image {i+1}")
                
            except Exception as img_error:
                print(f"❌ Error processing image {i+1}: {str(img_error)}")
                return jsonify({"error": f"Error processing image {i+1}: {str(img_error)}"}), 500

        # ✅ Enhanced prompt for multiple images
        image_count = len(uploaded_files)
        prompt = f"""
        Bu {image_count} görseldeki ürünle ilgili aşağıdaki bilgileri çıkar ve JSON formatında döndür.
        Tüm görselleri analiz ederek en doğru bilgiyi çıkar:

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

        Birden fazla görsel varsa, hepsini analiz et ve en kapsamlı bilgiyi çıkar.
        Sadece Türkçe, geçerli bir JSON formatı döndür.

        Örnek format:
        {{
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
          "notes": "Bu plak Elvis'in sinema kariyerine adanmış nadir baskılardan biridir.",
          "seoKeywords": "elvis, plak, vintage, müzik, rock",
          "title": "The Moviestar",
          "author": "Elvis Presley"
        }}
        """

        # ✅ Prepare messages with all images
        message_content = [{"type": "text", "text": prompt}]
        message_content.extend(image_data_urls)

        print(f"🤖 Sending {len(image_data_urls)} images to OpenAI...")

        # ✅ OpenAI call with multiple images
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bir ürün tanımlama asistanısın. Birden fazla görsel verildiğinde hepsini analiz et."},
                {"role": "user", "content": message_content}
            ],
            max_tokens=1500
        )

        print("✅ OpenAI response received")

        raw = response.choices[0].message.content.strip()

        # 🧹 Remove markdown code blocks
        cleaned = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
        
        # ✅ Parse the product data
        product_data = json.loads(cleaned)
        
        # ✅ Add image count and filenames
        product_data["imageCount"] = len(processed_images)
        product_data["imageFilenames"] = [img["filename"] for img in processed_images]
        product_data["images"] = processed_images  # Include ALL images

        return jsonify(product_data)

    except json.JSONDecodeError as e:
        print("❌ JSON Parse Error:", str(e))
        return jsonify({"error": f"JSON formatı hatası: {str(e)}"}), 500
    except Exception as e:
        print("❌ Error:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)