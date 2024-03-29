#!/usr/bin/env python3

# Copyright 2015-2023 Joel Allen Luellwitz and Emily Frost
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

# TODO: Consider running in a chroot or jail. (gpgmailer issue 17)
# TODO: Consider detecting and sending the most interesting images. (issue 5)
# TODO: Consider using facial detection. (issue 5)

__all__ = ['WatchmanSubprocess']
__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.8'

import datetime
import configparser
import logging
import math
import os
import random
import traceback
from parkbenchcommon import confighelper
import cv2
import gpgmailmessage
import watchmanconfig

# Constants
LOG_DIRS = '/var/log/watchman'
LOG_PATHNAME = os.path.join(LOG_DIRS, 'watchman-subprocess.log')
IMAGES_PATH = os.path.join(LOG_DIRS, 'images')


class WatchmanSubprocess():
    """Monitors a camera, sending e-mails and saving images when motion is detected.  This
    class runs in its own process because OpenCV does not support device removal.  The work
    around is to kill this process when the camera device disappears.
    """

    def __init__(self):

        print('Loading configuration.')
        config_parser = configparser.SafeConfigParser()
        config_parser.read('/etc/watchman/watchman.conf')

        # Figure out the logging options so that can start before anything else.
        print('Verifying configuration.')
        config_helper = confighelper.ConfigHelper()

        log_level = config_helper.verify_string_exists(config_parser, 'log_level')

        config_helper.configure_logger(LOG_PATHNAME, log_level)
        self.logger = logging.getLogger(__name__)

        try:
            self.config = watchmanconfig.WatchmanConfig(config_parser)

            self.subtractor = self._create_background_subtractor()
            # TODO: See if there is a better option than to create another background
            #   subtractor. (issue 6)
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
        except Exception as exception:  # pylint: disable=broad-except
            self.logger.critical('Fatal %s: %s\n%s', type(exception).__name__,
                                 str(exception), traceback.format_exc())
            raise exception

    def start_loop(self):
        """The main program loop monitoring a camera."""

        try:
            # Open the camera.
            self.capture_device = cv2.VideoCapture(self.config.video_device_number)
            current_frame = self._capture_frame()  # Capture the first frame
            # These next couple lines are not exactly accurate, but they will do for now.
            self.last_image_save_time = current_frame['time']
            # All e-mails, not just motion.
            self.last_email_sent_time = current_frame['time']
            self._calculate_still_running_email_delay()
            frame_count = 0

            # Sometimes we run this program interactively for debugging purposes.
            while cv2.waitKey(1) & 0xFF != ord('q'):

                # This will never wrap around. If there is a frame every millisecond, it
                #   would take millions of years for this value to exceed a 64 bit int, and
                #   even if this value is exceeded, it converts to an "unlimited" long.
                frame_count += 1

                last_frame = current_frame

                current_frame = self._capture_frame()  # Read the next frame

                self._calculate_absolute_difference_mean_total(current_frame, last_frame)

                self._detect_motion(frame_count, current_frame)

                # TODO: The following code and comments are half baked ideas. I need to fix
                #   something now so I'll leave them commented. (issue 12)
                # TODO: The following shouldn't always return. Maybe return by reference?
                #   (issue 12)
                #self.first_motion_email_sent = self._processInitialEmails(
                #    self.first_trigger_motion, self.first_email_image_save_times,
                #    last_frame, current_frame, 'Motion just detected.')
                #self.second_motion_email_sent = self._processInitialEmails(
                #    self.second_trigger_motion, self.second_email_image_save_times,
                #    last_frame, current_frame, 'Follow up one.')
                #self.third_motion_email_sent = self._processInitialEmails(
                #    self.third_trigger_motion, self.third_email_image_save_times,
                #    last_frame, current_frame, 'Follow up two.')

                # Grab images for the first e-mail.
                if self.first_trigger_motion is not None:
                    self._store_email_frames_on_threshold(
                        self.first_trigger_motion, last_frame, current_frame,
                        self.config.first_email_image_save_times)

                # Send first e-mail after so many seconds.
                if self.first_trigger_motion is not None and self._did_threshold_trigger(
                        self.first_trigger_motion, last_frame, current_frame,
                        self.config.first_email_delay):
                    self._send_image_emails('Motion just detected.', current_frame)
                    self.first_motion_email_sent = self.first_trigger_motion + \
                        datetime.timedelta(0, self.config.first_email_delay)

                # Grab images for the second e-mail.
                if self.first_motion_email_sent is not None:
                    self._store_email_frames_on_threshold(
                        self.first_motion_email_sent, last_frame, current_frame,
                        self.config.second_email_image_save_times)

                # Send another e-mail after so many seconds.
                if self.first_motion_email_sent is not None and self._did_threshold_trigger(
                        self.first_motion_email_sent, last_frame, current_frame,
                        self.config.second_email_delay):
                    self._send_image_emails('Follow up one.', current_frame)
                    self.second_motion_email_sent = self.first_motion_email_sent + \
                        datetime.timedelta(0, self.config.second_email_delay)

                # Grab images for the third e-mail.
                if self.second_motion_email_sent is not None:
                    self._store_email_frames_on_threshold(
                        self.second_motion_email_sent, last_frame, current_frame,
                        self.config.third_email_image_save_times)

                # Send third e-mail after so many seconds.
                if self.second_motion_email_sent is not None and self._did_threshold_trigger(
                        self.second_motion_email_sent, last_frame, current_frame,
                        self.config.third_email_delay):
                    self._send_image_emails('Follow up two.', current_frame)
                    self.last_motion_email_sent = self.second_motion_email_sent + \
                        datetime.timedelta(0, self.config.third_email_delay)

                # Grab images for subsequent e-mails.
                if self.last_motion_email_sent is not None:
                    self._store_email_frames_on_threshold(
                        self.last_motion_email_sent, last_frame, current_frame,
                        self.config.subsequent_email_image_save_times)

                # Send subsequent e-mails after so many seconds.
                if self.last_motion_email_sent is not None and self._did_threshold_trigger(
                        self.last_motion_email_sent, last_frame, current_frame,
                        self.config.subsequent_email_delay):
                    self._send_image_emails('Continued motion.', current_frame)
                    self.last_motion_email_sent = self.last_motion_email_sent + \
                        datetime.timedelta(0, self.config.subsequent_email_delay)

                # See if the motion has stopped.
                if self.last_trigger_motion is not None and self._did_threshold_trigger(
                        self.last_trigger_motion, last_frame, current_frame,
                        self.config.stop_threshold):

                    # Clear out the image buffer if images exist.
                    if self.email_frames:
                        self._send_image_emails('Continued motion.', current_frame)

                    self.first_trigger_motion = None
                    self.first_motion_email_sent = None
                    self.second_motion_email_sent = None
                    self.last_motion_email_sent = None
                    self.last_trigger_motion = None

                # Save the image?
                if current_frame['save'] is True:

                    pathname = os.path.join(
                        IMAGES_PATH,
                        current_frame['time'].strftime('%Y-%m-%d_%H-%M-%S_%f.jpg'))
                    cv2.imwrite(pathname, current_frame['rotated_image'])

                self._send_still_running_notification(current_frame)

                self._process_replacement_subtractor(last_frame, current_frame)

        finally:
            # Clean up.
            self.capture_device.release()
            cv2.destroyAllWindows()  # Again for interactive debugging.

    def _calculate_absolute_difference_mean_total(self, current_frame, last_frame):
        """Finds the summation of the absolute mean value of each channel from the difference
        of the two prior background subtracted images.  (If you don't understand what this
        means, read the code.)  This seems to provide a pretty good value that we can use to
        determine if there has been motion when compared against some threshold given the
        environment is sufficiently lit.
        """

        # Find the difference between the two subtracted images
        difference_image = last_frame['subtracted_image'] - current_frame['subtracted_image']

        #cv2.imshow('last subtracted_image', last_frame['subtracted_image'])
        #cv2.imshow('current subtracted_image', current_frame['subtracted_image'])
        #cv2.imshow('difference_image', difference_image)

        # Find the mean difference of each channel.
        channel_means = cv2.mean(difference_image)

        abs_diff_mean_total = 0
        for channel_mean in channel_means:
            # Add the absolute value of the mean.
            abs_diff_mean_total += math.fabs(channel_mean)

        self.logger.trace('abs_diff_mean_total: {0:.10f}'.format(abs_diff_mean_total))

        current_frame['abs_diff_mean_total'] = abs_diff_mean_total

    def _detect_motion(self, frame_count, current_frame):
        """See if there has been enough motion to start sending e-mails or to save an image.
        Also, ignore the first few frames. Initiates the sending of the first e-mail and
        marks images to be saved locally.
        """

        if frame_count > self.config.initial_frame_skip_count and \
                current_frame['abs_diff_mean_total'] > \
                self.config.pixel_difference_threshold:

            # Obtain the time of the differnce.
            now = current_frame['time']

            # Make sure a specific amount of time has passed since the last local image save.
            #   (E-mail initiated saves do not count.)
            if (now - self.last_image_save_time) >= \
                    datetime.timedelta(seconds=self.config.image_save_throttle_delay):

                # Mark the image to be saved.
                self.last_image_save_time = current_frame['time']
                self._mark_for_saving_and_rotate(current_frame)

            # See if there has been a sufficient amount of differences in the specified
            #   time frame.
            motion_detected = False
            if self.config.prior_movements_per_threshold < 1:
                motion_detected = True
            else:
                oldest_movement_time = \
                    self.prior_movements[self.config.prior_movements_per_threshold - 1]
                if oldest_movement_time is not None:
                    time_difference = now - oldest_movement_time
                    if time_difference.total_seconds() < \
                            self.config.movement_time_threshold:
                        motion_detected = True

                # Move the array contents down one, discard the oldest and add the new one
                self.prior_movements = [now] + self.prior_movements[:-1]

            if motion_detected is True:
                #self.logger.debug('Motion Detected')
                self.last_trigger_motion = now
                if self.first_trigger_motion is None:
                    self.first_trigger_motion = now

    # TODO: This is a work in progress. (issue 12)
    def _processInitialEmails(
            self, period_start_time, email_image_save_times, email_delay, last_frame,
            current_frame, message):

        email_sent_time = None

        # Grab images for the e-mail
        if period_start_time is not None:
            self._store_email_frames_on_threshold(
                period_start_time, last_frame, current_frame, email_image_save_times)

        # Send first e-mail after so many seconds
        if period_start_time is not None and self._did_threshold_trigger(
                period_start_time, last_frame, current_frame, email_delay):
            self._send_image_emails(message, current_frame)
            email_sent_time = period_start_time + datetime.timedelta(0, email_delay)

        return email_sent_time

    def _send_still_running_notification(self, current_frame):
        """Sends a still running notifcation e-mail if no e-mail has been sent in a while."""

        if current_frame['time'] > self.last_email_sent_time + datetime.timedelta(
                seconds=self.next_still_running_email_delay):

            email = gpgmailmessage.GpgMailMessage()
            email.set_subject(self.config.still_running_email_subject)
            email.set_body(
                'Watchman is still running as of %s.' %
                current_frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f'))

            self.logger.info('Sending still running notification e-mail.')
            email.queue_for_sending()

            self.last_email_sent_time = current_frame['time']
            self._calculate_still_running_email_delay()

    def _calculate_still_running_email_delay(self):
        """Calculates the number of seconds of e-mail inactivity before sending a "still
        running" e-mail.
        """

        # Calculate a 'random' value between 0 and still_running_email_max_delay converted
        #   to seconds.
        self.next_still_running_email_delay = random.uniform(
            0, self.config.still_running_email_max_delay * 86400)

    def _capture_frame(self):
        """Captures a frame, performs actions necessary for each frame, and stores the data
        in a frame dictionary.
        """

        return_value, image = self.capture_device.read()

        frame_dict = {}
        frame_dict['time'] = datetime.datetime.now()
        frame_dict['image'] = image
        # Remove the 'background'.  Basically this removes noise.
        # TODO: I might have found the solution to our background subtractor problem:
        #   https://stackoverflow.com/questions/26741081/opencv-python-cv2-backgroundsubtractor-parameters
        #   Consider explicitly setting learningRate when apply is called. (issue 6)
        frame_dict['subtracted_image'] = self.subtractor.apply(image)
        #frame_dict['subtracted_image'] = cv2.morphologyEx(frame_dict['subtracted_image'], \
        #    cv2.MORPH_OPEN, kernel)

        # If a replacement subtractor exists, also apply to that subtractor. We don't
        #   need to save the result however.
        if self.replacement_subtractor is not None:
            self.replacement_subtractor.apply(image)

        frame_dict['save'] = False
        return frame_dict

    def _store_email_frames_on_threshold(
            self, start_time, last_frame, current_frame, thresholds):
        """Stores current_frame in saves_frame frame array if the threshold has been crossed.
        """

        for threshold in thresholds:
            if self._did_threshold_trigger(start_time, last_frame, current_frame, threshold):
                self._mark_for_saving_and_rotate(current_frame)
                self.email_frames.append(current_frame)
                break

    # TODO: Consider returning False if start_time is null. (issue 7)
    def _did_threshold_trigger(self, start_time, last_frame, current_frame, threshold):
        """Compares previous and current frame times against a start time to see if enough
        time as elapsed to trigger a threshold.
        """

        threshold_triggered = False
        last_frame_difference = (last_frame['time'] - start_time).total_seconds()
        current_frame_difference = (current_frame['time'] - start_time).total_seconds()
        if last_frame_difference <= threshold and current_frame_difference > threshold:
            threshold_triggered = True
        return threshold_triggered

    def _send_image_emails(self, message, current_frame):
        """Send an signed encrypted MIME/PGP e-mail with a message and image attachments.
        Images might be resized and compressed before sending.

        Param message - A text message to be displayed in the e-mail.
        Param current_frame - The current frame because it contains the current time.
        """

        email = gpgmailmessage.GpgMailMessage()

        email.set_subject(self.config.motion_detection_email_subject)
        email.set_body(
            '%s E-mail queued at %s. Current abs_diff_mean_total: %f' %
            (message, current_frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f'),
             current_frame['abs_diff_mean_total']))

        # Process all the frames
        for frame in self.email_frames:

            # Resize for e-mail or don't resize if images is smaller than desired resolution.
            desired_image_width = self.config.email_image_width  # In pixels
            # depth is discarded
            current_image_height, current_image_width, depth = frame['rotated_image'].shape
            if desired_image_width < current_image_width:
                # Images are scaled proportionally.
                desired_image_height = int(desired_image_width * (current_image_height /
                                                                  current_image_width))
                small_frame = cv2.resize(frame['rotated_image'],
                                         (desired_image_width, desired_image_height))
            else:
                small_frame = frame['rotated_image']

            # Save the file in memory
            ret, small_jpeg = cv2.imencode('.jpg', small_frame)

            # Attach the image to the email message
            # Warning: Making this filename too long causes the signature to fail for some
            #   unknown reason.
            image_filename = '%s-sm.jpg' % frame['time'].strftime('%Y-%m-%d_%H-%M-%S_%f')
            email.add_attachment(image_filename, small_jpeg)

        del self.email_frames[:]

        self.logger.info('Sending "%s" e-mail.', message)
        email.queue_for_sending()

        self.last_email_sent_time = current_frame['time']

    def _mark_for_saving_and_rotate(self, frame):
        """Rotates an image either 0, 90, 180, or 270 degrees. Rotation angle is dictated by
        the configuration variable 'image_rotation_angle'.
        """

        # Don't do this operation if the frame has already been marked for saving.
        if frame['save'] is False:

            frame['save'] = True

            rotation_angle = self.config.image_rotation_angle

            # Don't rotate the image if the rotation angle is 0 (as an optimization).
            if rotation_angle == 0:
                frame['rotated_image'] = frame['image']
            else:

                (height, width) = frame['image'].shape[:2]
                (center_x, center_y) = (width / 2.0, height / 2.0)

                # Create the rotation matrix with the angle adjusted to turn the image
                #   clockwise.  The image is rotated around its center.  We subtract by .5
                #   because OpenCV rotates around the center of the (zero based indexed)
                #   pixel instead of the upper left corner.  The third parameter is the
                #   magnification scale (which is set to remain the same).
                rotation_matrix = cv2.getRotationMatrix2D(
                    (center_x - 0.5, center_y - 0.5), -rotation_angle, 1.0)

                # Adjust the window height and image position when the image is on its side.
                if rotation_angle == 90 or rotation_angle == 270:

                    # Swap the height and width of the new image.
                    original_width = width
                    width = height
                    height = original_width

                    # Adjust the rotation matrix to center the image in the new dimensions.
                    rotation_matrix[0, 2] += (width / 2.0) - center_x
                    rotation_matrix[1, 2] += (height / 2.0) - center_y

                # Actually do the rotation.
                frame['rotated_image'] = cv2.warpAffine(
                    frame['image'], rotation_matrix, (width, height))

                self.logger.trace('Image marked for local save at %s.' %
                                  frame['time'].strftime('%Y-%m-%d %H:%M:%S.%f'))

                # Show the images while testing.
                #cv2.imshow('Image Before Rotation', frame['image'])
                #cv2.imshow('Rotated Image', frame['rotated_image'])
                #cv2.waitKey(0)

    # TODO: This is probably temporary code to quickly get around a bug.  This is why this
    #   code is so self contained. (issue 6)
    def _process_replacement_subtractor(self, last_frame, current_frame):
        """Creates the replacement subtractor and replaces the main subtractor after
        appropriate delays.
        """

        # If motion is no longer detected, remove the replacement subtractor.
        if self.first_trigger_motion is None:
            self.replacement_subtractor = None
            self.subtractor_motion_start_time = None

        # Start the subtractor motion start time
        if self.first_trigger_motion is not None and \
                self.subtractor_motion_start_time is None:
            self.subtractor_motion_start_time = self.first_trigger_motion

        # Increment the replacement subtractor frame count if it has processed frames.
        if self.replacement_subtractor is not None:
            self.replacement_subtractor_frame_count += 1

        # See if enough time has passed since first motion detection to create a replacement
        #   background subtractor.
        if self.first_trigger_motion is not None and self._did_threshold_trigger(
                self.subtractor_motion_start_time, last_frame, current_frame,
                self.config.replacement_subtractor_creation_threshold):
            self.logger.info('Creating replacement background subtractor.')
            self.replacement_subtractor = self._create_background_subtractor()
            self.replacement_subtractor_frame_count = 0

        # Collect a certain number of frames before we replace the main subtractor. Use
        #   the same number of frames used to initiate the main subtractor on program start.
        if self.replacement_subtractor is not None and \
                self.replacement_subtractor_frame_count > \
                self.config.initial_frame_skip_count:
            self.logger.info('Replacing main background subtractor.')
            self.subtractor = self.replacement_subtractor
            self.replacement_subtractor = None
            self.subtractor_motion_start_time = current_frame['time']

    def _create_background_subtractor(self):
        """Creates and returns a background subtractor."""
        # I typically hate one line methods, but it is used in two places and is likely to
        #   change.

        # TODO: Consider using Python 3's more advanced background subtraction algorithms.
        #   (issue 8)
        return cv2.bgsegm.createBackgroundSubtractorMOG()
        #return cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))


# TODO: Consider making sure this class owns the process. (issue 9)
watchman_subprocess = WatchmanSubprocess()
try:
    watchman_subprocess.start_loop()
except Exception as exception:  # pylint: disable=broad-except
    # TODO: This is using an internal object variable. Will probably be solved when we fix
    #   gpgmailer issue 18.
    watchman_subprocess.logger.critical('Fatal %s: %s\n%s', type(exception).__name__,
                                        str(exception), traceback.format_exc())
