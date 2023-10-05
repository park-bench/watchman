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

__all__ = ['WatchmanConfig']
__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.8'

import logging
from parkbenchcommon import confighelper


class WatchmanConfig():
    """Loads the configuration for the 'watchman' program.  An instance of this object
    contains all the configuration values.
    """

    def __init__(self, config_parser):
        """Reads the watchman configuration file and throws an exception if there is an
        error.

        config_parser: The ConfigParser instance the configuration is read from.
        """
        logger = logging.getLogger()

        logger.info('Validating watchman configuration.')

        config_helper = confighelper.ConfigHelper()

        # The number of the video device we want to capture photos with. Corresponds to the
        #   video device number that is in the Linux /dev directory.
        self.video_device_number = config_helper.verify_integer_within_range(
            config_parser, 'video_device_number', lower_bound=0)

        # Skips this many frames before detecting motion.  Gives the camera a chance to warm
        #   up.  Set to zero to disable.
        self.initial_frame_skip_count = config_helper.verify_integer_within_range(
            config_parser, 'initial_frame_skip_count', lower_bound=0)

        # Subject on motion detection e-mails
        self.motion_detection_email_subject = config_helper.verify_string_exists(
            config_parser, 'motion_detection_email_subject')
        # Time in seconds
        self.movement_time_threshold = config_helper.verify_number_within_range(
            config_parser, 'movement_time_threshold', lower_bound=0)
        # Can be increased to make movements less sensitive
        self.prior_movements_per_threshold = config_helper.verify_integer_within_range(
            config_parser, 'prior_movements_per_threshold', lower_bound=0)
        # How much the two frames have to vary to be considered different
        self.pixel_difference_threshold = config_helper.verify_number_within_range(
            config_parser, 'pixel_difference_threshold', lower_bound=0)
        self.first_email_image_save_times = config_helper.verify_number_list_exists(
            config_parser, 'first_email_image_save_times')
        # Time in seconds before first e-mail
        self.first_email_delay = config_helper.verify_number_within_range(
            config_parser, 'first_email_delay', lower_bound=0)
        self.second_email_image_save_times = config_helper.verify_number_list_exists(
            config_parser, 'second_email_image_save_times')
        # Time in seconds since first e-mail
        self.second_email_delay = config_helper.verify_number_within_range(
            config_parser, 'second_email_delay', lower_bound=0)
        self.third_email_image_save_times = config_helper.verify_number_list_exists(
            config_parser, 'third_email_image_save_times')
        # Time in seconds since second e-mail
        self.third_email_delay = config_helper.verify_number_within_range(
            config_parser, 'third_email_delay', lower_bound=0)
        self.subsequent_email_image_save_times = config_helper.verify_number_list_exists(
            config_parser, 'subsequent_email_image_save_times')
        # Time in seconds since last e-mail
        self.subsequent_email_delay = config_helper.verify_number_within_range(
            config_parser, 'subsequent_email_delay', lower_bound=0)
        # Time in seconds since last e-mail triggering motion
        self.stop_threshold = config_helper.verify_number_within_range(
            config_parser, 'stop_threshold', lower_bound=0)
        # The maximum image width for images sent via the e-mail.  If the image width is
        #   smaller than this value, the image is sent as captured.  If the image width is
        #   larger than this value, the image is scaled proportionally before it is sent.
        self.email_image_width = config_helper.verify_integer_within_range(
            config_parser, 'email_image_width', lower_bound=1)

        # Angle to rotate the images before they are saved or e-mailed. Only values of 0, 90,
        #   180, or 270 are permitted. This is useful if your camera is placed sideways or
        #   upside down.
        self.image_rotation_angle = config_helper.verify_valid_integer_in_list(
            config_parser, 'image_rotation_angle', (0, 90, 180, 270))

        # The amount of time to wait between saving images locally in seconds.
        self.image_save_throttle_delay = config_helper.verify_number_within_range(
            config_parser, 'image_save_throttle_delay', lower_bound=0)

        # Subject for still running notification.
        self.still_running_email_subject = config_helper.verify_string_exists(
            config_parser, 'still_running_email_subject')
        # Maximum time in days before still running notification is sent.
        self.still_running_email_max_delay = config_helper.verify_number_within_range(
            config_parser, 'still_running_email_max_delay', lower_bound=0)

        # Number of seconds until subtractor is replaced during a motion detection period.
        self.replacement_subtractor_creation_threshold = \
            config_helper.verify_number_within_range(
                config_parser, 'replacement_subtractor_creation_threshold', lower_bound=0)
