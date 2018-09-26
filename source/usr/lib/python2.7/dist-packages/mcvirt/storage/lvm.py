# Copyright (c) 2018 - I.T. Dev Ltd
#
# This file is part of MCVirt.
#
# MCVirt is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# MCVirt is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCVirt.  If not, see <http://www.gnu.org/licenses/>

import os

from mcvirt.storage.base import Base, BaseVolume
from mcvirt.exceptions import (InvalidStorageConfiguration, InvalidNodesException,
                               ExternalStorageCommandErrorException,
                               MCVirtCommandException)
from mcvirt.system import System
from mcvirt.constants import DirectoryLocation


class Lvm(Base):
    """Storage backend for LVM based storage"""

    @staticmethod
    def check_exists_local(volume_group):
        """Determine if the volume group actually exists on the node."""
        _, out, _ = System.runCommand(['vgs', '|', 'grep', volume_group],
                                      False, DirectoryLocation.BASE_STORAGE_DIR)
        return bool(out)

    @classmethod
    def ensure_exists(cls, location):
        """Ensure that the volume group exists"""
        if not cls.check_exists(location):
            raise InvalidStorageConfiguration(
                'Volume group %s does not exist' % location
            )

    @property
    def _volume_class(self):
        """Return the volume class for the storage backend"""
        return LvmVolume

    def get_free_space(self):
        """Return the free space in megabytes."""
        _, out, _ = System.runCommand(['vgs', self.get_location(),
                                       '-o', 'free', '--noheadings', '--nosuffix', '--units',
                                       'm'], False,
                                      DirectoryLocation.BASE_STORAGE_DIR)
        return float(out)


class LvmVolume(BaseVolume):
    """Overriden volume object from base"""

    def get_path(self, node=None):
        """Return the full path of a given logical volume"""
        return '/dev/' + self.storage_backend.get_location(node=node) + '/' + self.name

    def create(self, size):
        """Create volume in storage backend"""
        # Create command list
        command_args = ['/sbin/lvcreate',
                        self.storage_backend.get_location(),  # Specify volume group
                        '--name', self.name,
                        '--size', '%sM' % size]
        try:
            # Create on local node
            System.runCommand(command_args)

        except MCVirtCommandException, exc:
            raise ExternalStorageCommandErrorException(
                "Error whilst creating disk logical volume:\n" + str(exc)
            )

    def delete(self, ignore_non_existent=False):
        """Delete volume"""
        # Create command arguments
        command_args = ['lvremove', '-f', self.get_path()]
        try:
            # Determine if logical volume exists before attempting to remove it
            if (not (ignore_non_existent and
                     not self.check_exists())):
                System.runCommand(command_args)

        except MCVirtCommandException, exc:
            raise ExternalStorageCommandErrorException(
                "Error whilst removing logical volume:\n" + str(exc)
            )

    def activate(self):
        """Activate volume"""
        # Create command arguments
        command_args = ['lvchange', '-a', 'y', '--yes', self.get_path()]
        try:
            # Run on the local node
            System.runCommand(command_args)

        except MCVirtCommandException, exc:
            raise ExternalStorageCommandErrorException(
                "Error whilst activating logical volume:\n" + str(exc)
            )

    def is_active(self):
        """Return whether volume is activated"""
        return os.path.exists(self.get_path())

    def snapshot(self, destination_volume, size):
        """Snapshot volume"""
        System.runCommand(['lvcreate', '--snapshot', self.get_path(),
                           '--name', destination_volume.name,
                           '--size', size])

    def deactivate(self):
        """Deactivate volume"""
        raise NotImplementedError

    def resize(self, size):
        """Reszie volume"""
        command_args = ['/sbin/lvresize', '--size', '%sM' % size,
                        self.get_path()]
        try:
            # Create on local node
            System.runCommand(command_args)

        except MCVirtCommandException, exc:
            raise ExternalStorageCommandErrorException(
                "Error whilst resizing disk logical volume:\n" + str(exc)
            )

    def check_exists(self):
        """Determine whether logical volume exists"""
        return os.path.lexists(self.get_path())

    def get_size(self):
        """Obtain the size of a logical volume"""
        # Use 'lvs' to obtain the size of the disk
        command_args = (
            'lvs',
            '--nosuffix',
            '--noheadings',
            '--units',
            'm',
            '--options',
            'lv_size',
            self.get_path())
        try:
            _, command_output, _ = System.runCommand(command_args)
        except MCVirtCommandException, exc:
            raise ExternalStorageCommandErrorException(
                "Error whilst obtaining the size of the logical volume:\n" +
                str(exc))

        lv_size = command_output.strip().split('.')[0]
        return int(lv_size)
