import confighelper
import ConfigParser
import timber

class CloverConfig:

    # Reads the clover subprocess configuration and exits the program there is an error.
    def __init__(self, config_file):

        logger = timber.get_instance()

        logger.info('Validating subprocess configuration.')

        config_helper = confighelper.ConfigHelper()

        # By the time this method is called in the subprocess, the logging should already be started. 
        #   However, the main process still needs to validate the subprocess's logging parameters.
        #   Hence why the result is simply discarded.
        config_helper.verify_string_exists(config_file, 'subprocess_log_file')
        config_helper.verify_string_exists(config_file, 'subprocess_log_level')

        self.image_save_path = config_helper.verify_string_exists(config_file, 'image_save_path')

        # Subject on motion detection e-mails
        self.motion_detection_email_subject = config_helper.verify_string_exists(config_file, 'motion_detection_email_subject')
        # Time in seconds
        self.movement_time_threshold = config_helper.verify_number_exists(config_file, 'movement_time_threshold')
        # Can be increased to make movements less sensitive
        self.prior_movements_per_threshold = config_helper.verify_integer_exists(config_file, 'prior_movements_per_threshold')
        # How much the two frames have to vary to be considered different
        self.pixel_difference_threshold = config_helper.verify_number_exists(config_file, 'pixel_difference_threshold')
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

        # Subject for still running notification.
        self.still_running_email_subject = config_helper.verify_string_exists(config_file, 'still_running_email_subject')
        # Maximum time in days before still running notification is sent.
        self.still_running_email_max_delay = config_helper.verify_number_exists(config_file, 'still_running_email_max_delay')
