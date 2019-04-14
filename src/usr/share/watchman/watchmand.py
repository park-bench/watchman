#!/usr/bin/python2

# Copyright 2015-2019 Joel Allen Luellwitz and Emily Frost
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
__version__ = '0.8'

import glob
import grp
import logging
import os
import pwd
import signal
import stat
import subprocess
import sys
import time
import traceback
import ConfigParser
import daemon
from lockfile import pidlockfile
import confighelper
import watchmanconfig

# Constants
PROGRAM_NAME = 'watchman'
CONFIGURATION_PATHNAME = os.path.join('/etc', PROGRAM_NAME, '%s.conf' % PROGRAM_NAME)
SYSTEM_PID_DIR = '/run'
PROGRAM_PID_DIRS = PROGRAM_NAME
PID_FILE = '%s.pid' % PROGRAM_NAME
LOG_DIR = os.path.join('/var/log', PROGRAM_NAME)
IMAGE_DIRS = 'images'
LOG_FILE = '%s.log' % PROGRAM_NAME
PROCESS_USERNAME = PROGRAM_NAME
PROCESS_GROUP_NAME = PROGRAM_NAME
SUBPROCESS_PATHNAME = os.path.join(
    '/usr/share', PROGRAM_NAME, '%s-subprocess.py' % PROGRAM_NAME)
VIDEO_DEVICE_PREFIX = '/dev/video%d'
PROGRAM_UMASK = 0o027  # -rw-r----- and drwxr-x---


class InitializationException(Exception):
    """Indicates an expected fatal error occurred during program initialization.
    Initialization is implied to mean, before daemonization.
    """


def get_user_and_group_ids():
    """Get user and group information for dropping privileges.

    Returns the user and group IDs that the program should eventually run as.
    """
    try:
        program_user = pwd.getpwnam(PROCESS_USERNAME)
    except KeyError as key_error:
        # TODO: When switching to Python 3, convert to chained exception.
        #   (gpgmailer issue 15)
        print('User %s does not exist. %s: %s' % (
            PROCESS_USERNAME, type(key_error).__name__, str(key_error)))
        raise key_error
    try:
        program_group = grp.getgrnam(PROCESS_GROUP_NAME)
    except KeyError as key_error:
        # TODO: When switching to Python 3, convert to chained exception.
        #   (gpgmailer issue 15)
        print('Group %s does not exist. %s: %s' % (
            PROCESS_GROUP_NAME, type(key_error).__name__, str(key_error)))
        raise key_error

    return program_user.pw_uid, program_group.gr_gid


def read_configuration_and_create_logger(program_uid, program_gid):
    """Reads the configuration file and creates the application logger. This is done in the
    same function because part of the logger creation is dependent upon reading the
    configuration file.

    program_uid: The system user ID this program should drop to before daemonization.
    program_gid: The system group ID this program should drop to before daemonization.
    Returns the read system config, a confighelper instance, and a logger instance.
    """
    print('Reading %s...' % CONFIGURATION_PATHNAME)

    if not os.path.isfile(CONFIGURATION_PATHNAME):
        raise InitializationException(
            'Configuration file %s does not exist. Quitting.' % CONFIGURATION_PATHNAME)

    config_file = ConfigParser.SafeConfigParser()
    config_file.read(CONFIGURATION_PATHNAME)

    config = {}
    config_helper = confighelper.ConfigHelper()
    # Figure out the logging options so that can start before anything else.
    # TODO: Eventually add a verify_string_list method. (gpgmailer issue 20)
    config['log_level'] = config_helper.verify_string_exists(config_file, 'log_level')

    # Create logging directory.  drwxr-x--- watchman watchman
    log_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
    # TODO: Look into defaulting the logging to the console until the program gets more
    #   bootstrapped. (gpgmailer issue 18)
    print('Creating logging directory %s.' % LOG_DIR)
    if not os.path.isdir(LOG_DIR):
        # Will throw exception if directory cannot be created.
        os.makedirs(LOG_DIR, log_mode)
    os.chown(LOG_DIR, program_uid, program_gid)
    os.chmod(LOG_DIR, log_mode)

    # Temporarily drop permissions and create the handle to the logger.
    print('Configuring logger.')
    os.setegid(program_gid)
    os.seteuid(program_uid)
    config_helper.configure_logger(os.path.join(LOG_DIR, LOG_FILE), config['log_level'])

    logger = logging.getLogger(__name__)

    logger.info('Verifying non-logging configuration.')

    # Parse the configuration file. The parsed result is returned as an object.
    config = watchmanconfig.WatchmanConfig(config_file)

    return config, config_helper, logger


# TODO: Consider checking ACLs. (gpgmailer issue 22)
def verify_safe_file_permissions(program_uid):
    """Crashes the application if unsafe file permissions exist on application configuration
    files.

    program_uid: The system user ID that should own the configuration file.
    """
    # Unlike other Parkbench programs, the configuration file should be owned by 'watchman'
    #   because the subprocess (running as watchman) needs to be able to read the
    #   configuration file.
    config_file_stat = os.stat(CONFIGURATION_PATHNAME)
    if config_file_stat.st_uid != program_uid:
        raise InitializationException(
            'File %s must be owned by %s.' % (CONFIGURATION_PATHNAME, PROGRAM_NAME))
    if bool(config_file_stat.st_mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH)):
        raise InitializationException(
            "File %s cannot have 'other user' access permissions set."
            % CONFIGURATION_PATHNAME)


def create_directory(system_path, program_dirs, uid, gid, mode):
    """Creates directories if they do not exist and sets the specified ownership and
    permissions.

    system_path: The system path that the directories should be created under. These are
      assumed to already exist. The ownership and permissions on these directories are not
      modified.
    program_dirs: A string representing additional directories that should be created under
      the system path that should take on the following ownership and permissions.
    uid: The system user ID that should own the directory.
    gid: The system group ID that should be associated with the directory.
    mode: The unix standard 'mode bits' that should be associated with the directory.
    """
    logger.info('Creating directory %s.', os.path.join(system_path, program_dirs))

    path = system_path
    for directory in program_dirs.strip('/').split('/'):
        path = os.path.join(path, directory)
        if not os.path.isdir(path):
            # Will throw exception if file cannot be created.
            os.makedirs(path, mode)
        os.chown(path, uid, gid)
        os.chmod(path, mode)


def drop_permissions_forever(uid, gid):
    """Drops escalated permissions forever to the specified user and group.

    uid: The system user ID to drop to.
    gid: The system group ID to drop to.
    """
    logger.info('Dropping permissions for user %s.', PROCESS_USERNAME)
    os.initgroups(PROCESS_USERNAME, gid)
    os.setgid(gid)
    os.setuid(uid)


def sig_term_handler(signal, stack_frame):
    """Signal handler for SIGTERM. Quits when SIGTERM is received.

    signal: Object representing the signal thrown.
    stack_frame: Represents the stack frame.
    """
    logger.info('SIGTERM received. Quitting.')
    if watchman_subprocess is not None:
        logger.info('Killing watchman subprocess.')
        watchman_subprocess.kill()
    sys.exit(0)


def setup_daemon_context(log_file_handle, program_uid, program_gid):
    """Creates the daemon context. Specifies daemon permissions, PID file information, and
    the signal handler.

    log_file_handle: The file handle to the log file.
    program_uid: The system user ID that should own the daemon process.
    program_gid: The system group ID that should be assigned to the daemon process.
    Returns the daemon context.
    """
    daemon_context = daemon.DaemonContext(
        working_directory='/',
        pidfile=pidlockfile.PIDLockFile(
            os.path.join(SYSTEM_PID_DIR, PROGRAM_PID_DIRS, PID_FILE)),
        umask=PROGRAM_UMASK,
    )

    daemon_context.signal_map = {
        signal.SIGTERM: sig_term_handler,
    }

    daemon_context.files_preserve = [log_file_handle]

    # Set the UID and GID to 'watchman' user and group.
    daemon_context.uid = program_uid
    daemon_context.gid = program_gid

    return daemon_context


def main_loop(config):
    """The main program loop.

    config: The program configuration object, mostly based on the configuration file.
    """
    global watchman_subprocess
    selected_device_pathname = VIDEO_DEVICE_PREFIX % config.video_device_number

    # Loop forever.
    while True:

        # Wait for the device to show up.
        while not glob.glob(selected_device_pathname):
            time.sleep(.1)

        # Startup the subprocess to that takes photos.
        logger.info("Detected video device %s. Starting watchman subprocess.",
                    selected_device_pathname)
        watchman_subprocess = subprocess.Popen([SUBPROCESS_PATHNAME])

        # Loop while the device exists and the subprocess is still running.
        while glob.glob(selected_device_pathname) and watchman_subprocess.poll() is None:
            time.sleep(.1)

        # Kill the subprocess so it can be restarted.
        try:
            logger.info('Detected device removal. Killing watchman subprocess.')
            # TODO: Send a signal to watchman to flush its current e-mail buffer, give it a
            #   second then do a kill or kill -9. (issue 4)
            watchman_subprocess.kill()
        except OSError as os_error:
            logger.error('Error killing watchman subprocess. %s: %s',
                         type(os_error).__name__, str(os_error))
            logger.error('%s', traceback.format_exc())
            logger.error('Ignoring.')  # The subprocess might no longer exist.


os.umask(PROGRAM_UMASK)
program_uid, program_gid = get_user_and_group_ids()
config, config_helper, logger = read_configuration_and_create_logger(
    program_uid, program_gid)

watchman_subprocess = None
try:
    verify_safe_file_permissions(program_uid)

    # Re-establish root permissions to create required directories.
    os.seteuid(os.getuid())
    os.setegid(os.getgid())

    # drwxr-x--- watchman watchman
    create_directory(
        LOG_DIR, IMAGE_DIRS, program_uid, program_gid,
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)

    # Non-root users cannot create files in /run, so create a directory that can be written
    #   to. Full access to user only.  drwx------ watchman watchman
    create_directory(SYSTEM_PID_DIR, PROGRAM_PID_DIRS, program_uid, program_gid,
                     stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    # Configuration has been read and directories setup. Now drop permissions forever.
    drop_permissions_forever(program_uid, program_gid)

    daemon_context = setup_daemon_context(
        config_helper.get_log_file_handle(), program_uid, program_gid)

    logger.info('Daemonizing...')
    with daemon_context:
        main_loop(config)

except Exception as exception:
    logger.critical('Fatal %s: %s\n%s', type(exception).__name__, str(exception),
                    traceback.format_exc())
    if watchman_subprocess is not None:
        logger.critical('Killing watchman subprocess.')
        watchman_subprocess.kill()
    raise exception
