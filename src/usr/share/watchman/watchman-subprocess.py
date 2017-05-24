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

# TODO: Consider detecting and sending the most interesting images.
# TODO: Consider using facial detection.

from __future__ import division

import watchmanconfig
import confighelper
import ConfigParser
import cv2
import datetime
import glob
import gpgmailmessage
import logging
import math
import random
import sys
import time

class WatchmanSubprocess:

    def __init__(self):

        print('Loading configuration.')
        config_file = ConfigParser.SafeConfigParser()
        config_file.read('/etc/watchman/watchman.conf')

        # Figure out the logging options so that can start before anything else.
        print('Verifying configuration.')
        config_helper = confighelper.ConfigHelper()
        log_file = config_helper.verify_string_exists_prelogging(config_file, 'subprocess_log_file')
        log_level = config_helper.verify_string_exists_prelogging(config_file, 'subprocess_log_level')

        config_helper.configure_logger(log_file, log_level)
        self.logger = logging.getLogger()

        self.config = watchmanconfig.WatchmanConfig(config_file)

        self.subtractor = self._create_background_subtractor()
        # TODO: See if there is a better option than to create another background subtractor.
        self.replacement_subtractor = None
        self.replacement_subtractor_frame_count = 0
        self.subtractor_motion_start_time = None

        self.email_frames = []
        self.prior_movements = [None] * self.config.prior_movements_per_threshold

        self.first_trigger_motion = None
        self.first_motion_email_sent = None
        self.second_motion_email_sent = None
        self.last_motion_email_sent = None
        self.last_trigger_motion = None

        self.video_device_number = int(sys.argv[1])

        # Read gpgmailer watch directory from the gpgmailer config file
        gpgmailmessage.GpgMailMessage.configure()


    def start_loop(self):

        try:
            self.capture_device = cv2.VideoCapture(self.video_device_number)  # Open the camera

            current_frame = self._capture_frame()  # Capture the first frame
            # These next couple lines are not exactly accurate, but they will do for now.
            self.last_image_save_time = current_frame['time']
            self.last_email_sent_time = current_frame['time']  # All e-mails, not just motion.
            self._calculate_still_running_email_delay()
            frame_count = 0

            # Sometimes we run this program interactively for debugging purposes.
            while(cv2.waitKey(1) & 0xFF != ord('q')):

                # This will never wrap around. If there is a frame every millisecond, it would take
                #   millions of years for this value to exceed a 64 bit int, and even if this value
                #   is exceeded, it converts to an "unlimited" long.
                frame_count += 1

                last_frame = current_frame

                current_frame = self._capture_frame()  # Read the next frame
     
                self._calculate_absolute_difference_mean_total(current_frame, last_frame)

                self._detect_motion(frame_count, current_frame)

                # TODO: The following code and comments are half baked ideas. I need to fix something 
                #   now so I'll leave them commented.
                # TODO: The following shouldn't always return. Maybe return by reference?
                # TODO: self.first_motion_email_sent = self._processInitialEmails(self.first_trigger_motion, self.first_email_image_save_times, last_frame, current_frame, 'Motion just detected.')
                # TODO: self.second_motion_email_sent = self._processInitialEmails(self.second_trigger_motion, self.second_email_image_save_times, last_frame, current_frame, 'Follow up one.')
                # TODO: self.third_motion_email_sent = self._processInitialEmails(self.third_trigger_motion, self.third_email_image_save_times, last_frame, current_frame, 'Follow up two.')

                # Grab images for the first e-mail
                if (self.first_trigger_motion != None):
                    self._store_email_frames_on_threshold(self.first_trigger_motion, \
                            last_frame, current_frame, self.config.first_email_image_save_times)

                # Send first e-mail after so many seconds
                if (self.first_trigger_motion != None and \
                        self._did_threshold_trigger(self.first_trigger_motion, \
                        last_frame, current_frame, self.config.first_email_delay)):
                    self._send_image_emails('Motion just detected.', current_frame)
                    self.first_motion_email_sent = self.first_trigger_motion + datetime.timedelta(0, \
                        self.config.first_email_delay)
 
                # Grab images for the second e-mail
                if (self.first_motion_email_sent != None):
                    self._store_email_frames_on_threshold(self.first_motion_email_sent, \
                            last_frame, current_frame, self.config.second_email_image_save_times)

                # Send another e-mail after so many seconds
                if (self.first_motion_email_sent != None and \
                        self._did_threshold_trigger(self.first_motion_email_sent, \
                        last_frame, current_frame, self.config.second_email_delay)):
                    self._send_image_emails('Follow up one.', current_frame)
                    self.second_motion_email_sent = self.first_motion_email_sent + datetime.timedelta(0, \
                        self.config.second_email_delay)

                # Grab images for the third e-mail
                if (self.second_motion_email_sent != None):
                    self._store_email_frames_on_threshold(self.second_motion_email_sent, \
                            last_frame, current_frame, self.config.third_email_image_save_times)

                # Send third e-mail after so many seconds
                if (self.second_motion_email_sent != None and \
                        self._did_threshold_trigger(self.second_motion_email_sent, \
                        last_frame, current_frame, self.config.third_email_delay)):
                    self._send_image_emails('Follow up two.', current_frame)
                    self.last_motion_email_sent = self.second_motion_email_sent + datetime.timedelta(0, \
                        self.config.third_email_delay)

                # Grab images for subsequent e-mails
                if (self.last_motion_email_sent != None):
                    self._store_email_frames_on_threshold(self.last_motion_email_sent, \
                        last_frame, current_frame, self.config.subsequent_email_image_save_times)

                # Send subsequent e-mails after so many seconds
                if (self.last_motion_email_sent != None and \
                        self._did_threshold_trigger(self.last_motion_email_sent, last_frame, \
                        current_frame, self.config.subsequent_email_delay)):
                    self._send_image_emails('Continued motion.', current_frame)
                    self.last_motion_email_sent = self.last_motion_email_sent + datetime.timedelta(0, \
                        self.config.subsequent_email_delay)

                # See if the motion has stopped.
                if (self.last_trigger_motion != None and \
                        self._did_threshold_trigger(self.last_trigger_motion, \
                        last_frame, current_frame, self.config.stop_threshold)):

                    # Clear out the image buffer if images exist
                    if (len(self.email_frames) > 0):
                        self._send_image_emails('Continued motion.', current_frame)

                    self.first_trigger_motion = None
                    self.first_motion_email_sent = None
                    self.second_motion_email_sent = None
                    self.last_motion_email_sent = None
                    self.last_trigger_motion = None

                # Save the image?
                if (current_frame['save'] == True):

                    # TODO: Rotate the image as soon as you know you are going to save it. (Create
                    #   a _markForSavingAndRotate method.)
                    # Rotate the image (if required) before saving it to disk.
                    rotated_image = self._rotate_image(current_frame['image'])

                    pathname = ('%s%s.jpg') % (self.config.image_save_path, \
                        current_frame['time'].strftime('%Y-%m-%d_%H-%M-%S_%f'))
                    cv2.imwrite(pathname, rotated_image)

                self._send_still_running_notification(current_frame)

                self._process_replacement_subtractor(last_frame, current_frame)

        finally:
            # Clean up
            self.capture_device.release()
            cv2.destroyAllWindows()  # Again for interactive debugging.


    # Finds the summation of the absolute mean value of each channel from the difference of
    #   the two prior background subtracted images. (If you don't understand what this means, 
    #   read the code.) This seems to provide a pretty good value that we can use to determine
    #   if there has been motion when compared against some threshold given the environment is
    #   sufficiently lit.
    def _calculate_absolute_difference_mean_total(self, current_frame, last_frame):

        # Find the difference between the two subtracted images
        difference_image = last_frame['subtracted_image'] - current_frame['subtracted_image']
        
        #cv2.imshow('last subtracted_image', last_frame['subtracted_image'])
        #cv2.imshow('current subtracted_image', current_frame['subtracted_image'])
        #cv2.imshow('difference_image', difference_image)

        channel_means = cv2.mean(difference_image)  # Find the mean difference of each channel

        abs_diff_mean_total = 0
        for channel_mean in channel_means:
            abs_diff_mean_total += math.fabs(channel_mean)  # Add the absolute value of the mean
        
        self.logger.trace('abs_diff_mean_total: {0:.10f}'.format(abs_diff_mean_total))

        current_frame['abs_diff_mean_total'] = abs_diff_mean_total
 

    # See if there has been enough motion to start sending e-mails or to save an image. Also, ignore 
    #   the first few frames. Initiates the sending of the first e-mail and marks images to be saved
    #   locally.
    def _detect_motion(self, frame_count, current_frame):
        
        if (frame_count > self.config.initial_frame_skip_count and \
                current_frame['abs_diff_mean_total'] > self.config.pixel_difference_threshold):

            # Obtain the time of the differnce
            now = current_frame['time']

            # Make sure a specific amount of time has passed since the last local image save.
            #   (E-mail initiated saves do not count.)
            if ((current_frame['time'] - self.last_image_save_time) >= 
                datetime.timedelta(seconds = self.config.image_save_throttle_delay)):

                # Save the image
                self.logger.trace('Image marked for local save at %s.' % \
                    current_frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f'))
                current_frame['save'] = True
                self.last_image_save_time = current_frame['time']

            # See if there has been another difference in the last second
            prior_movements_iterator = iter(self.prior_movements)
            prior_movement_time = next(prior_movements_iterator, 'End')
            if (prior_movement_time != None and prior_movement_time != 'End'):
                time_difference = now - prior_movement_time
            while (prior_movement_time != None and prior_movement_time != 'End' and \
                    time_difference.total_seconds() <= self.config.movement_time_threshold):
                prior_movement_time = next(prior_movements_iterator, 'End')
                if (prior_movement_time != None and prior_movement_time != 'End'):
                    time_difference = now - prior_movement_time

            if (prior_movement_time == 'End'):
                #self.logger.debug('Motion Detected')
                self.last_trigger_motion = now
                if (self.first_trigger_motion == None):
                    self.first_trigger_motion = now
                    # TODO: Remove if setting first threshold to 0 works.
                    #self.email_frames.append(current_frame)
                    #current_frame['save'] = True

            # Move the array contents down one, discard the oldest and add the new one
            if (len(self.prior_movements)):
                self.prior_movements = [now] + self.prior_movements[:-1]


    # TODO: This is a work in progress.
    def _processInitialEmails(self, period_start_time, email_image_save_times, email_delay, last_frame, current_frame, message):

        email_sent_time = None

        # Grab images for the e-mail
        if (period_start_time != None):
            self._store_email_frames_on_threshold(period_start_time, \
                    last_frame, current_frame, email_image_save_times)

        # Send first e-mail after so many seconds
        if (period_start_time != None and \
                self._did_threshold_trigger(period_start_time, \
                last_frame, current_frame, email_delay)):
            self._send_image_emails(message, current_frame)
            email_sent_time = period_start_time + datetime.timedelta(0, \
                email_delay)

        return email_sent_time


    # Sends a still running notifcation e-mail if no e-mail has been sent in a while. 
    def _send_still_running_notification(self, current_frame):
       
        if (current_frame['time'] > self.last_email_sent_time + \
                datetime.timedelta(seconds = self.next_still_running_email_delay)):

            email = gpgmailmessage.GpgMailMessage()
            email.set_subject(self.config.still_running_email_subject)
            email.set_body('Watchman is still running as of %s.' % \
                current_frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f'))

            self.logger.info('Sending still running notification e-mail.')
            email.queue_for_sending()

            self.last_email_sent_time = current_frame['time']
            self._calculate_still_running_email_delay()


    # Calculates the number of seconds of e-mail inactivity before sending a "still running" e-mail.
    def _calculate_still_running_email_delay(self):
        # Calculate a 'random' value between 0 and still_running_email_max_delay converted to seconds.
        self.next_still_running_email_delay = random.uniform(0, \
            self.config.still_running_email_max_delay * 86400)


    # Captures a frame, performs actions necessary for each frame, and stores the data
    #   in a frame dictionary.
    def _capture_frame(self):
        return_value, image = self.capture_device.read()

        frame_dict = {}
        frame_dict['time'] = datetime.datetime.now()
        frame_dict['image'] = image 
        # Remove the 'background'.  Basically this removes noise.
        # TODO: I might have found the solution to our background subtractor problem:
        #   https://stackoverflow.com/questions/26741081/opencv-python-cv2-backgroundsubtractor-parameters
        #   Consider explicitly setting learningRate when apply is called.
        frame_dict['subtracted_image'] = self.subtractor.apply(image)
        #frame_dict['subtracted_image'] = cv2.morphologyEx(frame_dict['subtracted_image'], \
        #    cv2.MORPH_OPEN, kernel)
 
        # If a replacement subtractor exists, also apply to that subtractor. We don't
        #   need to save the result however.
        if self.replacement_subtractor <> None:
            self.replacement_subtractor.apply(image)

        frame_dict['save'] = False
        return frame_dict
 

    # Stores current_frame in saves_frame frame array if the threshold has been crossed.
    def _store_email_frames_on_threshold(self, start_time, last_frame, current_frame, thresholds):
        for threshold in thresholds:
            if (self._did_threshold_trigger(start_time, last_frame, current_frame, threshold)):
                current_frame['save'] = True
                self.email_frames.append(current_frame)
                break


    # Compares previous and current frame times against a start time to see if enough
    #   time as elapsed to trigger a threshold.
    # TODO: Consider returning False if start_time is null.
    def _did_threshold_trigger(self, start_time, last_frame, current_frame, threshold):
        threshold_triggered = False
        last_frame_difference = (last_frame['time'] - start_time).total_seconds()
        current_frame_difference = (current_frame['time'] - start_time).total_seconds()
        if (last_frame_difference < threshold and current_frame_difference >= threshold):
            threshold_triggered = True
        return threshold_triggered


    # Send an signed encrypted MIME/PGP e-mail with a message and image attachments.
    #   Images might be resized and compressed before sending.
    # Param message - A text message to be displayed in the e-mail.
    # Param current_frame - The current frame because it contains the current time.
    def _send_image_emails(self, message, current_frame):

        email = gpgmailmessage.GpgMailMessage()

        email.set_subject(self.config.motion_detection_email_subject)
        email.set_body('%s E-mail queued at %s. Current abs_diff_mean_total: %f' % \
                (message, current_frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f'),
                current_frame['abs_diff_mean_total']))

        # Process all the frames
        for frame in self.email_frames:

            # Resize for e-mail or don't resize if images is smaller than desired resolution.
            desired_image_width = self.config.email_image_width  # In pixels
            # depth is discarded
            current_image_height, current_image_width, depth = frame['image'].shape
            if desired_image_width < current_image_width:
                # Images are scaled proportionally.
                desired_image_height = int(desired_image_width * (current_image_height / \
                    current_image_width))
                small_frame = cv2.resize(frame['image'], (desired_image_width, desired_image_height))
            else:
                small_frame = frame['image']

            # TODO: Rotate the image before scaling. Actually, rotate the image as soon as you know
            #   you are going to save it. (Create a _markForSavingAndRotate method.)
            # Rotate the image if needed.
            small_frame = self._rotate_image(small_frame)

            # Save the file in memory
            ret, small_jpeg = cv2.imencode('.jpg', small_frame)

            # Attach the image to the email message
            # Warning: Making this filename too long causes the signature to fail for some unknown 
            #   reason.
            image_filename = '%s-sm.jpg' % frame['time'].strftime('%Y-%m-%d_%H-%M-%S_%f')
            email.add_attachment(image_filename, small_jpeg)

        del self.email_frames[:]

        self.logger.info('Sending "%s" e-mail.' % message)
        email.queue_for_sending()

        self.last_email_sent_time = current_frame['time']


    # Rotates an image either 0, 90, 180, or 270 degrees. Rotation angle is dictated by the
    #   configuration variable 'image_rotation_angle'.
    def _rotate_image(self, image):

        # TODO: Don't rotate the image when the angle is 0. This is a performance optimization.

        (height, width) = image.shape[:2]
        (center_x, center_y) = (width / 2, height / 2)

        rotation_angle = self.config.image_rotation_angle

        # Create the rotation matrix with the angle adjusted to turn the image clockwise. The image
        #   is rotated around its center. The third parameter is the magnification scale (which
        #   is set to remain the same).
        rotation_matrix = cv2.getRotationMatrix2D((center_x, center_y), -rotation_angle, 1.0)

        # Adjust the window height and image position when the image is on its side.
        if rotation_angle == 90 or rotation_angle == 270:

            # Swap the height and width of the new image.
            original_width = width
            width = height
            height = original_width

            # Adjust the rotation matrix to center the image in the new dimensions.
            rotation_matrix[0, 2] += (width / 2) - center_x
            rotation_matrix[1, 2] += (height / 2) - center_y

        # Actually do the rotation.
        rotated_image = cv2.warpAffine(image, rotation_matrix, (width, height))

        # Show the images while testing.
        #cv2.imshow('Image Before Rotation', image)
        #cv2.imshow('Rotated Image', rotated_image)
        #cv2.waitKey(0)

        return rotated_image


    # Creates the replacement subtractor and replaces the main subtractor after appropriate delays.
    # TODO: This is probably temporary code to quickly get around a bug. This is why this code is
    #   so self contained.
    def _process_replacement_subtractor(self, last_frame, current_frame):

        # If motion is no longer detected, remove the replacement subtractor.
        if self.first_trigger_motion == None:
            self.replacement_subtractor = None
            self.subtractor_motion_start_time = None

        # Start the subtractor motion start time
        if self.first_trigger_motion <> None and self.subtractor_motion_start_time == None:
            self.subtractor_motion_start_time = self.first_trigger_motion

        # Increment the replacement subtractor frame cound if it has processed frames.
        if self.replacement_subtractor <> None:
            self.replacement_subtractor_frame_count += 1
 
        # See if enough time has passed since first motion detection to create a replacement
        #   background subtractor.
        if self.first_trigger_motion <> None and self._did_threshold_trigger(self.subtractor_motion_start_time, \
                last_frame, current_frame, self.config.replacement_subtractor_creation_threshold):
            self.logger.info('Creating replacement background subtractor.')
            self.replacement_subtractor = self._create_background_subtractor()
            self.replacement_subtractor_frame_count = 0

        # Collect a certain number of frames before we replace the main subtractor. Use
        #   the same number of frames used to initiate the main subtractor on program start.
        if self.replacement_subtractor <> None and \
                self.replacement_subtractor_frame_count > self.config.initial_frame_skip_count:
            self.logger.info('Replacing main background subtractor.')
            self.subtractor = self.replacement_subtractor
            self.replacement_subtractor = None
            self.subtractor_motion_start_time = current_frame['time']


    # Creates and returns a background subtractor.
    # I typically hate one line methods, but it is used in two places and is likely to change.
    # TODO: Consider switching to Python 3 to use more advanced background subtraction algorithms.
    def _create_background_subtractor(self):
        
        return cv2.BackgroundSubtractorMOG()
        #return cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))


# TODO: Consider making sure this class owns the process.
watchman_subprocess = WatchmanSubprocess()
watchman_subprocess.start_loop()
