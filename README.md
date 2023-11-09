# watchman

_watchman_ monitors a camera for motion and sends encrypted e-mails containing images of the
area being monitored as long as motion is detected.

watchman is licensed under the GNU GPLv3. All source code commits prior to the public release
are also retroactively licensed under the GNU GPLv3.

This software is still in _beta_ and may not be ready for use in a production environment.

Bug fixes are welcome!

## Prerequisites

This software is currently only supported on Ubuntu 18.04.

Currently, the only supported method for installation of this project is building and
installing a Debian package. The rest of these instructions make the following assumptions:

*   You are familiar with using a Linux terminal.
*   You are somewhat familiar with using `debuild`.
*   You are familiar with using `git` and GitHub.
*   `debhelper` and `devscripts` are installed on your build server.
*   You are familiar with GnuPG (for deb signing).

## Parkbench Dependencies

watchman depends on two other Parkbench packages, which must be installed first:

*   [parkbench-common](https://github.com/park-bench/parkbench-common)
*   [gpgmailer](https://github.com/park-bench/gpgmailer)

## Steps to Build and Install

1.  Clone the repository and checkout the latest release tag. (Do not build against the
    `master` branch. The `master` branch might not be stable.)
2.  Run `debuild` in the project root directory to build the package.
3.  Run `apt install /path/to/package.deb` to install the package. The daemon will attempt to
    start and fail. (This is expected.)
4.  Copy or rename the example configuration file `/etc/watchman/watchman.conf.example` to
    `/etc/watchman/watchman.conf`.
5.  Change the ownership and permissions of the configuration file:
```
chown watchman:watchman /etc/watchman/watchman.conf
chmod u=rw,g=r,o= /etc/watchman/watchman.conf
```
6.  Make any desired configuration changes to `/etc/watchman/watchman.conf`.
7.  To ease system maintenance, add `watchman` as a supplemental group to administrative
    users. Doing this will allow these users to view watchman log files.
8.  Restart the daemon with `systemctl restart watchman`. If the configuration file is valid,
    named correctly, and has the correct file permissions, the service will start
    successfully.

## Updates

Updates may change configuration file options. If a configuration file already exists, check
that it has all of the required options from the current example file.
