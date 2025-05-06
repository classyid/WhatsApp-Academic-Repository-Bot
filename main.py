import asyncio
import logging
import os
import sys
import traceback
import base64
import json
import aiohttp
import requests
import tempfile
import PyPDF2
from neonize.aioze.client import ClientFactory, NewAClient
from neonize.events import (
    ConnectedEv,
    MessageEv,
)
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
from neonize.utils import log

# Tambahkan import dari thundra_io
from thundra_io.utils import get_message_type, get_user_id
from thundra_io.types import MediaMessageType
from thundra_io.storage.file import File

sys.path.insert(0, os.getcwd())

# Konfigurasi logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
log.setLevel(logging.DEBUG)

# Gemini API configuration
GEMINI_API_KEY = "<APIKEY-GEMINI>"
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_CONTENT_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

# Repository API configuration
REPOSITORY_API_BASE_URL = "<URL-API-REPOSITORY>"

# Setup client
client_factory = ClientFactory("db.sqlite3")
os.makedirs("temp_media", exist_ok=True)

# Load existing sessions
sessions = client_factory.get_all_devices()
for device in sessions:
    client_factory.new_client(device.JID)

# Dictionary untuk menyimpan hasil pencarian terakhir
last_search_results = {}

# Helper function untuk mendapatkan pesan yang dikutip dan jenisnya
async def get_quoted_message_info(message):
    has_quoted = False
    quoted_message = None
    quoted_type = None
    
    try:
        # Check untuk extended text message
        if (hasattr(message.Message, 'extendedTextMessage') and 
            hasattr(message.Message.extendedTextMessage, 'contextInfo') and
            hasattr(message.Message.extendedTextMessage.contextInfo, 'quotedMessage')):
            
            quoted_message = message.Message.extendedTextMessage.contextInfo.quotedMessage
            has_quoted = True
            
            # Coba gunakan thundra_io untuk deteksi tipe
            try:
                msg_type = get_message_type(quoted_message)
                if isinstance(msg_type, MediaMessageType):
                    quoted_type = msg_type.__class__.__name__.lower().replace('message', '')
                    log.info(f"Detected quoted {quoted_type} message using thundra_io")
            except Exception as e:
                log.error(f"Error using thundra_io for type detection: {e}")
            
            # Fallback ke metode deteksi lama jika thundra_io gagal
            if not quoted_type:
                if hasattr(quoted_message, 'videoMessage'):
                    quoted_type = "video"
                    log.info("Detected quoted video message")
                elif hasattr(quoted_message, 'audioMessage'):
                    quoted_type = "audio"
                    log.info("Detected quoted audio message")
                elif hasattr(quoted_message, 'imageMessage'):
                    quoted_type = "image"
                    log.info("Detected quoted image message")
                elif hasattr(quoted_message, 'documentMessage'):
                    quoted_type = "document"
                    log.info("Detected quoted document message")
                else:
                    log.info("Unknown quoted message type")
                    # Log atribut
                    for attr in dir(quoted_message):
                        if not attr.startswith('_'):
                            log.info(f"Quoted message has attribute: {attr}")
    
    except Exception as e:
        log.error(f"Error in get_quoted_message_info: {e}")
        log.error(traceback.format_exc())
    
    return has_quoted, quoted_message, quoted_type

# Fungsi download langsung dari URL jika tersedia
async def download_from_url(url):
    try:
        log.info(f"Downloading from URL: {url}")
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            log.info(f"Successfully downloaded {len(response.content)} bytes from URL")
            return response.content
        else:
            log.error(f"Failed to download from URL: status code {response.status_code}")
            return None
    except Exception as e:
        log.error(f"Error downloading from URL: {e}")
        log.error(traceback.format_exc())
        return None

# Fungsi untuk ekstraksi teks dari PDF
async def extract_text_from_pdf(pdf_path):
    try:
        log.info(f"Extracting text from PDF: {pdf_path}")
        text = ""
        
        with open(pdf_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            num_pages = len(pdf_reader.pages)
            
            log.info(f"PDF has {num_pages} pages")
            
            # Ekstrak teks dari setiap halaman (batasi ke 10 halaman pertama untuk efisiensi)
            max_pages = min(num_pages, 10)
            for page_num in range(max_pages):
                page = pdf_reader.pages[page_num]
                page_text = page.extract_text()
                if page_text:
                    text += f"\n--- Halaman {page_num + 1} ---\n{page_text}\n"
                else:
                    text += f"\n--- Halaman {page_num + 1} tidak memiliki teks yang dapat diekstrak ---\n"
            
            if num_pages > max_pages:
                text += f"\n--- (Teks hanya diekstrak dari {max_pages} halaman pertama dari total {num_pages} halaman) ---\n"
        
        log.info(f"Successfully extracted {len(text)} characters of text from PDF")
        return text
    except Exception as e:
        log.error(f"Error extracting text from PDF: {e}")
        log.error(traceback.format_exc())
        return f"Error ekstraksi PDF: {str(e)}"

# Fungsi untuk mengirim teks ke Gemini AI
async def query_gemini_text(text):
    try:
        log.info(f"Sending text to Gemini: {text[:50]}...")
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": text
                        }
                    ]
                }
            ]
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(GEMINI_CONTENT_URL, json=payload, headers=headers) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    response_json = json.loads(response_text)
                    try:
                        return response_json["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError) as e:
                        log.error(f"Error parsing Gemini response: {e}")
                        return "Terjadi kesalahan saat memproses respons dari Gemini AI."
                else:
                    log.error(f"Gemini API error: {response_text}")
                    return f"Error dari Gemini API: Status {response.status}."
    except Exception as e:
        log.error(f"Exception in query_gemini_text: {e}")
        return f"Error: {str(e)}"

# Fungsi untuk mencari dokumen dari repository API
async def search_repository(keyword):
    try:
        log.info(f"Searching repository for: {keyword}")
        
        url = f"{REPOSITORY_API_BASE_URL}/search?q={keyword}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    response_json = json.loads(response_text)
                    if response_json.get("status") == "success":
                        return response_json
                    else:
                        log.error(f"Repository API error: {response_json.get('message', 'Unknown error')}")
                        return None
                else:
                    log.error(f"Repository API error: Status {response.status}")
                    return None
    except Exception as e:
        log.error(f"Error in search_repository: {e}")
        log.error(traceback.format_exc())
        return None

# Fungsi untuk mendapatkan detail dokumen dari repository API
async def get_document_detail(url):
    try:
        log.info(f"Getting document detail for: {url}")
        
        api_url = f"{REPOSITORY_API_BASE_URL}/detail?url={url}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    response_json = json.loads(response_text)
                    if response_json.get("status") == "success":
                        return response_json.get("data")
                    else:
                        log.error(f"Repository API error: {response_json.get('message', 'Unknown error')}")
                        return None
                else:
                    log.error(f"Repository API error: Status {response.status}")
                    return None
    except Exception as e:
        log.error(f"Error in get_document_detail: {e}")
        log.error(traceback.format_exc())
        return None

# Fungsi untuk mendownload PDF dari link dan menganalisisnya
async def download_and_analyze_paper(client, chat, pdf_url, title, authors, year, abstract=None):
    try:
        log.info(f"Downloading and analyzing paper: {title}")
        
        # Kirim pesan sedang mengunduh
        await client.send_message(chat, f"📄 Mengunduh karya ilmiah: *{title}* ({year})")
        
        # Download PDF
        media_bytes = await download_from_url(pdf_url)
        
        if not media_bytes:
            await client.send_message(chat, "❌ Gagal mengunduh PDF karya ilmiah")
            return
        
        # Simpan PDF
        temp_path = f"temp_media/paper_{os.urandom(4).hex()}.pdf"
        with open(temp_path, 'wb') as f:
            f.write(media_bytes)
        
        # Ekstrak teks dari PDF
        await client.send_message(chat, "⏳ Mengekstrak teks dari PDF karya ilmiah...")
        pdf_text = await extract_text_from_pdf(temp_path)
        
        if not pdf_text or pdf_text.startswith("Error"):
            await client.send_message(chat, f"❌ Gagal mengekstrak teks dari PDF: {pdf_text}")
            return
        
        # Buat prompt khusus untuk analisis karya ilmiah
        authors_str = ", ".join(authors) if isinstance(authors, list) else authors
        
        prompt = f"""Analisis karya ilmiah berikut dengan detail:
Judul: {title}
Penulis: {authors_str}
Tahun: {year}
"""
        
        if abstract:
            prompt += f"Abstrak: {abstract}\n\n"
        
        prompt += """Berikan rangkuman yang komprehensif dari karya ilmiah ini dengan mencakup aspek berikut:
1. Ringkasan singkat tentang apa isi dokumen ini
2. Kontribusi utama atau temuan penting dalam penelitian ini
3. Metodologi yang digunakan (jika ada)
4. Kesimpulan dan implikasi dari penelitian
5. Relevansi dan signifikansi karya ilmiah ini

Tolong berikan informasi dalam format yang terstruktur dan mudah dipahami."""
        
        # Batasi teks jika terlalu panjang
        max_length = 16000  # Batas karakter untuk input ke Gemini
        if len(pdf_text) > max_length:
            pdf_text = pdf_text[:max_length] + "...[teks terpotong karena terlalu panjang]"
        
        # Gabungkan prompt dan teks PDF
        full_prompt = f"{prompt}\n\nIsi Dokumen PDF:\n{pdf_text}"
        
        await client.send_message(chat, "🧠 Menganalisis karya ilmiah dengan Gemini AI...")
        response = await query_gemini_text(full_prompt)
        
        # Kirim hasil analisis
        await client.send_message(chat, response)
        
    except Exception as e:
        log.error(f"Error in download_and_analyze_paper: {e}")
        log.error(traceback.format_exc())
        await client.send_message(chat, f"❌ Error saat menganalisis karya ilmiah: {str(e)}")

# Fungsi untuk mengirim hasil pencarian
async def send_search_results(client, chat, results, keyword):
    try:
        if not results or "data" not in results or not results["data"]:
            await client.send_message(chat, f"❌ Tidak ditemukan hasil untuk pencarian: *{keyword}*")
            return
        
        count = results.get("count", 0)
        total = results.get("total", 0)
        
        header = f"🔍 Hasil pencarian untuk: *{keyword}*\n"
        header += f"Menampilkan {count} dari {total} hasil\n\n"
        
        # Batasi jumlah hasil yang dikirim untuk menghindari pesan terlalu panjang
        max_results = 5
        data = results["data"][:max_results]
        
        # Format hasil pencarian
        message = header
        for i, item in enumerate(data):
            title = item.get("title", "Tidak ada judul")
            authors = ", ".join(item.get("authors", ["Tidak ada penulis"]))
            year = item.get("year", "Tidak ada tahun")
            url = item.get("url", "#")
            download_links = item.get("download_links", [])
            
            message += f"*{i+1}. {title}*\n"
            message += f"Penulis: {authors}\n"
            message += f"Tahun: {year}\n"
            
            if download_links:
                message += f"Download: {download_links[0]}\n"
            
            message += f"URL: {url}\n\n"
        
        if len(data) < total:
            message += f"...dan {total - len(data)} hasil lainnya.\n"
        
        message += "\nKetik *paper detail [nomor]* untuk melihat detail dan *paper analyze [nomor]* untuk menganalisis isi paper."
        
        await client.send_message(chat, message)
        
        # Simpan hasil pencarian untuk digunakan nanti
        chat_id_str = str(chat)  # Menggunakan string sebagai kunci
        last_search_results[chat_id_str] = results
        
    except Exception as e:
        log.error(f"Error in send_search_results: {e}")
        log.error(traceback.format_exc())
        await client.send_message(chat, f"❌ Error saat mengirim hasil pencarian: {str(e)}")

@client_factory.event(ConnectedEv)
async def on_connected(_: NewAClient, __: ConnectedEv):
    log.info("⚡ WhatsApp terhubung")

@client_factory.event(MessageEv)
async def on_message(client: NewAClient, message: MessageEv):
    await handle_message(client, message)

async def handle_message(client, message):
    try:
        chat = message.Info.MessageSource.Chat
        chat_id_str = str(chat)  # Menggunakan string sebagai kunci dictionary
        
        # Extract text content
        if hasattr(message.Message, 'conversation') and message.Message.conversation:
            text = message.Message.conversation
        elif hasattr(message.Message, 'extendedTextMessage') and message.Message.extendedTextMessage.text:
            text = message.Message.extendedTextMessage.text
        else:
            text = ""
        
        # Get quoted message if any
        has_quoted, quoted_message, quoted_type = await get_quoted_message_info(message)
        
        # Handle commands
        if text.lower() == "ping":
            await client.reply_message("pong", message)

        # Command untuk mencari dokumen di repositori
        elif text.lower().startswith("paper search "):
            keyword = text[13:]  # Remove "paper search " prefix
            await client.send_message(chat, f"🔍 Mencari dokumen dengan kata kunci: *{keyword}*...")
            
            results = await search_repository(keyword)
            if results:
                await send_search_results(client, chat, results, keyword)
            else:
                await client.send_message(chat, f"❌ Gagal mencari dokumen dengan kata kunci: *{keyword}*")

        # Command untuk melihat detail dokumen
        elif text.lower().startswith("paper detail "):
            try:
                index = int(text[13:]) - 1  # Remove "paper detail " prefix and convert to 0-based index
                
                # Cek apakah ada hasil pencarian yang tersimpan
                if chat_id_str in last_search_results and "data" in last_search_results[chat_id_str]:
                    data = last_search_results[chat_id_str]["data"]
                    
                    if 0 <= index < len(data):
                        item = data[index]
                        url = item.get("url", "")
                        
                        await client.send_message(chat, f"🔍 Mendapatkan detail untuk dokumen: *{item.get('title', '')}*...")
                        
                        # Dapatkan detail dokumen
                        document_detail = await get_document_detail(url)
                        
                        if document_detail:
                            title = document_detail.get("title", "Tidak ada judul")
                            abstract = document_detail.get("abstract", "Tidak ada abstrak")
                            metadata = document_detail.get("metadata", {})
                            download_links = document_detail.get("download_links", [])
                            
                            # Format authors dari metadata
                            authors = metadata.get("Penulis", "Tidak ada penulis").split("; ")
                            year = metadata.get("Tahun Terbit", "Tidak ada tahun")
                            
                            # Tampilkan detail dokumen
                            detail_message = f"📝 *Detail Dokumen*\n\n"
                            detail_message += f"*Judul:* {title}\n"
                            detail_message += f"*Penulis:* {', '.join(authors)}\n"
                            detail_message += f"*Tahun:* {year}\n\n"
                            detail_message += f"*Abstrak:*\n{abstract}\n\n"
                            
                            # Tampilkan metadata lainnya
                            if metadata:
                                detail_message += "*Metadata Lainnya:*\n"
                                for key, value in metadata.items():
                                    if key not in ["Penulis", "Tahun Terbit"]:
                                        detail_message += f"{key}: {value}\n"
                            
                            # Tampilkan link download
                            if download_links:
                                detail_message += "\n*Link Download:*\n"
                                for i, link in enumerate(download_links):
                                    if isinstance(link, dict):
                                        detail_message += f"{i+1}. {link.get('label', 'Link')}: {link.get('url', '#')}\n"
                                    else:
                                        detail_message += f"{i+1}. {link}\n"
                            
                            await client.send_message(chat, detail_message)
                        else:
                            await client.send_message(chat, f"❌ Gagal mendapatkan detail dokumen")
                    else:
                        await client.send_message(chat, f"❌ Nomor tidak valid. Gunakan nomor 1-{len(data)}")
                else:
                    await client.send_message(chat, "❌ Tidak ada hasil pencarian sebelumnya. Gunakan command 'paper search [keyword]' terlebih dahulu.")
                
            except ValueError:
                await client.send_message(chat, "❌ Format salah. Gunakan: *paper detail [nomor]*")

        # Command untuk menganalisis dokumen dari repositori
        elif text.lower().startswith("paper analyze "):
            try:
                index = int(text[14:]) - 1  # Remove "paper analyze " prefix and convert to 0-based index
                
                # Cek apakah ada hasil pencarian yang tersimpan
                if chat_id_str in last_search_results and "data" in last_search_results[chat_id_str]:
                    data = last_search_results[chat_id_str]["data"]
                    
                    if 0 <= index < len(data):
                        item = data[index]
                        url = item.get("url", "")
                        title = item.get("title", "")
                        authors = item.get("authors", [])
                        year = item.get("year", "")
                        download_links = item.get("download_links", [])
                        
                        # Cek apakah ada link download
                        if download_links:
                            pdf_url = download_links[0]
                            if isinstance(pdf_url, dict):
                                pdf_url = pdf_url.get("url", "")
                            
                            # Dapatkan detail tambahan jika tersedia
                            document_detail = await get_document_detail(url)
                            abstract = ""
                            
                            if document_detail:
                                abstract = document_detail.get("abstract", "")
                                metadata = document_detail.get("metadata", {})
                                if "Penulis" in metadata:
                                    authors = metadata.get("Penulis", "").split("; ")
                                if "Tahun Terbit" in metadata:
                                    year = metadata.get("Tahun Terbit", "")
                            
                            # Download dan analisis dokumen
                            await download_and_analyze_paper(client, chat, pdf_url, title, authors, year, abstract)
                        else:
                            await client.send_message(chat, "❌ Tidak ada link download untuk dokumen ini")
                    else:
                        await client.send_message(chat, f"❌ Nomor tidak valid. Gunakan nomor 1-{len(data)}")
                else:
                    await client.send_message(chat, "❌ Tidak ada hasil pencarian sebelumnya. Gunakan command 'paper search [keyword]' terlebih dahulu.")
                
            except ValueError:
                await client.send_message(chat, "❌ Format salah. Gunakan: *paper analyze [nomor]*")
                
        # Command untuk menganalisis dokumen dari URL langsung
        elif text.lower().startswith("paper url "):
            url = text[10:]  # Remove "paper url " prefix
            
            await client.send_message(chat, f"🔍 Mencari detail dokumen dari URL: {url}...")
            
            # Dapatkan detail dokumen
            document_detail = await get_document_detail(url)
            
            if document_detail:
                title = document_detail.get("title", "Tidak ada judul")
                abstract = document_detail.get("abstract", "Tidak ada abstrak")
                metadata = document_detail.get("metadata", {})
                download_links = document_detail.get("download_links", [])
                
                # Format authors dari metadata
                authors = metadata.get("Penulis", "Tidak ada penulis").split("; ")
                year = metadata.get("Tahun Terbit", "Tidak ada tahun")
                
                # Tampilkan detail dokumen
                detail_message = f"📝 *Detail Dokumen*\n\n"
                detail_message += f"*Judul:* {title}\n"
                detail_message += f"*Penulis:* {', '.join(authors)}\n"
                detail_message += f"*Tahun:* {year}\n\n"
                detail_message += f"*Abstrak:*\n{abstract}\n\n"
                
                # Tampilkan metadata lainnya
                if metadata:
                    detail_message += "*Metadata Lainnya:*\n"
                    for key, value in metadata.items():
                        if key not in ["Penulis", "Tahun Terbit"]:
                            detail_message += f"{key}: {value}\n"
                
                # Tampilkan link download
                if download_links:
                    detail_message += "\n*Link Download:*\n"
                    for i, link in enumerate(download_links):
                        if isinstance(link, dict):
                            detail_message += f"{i+1}. {link.get('label', 'Link')}: {link.get('url', '#')}\n"
                        else:
                            detail_message += f"{i+1}. {link}\n"
                
                await client.send_message(chat, detail_message)
                
                # Tawarkan untuk menganalisis dokumen
                if download_links:
                    await client.send_message(chat, "Ketik *paper download [URL]* untuk mengunduh dan menganalisis dokumen ini.")
            else:
                await client.send_message(chat, f"❌ Gagal mendapatkan detail dokumen dari URL: {url}")

        # Command untuk mengunduh dan menganalisis dokumen dari URL langsung
        elif text.lower().startswith("paper download "):
            pdf_url = text[15:]  # Remove "paper download " prefix
            
            await client.send_message(chat, f"📥 Mengunduh dokumen dari URL: {pdf_url}...")
            
            # Coba ekstrak informasi dari URL
            title = "Dokumen"
            authors = ["Penulis tidak diketahui"]
            year = "Tahun tidak diketahui"
            
            # Coba ekstrak nama file dari URL
            try:
                file_name = pdf_url.split('/')[-1]
                if file_name:
                    title = file_name.replace('%20', ' ').replace('%', ' ').replace('.pdf', '')
            except:
                pass
            
            # Download dan analisis dokumen
            await download_and_analyze_paper(client, chat, pdf_url, title, authors, year)

        # Command untuk menganalisis dokumen PDF yang direply
        elif has_quoted and quoted_type == "document" and text.lower() == "paper analyze":
            await client.send_message(chat, "📄 Mengunduh dan memproses dokumen yang direply...")
            
            # Download dokumen
            media_bytes, mime_type, temp_path = None, None, None
            try:
                # Coba download media
                from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
                message_obj = Message()
                message_obj.documentMessage.CopyFrom(quoted_message.documentMessage)
                media_bytes = await client.download_any(message_obj)
                
                if media_bytes:
                    # Simpan file
                    temp_path = f"temp_media/document_{os.urandom(4).hex()}.pdf"
                    with open(temp_path, 'wb') as f:
                        f.write(media_bytes)
                    mime_type = "application/pdf"
            except Exception as e:
                log.error(f"Error downloading document: {e}")
                log.error(traceback.format_exc())
                
            if not media_bytes or not temp_path:
                await client.send_message(chat, "❌ Gagal mengunduh dokumen PDF")
                return
                
            # Verifikasi mime_type untuk PDF
            if not mime_type or not mime_type.lower() == "application/pdf":
                await client.send_message(chat, f"❌ Dokumen bukan PDF. Tipe: {mime_type}")
                return
                
            # Ekstrak teks dari PDF
            await client.send_message(chat, "⏳ Mengekstrak teks dari PDF...")
            pdf_text = await extract_text_from_pdf(temp_path)
            
            if not pdf_text or pdf_text.startswith("Error"):
                await client.send_message(chat, f"❌ Gagal mengekstrak teks dari PDF: {pdf_text}")
                return
                
            # Batasi teks jika terlalu panjang
            max_length = 16000  # Batas karakter untuk input ke Gemini
            if len(pdf_text) > max_length:
                pdf_text = pdf_text[:max_length] + "...[teks terpotong karena terlalu panjang]"
            
            # Buat prompt untuk analisis
            prompt = """Analisis karya ilmiah ini dengan mencakup aspek berikut:
1. Ringkasan singkat tentang apa isi dokumen ini
2. Kontribusi utama atau temuan penting dalam penelitian
3. Metodologi yang digunakan (jika ada)
4. Kesimpulan dan implikasi dari penelitian
5. Relevansi dan signifikansi karya ilmiah ini

Tolong berikan informasi dalam format yang terstruktur dan mudah dipahami."""
            
            # Gabungkan prompt dan teks PDF
            full_prompt = f"{prompt}\n\nIsi Dokumen PDF:\n{pdf_text}"
            
            await client.send_message(chat, "🧠 Menganalisis dokumen dengan Gemini AI...")
            response = await query_gemini_text(full_prompt)
            
            # Kirim hasil analisis
            await client.send_message(chat, response)

        elif text.lower() == "help":
            help_text = """
*WhatsApp Repository Bot*

*Perintah Dasar:*
- `ping` - Cek apakah bot aktif

*Perintah Repositori:*
- `paper search [keyword]` - Mencari dokumen di repositori
- `paper detail [nomor]` - Menampilkan detail dokumen dari hasil pencarian
- `paper analyze [nomor]` - Menganalisis isi dokumen dari hasil pencarian
- `paper url [URL]` - Mendapatkan detail dokumen dari URL repositori
- `paper download [URL]` - Mengunduh dan menganalisis dokumen dari URL
- `paper analyze` - Menganalisis dokumen PDF yang direply

*Contoh:*
> paper search pendidikan islam
> paper detail 1
> paper analyze 2
> paper url https://repository.iainkediri.ac.id/1023/
> paper download https://repository.iainkediri.ac.id/1023/1/Pendidikan%20Islam%20Dalam%20Guncangan%20Post%20Truth.pdf
"""
            await client.send_message(chat, help_text)
            
    except Exception as e:
        log.error(f"Error in message handler: {e}")
        log.error(traceback.format_exc())

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(client_factory.run())
