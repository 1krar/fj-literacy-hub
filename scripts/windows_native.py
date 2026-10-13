"""Win7-compatible window pinning and explicit image clipboard reads; stdlib only."""
import base64
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import re
import struct
import threading
import time
import zlib

MAX_PIXELS=16_000_000
MAX_PNG=5*1024*1024
clipboard_lock=threading.Lock()

def user32():
    if os.name!='nt':raise ValueError('此功能需要 Windows 本机助手')
    return c.WinDLL('user32',use_last_error=True)

def bitmap_pixels(bitmap):
    user=user32();gdi=c.WinDLL('gdi32',use_last_error=True)
    class Bitmap(c.Structure):
        _fields_=[('kind',w.LONG),('width',w.LONG),('height',w.LONG),('stride',w.LONG),
                  ('planes',w.WORD),('bits',w.WORD),('pixels',c.c_void_p)]
    class Header(c.Structure):
        _fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),
                  ('bits',w.WORD),('compression',w.DWORD),('image_size',w.DWORD),
                  ('x',w.LONG),('y',w.LONG),('colors',w.DWORD),('important',w.DWORD)]
    gdi.GetObjectW.argtypes=[w.HANDLE,c.c_int,c.c_void_p];gdi.GetObjectW.restype=c.c_int
    info=Bitmap()
    if not gdi.GetObjectW(bitmap,c.sizeof(info),c.byref(info)):raise ValueError('剪贴板位图读取失败，请重新截图')
    width,height=info.width,abs(info.height)
    if not 0<width<=16000 or not 0<height<=16000 or width*height>MAX_PIXELS:
        raise ValueError('截图尺寸过大，请裁剪后粘贴')
    header=Header(c.sizeof(Header),width,-height,1,32,0,width*height*4,0,0,0,0)
    pixels=c.create_string_buffer(width*height*4)
    user.GetDC.argtypes=[w.HWND];user.GetDC.restype=w.HDC
    user.ReleaseDC.argtypes=[w.HWND,w.HDC];user.ReleaseDC.restype=c.c_int
    gdi.GetDIBits.argtypes=[w.HDC,w.HANDLE,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT]
    gdi.GetDIBits.restype=c.c_int
    dc=user.GetDC(None)
    if not dc:raise ValueError('无法读取截图像素，请重试')
    try:
        if gdi.GetDIBits(dc,bitmap,0,height,pixels,c.byref(header),0)!=height:
            raise ValueError('截图格式转换失败，请改用图片文件上传')
    finally:user.ReleaseDC(None,dc)
    return width,height,pixels.raw

def png_from_bgra(width,height,pixels):
    if width<=0 or height<=0 or width*height>MAX_PIXELS or len(pixels)!=width*height*4:
        raise ValueError('无效的截图像素')
    def chunk(kind,raw):
        return struct.pack('>I',len(raw))+kind+raw+struct.pack('>I',zlib.crc32(kind+raw)&0xffffffff)
    compressor=zlib.compressobj(6);parts=[];size=0
    for row in range(height):
        bgra=pixels[row*width*4:(row+1)*width*4]
        rgb=bytearray(width*3);rgb[0::3]=bgra[2::4];rgb[1::3]=bgra[1::4];rgb[2::3]=bgra[0::4]
        encoded=compressor.compress(b'\0'+rgb);parts.append(encoded);size+=len(encoded)
        if size>MAX_PNG:raise ValueError('截图超过 5 MB，请裁剪后粘贴')
    parts.append(compressor.flush())
    result=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',b''.join(parts))+chunk(b'IEND',b'')
    if len(result)>MAX_PNG:raise ValueError('截图超过 5 MB，请裁剪后粘贴')
    return result

def clipboard_image():
    user=user32()
    user.OpenClipboard.argtypes=[w.HWND];user.OpenClipboard.restype=w.BOOL
    user.CloseClipboard.argtypes=[];user.CloseClipboard.restype=w.BOOL
    user.IsClipboardFormatAvailable.argtypes=[w.UINT];user.IsClipboardFormatAvailable.restype=w.BOOL
    user.GetClipboardData.argtypes=[w.UINT];user.GetClipboardData.restype=w.HANDLE
    with clipboard_lock:
        for attempt in range(5):
            if user.OpenClipboard(None):break
            time.sleep(.04)
        else:raise ValueError('剪贴板暂被占用，请再次粘贴')
        try:
            # Windows synthesizes CF_BITMAP for standard DIB/DIBV5 screenshots.
            if not user.IsClipboardFormatAvailable(2):raise ValueError('剪贴板没有截图，请先用截图工具复制图片，或拖入图片文件')
            bitmap=user.GetClipboardData(2)
            if not bitmap:raise ValueError('剪贴板图片尚未就绪，请重试')
            width,height,pixels=bitmap_pixels(bitmap)
        finally:user.CloseClipboard()
    raw=png_from_bgra(width,height,pixels)
    return {'image':'data:image/png;base64,'+base64.b64encode(raw).decode('ascii'),'bytes':len(raw)}

def edge_window(token):
    if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('小窗标识无效')
    user=user32();kernel=c.WinDLL('kernel32',use_last_error=True)
    callback_type=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    user.EnumWindows.argtypes=[callback_type,w.LPARAM];user.EnumWindows.restype=w.BOOL
    user.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,c.c_int];user.GetWindowTextW.restype=c.c_int
    user.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)];user.GetWindowThreadProcessId.restype=w.DWORD
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)];kernel.QueryFullProcessImageNameW.restype=w.BOOL
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
    matches=[];prefix='CTRL-FLOAT-'+token
    def callback(hwnd,param):
        title=c.create_unicode_buffer(512);user.GetWindowTextW(hwnd,title,len(title))
        if title.value!=prefix and not title.value.startswith(prefix+' - '):return True
        pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,c.byref(pid))
        process=kernel.OpenProcess(0x1000,False,pid.value)
        if process:
            try:
                path=c.create_unicode_buffer(32768);size=w.DWORD(len(path))
                if kernel.QueryFullProcessImageNameW(process,0,path,c.byref(size)) and Path(path.value).name.lower()=='msedge.exe':matches.append(hwnd)
            finally:kernel.CloseHandle(process)
        return True
    user.EnumWindows(callback_type(callback),0)
    if len(matches)>1:raise ValueError('检测到重复小窗，请关闭重复窗口后重试')
    return matches[0] if matches else None

def pin_window(token,enabled=True):
    if not isinstance(enabled,bool):raise ValueError('置顶参数无效')
    deadline=time.monotonic()+4
    while True:
        hwnd=edge_window(token)
        if hwnd:break
        if time.monotonic()>=deadline:raise ValueError('尚未找到助手小窗，请允许弹窗并重试置顶')
        time.sleep(.08)
    user=user32()
    user.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT];user.SetWindowPos.restype=w.BOOL
    if not user.SetWindowPos(hwnd,w.HWND(-1 if enabled else -2),0,0,0,0,0x13):
        raise ValueError('Windows 无法设置小窗置顶，请重试')
    return {'topmost':enabled}
