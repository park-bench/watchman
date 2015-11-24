#!/usr/bin/env python2

import cloverconfig
import confighelper
import ConfigParser
import glob
import os
import signal
import subprocess
import sys
import timber
import time
import traceback

pid_file = '/var/opt/run/clover.pid'

print('Loading configuration.')
config_file = ConfigParser.RawConfigParser()
config_file.read('/etc/opt/clover/clover.conf')

# Figure out the logging options so that can start before anything else.
print('Verifying configuration.')
config_helper = confighelper.ConfigHelper()
log_file = config_helper.verify_string_exists_prelogging(config_file, 'main_process_log_file')
log_level = config_helper.verify_string_exists_prelogging(config_file, 'main_process_log_level')

logger = timber.get_instance_with_filename(log_file, log_level)

subprocess_pathname = config_helper.verify_string_exists(config_file, 'subprocess_pathname')

# We don't care what the results are, we just want the program to die if there is an error
#   with the subprocess configuration.
cloverconfig.CloverConfig(config_file)

# The device we want to capture video with.
# TODO: Consider validating for a malicious path.
video_device_number = config_helper.verify_integer_exists(config_file, 'video_device_number')

# TODO: Move this to common library.
def daemonize():
    # Fork the first time to make init our parent.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError, e:
        logger.fatal("Failed to make parent process init: %d (%s)" % (e.errno, e.strerror))
        sys.exit(1)

    # TODO: Consider changing these to be more restrictive
    os.chdir("/")  # Change the working directory
    os.setsid()  # Create a new process session.
    os.umask(0)

    # Fork the second time to make sure the process is not a session leader. 
    #   This apparently prevents us from taking control of a TTY.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError, e:
        logger.fatal("Failed to give up session leadership: %d (%s)" % (e.errno, e.strerror))
        sys.exit(1)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, sys.stdin.fileno())
    os.dup2(devnull, sys.stdout.fileno())
    os.dup2(devnull, sys.stderr.fileno())
    os.close(devnull)

    pid = str(os.getpid())
    pid_file_handle = file(pid_file,'w')
    pid_file_handle.write("%s\n" % pid)
    pid_file_handle.close()
    
daemonize()

clover_subprocess = None

# Quit when SIGTERM is received
def sig_term_handler(signal, stack_frame):
    logger.fatal("Quitting.")
    if clover_subprocess <> None:
        logger.info("Killing clover subprocess.");
        clover_subprocess.kill()
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_term_handler)

try:
    # Loop forever
    while 1:   

        # Startup the subprocess to that takes photos
        logger.info("Starting clover subprocess with device %s." % selected_device)
        clover_subprocess = subprocess.Popen([subprocess_pathname, video_device_number])

        # Loop while the device exists
        while len(glob.glob(selected_device)) == 1 and clover_subprocess.poll() == None:
            time.sleep(.1)

        # Kill the subprocess so it can be restarted
        try:
            logger.info("Detected device removal. Killing clover subprocess.");
            clover_subprocess.kill()
        except OSError as e:
            logger.error("Error killing clover subprocess. %s: %s" % \
                (type(e).__name__, e.message))
            logger.error("%s" % traceback.format_exc())
            logger.error("Ignoring.")

        # Wait for the device to come back
        while len(glob.glob(selected_device)) == 0:
            time.sleep(.1)

        logger.info("Detected device insertion.");

except Exception as e:
    logger.fatal("Fatal %s: %s" % (type(e).__name__, e.message))
    logger.error("%s" % traceback.format_exc())
    if clover_subprocess <> None:
        logger.info("Killing clover subprocess.");
        clover_subprocess.kill()
    sys.exit(1)
