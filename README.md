# watchman

_watchman_ monitors a camera for motion and sends encrypted e-mails containing
images of the area being monitored as long as motion is detected.

watchman is licensed under the GNU GPLv3. All source code commits prior to the
public release are also retroactively licensed under the GNU GPLv3.

Bug fixes are welcome!

## Warnings

This software is currently only supported on Ubuntu 14.04 and may not be ready for use in a production environment.

The only current method of installation for our software is building and
installing your own package. We make the following assumptions:

*    You are already familiar with using a Linux terminal.
*    You already know how to use GnuPG.
*    You are already somewhat familiar with using debuild.

## Dependencies

_watchman_ depends on two other pieces of the Parkbench project, which must be installed first:

1. [_confighelper_](https://github.com/park-bench/confighelper)
2. [_gpgmailer_](https://github.com/park-bench/gpgmailer)

## Steps to Build and Install
1.   Clone the latest release tag. (Do not clone the master branch. `master` may not be stable.)
2.   Use `debuild` in the project root directory to build the package.
3.   Use `dpkg -i` to install the package.
4.   Use `apt-get -f install` to resolve any missing dependencies. The daemon will attempt to start and fail. (This is expected.)
5.   Locate the example configuration file at `/etc/watchman/watchman.config.example`. Copy or rename this file to `watchman.conf` in the same directory. Edit this file to change any configuration details.
6.   Restart the daemon with `service watchman restart`. If the configuration file is valid and named correctly, the service will now start successfully.

## Updates

Updates may add or change configuration file options, so if you have a 
configuration file already, check that it has all of the required options 
in the current example file.
