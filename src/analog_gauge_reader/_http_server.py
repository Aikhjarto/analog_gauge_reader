import base64
import logging
import pickle
import socket
import socketserver
import time
from threading import Lock
from analog_gauge_reader._http_request_handler import html_template, HTTPRequestHandler

logger = logging.getLogger('analog_gauge_reader.httpd')

# HTML template string with refresh
# Use with caution, since http-equiv="refresh" causes severe flickering in most browsers
html_template_autoreload = html_template.format(head='<meta http-equiv="refresh" content="1" />',
                                                body='{body}')


# TODO: append journalctl -u gauge\@-home-thomas-settings_heizungsdruck.txt.service --since= 

def str_to_html_id(s):
    """
    Encode a string, so it can be used as an id in HTML.
    """
    # prefix (here `id_`) is required since base64 encoded strings can start with a number
    return f'id_{base64.b64encode(s.encode()).decode()}'


class DebugViewerServer(socketserver.ThreadingTCPServer):
    # allow for rapid stop/start cycles during debugging
    # Assumption is, that no other process will start listening on `port` during restart of this script
    allow_reuse_address = True

    # allow IPv4 and IPv6
    address_family = socket.AF_INET6

    def __init__(self, *args, **kwargs):
        self.my_lock = Lock()
        self.server_data = {}
        super().__init__(*args, **kwargs)


# noinspection PyPep8Naming


debug_image_names = ('raw', 'detect_dial_debug_img', 'after_threshold_img', 'detect_needle_debug_img', 'final_img')


class DebugViewerRequestHandler(HTTPRequestHandler):
    server: DebugViewerServer

    def do_GET(self):

        # TODO: serve folder with debug images of failed detections

        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Cache-Control", "public")
            self.end_headers()
            # body = '<img src="/result.jpg" alt="Result"/><p><a href="/time" class="button">History</a></p>'
            # html = html_template_autoreload.format(body)
            html = """<html><head>
<script type="text/JavaScript">
var timeoutPeriod = 1000;
var imageURI = '/result.jpg';
var img = new Image();
img.onload = function() {
    var canvas = document.getElementById("x");
    var context = canvas.getContext("2d");
    canvas.setAttribute("width", img.width)
    canvas.setAttribute("height", img.height)

    context.drawImage(img, 0, 0);
    setTimeout(timedRefresh,timeoutPeriod);
};

function timedRefresh() {
    // just change src attribute, will always trigger the onload callback
    //img.src = imageURI + '#d=' + Date.now();
    img.src = imageURI;
}
</script>
<title>Gauge Reader</title>
</head>
<body onload="JavaScript:timedRefresh(1000);">
<p><canvas id="x" width="30" height="30"></canvas></p>
<p><a href="/debug" class="button">Debug</a></p>
</body>
</html>
"""
            self.wfile.write(html.encode())

        elif self.path == '/data':
            # without arguments, data servers the current value
            with self.server.my_lock:
                if 'data' in self.server.server_data:
                    content_type = 'text/plain'
                    data = self.server.server_data['data'].encode()
                else:
                    content_type = 'text/html'
                    data = html_template_autoreload.format(body='Waiting for first data sample...').encode()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header('Cache-Control', 'no-store, must-revalidate')
            self.send_header('Expires', '0')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif self.path == '/result.jpg' or self.path.startswith('/result.jpg#'):
            """
            Serve resulting image. The hash-suffix is required for javascript based
            flicker-free reload.
            """

            if 'img' in self.server.server_data:
                data = self.server.server_data['img']
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header('Cache-Control', 'no-store, must-revalidate')
                self.send_header('Expires', '0')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(503, message='Cannot find requested image')

        elif self.path.startswith('/debug/') and self.path[-4:] == '.jpg':
            # /debug/*.jpg is requested

            with self.server.my_lock:
                # reset debug timer
                self.server.server_data['last_time_debug_was_requested'] = time.time()

                if 'debug_jpgs' in self.server.server_data and self.path[7:-4] in self.server.server_data['debug_jpgs']:
                    # serve image if available
                    data = self.server.server_data['debug_jpgs'][self.path[7:-4]]
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header('Cache-Control', 'no-store, must-revalidate')
                    self.send_header('Expires', '0')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    # serve list of available images
                    debug_jpgs = self.server.server_data.get('debug_jpgs', {})
                    body = f'Currently available debug images: {debug_jpgs.keys()}'
                    data = html_template_autoreload.format(body=body).encode()

                    self.send_response(503)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(data)))
                    self.wfile.write(data)

        elif self.path == '/debug':

            with self.server.my_lock:
                # reset debug timer
                self.server.server_data['last_time_debug_was_requested'] = time.time()

                # generate content for HTML <body>
                if 'debug_jpgs' in self.server.server_data:
                    # auto-reload page would be simple, but shows heavy flickering on most browsers
                    # body = []
                    # for key in self.server.server_data['debug_jpgs']:
                    #     body.append(f'<img src="/debug/{key}.jpg" alt="{key}" id="{str_to_html_id(key)}" />')
                    # html = html_template_autoreload.format(''.join(body))

                    # reload via javascript is flicker-less, but image position does not auto-adjust with page-resize
                    body = ["<html><head>\n"
                            '<script type="text/JavaScript">\n'
                            'var timeoutPeriod = 1000;\n'
                            'var imgs = [']
                    body.extend(['new Image(),'] * len(debug_image_names))
                    body.append('];\n')
                    for i, key in enumerate(debug_image_names):
                        body.append(f'\nimgs[{i}].onload = function() {{\n'
                                    f'var canvas = document.getElementById("{str_to_html_id(key)}");\n'
                                    'var context = canvas.getContext("2d");\n'
                                    f'canvas.setAttribute("width", imgs[{i}].width);\n'
                                    f'canvas.setAttribute("height", imgs[{i}].height);\n'
                                    f'context.drawImage(imgs[{i}], 0, 0);\n'
                                    'setTimeout(timedRefresh,timeoutPeriod);\n'
                                    '};\n')
                    body.append('function timedRefresh() {\n'
                                '// just change src attribute, will always trigger the onload callback\n'
                                "//img.src = imageURI + '#d=' + Date.now();\n")
                    for i, key in enumerate(debug_image_names):
                        body.append(f'imgs[{i}].src = "/debug/{key}.jpg";\n')
                    body.append('};\n</script>\n')

                    body.append('<title>Gauge Reader</title>\n')
                    body.append('</head><body onload="JavaScript:timedRefresh(1000);">\n')
                    for key in debug_image_names:
                        body.append(f'<canvas id="{str_to_html_id(key)}" width="30" height="30"></canvas>\n')
                    body.append('<p>'
                                '<a href="/" class="button">Live</a></p>\n')

                    body.append('</body></html>')
                    html = ''.join(body)
                else:
                    body = '<p>Debug images are generated. Please wait...</p>\n'
                    html = html_template_autoreload.format(body=body)

            data = html.encode()

            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()

            self.wfile.write(data)

        elif self.path == '/is_debug':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', '1')
            self.end_headers()

            # keep debug flag active for 10 seconds after last time a debug was requested
            data = b'0'
            with self.server.my_lock:
                last_time = self.server.server_data.get('last_time_debug_was_requested', 0.0)
            if time.time() < last_time + 10:
                data = b'1'

            self.wfile.write(data)

        else:  # any other path
            super().do_GET()

    # noinspection PyPep8Naming
    def do_POST(self):
        if not self.is_localhost():
            # only accept POST from localhost, ideally it would be only from this process
            logger.debug('POST from %s rejected', self.client_address)
            self.send_response(403)
            self.end_headers()
            return

        # send OK response
        self.send_response(200)
        self.end_headers()

        # get data
        content_len = self.headers.get('Content-Length')
        post_body = self.rfile.read(int(content_len))

        for path in ('data', 'time'):
            if self.path == '/'+path:
                data = post_body.decode()
                with self.server.my_lock:
                    self.server.server_data[path] = data

        for path in ('img', ):
            if self.path == '/'+path:
                with self.server.my_lock:
                    self.server.server_data[path] = post_body

        if self.path == '/debug':
            data = pickle.loads(post_body)
            with self.server.my_lock:
                self.server.server_data['debug_jpgs'] = data


def start_httpserver(port=8000):
    logger.info('Starting debug HTTP server on port %s', port)

    # start server
    with DebugViewerServer(("", port), DebugViewerRequestHandler) as httpd:
        httpd.serve_forever()
