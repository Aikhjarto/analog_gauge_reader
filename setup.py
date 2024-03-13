#!/usr/bin/env python

from distutils.core import setup

setup(name='analog_gauge_reader',
      version='0.1',
      description='Takes webcam images from analog gauges and publishes readout values via mqtt',
      author='Thomas Wagner',
      author_email='wagner-thomas@gmx.at',
      url='https://github.com/Aikhjarto/analog_gauge_reader',
      include_package_data=True,
      package_data={'analog_gauge_reader': ['**/*.service', '**/*.timer'], }
      )
