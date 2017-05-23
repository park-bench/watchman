#!/usr/bin/env python2

# Copyright 2015-2016 Joel Allen Luellwitz and Andrew Klapp
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import confighelper
import ConfigParser
import daemon
import glob
import logging
import os
import signal
import subprocess
import sys
import time
import traceback
import watchmanconfig

pid_file = '/run/watchman.pid'

print('Loading configuration.')
config_file = ConfigParser.RawConfigParser()
config_file.read('/etc/watchman/watchman.conf')

# Figure out the logging options so that can start before anything else.
print('Verifying configuration.')
config_helper = confighelper.ConfigHelper()
log_file = config_helper.verify_string_exists_prelogging(config_file, 'main_process_log_file')
log_level = config_helper.verify_string_exists_prelogging(config_file, 'main_process_log_level')

config_helper.configure_logger(log_file, log_level)
logger = logging.getLogger()

subprocess_pathname = config_helper.verify_string_exists(config_file, 'subprocess_pathname')

# We don't care what the results are, we just want the program to die if there is an error
#   with the subprocess configuration.
watchmanconfig.WatchmanConfig(config_file)

# The device we want to capture video with.
# TODO: Consider validating for a malicious path.
video_device_number = config_helper.verify_integer_exists(config_file, 'video_device_number')

watchman_subprocess = None

# Quit when SIGTERM is received
def sig_term_handler(signal, stack_frame):
    logger.critical("Quitting.")
    if watchman_subprocess <> None:
        logger.info("Killing watchman subprocess.");
        watchman_subprocess.kill()
    sys.exit(0)

# TODO: Work out a permissions setup for this program that it doesn't run as root.
daemon_context = daemon.DaemonContext(
    working_directory = '/',
    pidfile = pidlockfile.PIDLockFile(PID_FILE),
    umask = 0
    )

daemon_context.signal_map = {
    signal.SIGTERM : sig_term_handler
    }

with daemon_context:
    try:
        selected_device = '/dev/video%d' % video_device_number

        # Loop forever
        while 1:   

            # Startup the subprocess to that takes photos
            logger.info("Starting watchman subprocess with device %s." % selected_device)
            watchman_subprocess = subprocess.Popen([subprocess_pathname, '%d' % video_device_number])

            # Loop while the device exists
            while len(glob.glob(selected_device)) == 1 and watchman_subprocess.poll() == None:
                time.sleep(.1)

            # Kill the subprocess so it can be restarted
            try:
                logger.info("Detected device removal. Killing watchman subprocess.");
                # TODO: Send a signal to watchman to flush its current e-mail buffer, give it a second
                #   then do a kill or kill -9.
                watchman_subprocess.kill()
            except OSError as e:
                logger.error("Error killing watchman subprocess. %s: %s" % \
                    (type(e).__name__, e.message))
                logger.error("%s" % traceback.format_exc())
                logger.error("Ignoring.")

            # Wait for the device to come back
            while len(glob.glob(selected_device)) == 0:
                time.sleep(.1)

            logger.info("Detected device insertion.");

    except Exception as e:
        logger.critical("Fatal %s: %s" % (type(e).__name__, e.message))
        logger.error("%s" % traceback.format_exc())
        if watchman_subprocess <> None:
            logger.info("Killing watchman subprocess.");
            watchman_subprocess.kill()
        sys.exit(1)
