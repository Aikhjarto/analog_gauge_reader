import http.server
import logging
import logging.handlers
import os
import shutil
import zlib
from http import HTTPStatus

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# HTML template string without refresh
html_template = r"""<html><head>
<meta charset="utf-8" />
{head}
</head><body>
{body}
</body></html>
"""

# img = np.array((32, 32, 3), dtype=np.uint8)
# favicon = cv2.imencode('*.png', img)[1].tobytes()
favicon = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x03\x08\x00\x00\x00\x00w\xb6:^\x00\x00\x00\x0eIDAT\x08\x1dcP`P``\x06\x00\x01\t\x00D\x80E+\xa9\x00\x00\x00\x00IEND\xaeB`\x82'


# noinspection PyPep8Naming
class HTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    HTTP request handler with support for chunking and compression in do_GET.
    """

    def do_HEAD(self):
        """ send a simple HTTP text/html header with caching disabled"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        self.send_header('Expires', '0')
        self.end_headers()

    def do_GET(self):

        if self.path == '/favicon.ico':
            self.send_response(200)
            self.send_header('Content-Type', 'image/vnd.microsoft.icon')
            self.send_header('Content-Length', str(len(favicon)))
            self.end_headers()
            self.wfile.write(favicon)

        else:  # any other path
            self.send_response(404)
            self.end_headers()

    def send_chunked_header(self):
        """
        Uses `self.send_header` to set 'Transfer-Encoding' and 'Content-Encoding'
        """
        self.send_header('Transfer-Encoding', 'chunked')
        if 'gzip' in self.headers.get('Accept-Encoding', '').split(', '):
            self.send_header('Content-Encoding', 'gzip')

    def write_chunked(self, data: bytes):
        """
        Like `self.write`, but transparently uses chunked encoding and compression.
        After last use of `write_chunked`, `self.end_write` must be used to flush buffers.

        """
        if 'gzip' in self.headers.get('Accept-Encoding', '').split(', '):
            if not hasattr(self, '_cmp'):
                # noinspection PyAttributeOutsideInit
                self._cmp = zlib.compressobj(-1, zlib.DEFLATED, zlib.MAX_WBITS | 16)
            data = self._cmp.compress(data)

        self._write_chunk(data)

    def _write_chunk(self, data: bytes):
        if data:
            self.wfile.write('{:X}\r\n'.format(len(data)).encode())
            self.wfile.write(data)
            self.wfile.write('\r\n'.encode())

    def end_write(self):
        """
        Must be used after last call to `self.write_chunked` to flush buffers.
        """
        if hasattr(self, '_cmp'):
            ret = self._cmp.flush()

            # force delete _cmp so for the next request a new instance is generated
            del self._cmp

            self._write_chunk(ret)

        self.wfile.write('0\r\n\r\n'.encode())

    # noinspection PyShadowingBuiltins,PyShadowingNames
    def log_message(self, format, *args):
        """
        Override logging function, since per default every request is printed to stderr
        """

        if logger.level == logging.debug:
            logger.debug("%s %s",
                         self.address_string(), format % args)
        elif not self.is_localhost():
            logger.info("%s %s",
                        self.address_string(), format % args)

    def is_localhost(self):
        # noinspection SpellCheckingInspection
        return self.client_address[0] in ('127.0.0.1',
                                          '127.0.0.2',
                                          '::ffff:127.0.0.1',
                                          '::1')
