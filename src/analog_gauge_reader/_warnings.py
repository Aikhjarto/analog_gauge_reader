import logging
import subprocess
import sys


logger = logging.getLogger('analog_gauge_reader')


def send_warning(msg, no_send=False, xmpp_recipients=None):
    """
    Process a warning.

    Parameters
    ----------
    msg : str
        The string that should be sent.
    no_send : bool
        If True, warning will be logged but not send (for debugging)
    xmpp_recipients : list[str]
        List of xmpp recipients.
        The program 'sendxmpp' must be installed and configured, so it does not query for a password.
    """

    if logger.level > logging.WARNING:
        # print to stderr if logger wouldn't catch it
        print(msg, file=sys.stderr)
    else:
        # send to logger
        logger.warning(msg)

    # send via XMPP
    if not no_send and xmpp_recipients is not None and len(xmpp_recipients) > 0:
        # '-a /etc/ssl/certs' must be given, since a bug in sendxmpp currently (2022Q1) prevents sendxmpp
        # from auto-detecting system-wide installed CAs.
        p = subprocess.Popen(['sendxmpp', '-t', '-a', '/etc/ssl/certs'] + xmpp_recipients,
                             stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout_data, stderr_data = p.communicate(input=msg.encode())
        # forward stderr of sendxmpp to stderr of this script
        if logger.level > logging.WARNING:
            # print to stderr if logger wouldn't catch it
            print(stdout_data.decode(), end='', file=sys.stderr)
            print(stderr_data.decode(), end='', file=sys.stderr)
        else:
            if len(stdout_data):
                logger.warning(stdout_data.decode())
            if len(stderr_data):
                logger.warning(stderr_data.decode())
