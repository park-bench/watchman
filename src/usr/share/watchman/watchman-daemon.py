#!/usr/bin/env python2

# Copyright 2015-2018 Joel Allen Luellwitz and Andrew Klapp
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
import grp
import logging
import os
# TODO: Remove try/except when we drop support for Ubuntu 14.04 LTS.
try:
    from lockfile import pidlockfile
except ImportError:
    from daemon import pidlockfile
import pwd
import signal
import subprocess
import stat
import sys
import time
import traceback
import watchmanconfig

# Constants
PROGRAM_NAME = 'watchman'
CONFIGURATION_PATHNAME = os.path.join('/etc', PROGRAM_NAME, '%s.conf' % PROGRAM_NAME)
SYSTEM_PID_DIR = '/run'
PROGRAM_PID_DIRS = PROGRAM_NAME
PID_FILE = '%s.pid' % PROGRAM_NAME
LOG_DIR = os.path.join('/var/log', PROGRAM_NAME)
LOG_FILE = '%s.log' % PROGRAM_NAME
PROCESS_USERNAME = PROGRAM_NAME
PROCESS_GROUP_NAME = PROGRAM_NAME
SUBPROCESS_PATHNAME = os.path.join(
    '/usr/share', PROGRAM_NAME, '%s-subprocess.py' % PROGRAM_NAME)
VIDEO_DEVICE_PREFIX = '/dev/video%d'


def get_user_and_group_ids():
    """Get user and group information for dropping privileges.

    Returns the user and group IDs that the program should eventually run as.
    """
    try:
        program_user = pwd.getpwnam(PROCESS_USERNAME)
    except KeyError as key_error:
        raise Exception('User %s does not exist.' % PROCESS_USERNAME, key_error)
    try:
        program_group = grp.getgrnam(PROCESS_GROUP_NAME)
    except KeyError as key_error:
        raise Exception('Group %s does not exist.' % PROCESS_GROUP_NAME, key_error)

    return (program_user.pw_uid, program_group.gr_gid)


def read_configuration_and_create_logger(program_uid, program_gid):
    """Reads the configuration file and creates the application logger.  This is done in the
    same function because part of the logger creation is dependent upon reading the
    configuration file.

    program_uid: The system user ID this program should drop to before daemonization.
    program_gid: The system group ID this program should drop to before daemonization.
    Returns the read system config, a confighelper instance, and a logger instance.
    """
    config_parser = ConfigParser.SafeConfigParser()
    config_parser.read(CONFIGURATION_PATHNAME)

    # Logging config goes first
    config = {}
    config_helper = confighelper.ConfigHelper()
    config['log_level'] = config_helper.verify_string_exists_prelogging(
        config_parser, 'log_level')

    # Create logging directory.
    log_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | \
        stat.S_IROTH | stat.S_IXOTH
    # TODO: Look into defaulting the logging to the console until the program gets more
    #   bootstrapped.
    print('Creating logging directory %s.' % LOG_DIR)
    if not os.path.isdir(LOG_DIR):
        # Will throw exception if file cannot be created.
        os.makedirs(LOG_DIR, log_mode)
    os.chown(LOG_DIR, program_uid, program_gid)
    os.chmod(LOG_DIR, log_mode)

    # Temporarily drop permission and create the handle to the logger.
    os.setegid(program_gid)
    os.seteuid(program_uid)
    config_helper.configure_logger(os.path.join(LOG_DIR, LOG_FILE), config['log_level'])
    os.seteuid(os.getuid())
    os.setegid(os.getgid())

    logger = logging.getLogger('%s-daemon' % PROGRAM_NAME)

    logger.info('Verifying non-logging config')

    # Parse the configuration file which is returned as an object.
    config = watchmanconfig.WatchmanConfig(config_parser)

    return (config, config_helper, logger)


def create_directory(system_path, program_dirs, uid, gid, mode):
    """Creates directories if they do not exist and sets the specified ownership and
    permissions.

    system_path: The system path that the directories should be created under.  These are
      assumed to already exist.  The ownership and permissions on these directories are not
      modified.
    program_dirs: A string representing additional directories that should be created under
      the system path that should take on the following ownership and permissions.
    uid: The system user ID that should own the directory.
    gid: The system group ID that should own be associated with the directory.
    mode: The umask of the directory access permissions.
    """
    logger.info('Creating directory %s.' % os.path.join(system_path, program_dirs))

    for directory in program_dirs.strip('/').split('/'):
        path = os.path.join(system_path, directory)
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
    logger.info('Dropping permissions for user %s.' % PROCESS_USERNAME)
    os.initgroups(PROCESS_USERNAME, gid)
    os.setgid(gid)
    os.setuid(uid)


def sig_term_handler(signal, stack_frame):
    """Signal handler for SIGTERM.  Quits when SIGTERM is received.

    signal: Object representing the signal thrown.
    stack_frame: Represents the stack frame.
    """
    logger.info("Received SIGTERM, quitting.")
    if watchman_subprocess is not None:
        logger.info("Killing watchman subprocess.")
        watchman_subprocess.kill()
    sys.exit(0)


def setup_daemon_context(log_file_handle, program_uid, program_gid):
    """Creates the daemon context. Specifies daemon permissions, PID file information, and
    signal handler.

    log_file_handle: The file handle to the log file.
    Returns the daemon context.
    """
    daemon_context = daemon.DaemonContext(
        working_directory='/',
        pidfile=pidlockfile.PIDLockFile(
            os.path.join(SYSTEM_PID_DIR, PROGRAM_PID_DIRS, PID_FILE)),
        umask=0o117,  # Read/write by user and group.
        )

    daemon_context.signal_map = {
        signal.SIGTERM: sig_term_handler,
        }

    daemon_context.files_preserve = [log_file_handle]

    # Set the UID and PID to 'watchman' user and group.
    daemon_context.uid = program_uid
    daemon_context.gid = program_gid

    return daemon_context


def main_loop(config):
    """The main program loop.

    config: The program configuration object, mostly based on the configuration file.
    """
    selected_device_pathname = VIDEO_DEVICE_PREFIX % config.video_device_number

    # Loop forever
    while True:

        # Wait for the device to show up.
        while len(glob.glob(selected_device_pathname)) == 0:
            time.sleep(.1)

        logger.info("Detected video device %s." % selected_device_pathname)

        # Startup the subprocess to that takes photos
        logger.info(
            "Starting watchman subprocess with device %s." % selected_device_pathname)
        watchman_subprocess = subprocess.Popen(
            [SUBPROCESS_PATHNAME, '%d' % config.video_device_number])

        # Loop while the device exists and the subprocess is still running.
        while len(glob.glob(selected_device_pathname)) == 1 and \
                watchman_subprocess.poll() is None:
            time.sleep(.1)

        # Kill the subprocess so it can be restarted
        try:
            logger.info("Detected device removal. Killing watchman subprocess.")
            # TODO: Send a signal to watchman to flush its current e-mail buffer, give it a
            #   second then do a kill or kill -9.
            watchman_subprocess.kill()
        except OSError as e:
            logger.error("Error killing watchman subprocess. %s: %s" % (
                type(e).__name__, e.message))
            logger.error("%s" % traceback.format_exc())
            logger.error("Ignoring.")  # The subprocess might no longer exist.


program_uid, program_gid = get_user_and_group_ids()

config, config_helper, logger = read_configuration_and_create_logger(
    program_uid, program_gid)

watchman_subprocess = None
try:
    # Non-root users cannot create files in /run, so create a directory that can be written
    #   to. Full access to user only.
    create_directory(
        SYSTEM_PID_DIR, PROGRAM_PID_DIRS, program_uid, program_gid,
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    # Configuration has been read and directories setup. Now drop permissions forever.
    drop_permissions_forever(program_uid, program_gid)

    daemon_context = setup_daemon_context(
        config_helper.get_log_file_handle(), program_uid, program_gid)

    with daemon_context:
        main_loop(config)

except Exception as exception:
    logger.critical('Fatal %s: %s\n' % (type(exception).__name__, exception.message))
    logger.critical(traceback.format_exc())
    if watchman_subprocess is not None:
        logger.critical("Killing watchman subprocess.")
        watchman_subprocess.kill()
    raise exception
