"""Local Windows OCR for the small visible group-sender label only."""
import asyncio,re
from difflib import SequenceMatcher
from PIL import Image,ImageEnhance,ImageOps


def resolve_sender(text,members):
    normalize=lambda s:re.sub(r'\s+','',s)
    text=normalize(text)
    if not text:return ''
    exact=[name for name in members if normalize(name)==text]
    if len(exact)==1:return exact[0]
    scores=sorted(((SequenceMatcher(None,text,normalize(name)).ratio(),name) for name in members),reverse=True)
    if not scores or scores[0][0]<.65:return ''
    if len(scores)>1 and scores[0][0]-scores[1][0]<.2:return ''
    return scores[0][1]


class SenderReader:
    def __init__(self):
        from winrt.windows.media.ocr import OcrEngine
        self.engine=OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:raise RuntimeError('Windows 缺少文字识别语言，无法识别群成员昵称。')

    def read(self,picture,enhance=True):
        from winrt.windows.storage.streams import Buffer
        from winrt.windows.graphics.imaging import SoftwareBitmap,BitmapPixelFormat,BitmapAlphaMode
        # This is a transient in-memory label crop. No desktop screenshots
        # are written to Documents or uploaded to Muse.
        if enhance:picture=ImageOps.autocontrast(ImageOps.grayscale(picture))
        picture=picture.resize((picture.width*3,picture.height*3),Image.Resampling.LANCZOS).convert('RGBA')
        raw=picture.tobytes('raw','BGRA');buffer=Buffer(len(raw));buffer.length=len(raw)
        memoryview(buffer)[:]=raw
        bitmap=SoftwareBitmap.create_copy_from_buffer(buffer,BitmapPixelFormat.BGRA8,
                   picture.width,picture.height,BitmapAlphaMode.IGNORE)
        async def recognize():return await self.engine.recognize_async(bitmap)
        try:
            result=asyncio.run(recognize())
            lines=list(result.lines)
            return lines[0].text.strip()[:100] if len(lines)==1 else ''
        finally:bitmap.close()
