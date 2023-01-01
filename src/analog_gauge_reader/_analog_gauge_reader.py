import cv2
from datetime import datetime
import exifread
import glob
import logging
import numpy as np
import os
import pickle
import time
import requests
import string
from threading import Thread
import urllib3
from ._http_server import start_httpserver
from ._image_processing import detect_dial, draw_dial, get_needle_angle
from ._warnings import send_warning


logger = logging.getLogger('analog_gauge_reader.main')


class DetectionError(Exception):
    """
    Named exception for easier exception handling when the Hough-transform
    does not find plausible circles or lines
    """
    pass


def angle2value(min_angle: float, max_angle: float, min_value: float,
                max_value: float, angle: float) -> float:
    """
    Convert angle of the needle to sensed value
    """
    angle_range = (max_angle - min_angle)
    value_range = (max_value - min_value)
    new_value = min_value + ((angle - min_angle) * value_range) / angle_range

    return float(new_value)


def get_image(url=None, cam_id=None, username=None, password=None, **kwargs):
    """
    Imports an image.

    **kwargs are forwarded to `requests.get()`, e.g. to set a timeout.

    Parameters
    ----------
    url : str
        If `url` starts with http, it will be downloaded using `username` and `password`.
        If `url` starts with file:// it will be opened.
    cam_id : int
        If `url` was None, `cam_id` will be used for cv2.VideoCapture() to grab a frame from the attached camera
        with id `cam_id`.
    username : str
        Optional username for image download.
    password : str
        Optional password for image download.

    Returns
    -------
    timestamp : datetime
        If url started with 'file://', timestamp is taken from exif data (if existing) or from file creation time.
        Otherwise, timestamp is taken at the start of execution of this function.

    img : np.ndarray
        The obtained image.

    """
    if (url is None and cam_id is None) or (url is not None and cam_id is not None):
        raise RuntimeError('Either an URL or a camera ID must be given')

    if url is not None and url.lower().startswith('http'):
        while True:
            timestamp = datetime.now()
            logger.debug('Import image from URL %s', url)
            try:
                # TODO do this in background thread
                resp = requests.get(url,
                                    auth=(username, password) if username is not None else None,
                                    **kwargs)
            except (requests.exceptions.RequestException,
                    urllib3.exceptions.HTTPError) as e:
                logger.error('%s', e)
                continue
            img = np.asarray(bytearray(resp.content), dtype='uint8')
            if len(img) == 0 or not resp.ok:
                logger.error('Empty image received from %s with %s: %s',
                             url, resp, resp.reason)
            else:
                img = cv2.imdecode(img, cv2.IMREAD_COLOR)
                logger.debug('Import image is done')
                yield timestamp, img

    elif url is not None and url.lower().startswith('file://'):
        filename = url[7:]
        for filename in glob.glob(filename):
            logger.debug('Import image from file %s', filename)
            if not os.path.isfile(filename):
                logger.error('%s is not a file', filename)
            else:
                img = cv2.imread(filename)
                with open(filename, 'rb') as f:
                    exif_data = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal")
                if 'EXIF DateTimeOriginal' in exif_data:
                    timestamp = datetime.strptime(exif_data['EXIF DateTimeOriginal'].values, '%Y:%m:%d %H:%M:%S')
                else:
                    timestamp = datetime.fromtimestamp(os.stat(filename).st_ctime)
                logger.debug('Import image is done')
                yield timestamp, img

    elif cam_id is not None:
        cam_id = int(cam_id)
        logger.debug('Import image from camera %d', cam_id)
        cap = cv2.VideoCapture(cam_id)
        while True:
            timestamp = datetime.now()
            s, img = cap.read()
            if not s:
                logger.error('Empty image received from camera %d', cam_id)
            else:
                logger.debug('Import image is done')
                yield timestamp, img

    else:
        raise RuntimeError(f'Neither url "{url}" nor cam_id "{cam_id}" is understandable.')


def main(port=None,
         url=None, cam_id=0, username=None, password=None,  # parameters to access live image
         min_angle=None, max_angle=None, min_value=None, max_value=None, unit='degree',  # scaling the dial
         min_warn=None, max_warn=None, warn_interval=600, no_warnings=False,  # warnings
         warning_template='Pressure is $value at $time!',
         xmpp_recipients=None,  # warning recipients
         test_warning='', warn_no_detections_s=1800,
        sensor_name='sensor1',
         r_inner_min=0.15, r_inner_max=0.6, r_outer_min=0.65, r_outer_max=1.0,  # valid needle location
         threshold=175, threshold_mode=None,  # threshold for detecting black needle from white background
         blur_size=5,  # line detection works better on slight blur. must be an odd number
         text_scale=1.0, min_measurement_interval=None,
         post_url=None, post_username=None, post_password=None,
         mqtt_broker=None, mqtt_broker_port=1883, mqtt_username=None, mqtt_password=None, mqtt_publish_topic=None,
         median_filter_dial_position_N=20,
         median_filter_value_N=20,
         ):

    # just send a test-warning message and quit
    if test_warning:
        send_warning(test_warning, no_send=False, xmpp_recipients=xmpp_recipients)
        return

    # compile warning template and execute it right at the beginning to verify correctness.
    warning_template = string.Template(warning_template)
    warning_template.substitute(value='3.1 bar',
                                time=datetime.now().isoformat())

    if port:
        # start webserver
        http_thd = Thread(target=start_httpserver, daemon=True,
                          kwargs={'port': port, })
        http_thd.start()

        # sometimes the webserver needs a bit to start up and the first get to http://localhost:{port}/is_debug fails
        # Crude solution: wait a bit
        time.sleep(0.2)
        requests.get(f'http://localhost:{port}/is_debug', timeout=1.0)

    if mqtt_broker:
        import paho.mqtt.client as mqtt
        mqtt_client = mqtt.Client()
        mqtt_client.username_pw_set(mqtt_username, mqtt_password)
        mqtt_client.connect(host=mqtt_broker, port=mqtt_broker_port)
        mqtt_client.loop_start()

    # init
    debug_export_number = 0
    last_warn_time = time.time()-warn_interval  # time keeping for interval of warning messages
    calibration_lst = []
    values_lst = []
    avg = np.nan
    loop_start_time = 0.0  # time keeping for minimum loop duration
    last_successful_detection_time = time.time()  # watchdog for series of non-detections

    # main loop
    for timestamp, img_c in get_image(url=url, cam_id=cam_id,
                                      username=username, password=password,
                                      timeout=5.0):

        # limit rate for the case the loop just falls through due to errors like "ConnectionRefused" or firewall
        # errors preventing import_img() to retry too quickly
        if min_measurement_interval:
            time.sleep(max(0.0, (loop_start_time+min_measurement_interval)-time.time()))

        loop_start_time = time.time()

        debug_imgs = {'raw': img_c.copy()  # store image before it's annotated
                      }

        # convert to grayscale
        if img_c.ndim == 2:
            gray = img_c
            img_c = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        else:
            gray = cv2.cvtColor(img_c, cv2.COLOR_BGR2GRAY)

        # draw timestamp as text with outline
        for color, thickness in (((0, 0, 0), 2), ((255, 255, 255), 1)):
            cv2.putText(img_c, f'{timestamp.isoformat()}',
                        (0, img_c.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        text_scale * 1.3, color, thickness, cv2.LINE_AA)

        try:
            # detect circle of gauge median filter over found circles
            x, y, r, detect_dial_debug_img = detect_dial(gray)
            debug_imgs['detect_dial_debug_img'] = detect_dial_debug_img

            # abort no circles have been found
            if x is None:
                raise DetectionError('No circles found')

            # median filter position and radius of detected dial
            if int(median_filter_dial_position_N) > 1:
                calibration_lst.append((x, y, r))
                while len(calibration_lst) > median_filter_dial_position_N:
                    del calibration_lst[0]
                x, y, r = np.median(calibration_lst, axis=0)

            # draw median filtered dial
            cv2.circle(img_c, (int(x), int(y)), int(r), (0, 0, 255), 3, cv2.LINE_AA)  # draw red chassis
            draw_dial(img_c, x, y, r, text_scale=text_scale,
                      min_value=min_value, max_value=max_value, min_angle=min_angle, max_angle=max_angle)

            # get needle angle
            needle_angle, \
                detect_needle_debug_img, \
                after_threshold_debug_img = get_needle_angle(gray, x, y, r,
                                                             threshold=threshold,
                                                             threshold_mode=threshold_mode,
                                                             blur_size=blur_size,
                                                             r_inner_min=r_inner_min,
                                                             r_inner_max=r_inner_max,
                                                             r_outer_min=r_outer_min,
                                                             r_outer_max=r_outer_max,)
            debug_imgs['after_threshold_img'] = after_threshold_debug_img
            debug_imgs['detect_needle_debug_img'] = detect_needle_debug_img

            # abort when needle is not found
            if isinstance(needle_angle, str):
                raise DetectionError(needle_angle)

            # draw needle
            cv2.line(img_c,
                     (int(x), int(y)),
                     (int(x+r*np.sin(-needle_angle)), int(y+r*np.cos(-needle_angle))),
                     (255, 0, 0), 2)  # draw blue needle

            # convert angle to read-out value if a conversion is given
            if min_angle is not None and max_angle is not None and min_value is not None and max_value is not None:
                value = angle2value(min_angle, max_angle, min_value, max_value, needle_angle*180/np.pi)
            else:
                value = needle_angle*180/np.pi

            # write value on image
            if not np.isnan(avg):
                w, h = cv2.getTextSize(f'{timestamp.isoformat()}', cv2.FONT_HERSHEY_SIMPLEX, 1, 2)[0]
                # plot value as text with outline
                for color, thickness in (((0, 0, 0), 2), ((255, 255, 255), 1)):
                    cv2.putText(img_c, f'{avg:g} {unit}',
                                (int(w*text_scale*1.3)+10, img_c.shape[0]-10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                text_scale*1.3, color, thickness, cv2.LINE_AA)

            # send current timestamp/value-pair to various locations
            status = f"{timestamp.isoformat()},{sensor_name},{value},{unit}"
            logger.info('%s', status)

            # send to an auxiliary webservice via HTTP post
            if post_url:
                try:
                    resp = requests.post(post_url, auth=(post_username, post_password),
                                         data={'timestamp': timestamp.isoformat(),
                                               'sensor_name': sensor_name,
                                               'value': value
                                               })
                    logger.error('Posting to %s failed with %s; %s',
                                 post_url, resp.reason, resp.content)
                except (requests.exceptions.RequestException,
                        urllib3.exceptions.HTTPError) as e:
                    logger.error('Cannot post to url %s, error was %s',
                                 post_url, e)
            if port:
                # send new data to visualization server
                requests.post(f'http://localhost:{port}/data', status.encode(), timeout=1.0)

            if mqtt_broker:
                mqtt_client.publish(mqtt_publish_topic,
                                    '{{"epoch":{},"value":{:0.2f}}}'.format(timestamp.timestamp(), value),
                                    qos=1)

            # store last few values for median filter for warnings
            values_lst.append(value)
            while len(values_lst) > median_filter_value_N:
                del values_lst[0]
            if len(values_lst) >= median_filter_value_N and (last_warn_time+warn_interval) < time.time():
                # warn if averaged needle position is out of desired region
                avg = np.median(values_lst)
                if avg <= min_warn or avg >= max_warn:
                    msg = warning_template.substitute(value=f'{avg:g}{" "+unit if unit else ""}',
                                                      time=datetime.now().isoformat())

                    send_warning(msg, no_send=no_warnings, xmpp_recipients=xmpp_recipients)
                    last_warn_time = time.time()

            # reset watchdog
            last_successful_detection_time = time.time()

            logger.debug('Image processing finished')

        except DetectionError as e:
            logger.warning('%s', e)
            # increase number to store the last few images for which detection went wrong
            debug_export_number = (debug_export_number + 1) % 10

        if port:
            # send resulting images to HTTP server as JPG
            jpg = cv2.imencode('.jpg', img_c)[1].tobytes()
            requests.post(f'http://localhost:{port}/img', jpg, timeout=1.0)

            # check is we need to supply debug images to webserver
            is_debug = bool(int(requests.get(f'http://localhost:{port}/is_debug', timeout=1.0).content))

            if is_debug:
                # encode numpy arrays of debug plots to JPG
                debug_jpgs = {}
                for key, value in debug_imgs.items():
                    debug_jpgs[key] = cv2.imencode('.jpg', value)[1].tobytes()
                debug_jpgs['final_img'] = jpg

                requests.post(f'http://localhost:{port}/debug', pickle.dumps(debug_jpgs), timeout=1.0)

            # TODO: write to disk if --url was pointing to a file and in debug mode


        # send a warning if no successful needle detection was made in quite some time
        if (last_successful_detection_time + warn_no_detections_s) < time.time() and \
                (last_warn_time + warn_interval) < time.time():
            last_warn_time = time.time()
            last_successful_detection_time_str = datetime.fromtimestamp(last_successful_detection_time).isoformat()
            send_warning(f'No measurement since {last_successful_detection_time_str}')


class AnalogGaugeReader:

    def __init__(self, **kwargs):
        for key, val in kwargs:
            setattr(self, key, val)

        self.img_c = None

    def get_image(self):
        pass

    def run_once(self):
        pass

    def loop(self):
        pass

    def get_needle_angle(self):
        pass

    def get_gauge_outline(self):
        pass
