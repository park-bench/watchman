#!/usr/bin/python3

# Copyright 2015-2026 Joel Allen Luellwitz and Emily Frost
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

"""Daemon to record and send images when motion is detected on a camera."""

# TODO: Eventually consider running in a chroot or jail. (gpgmailer issue 17)

__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.9'

import glob
import logging
import os
import pwd
import sdnotify
import signal
import stat
import subprocess
import time
import traceback
import threading
import cammonconfig
from parkbenchcommon import confighelper

# Constants
PROGRAM_NAME = 'cammon'
CONFIGURATION_PATHNAME = f'/etc/{PROGRAM_NAME}/{PROGRAM_NAME}.conf'
IMAGE_DIR = f'/var/log/{PROGRAM_NAME}/images'
PROCESS_USERNAME = PROGRAM_NAME
SUBPROCESS_PATHNAME = f'/usr/share/{PROGRAM_NAME}/{PROGRAM_NAME}-subprocess.py'
VIDEO_DEVICE_PREFIX = '/dev/video%d'

termination_event = threading.Event()


class InitializationException(Exception):
    """Indicates an expected fatal error occurred during program initialization.
    Initialization is implied to mean, before daemonization.
    """


def get_user_id():
    """Return (int): The user ID that the program runs as."""

    try:
        program_user = pwd.getpwnam(PROCESS_USERNAME)
    except KeyError as key_error:
        message = f'User {PROCESS_USERNAME} does not exist.'
        raise InitializationException(message) from key_error

    return program_user.pw_uid


# TODO: Consider checking ACLs. (gpgmailer issue 22)
def verify_safe_file_permissions():
    """Crashes the application if unsafe file permissions exist on application configuration
    files.
    """
    if not os.path.isfile(CONFIGURATION_PATHNAME):
        raise InitializationException(
            f'Configuration file {CONFIGURATION_PATHNAME} does not exist. Quitting.')

    # The configuration file should be owned by cammon.
    config_file_stat = os.stat(CONFIGURATION_PATHNAME)
    if config_file_stat.st_uid != get_user_id():
        raise InitializationException(
            f'File {CONFIGURATION_PATHNAME} must be owned by {PROCESS_USERNAME}.')
    if bool(config_file_stat.st_mode & stat.S_IWGRP):
        raise InitializationException(
            f'File {CONFIGURATION_PATHNAME} cannot be writable via the group access '
            'permission.')
    if bool(config_file_stat.st_mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH)):
        raise InitializationException(
            f"File {CONFIGURATION_PATHNAME} cannot have 'other user' access permissions set."
            )


def sig_term_handler(_signal, _stack_frame):
    """Signal handler for SIGTERM. Sets a thread safe event that should cause the program to
    gracefully exit.

    _signal: Object representing the signal thrown.
    _stack_frame: Represents the stack frame.
    """
    termination_event.set()


def start():
    """The parent function for the entire program. It loads and verifies configuration,
    and starts the main program loop.
    """
    confighelper.ConfigHelper.configure_logger()
    logger = logging.getLogger(__name__)

    try:
        verify_safe_file_permissions()
        config = cammonconfig.CammonConfig()
        logger.setLevel(config.log_level)

        signal.signal(signal.SIGTERM, sig_term_handler)

        main_loop(config)

    except Exception as exception:  # pylint: disable=broad-except
        logger.critical(f'Fatal {type(exception).__name__}: {str(exception)}\n'
                        f'{traceback.format_exc()}')
        if cammon_subprocess is not None:
            logger.critical('Killing cammon subprocess.')
            cammon_subprocess.kill()
        raise exception


def main_loop(config):
    """The main program loop.

    config: The program configuration object, mostly based on the configuration file.
    """
    global cammon_subprocess
    logger = logging.getLogger()

    selected_device_pathname = VIDEO_DEVICE_PREFIX % config.video_device_number
    cammon_subprocess = None

    sdnotify.SystemdNotifier().notify('READY=1')

    # Loop forever.
    while not termination_event.is_set():
        try:
            # Wait for the device to show up.
            while not glob.glob(selected_device_pathname) and not termination_event.is_set():
                time.sleep(.1)
                sdnotify.SystemdNotifier().notify('WATCHDOG=1')

            if not termination_event.is_set():
                # Startup the subprocess to that takes photos.
                logger.info(f'Detected video device {selected_device_pathname}. Starting '
                            'cammon subprocess.')
                cammon_subprocess = subprocess.Popen([SUBPROCESS_PATHNAME])

            # Loop while the device exists and the subprocess is still running.
            while glob.glob(selected_device_pathname) and cammon_subprocess.poll() is None \
                    and not termination_event.is_set():
                time.sleep(.1)
                sdnotify.SystemdNotifier().notify('WATCHDOG=1')

            # Kill the subprocess so it can be restarted.
            if cammon_subprocess is not None:
                try:
                    if termination_event.is_set():
                        logger.info('SIGTERM received. Killing cammon subprocess.')
                    else:
                        logger.info('Detected device removal. Killing cammon subprocess.')
                    # TODO: Send a signal to cammon to flush its current e-mail buffer, give
                    #   it a second then do a kill or kill -9. (issue 4)
                    cammon_subprocess.kill()
                except OSError as os_error:
                    logger.error(f'Error killing cammon subprocess. '
                                 f'{type(os_error).__name__}: {str(os_error)}')
                    logger.error(f'{traceback.format_exc()}')
                    logger.error('Ignoring.')  # The subprocess might no longer exist.

        except Exception as exception:  # pylint: disable=broad-except
            logger.error(
                f'Unexpected error {type(exception).__name__}: {str(exception)}\n'
                f'{traceback.format_exc()}')
            time.sleep(.1)
            sdnotify.SystemdNotifier().notify('WATCHDOG=1')

    logging.info('Program terminated from receiving SIGTERM.')


if __name__ == '__main__':
    start()
