"""
This module provides a service for reading images from an IP cam,
detecting lines and circles via Hough transform and produce a needle
position estimate.

Results are provided via built-in webserver, e.g. <http://localhost:8000>,
<http://localhost:8000/debug>, or <http://localhost:8000/time>.


TODO: JS onload update does not warn if server is stalling and providing no image

TODO: adjust example-settings for the images placed in README.md

TODO: opencv natively only supports the Hershey font, which lacks special characters like the degree symbol
    Either use PIL instead of cv2.putText https://stackoverflow.com/questions/37191008/load-truetype-font-to-opencv
        which introduces a additional dependency
    or use the TTF font support that comes with opencv 3.0, but not all opencv installations are compiled with
        freetype support

TODO: are lines long enough to get angle from start and end?
    (It would avoid extrapolation to the noise center position) median filter would not be required (make single image
    mode easier)

"""

__version__ = 0.1
