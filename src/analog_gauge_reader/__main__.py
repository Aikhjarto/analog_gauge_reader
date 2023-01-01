import argparse
import logging
import numpy as np
import os
from ._analog_gauge_reader import main
from ._image_processing import ThresholdMode
from analog_gauge_reader._parser import add_logging, setup_logging, LoadFromFile, add_mqtt
logger = logging.getLogger('analog_gauge_reader')

def setup_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()

    p.add_argument('--settings-filename', type=open, action=LoadFromFile,
                   help='Read parameters from a file')

    p.add_argument('--port', type=int, default=None, choices=range(1, 65534),
                   metavar='[1-65534]',
                   help='TCP port number to start a http server showing live and debug images.')

    p.add_argument('--sensor-name', type=str, default='sensor1',
                   help='Used when publishing data.')

    # logging
    g = p.add_argument_group(title='Logging')

    add_logging(g)
    # parameters for obtaining images
    g = p.add_argument_group(title='Parameters for obtaining images')
    g1 = g.add_mutually_exclusive_group()
    # Note: mutually_exclusive_group does not trigger if one argument is given with --settings-file and
    #       the other one is given directly, thus have a separate check later.

    g1.add_argument('--cam-id', type=int, default=None,
                    help='If given, it will be passed to cv2.VideoCapture() as camera ID. '
                         'If you have only one camera in your system, camera  is usually 0. '
                         'In case of multiple cameras, consult the documentation of '
                         'openCV on how to obtain the camera ID')

    g1.add_argument('--url', type=str, default=None,
                    help='Download image from an URL, e.g. http://camera.private.lan:8000/snapshot.cgi')

    g.add_argument('--username', type=str, default=None,
                   help='Username used to download --url')

    g.add_argument('--password', type=str, default=None,
                   help='Password used to download --url.'
                        'Using this in the CLI exposes your password to all users '
                        '(visible with programs like `ps` or `top`). '
                        'Better read it via the --settings-file argument for a file with restrictive read-permissions '
                        'or provide it via the environment variable ANALOG_GAUGE_READER_IMAGE_PASSWORD')

    g.add_argument('--min-measurement-interval', type=float, default=None)

    # image processing parameters
    g = p.add_argument_group(title='Image processing',
                             description='Tuning for lighting conditions')
    g.add_argument('--threshold', type=int, choices=range(1, 254), default=175, metavar='[1-254]',
                   help='For line detection a threshold is used to discriminate the black needle '
                        'from the non-black face of the gauge')
    g.add_argument('--threshold-mode', type=ThresholdMode, choices=list(ThresholdMode))

    g.add_argument('--blur-size', type=int, default=5)
    g.add_argument('--r-inner-min', type=float, default=0.15)
    g.add_argument('--r-inner-max', type=float, default=0.6)
    g.add_argument('--r-outer-min', type=float, default=0.65)
    g.add_argument('--r-outer-max', type=float, default=0.95,
                   help='Crop rim of gauge.')

    # conversion from needle angle to value
    g = p.add_argument_group(title='Conversion from angle to value')
    g.add_argument('--min-value', default=None, type=float)
    g.add_argument('--max-value', default=None, type=float)
    g.add_argument('--min-angle', default=None, type=float)
    g.add_argument('--max-angle', default=None, type=float)
    g.add_argument('--unit', type=str, default=None,
                   help='Suffix used as unit, e.g. "V" for voltmeter, "bar" for a pressure gauge.')

    # warnings
    g = p.add_argument_group(title='Warnings')
    g.add_argument('--min-warn', default=-np.inf, type=float)
    g.add_argument('--max-warn', default=np.inf, type=float)
    g.add_argument('--warn-interval', default=600, type=float,
                   help='Minimum interval in seconds between consecutive warning messages sent.')
    g.add_argument('--no-warnings', default=False, action='store_true')
    g.add_argument('--xmpp-recipients', type=str, nargs='*', default=[],
                   help='The external program `sendxmpp` is used to deliver warnings via XMPP.'
                        'Sender credentials go to `~/.sendxmpprc`')
    g.add_argument('--warn-no-detections-s', type=float, default=1800.0, metavar='x',
                   help='Send a warning after `x` seconds of no detections')
    g.add_argument('--test-warning', type=str, default=None,
                   help='Send a test-warning and the quit.')
    g.add_argument('--warning-template', type=str, default='$value at $time')

    # look
    g = p.add_argument_group(title='Look')
    g.add_argument('--text-scale', default=1.0, type=float)

    g = p.add_argument_group(title='MQTT')
    add_mqtt(g)
    g.add_argument('--mqtt-publish-topic', type=str, default="analog_gauge_reader")

    return p


if __name__ == '__main__':

    # parse arguments
    parser = setup_parser()
    args = parser.parse_args()
    del args.settings_filename

    # input sanity checks
    # Lots of checks are necessary because mutual inclusive groups are not yet in argparse
    # https://bugs.python.org/issue11588
    scale = [args.min_value, args.max_value, args.min_angle, args.max_angle]
    if not (all([val is None for val in scale]) or all([val is not None for val in scale])):
        parser.error('Either all or none of {--min-value, --max-value, --min-angle, --max-angle} must be given')

    if (args.url is None and args.cam_id is None) or (args.url is not None and args.cam_id is not None):
        parser.error('Either an --url or a --cam-id must be given')

    if not args.password:
        args.password = os.getenv('ANALOG_GAUGE_READER_IMAGE_PASSWORD')

    setup_logging(logger, syslog=args.syslog, loglevel=args.loglevel)
    logger.debug('Starting with parameters %s', args.__dict__)
    del args.loglevel
    del args.syslog

    # logging.getLogger('analog_gauge_reader.image_processing').setLevel(logging.WARNING)

    # start image processing
    main(**args.__dict__)
