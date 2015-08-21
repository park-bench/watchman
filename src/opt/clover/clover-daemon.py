#!/usr/bin/env python2

import glob
import os
import signal
import subprocess
import sys
import timber
import time
import traceback

LOG_FILE = '/var/opt/log/clover.log'
PID_FILE = '/var/opt/run/clover.pid'

logger = timber.get_instance_with_filename(LOG_FILE)

def daemonize():
    # Fork the first time to make init our parent.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError, e:
        logger.trace("Failed to make parent process init: %d (%s)" % (e.errno, e.strerror))
        sys.exit(1)

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
        logger.trace("Failed to give up session leadership: %d (%s)" % (e.errno, e.strerror))
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
    pidFile = file(PID_FILE,'w')
    pidFile.write("%s\n" % pid)
    pidFile.close()
    
daemonize()

clover_subprocess = None

# Quit when SIGTERM is received
def sig_term_handler(signal, stack_frame):
    logger.trace("Quitting.")
    if clover_subprocess <> None:
        logger.trace("Killing clover subprocess.");
        clover_subprocess.kill()
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_term_handler)

try:
    # There is nothing in OpenCV to detect if a device is removed. This forces us to use platform
    #   specific methods.
    video_devices = glob.glob("/dev/video[0-9]")
    video_devices.sort(reverse=True)
    selected_device = video_devices[0]
    device_number = selected_device[-1] 

    # Loop forever
    while 1:   

        # Startup the subprocess to that takes photos
        # TODO: Change to /opt/clover/clover-subprocess.py
        logger.trace("Starting clover subprocess with device number %s." % device_number)
        clover_subprocess = subprocess.Popen(["/opt/clover/clover-subprocess.py", device_number])

        # Loop while the device exists
        while len(glob.glob(selected_device)) == 1 and clover_subprocess.poll() == None:
            time.sleep(.1)

        # Kill the subprocess so it can be restarted
        try:
            logger.trace("Detected device removal. Killing clover subprocess.");
            clover_subprocess.kill()
        except OSError as e:
            logger.trace("Error killing clover subprocess. %s: %s" % \
                (type(e).__name__, e.message))
            logger.trace("%s" % traceback.format_exc())
            logger.trace("Ignoring.")

        # Wait for the device to come back
        while len(glob.glob(selected_device)) == 0:
            time.sleep(.1)

        logger.trace("Detected device insertion.");

except Exception as e:
    logger.trace("Fatal %s: %s" % (type(e).__name__, e.message))
    logger.trace("%s" % traceback.format_exc())
    if clover_subprocess <> None:
        logger.trace("Killing clover subprocess.");
        clover_subprocess.kill()
    sys.exit(1)
