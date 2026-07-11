import yt_dlp
import os
import asyncio
import uuid
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def download_instagram_video(url: str) -> Optional[str]:
    """
    Instagram videosini yuklab oladi va fayl yo'lini qaytaradi.
    Xatolik yuz bersa Exception chiqaradi.
    """
    # Vaqtinchalik fayl nomi uchun unique ID
    file_id = str(uuid.uuid4())
    
    # Downloads papkasi mavjudligini tekshirish
    if not os.path.exists("downloads"):
        os.makedirs("downloads", exist_ok=True)
        
    output_template = os.path.join("downloads", f"{file_id}.%(ext)s")

    ydl_opts = {
        'format': 'bestvideo+bestaudio[ext=m4a]/best', # Try to get mp4/m4a
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/',
        },
        'nocheckcertificate': True,
        'ignoreerrors': False, # Set to False to catch exceptions
        'socket_timeout': 30,
        'retries': 5,
        'geo_bypass': True,
    }

    def _download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Try to extract info and download
                info = ydl.extract_info(url, download=True)
                if not info:
                    return None
                # Return the filename that was actually written
                return ydl.prepare_filename(info)
        except Exception as e:
            logger.error(f"yt-dlp error for {url}: {e}")
            return None

    try:
        # yt-dlp sync bloklovchi bo'lgani uchun thread'da ishlatamiz
        loop = asyncio.get_event_loop()
        file_path = await loop.run_in_executor(None, _download)
        
        if not file_path:
            return None
            
        # Ba'zan extension kutilganidan farq qilishi mumkin
        if not os.path.exists(file_path):
            # Agar template bo'yicha topilmasa, mp4 qidirib ko'ramiz
            expected_mp4 = os.path.join("downloads", f"{file_id}.mp4")
            if os.path.exists(expected_mp4):
                file_path = expected_mp4
            else:
                return None
                
        return file_path
    except Exception as e:
        logger.error(f"Download task error: {e}")
        return None
