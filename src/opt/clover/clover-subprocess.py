#!/usr/bin/env python2

#import numpy as np
import cloverconfig
import confighelper
import ConfigParser
import cv2
import datetime
import gpgmailqueue
import glob
import math
import sys
import timber
import time

print('Loading configuration.')
config_file = ConfigParser.SafeConfigParser()
config_file.read('/etc/opt/clover/clover.conf')

# Figure out the logging options so that can start before anything else.
print('Verifying configuration.')
log_file = config_helper.verify_string_exists_prelogging(config_file, 'subprocess_log_file')
log_level = config_helper.verify_string_exists_prelogging(config_file, 'subprocess_log_level')

logger = timber.get_instance_with_filename(log_file, log_level)

config = cloverconfig.CloverConfig(config_file)

subtractor = cv2.BackgroundSubtractorMOG()  # Can use different subtractors
#kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))

saved_frames = []
prior_movements = [None] * prior_movements_per_threshold

first_email_sent = None
second_email_sent = None
last_email_sent = None
prior_movement_time = None
last_trigger_motion = None

capture_device = cv2.VideoCapture(int(sys.argv[1]))  # Open the camera

# Captures a frame, performs actions necessary for each frame, and stores the data
#   in a frame dictionary.
def capture_frame(capture_device):
    ret, frame = capture_device.read();

    frame_dict = {}
    frame_dict['time'] = datetime.datetime.now()
    frame_dict['frame'] = frame
    # Remove the 'background'.  Basically this removes noise.
    frame_dict['subtracted_frame'] = subtractor.apply(frame)
    #frame_dict['subtracted_frame'] = cv2.morphologyEx(frame_dict['subtracted_frame'], cv2.MORPH_OPEN, kernel)
    frame_dict['save'] = False
    return frame_dict
    

# Stores current_frame in saves_frame frame array if the threshold has been crossed.
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
# Param message - A text message to be displayed in the e-mail.
# Param images - An array of opencv images that will be sent to the recipients.
def send_image_emails(message, images):

    jpeg_images = []

    # Process all the images
    for image in images:

        # Resize to fit in a hi-def screen
        small_frame = cv2.resize(image['frame'], (1440,1080))

        # Save the file in memory
        ret, small_jpeg = cv2.imencode('.jpg', small_frame)

        # Put it in the format that the mailer expects it
        image_dict = {}
        image_dict['data'] = small_jpeg
        image_dict['filename'] = '%s-small.jpg' % image['time'].strftime('%Y%m%d%H%M%S%f')
        jpeg_images.append(image_dict)

    del images[:]

    body = {}
    body['subject'] = 'Bandersnatch 3'
    body['message'] = message
    body['attachments'] = jpeg_images

    global logger
    logger.info('Sending E-mail.')
    gpgmailqueue.send(body)


current_frame = capture_frame(capture_device)  # Capture the first frame


while(cv2.waitKey(1) & 0xFF != ord('q')):

    last_frame = current_frame

    current_frame = capture_frame(capture_device)  # Read the next frame
    
    # Find the difference between the two subtracted frames
    difference_frame = last_frame['subtracted_frame'] - current_frame['subtracted_frame']
    
    #cv2.imshow('lastFrame', last_frame['subtracted_frame'])
    #cv2.imshow('currentFrame', current_frame['subtracted_frame'])
    #cv2.imshow('difference', difference_frame)

    channel_means = cv2.mean(difference_frame)  # Find the mean difference of each channel

    absolute_mean_total = 0;
    for channel_mean in channel_means:
        absolute_mean_total += math.fabs(channel_mean)  # Add the absolute value of the mean
    
    #logger.debug('difference: %s' % str(difference))
    #logger.debug('absolute_mean_total: {0:.10f}'.format(absolute_mean_total))

    # See if there has been enough motion to start sending e-mails
    if (absolute_mean_total > pixel_difference_threshold):

        # Obtain the time of the differnce
        now = current_frame['time']

        # Save the image
        #logger.debug('Save image')
        current_frame['save'] = True

        # See if there has been another difference in the last second
        prior_movements_iterator = iter(prior_movements)
        prior_movement_time = next(prior_movements_iterator, 'End')
        if (prior_movement_time != None and prior_movement_time != 'End'):
            time_difference = now - prior_movement_time
        while (prior_movement_time != None and prior_movement_time != 'End' and \
                time_difference.total_seconds() <= movement_time_threshold):
            prior_movement_time = next(prior_movements_iterator, 'End')
            if (prior_movement_time != None and prior_movement_time != 'End'):
                time_difference = now - prior_movement_time

        if (prior_movement_time == 'End'):
            #logger.debug('Motion Detected')
            last_trigger_motion = now
            if (first_email_sent == None):
                first_email_sent = now
                saved_frames.append(current_frame)
                send_image_emails('Motion just detected.', saved_frames)

        # Move the array contents down one, discard the oldest and add the new one
	if (len(prior_movements)):
            prior_movements = [now] + prior_movements[:-1]

    # Grab images for the second e-mail
    if (first_email_sent != None):
        store_frames_on_threshold(saved_frames, first_email_sent, \
                last_frame, current_frame, second_email_image_save_times)

    # Send another e-mail after so many seconds
    if (first_email_sent != None and did_threshold_trigger(first_email_sent, last_frame, \
            current_frame, second_email_delay)):
        send_image_emails('Follow up one.', saved_frames)
        second_email_sent = first_email_sent + datetime.timedelta(0, second_email_delay)

    # Grab images for the third e-mail
    if (second_email_sent != None):
        store_frames_on_threshold(saved_frames, second_email_sent, \
                last_frame, current_frame, third_email_image_save_times)

    # Send third e-mail after so many seconds
    if (second_email_sent != None and did_threshold_trigger(second_email_sent, last_frame, \
            current_frame, third_email_delay)):
        send_image_emails('Follow up two.', saved_frames)
        last_email_sent = second_email_sent + datetime.timedelta(0, third_email_delay)

    # Grab images for subsequent e-mails
    if (last_email_sent != None):
        store_frames_on_threshold(saved_frames, last_email_sent, \
                last_frame, current_frame, subsequent_email_image_save_times)

    # Send subsequent e-mails after so many seconds
    if (last_email_sent != None and did_threshold_trigger(last_email_sent, last_frame, \
            current_frame, subsequent_image_delay)):
        send_image_emails('Continued motion.', saved_frames)
        last_email_sent = last_email_sent + datetime.timedelta(0, subsequent_image_delay)

    # See if the motion has stopped.
    if (last_trigger_motion != None and did_threshold_trigger(last_trigger_motion, \
            last_frame, current_frame, stop_threshold)):

        # Clear out the image buffer if images exist
        if (len(saved_frames) > 0):
            send_image_emails('Continued motion.', saved_frames)

        first_email_sent = None
        second_email_sent = None
        last_email_sent = None
        last_trigger_motion = None

    # Save the image?
    if (current_frame['save'] == True):
        pathname = ('%s%s.jpg') % (save_path, current_frame['time'].strftime('%Y%m%d%H%M%S%f'))
        # TODO: Find a way to enable this before going live.
        #cv2.imwrite(pathname, current_frame['frame']);

# Clean up
capture_device.release()
cv2.destroyAllWindows()
