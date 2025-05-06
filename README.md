# WhatsApp Academic Repository Bot

Bot WhatsApp cerdas yang memungkinkan pengguna mencari, mengakses, dan menganalisis dokumen dari repositori karya ilmiah dengan mudah dan cepat. Terintegrasi dengan Gemini AI untuk memberikan analisis dan rangkuman komprehensif atas dokumen PDF ilmiah.

![Repository Bot Demo](assets/demo.png)

## Fitur Utama

- 🔍 **Pencarian Repository**: Mencari dokumen di repositori berdasarkan kata kunci
- 📝 **Detail Dokumen**: Menampilkan metadata dan informasi detail dari dokumen ilmiah
- 🧠 **Analisis Cerdas**: Memanfaatkan Gemini AI untuk menganalisis isi dokumen secara otomatis
- 📄 **Dukungan PDF**: Penanganan dan ekstraksi teks dari file PDF
- 🔧 **Mudah Digunakan**: Perintah sederhana berbasis chat di WhatsApp

## Perintah yang Tersedia

- `ping` - Cek apakah bot aktif
- `paper search [keyword]` - Mencari dokumen dengan kata kunci
- `paper detail [nomor]` - Menampilkan detail dokumen dari hasil pencarian
- `paper analyze [nomor]` - Menganalisis isi dokumen dari hasil pencarian
- `paper url [URL]` - Mendapatkan detail dokumen dari URL repositori
- `paper download [URL]` - Mengunduh dan menganalisis dokumen dari URL
- `paper analyze` - Menganalisis dokumen PDF yang direply
- `help` - Menampilkan menu bantuan

## Persyaratan

- Python 3.8+
- Neonize (Library WhatsApp)
- Thundra IO
- PyPDF2
- Akses ke Gemini API
- API Repository Karya Ilmiah

## Instalasi

1. Clone repository ini
   ```bash
   git clone https://github.com/classyid/WhatsApp-Academic-Repository-Bot.git
   cd WhatsApp-Academic-Repository-Bot
   ```

2. Install dependensi
   ```bash
   pip install -r requirements.txt
   ```

3. Konfigurasi
   - Sesuaikan `GEMINI_API_KEY` di file `config.py`
   - Atur `REPOSITORY_API_BASE_URL` sesuai dengan API repository Anda

4. Jalankan bot
   ```bash
   python main.py
   ```

5. Scan QR code untuk login ke WhatsApp

## Konfigurasi API Repository

Bot ini menggunakan API Repository dengan endpoint berikut:
- `/api/search` - Untuk mencari dokumen
- `/api/detail` - Untuk mendapatkan detail dokumen

Pastikan API Repository berjalan dan dapat diakses oleh bot.

## Kontribusi

Kontribusi selalu diterima! Silakan buat pull request atau laporkan isu jika Anda menemukan bug atau memiliki saran fitur baru.

## Lisensi

[MIT License](LICENSE)
```
