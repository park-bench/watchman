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
import logging

class WatchmanConfig:

    # Reads the watchman subprocess configuration and exits the program if there is an error.
    def __init__(self, config_file):

        logger = logging.getLogger()

        logger.info('Validating subprocess configuration.')

        config_helper = confighelper.ConfigHelper()

        # By the time this method is called in the subprocess, the logging should already be started. 
        #   However, the main process still needs to validate the subprocess's logging parameters.
        #   Hence why the result is simply discarded.
        config_helper.verify_string_exists(config_file, 'subprocess_log_file')
        config_helper.verify_string_exists(config_file, 'subprocess_log_level')

        # Skips this many frames before detecting motion. Gives the camera a chance to warm up.
        #   Set to zero to disable.
        self.initial_frame_skip_count = config_helper.verify_integer_exists(config_file, 'initial_frame_skip_count')

        self.image_save_path = config_helper.verify_string_exists(config_file, 'image_save_path')

        # Subject on motion detection e-mails
        self.motion_detection_email_subject = config_helper.verify_string_exists(config_file, 'motion_detection_email_subject')
        # Time in seconds
        self.movement_time_threshold = config_helper.verify_number_exists(config_file, 'movement_time_threshold')
        # Can be increased to make movements less sensitive
        self.prior_movements_per_threshold = config_helper.verify_integer_exists(config_file, 'prior_movements_per_threshold')
        # How much the two frames have to vary to be considered different
        self.pixel_difference_threshold = config_helper.verify_number_exists(config_file, 'pixel_difference_threshold')
        self.first_email_image_save_times = config_helper.verify_number_list_exists(config_file, 'first_email_image_save_times')
        # Time in seconds before first e-mail
        self.first_email_delay = config_helper.verify_number_exists(config_file, 'first_email_delay')
        self.second_email_image_save_times = config_helper.verify_number_list_exists(config_file, 'second_email_image_save_times')
        # Time in seconds since last e-mail
        self.second_email_delay = config_helper.verify_number_exists(config_file, 'second_email_delay')
        self.third_email_image_save_times = config_helper.verify_number_list_exists(config_file, 'third_email_image_save_times')
        # Time in seconds since last e-mail
        self.third_email_delay = config_helper.verify_number_exists(config_file, 'third_email_delay')
        self.subsequent_email_image_save_times = config_helper.verify_number_list_exists(config_file, 'subsequent_email_image_save_times')
        # Time in seconds since last e-mail
        self.subsequent_email_delay = config_helper.verify_number_exists(config_file, 'subsequent_email_delay')
        # Time in seconds since last e-mail triggering motion
        self.stop_threshold = config_helper.verify_number_exists(config_file, 'stop_threshold')
        # The maximum image width for images sent via the e-mail. If the image width is smaller than this value, the image is
        #   sent as captured. If the image width is larger than this value, the image is scaled proportionally before it is sent.
        self.email_image_width = config_helper.verify_integer_exists(config_file, 'email_image_width')

        # Angle to rotate the images before they are saved or e-mailed. Only values of 0, 90, 180, or 270 are
        #   permitted. This is useful if your camera is placed sideways or upside down.
        self.image_rotation_angle = config_helper.verify_valid_integer_in_list(config_file, 'image_rotation_angle', (0, 90, 180, 270))

        self.image_save_throttle_delay = config_helper.verify_number_exists(config_file, 'image_save_throttle_delay')

        # Subject for still running notification.
        self.still_running_email_subject = config_helper.verify_string_exists(config_file, 'still_running_email_subject')
        # Maximum time in days before still running notification is sent.
        self.still_running_email_max_delay = config_helper.verify_number_exists(config_file, 'still_running_email_max_delay')

        # Number of seconds until subtractor is replaced during a motion detection period.
        self.replacement_subtractor_creation_threshold = config_helper.verify_number_exists(config_file, 'replacement_subtractor_creation_threshold')
