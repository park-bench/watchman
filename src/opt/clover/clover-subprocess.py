#!/usr/bin/env python2

# TODO: Consider detecting and sending the most interesting images.
# TODO: Consider using facial detection.
# TODO: Consider switching to Python 3 to use more advanced detection algorithms.
# TODO: Make this file a class

#import numpy as np
import cloverconfig
import confighelper
import ConfigParser
import cv2
import datetime
import gpgmailqueue
import glob
import math
import random
import sys
import timber
import time

from __future__ import division

print('Loading configuration.')
config_file = ConfigParser.SafeConfigParser()
config_file.read('/etc/opt/clover/clover.conf')

# Figure out the logging options so that can start before anything else.
print('Verifying configuration.')
config_helper = confighelper.ConfigHelper()
log_file = config_helper.verify_string_exists_prelogging(config_file, 'subprocess_log_file')
log_level = config_helper.verify_string_exists_prelogging(config_file, 'subprocess_log_level')

logger = timber.get_instance_with_filename(log_file, log_level)

config = cloverconfig.CloverConfig(config_file)

subtractor = cv2.BackgroundSubtractorMOG()  # Can use different subtractors
#kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))

saved_frames = []
prior_movements = [None] * config.prior_movements_per_threshold

first_email_sent = None
second_email_sent = None
last_email_sent = None
prior_movement_time = None
last_trigger_motion = None

capture_device = cv2.VideoCapture(int(sys.argv[1]))  # Open the camera

# Captures a frame, performs actions necessary for each frame, and stores the data
#   in a frame dictionary.
def capture_frame(capture_device):
    ret, frame = capture_device.read()

    frame_dict = {}
    frame_dict['time'] = datetime.datetime.now()
    frame_dict['frame'] = frame
    # Remove the 'background'.  Basically this removes noise.
    frame_dict['subtracted_frame'] = subtractor.apply(frame)
    #frame_dict['subtracted_frame'] = cv2.morphologyEx(frame_dict['subtracted_frame'], cv2.MORPH_OPEN, kernel)
    frame_dict['save'] = False
    return frame_dict
    

# Stores current_frame in saves_frame frame array if the threshold has been crossed.
# TODO: pass in the last time an image was saved via this method, check if 1s has passed
#       before saving the image again.
def store_frames_on_threshold(saved_frames, start_time, last_frame, current_frame, thresholds):
    for threshold in thresholds:
        if (did_threshold_trigger(start_time, last_frame, current_frame, threshold)):
            current_frame['save'] = True
            saved_frames.append(current_frame)
            break


# Compares previous and current frame times against a start time to see if enough
#   time as elapsed to trigger a threshold.
def did_threshold_trigger(start_time, last_frame, current_frame, threshold):
    threshold_triggered = False
    last_frame_difference = (last_frame['time'] - start_time).total_seconds()
    current_frame_difference = (current_frame['time'] - start_time).total_seconds()
    if (last_frame_difference < threshold and current_frame_difference > threshold):
        threshold_triggered = True
    return threshold_triggered


# Send an signed encrypted MIME/PGP e-mail with a message and image attachments.
#   Images will be resized and compressed before sending.
# Param config - The application configuation from the configuration file. When we
#   convert this file to a class, change this to 'this'.
# Param message - A text message to be displayed in the e-mail.
# Param images - An array of opencv images that will be sent to the recipients.
def send_image_emails(config, message, images):

    jpeg_images = []

    # Process all the images
    for image in images:

        # Resize for e-mail or don't resize if images is smaller than desired resolution.
        desired_image_width = config['email_image_width']  # In pixels
        current_image_height, current_image_width = image['frame'].shape[0:1]
        if desired_image_width < current_image_width:
            # Images are scaled proportionally.
            desired_image_height = int(desired_image_width * (current_image_height / current_image_width))
            small_frame = cv2.resize(image['frame'], (desired_image_width, desired_image_height))
        else:
            small_frame = image['frame']

        # Save the file in memory
        ret, small_jpeg = cv2.imencode('.jpg', small_frame)

        # Put it in the format that the mailer expects it
        image_dict = {}
        image_dict['data'] = small_jpeg
        # Warning: Making this filename too long causes the signature to fail for some unknown 
        #   reason.
        image_dict['filename'] = '%s-sm.jpg' % image['time'].strftime('%Y-%m-%d_%H-%M-%S_%f')
        jpeg_images.append(image_dict)

    del images[:]

    body = {}
    body['subject'] = config.motion_detection_email_subject
    body['message'] = message
    body['attachments'] = jpeg_images

    # TODO: Remove use of 'global'.
    global logger
    logger.info('Sending E-mail.')
    gpgmailqueue.send(body)

current_frame = capture_frame(capture_device)  # Capture the first frame
last_image_save_time = current_frame['time']
next_still_running_email_time = current_frame['time'] + \
        datetime.timedelta(seconds=random.uniform(0, config.still_running_email_max_delay * 86400))

# Sometimes we run this program interactively for debugging purposes.
while(cv2.waitKey(1) & 0xFF != ord('q')):

    last_frame = current_frame

    current_frame = capture_frame(capture_device)  # Read the next frame
    
    # Find the difference between the two subtracted frames
    difference_frame = last_frame['subtracted_frame'] - current_frame['subtracted_frame']
    
    #cv2.imshow('lastFrame', last_frame['subtracted_frame'])
    #cv2.imshow('currentFrame', current_frame['subtracted_frame'])
    #cv2.imshow('difference', difference_frame)

    channel_means = cv2.mean(difference_frame)  # Find the mean difference of each channel

    absolute_mean_total = 0
    for channel_mean in channel_means:
        absolute_mean_total += math.fabs(channel_mean)  # Add the absolute value of the mean
    
    #logger.debug('difference: %s' % str(difference))
    logger.trace('absolute_mean_total: {0:.10f}'.format(absolute_mean_total))

    # See if there has been enough motion to start sending e-mails
    if (absolute_mean_total > config.pixel_difference_threshold):

        # Obtain the time of the differnce
        now = current_frame['time']

        # Make sure a specific amount of time has passed since the last local image save.
        #   (E-mail initiated saves do not count.)
        if((current_frame['time'] - last_image_save_time) >= datetime.timedelta(seconds=config.image_save_throttle_delay)):
            # Save the image
            logger.trace('Image marked for local save at %s.' % current_frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f'))
            current_frame['save'] = True
            last_image_save_time = current_frame['time']

        # See if there has been another difference in the last second
        prior_movements_iterator = iter(prior_movements)
        prior_movement_time = next(prior_movements_iterator, 'End')
        if (prior_movement_time != None and prior_movement_time != 'End'):
            time_difference = now - prior_movement_time
        while (prior_movement_time != None and prior_movement_time != 'End' and \
                time_difference.total_seconds() <= config.movement_time_threshold):
            prior_movement_time = next(prior_movements_iterator, 'End')
            if (prior_movement_time != None and prior_movement_time != 'End'):
                time_difference = now - prior_movement_time

        if (prior_movement_time == 'End'):
            #logger.debug('Motion Detected')
            last_trigger_motion = now
            if (first_email_sent == None):
                first_email_sent = now
                saved_frames.append(current_frame)
                send_image_emails(config, 'Motion just detected.', saved_frames)

        # Move the array contents down one, discard the oldest and add the new one
	if (len(prior_movements)):
            prior_movements = [now] + prior_movements[:-1]

    # Grab images for the second e-mail
    if (first_email_sent != None):
        store_frames_on_threshold(saved_frames, first_email_sent, \
                last_frame, current_frame, config.second_email_image_save_times)

    # Send another e-mail after so many seconds
    if (first_email_sent != None and did_threshold_trigger(first_email_sent, last_frame, \
            current_frame, config.second_email_delay)):
        send_image_emails(config, 'Follow up one.', saved_frames)
        second_email_sent = first_email_sent + datetime.timedelta(0, config.second_email_delay)

    # Grab images for the third e-mail
    if (second_email_sent != None):
        store_frames_on_threshold(saved_frames, second_email_sent, \
                last_frame, current_frame, config.third_email_image_save_times)

    # Send third e-mail after so many seconds
    if (second_email_sent != None and did_threshold_trigger(second_email_sent, last_frame, \
            current_frame, config.third_email_delay)):
        send_image_emails(config, 'Follow up two.', saved_frames)
        last_email_sent = second_email_sent + datetime.timedelta(0, config.third_email_delay)

    # Grab images for subsequent e-mails
    if (last_email_sent != None):
        store_frames_on_threshold(saved_frames, last_email_sent, \
                last_frame, current_frame, config.subsequent_email_image_save_times)

    # Send subsequent e-mails after so many seconds
    if (last_email_sent != None and did_threshold_trigger(last_email_sent, last_frame, \
            current_frame, config.subsequent_email_delay)):
        send_image_emails(config, 'Continued motion.', saved_frames)
        last_email_sent = last_email_sent + datetime.timedelta(0, config.subsequent_email_delay)

    # See if the motion has stopped.
    if (last_trigger_motion != None and did_threshold_trigger(last_trigger_motion, \
            last_frame, current_frame, config.stop_threshold)):

        # Clear out the image buffer if images exist
        if (len(saved_frames) > 0):
            send_image_emails(config, 'Continued motion.', saved_frames)

        first_email_sent = None
        second_email_sent = None
        last_email_sent = None
        last_trigger_motion = None

    # Save the image?
    if (current_frame['save'] == True):
        pathname = ('%s%s.jpg') % (config.image_save_path, current_frame['time'].strftime('%Y-%m-%d_%H-%M-%S_%f'))
        cv2.imwrite(pathname, current_frame['frame'])

    # Send still running notification?
    if (current_frame['time'] > next_still_running_email_time):
        body = {}
        body['subject'] = config.still_running_email_subject
        body['message'] = 'Clover is still running as of %s.' % current_frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f')

        logger.info('Sending still running notification e-mail.')
        gpgmailqueue.send(body)

        # Convert still_running_email_max_delay to seconds
        next_still_running_email_time = current_frame['time'] + \
                datetime.timedelta(seconds=random.uniform(0, config.still_running_email_max_delay * 86400))

# Clean up
capture_device.release()
cv2.destroyAllWindows()  # Again for interactive debugging.
