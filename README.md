# watchman

_watchman_ monitors a camera for motion and sends encrypted e-mails containing images of the
area being monitored as long as motion is detected.

watchman is licensed under the GNU GPLv3. All source code commits prior to the public release
are also retroactively licensed under the GNU GPLv3.

This is software is still in _beta_ and may not be ready for use in a production environment.

Bug fixes are welcome!

## Prerequisites

Currently, the only supported method for installation of this project is building and
installing a Debian package. The rest of these instructions make the following assumptions:

*   Your server is running Ubuntu 18.04 LTS. (Other operating systems may work, but are not
    supported.)
*   `build-essential` is installed on your build server.
*   `devscripts` is installed on your build server.
*   You are already familiar with using a Linux terminal.
*   You are familiar with using `git` and GitHub.
*   You already know how to use GnuPG.
*   You are already somewhat familiar with using `debuild`.

## Parkbench Dependencies

_torwatchdog_ depends on two other Parkbench projects which must be installed first:

1.  [_parkbench-common_](https://github.com/park-bench/parkbench-common)
2.  [_gpgmailer_](https://github.com/park-bench/gpgmailer)

## Steps to Build and Install

1.  Clone the repository and checkout the lastest release tag. (Do not build against the
    `master` branch. The `master` branch might not be stable.)
2.  Use `debuild` in the project root directory to build the package.
3.  Use `dpkg -i` to install the package.
4.  Run `apt-get -f install` to resolve any missing dependencies. The daemon will attempt to
    start and fail. (This is expected.)
5.  Copy or rename the example configuration file `/etc/watchman/watchman.conf.example` to
    `/etc/watchman/watchman.conf`. Edit this file to change any configuration settings.
6.  Use `chmod` to clear the _other user_ permissions bits of `watchman.conf`. Namely, remove
    read, write, and execute permissions for _other_.
7.  Use `chown` to change the ownership of `watchman.conf` to be owned by the `watchman`
    user.
8.  To ease system maintenance, add `watchman` as a supplemental group to administrative
    users. Doing this will allow these users to view watchman log files.
9.  Restart the daemon with `systemctl restart watchman`. If the configuration file is valid,
    named correctly, and has the correct file permissions, the service will start
    successfully.

## Updates

Updates may change configuration file options. So if you have a configuration file already,
check the current example file to make sure it has all the required options.
