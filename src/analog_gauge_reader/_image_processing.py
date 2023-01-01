import cv2
from enum import Enum
import logging
import numpy as np
logger = logging.getLogger('analog_gauge_reader.image_processing')


class ThresholdMode(Enum):
    """
    Enum to select different threshold modes.

    This enum is specially crafted, so it can be used with argparse.ArgumentParser [1].

    References
    ----------
    .. [1] https://stackoverflow.com/questions/43968006/support-for-enum-arguments-in-argparse/55500795
    """
    none = None
    binary = 'binary'
    gray = 'gray'
    gauss = 'gauss'
    otsu = 'otsu'

    def __str__(self):
        return self.name


def dist_2_pts(x1, y1, x2, y2):
    return ((x2 - x1)**2 + (y2 - y1)**2)**0.5


def detect_dial(gray, use_filter=True,
                threshold_mode=None, threshold=150, blur_size=5,
                min_diameter=0.4, max_diameter=0.9):
    """
    Detects the face of the dial by searching for circles in the image `img` using HoughCircles function from OpenCV and
    averaging found circles to get a reliable result.

    Parameters
    ----------
    gray : np.ndarray
        The grayscale image where circles should be detected.

    use_filter : bool
        If True (Default), a median blur filter is applied to the image prior to the Hough transform. This is
        recommended by its documentation to get the best detection result. However, a median blur filter is
        computationally heavy. If `use_filter was False, the median blur filter is not applied.

    blur_size : int
        A positive integer used for the size in pixels of the median-blur filter.

    min_diameter : float
        Minimum diameter of circles to look for in percent (between 0.0 and 1.0) of the size
        (minimum of height and width) of the image.

    max_diameter : float
        See min_diameter.

    Returns
    -------
    x : float or None
        Horizontal position (left is 0.0) in pixels of the center of the averaged circles
        or None if no circles have been found.
    y : float or None
        Vertical position (top is 0.0) in pixels of the center of the averaged circles
        or None if no circles have been found.
    r : float or None
        Radius in pixels of the averaged circles or None if no circles have been found.
    img_c : np.ndarray
        A debug image with found circles and the average circle with its center on top of the input image
        to the Hough-transform is written to a file denoted by `debug_filename`.

    """

    height, width = gray.shape[:2]

    # worse performance with thresholding here
    # ret, gray = apply_threshold(gray, threshold_mode=threshold_mode, threshold=threshold, blur_size=blur_size)

    if use_filter:
        gray = cv2.medianBlur(gray, blur_size)
        # gray = cv2.Canny(gray, 50, 150)

    # detect circles
    r_max = min(height, width)*0.5  # maximum diameter for a circle to fit fully in image
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 20, np.array([]), 100, 50,
                               int(r_max*min_diameter), int(r_max*max_diameter))
    if circles is None or len(circles) == 0:
        x = None
        y = None
        r = None
        img_c = gray
        logger.debug('Found 0 circles')
    else:
        logger.debug('Found %d circles', len(circles))

        # average found circles, which is easier than tuning HoughCircles' parameters
        # for a perfect result under all conditions since the dial is never a perfect circle
        # in the camera image
        x, y, r = np.mean(circles, axis=1).flatten()

        # output circles on image
        img_c = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        for c in circles[0]:
            cv2.circle(img_c, (int(c[0]), int(c[1])), int(c[2]), (255, 200, 0), 1, cv2.LINE_AA)
        # draw center and circle
        cv2.circle(img_c, (int(x), int(y)), int(r), (0, 0, 255), 3, cv2.LINE_AA)  # draw circle
        cv2.circle(img_c, (int(x), int(y)), 2, (0, 255, 0), 3, cv2.LINE_AA)  # draw center of circle

    return x, y, r, img_c


def draw_dial(img, x, y, r, tick_width=2, text_scale=0.3, num=None,
              min_value=None, max_value=None, min_angle=None, max_angle=None):
    """
    Draws green ticks and black labels in a clock-wise circle starting with zero from the bottom

    Parameters
    ----------
    img : np.ndarray
        Image to draw on
    x : float
        See `detect_dial`
    y : float
        See `detect_dial`
    r : float
        See `detect_dial`
    tick_width : int
        Line-width used for ticks
    text_scale : float
        Adjust according to your camera resolution (larger scale for higher resolution).
    num : int
        Positive integer denoting the number of ticks.
    min_value : float
    max_value : float
    min_angle : float
    max_angle : float

    """
    from ._analog_gauge_reader import angle2value

    # generate points on a unit circle
    if min_value is None:
        if not num:
            num = 36
        steps_deg = np.linspace(0, 360, num, endpoint=False)
        text = [f'{step:g}' for step in steps_deg]
    else:
        if not num:
            num = 21
        steps_deg = np.linspace(min_angle, max_angle, num=num, endpoint=True)
        text = [f'{angle2value(min_angle, max_angle, min_value, max_value, step):g}' for step in steps_deg]

    # convert to radians
    steps_rad = steps_deg * np.pi / 180

    # generate points on unit circle
    x_c = np.sin(-steps_rad)
    y_c = np.cos(-steps_rad)

    # move and scale unit circle to match inner points of ticks
    p1x = x+0.9*r*x_c
    p1y = y+0.9*r*y_c

    # move and scale unit circle to match outer points of ticks
    p2x = x+r*x_c
    p2y = y+r*y_c

    # move and scale unit circle to match location of tick labels
    p_text_x = x+1.2*r*x_c
    p_text_y = y+1.2*r*y_c

    for i in range(0, len(steps_rad)):
        # draw ticks
        cv2.line(img, (int(p1x[i]), int(p1y[i])), (int(p2x[i]), int(p2y[i])), (0, 255, 0), tick_width)

        # get size of label
        w, h = cv2.getTextSize(text[i], cv2.FONT_HERSHEY_SIMPLEX, 1, 2)[0]

        # plot tick labels as text with outline
        for color, thickness in (((0, 0, 0), 2), ((255, 255, 255), 1)):
            cv2.putText(img, text[i],
                        (int(p_text_x[i]-w/2*text_scale), int(p_text_y[i]+h/2*text_scale*0)),
                        cv2.FONT_HERSHEY_SIMPLEX, text_scale, color, thickness, cv2.LINE_AA)


def apply_threshold(gray, threshold_mode, threshold=175, blur_size=5):

    # apply thresholding which helps for finding lines,
    # but fixed threshold is (a) hard to determine and (b) not working well when there is a shadow.

    ret = True

    if threshold_mode is None or threshold_mode == ThresholdMode.binary:
        ret, gray = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)  # black white
    elif threshold_mode == ThresholdMode.gray:
        ret, gray = cv2.threshold(gray, threshold, 255, cv2.THRESH_TOZERO)  # gray white
    elif threshold_mode == ThresholdMode.gauss:
        # adaptive gaussian thresholding has too many speckles for reliable detection
        gray = cv2.adaptiveThreshold(gray, 255,
                                     cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY_INV, 11, 2)
    elif threshold_mode == ThresholdMode.otsu:
        # OTSU
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        ret, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return ret, gray


def get_needle_angle(gray, x, y, r, threshold=150,
                     use_filter=False, blur_size=3,
                     min_line_length=10,
                     threshold_mode=None,
                     r_inner_min=0.15, r_inner_max=0.6, r_outer_min=0.65, r_outer_max=1.0):
    """
    Aims to detect the handle by finding lines in the image and returns the angle of the handle.

    First the image is converted to a grayscale image. Then the threshold is applied.
    In the binary image, lines are detected. Found lines are filtered to only contain
    valid handle positions. Remaining lines are averaged with a weight corresponding to the line
    length.

    Parameters
    ----------
    gray : np.ndarray
        The grayscale image the needle should be detected from.
    x : number
        x-coordinate of the rotary point of the needle in pixels
    y : number
        x-coordinate of the rotary point of the needle in pixels
    r : number
        radius of the gauge
    threshold : Integer
        Threshold (0-255) for black-white image.
    use_filter : bool
        On some gauges, Canny/blurring helps for line detection, on some gauges it does not.
    min_line_length : float or int
        Minimum length in pixels to be considered valid as a needle.
    blur_size : int
        Size in pixel for the blur-filter. Must be an odd number.
    threshold_mode : ThresholdMode
    r_inner_min : float
       On some gauges the needle is protruding lines from a quite large disk in the center of the gauge,
        which has the same color as the needle or has a counter-weight needle of significant length.
        To avoid false detections in this region, a blind radius in pixels can be given.
    r_inner_max : float
    r_outer_min : float
    r_outer_max : float

    Returns
    -------
    status : str or float
        Angle of the dial in radians (zero at bottom, positive direction is clockwise) of the found needle or a string
        with an error message if no needle was detected.

    img : np.ndarray
        Debug image with found lines in green, red and yellow circles denoting the valid regions for start- and
        end-points of lines representing the needle, and a blue line representing the found needle on top of the
        input image to the Hough transform.

    img_threshold : np.ndarray
        Debug image after thresholding (before filtering).
    """

    # mask inner disk (the round part where the needle is attached) by setting it to white
    cv2.circle(gray, (int(x), int(y)), int(r*r_inner_min), 255, -1, cv2.LINE_AA)

    # mask region outside of gauge
    mask = cv2.circle(255*np.ones_like(gray), (int(x), int(y)), int(r*r_outer_max), (0, 0, 0), -1)
    gray = cv2.bitwise_or(gray, mask)

    ret, gray = apply_threshold(gray, threshold_mode, threshold=threshold, blur_size=blur_size)

    # store image after thresholding (no .copy() needed since nothing writes on `gray` anymore)
    after_threshold = gray

    # HoughLines can perform better without or without Canny/blurring
    if use_filter:
        gray = cv2.medianBlur(gray, blur_size)
        gray = cv2.Canny(gray, 50, 150)
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)

    # find lines
    # rho is set to 3 to detect more lines, easier to get more than filter them out later
    lines = cv2.HoughLinesP(image=gray, rho=3, theta=np.pi / 180, threshold=100,
                            minLineLength=min_line_length, maxLineGap=0)

    if lines is None:
        return 'no lines from Hough transform detected', gray, after_threshold
    else:

        logger.debug('Found %d lines', len(lines))
        # show all found lines in green
        img_c = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        for i in range(0, len(lines)):
            for x1, y1, x2, y2 in lines[i]:
                cv2.line(img_c, (x1, y1), (x2, y2), (0, 255, 0), 1)

        final_line_list = filter_lines_for_needle(lines, x, y, r,
                                                  img=img_c,
                                                  r_inner_min=r_inner_min,
                                                  r_inner_max=r_inner_max,
                                                  r_outer_min=r_outer_min,
                                                  r_outer_max=r_outer_max
                                                  )
        logger.debug('%d lines are possible needles', len(final_line_list))
        if len(final_line_list) > 75:
            return f'found {len(final_line_list)} possible candidates for needle; ' \
                   f'check threshold level or reflections in glass', img_c, after_threshold

        # get angles from lines
        if len(final_line_list):
            angles = []
            lengths = []
            for line in final_line_list:
                x1, y1, x2, y2 = line

                dist_pt_1 = dist_2_pts(x, y, x1, y1)
                dist_pt_2 = dist_2_pts(x, y, x2, y2)
                if dist_pt_1 > dist_pt_2:
                    # atan2 is used weirdly to have the 0 degree at the bottom and go positive clock-wise
                    ang = np.arctan2(-(x1 - x), y1 - y)
                else:
                    ang = np.arctan2(-(x2 - x), y2 - y)

                length = dist_2_pts(x1, y1, x2, y2)  # length of found line
                lengths.append(length)
                if ang < 0:
                    ang += 2*np.pi
                angles.append(ang)

            final_angle_rad = np.average(angles, weights=lengths)

            return final_angle_rad, img_c, after_threshold
        else:
            return 'no lines after filtering for valid needle positions', img_c, after_threshold


def filter_lines_for_needle(lines, x, y, r, img=None,
                            min_length=0.2,
                            r_inner_min=0.15, r_inner_max=0.6, r_outer_min=0.65, r_outer_max=1.0):
    """
    Valid lines have one point in a disc near the rim of the gauge and one point in a disc near the
    center (but outside the disk from which the handle starts).
    """

    final_line_list = []

    # draw bounds for line detection
    if img is not None:
        cv2.circle(img, (int(x), int(y)), int(r*r_inner_min), (0, 0, 255), 1, cv2.LINE_AA)
        cv2.circle(img, (int(x), int(y)), int(r*r_inner_max), (0, 0, 255), 1, cv2.LINE_AA)
        cv2.circle(img, (int(x), int(y)), int(r*r_outer_min), (0, 255, 255), 1, cv2.LINE_AA)
        cv2.circle(img, (int(x), int(y)), int(r*r_outer_max), (0, 255, 255), 1, cv2.LINE_AA)

    for i in range(0, len(lines)):
        for x1, y1, x2, y2 in lines[i]:
            length = dist_2_pts(x1, y1, x2, y2)  # length of line
            if length < min_length*r:
                continue

            diff1 = dist_2_pts(x, y, x1, y1)     # x, y is center of circle
            diff2 = dist_2_pts(x, y, x2, y2)     # x, y is center of circle
            # set diff1 to be the smaller (closest to the center) of the two, to make logic easier
            if diff1 > diff2:
                temp = diff1
                diff1 = diff2
                diff2 = temp
            # check if line is within an acceptable range
            if (r_inner_min*r < diff1 < r_inner_max*r) and (r_outer_min*r < diff2 < r_outer_max*r):
                # add to final list
                final_line_list.append([x1, y1, x2, y2])

    # TODO: make a check whether or not a line goes through the center of the gauge (by means of the size of the disk
    #     on which the needle is attached, i.e. r_inner_min.
    #     Reason: it can be the case that lines from labels on the gauge are detected, and many of those lines don't go
    #     through the center of the gauge.

    # show all lines after filtering in blue
    if img is not None:
        for x1, y1, x2, y2 in final_line_list:
            cv2.line(img, (x1, y1), (x2, y2), (255, 0, 0), 1)

    return final_line_list
