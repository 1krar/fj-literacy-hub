import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from windows_native import png_from_bgra,bitmap_pixels,edge_window,pin_window,clipboard_image

class NativeWindowsTests(unittest.TestCase):
    def test_png_converts_channels_and_ignores_undefined_clipboard_alpha(self):
        png=png_from_bgra(2,1,b'\x00\x00\xff\x00\x00\xff\x00\x00')
        self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n')
        offset=8;data=b''
        while offset<len(png):
            size=struct.unpack('>I',png[offset:offset+4])[0]
            kind=png[offset+4:offset+8];raw=png[offset+8:offset+8+size]
            if kind==b'IDAT':data+=raw
            offset+=size+12
        self.assertEqual(zlib.decompress(data),b'\0\xff\0\0\0\xff\0')

    def test_native_gdi_bitmap_conversion_without_touching_user_clipboard(self):
        gdi=c.WinDLL('gdi32')
        gdi.CreateBitmap.argtypes=[c.c_int,c.c_int,w.UINT,w.UINT,c.c_void_p];gdi.CreateBitmap.restype=w.HANDLE
        gdi.DeleteObject.argtypes=[w.HANDLE];gdi.DeleteObject.restype=w.BOOL
        raw=c.create_string_buffer(b'\0\0\xff\0'*4)
        handle=gdi.CreateBitmap(2,2,1,32,raw)
        self.assertTrue(handle)
        try:
            width,height,pixels=bitmap_pixels(handle)
            self.assertEqual((width,height),(2,2))
            self.assertTrue(png_from_bgra(width,height,pixels).startswith(b'\x89PNG'))
        finally:gdi.DeleteObject(handle)

    def test_window_token_rejects_arbitrary_titles_or_handles(self):
        for value in ('123','msedge.exe',123,None,'a'*33):
            with self.assertRaises(ValueError):edge_window(value)
        with self.assertRaises(ValueError):pin_window('a'*32,'yes')

    def test_missing_image_keeps_clipboard_closed_and_unchanged(self):
        with patch('windows_native.user32') as factory:
            user=factory.return_value;user.OpenClipboard.return_value=True
            user.IsClipboardFormatAvailable.return_value=False
            with self.assertRaisesRegex(ValueError,'没有截图'):clipboard_image()
            user.CloseClipboard.assert_called_once();user.GetClipboardData.assert_not_called()

    def test_oversized_or_truncated_pixels_rejected(self):
        for width,height,pixels in [(0,1,b''),(40000,40000,b''),(2,1,b'\0')]:
            with self.assertRaises(ValueError):png_from_bgra(width,height,pixels)

if __name__=='__main__':unittest.main()
