# Copyright (c) 2014 - I.T. Dev Ltd
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

from mcvirt.system import System
from mcvirt.exceptions import (VmAlreadyStartedException, VmIsCloneException,
                               ExternalStorageCommandErrorException,
                               DiskAlreadyExistsException,
                               CannotMigrateLocalDiskException,
                               MCVirtCommandException)
from mcvirt.virtual_machine.hard_drive.base import Base
from mcvirt.auth.permissions import PERMISSIONS
from mcvirt.rpc.expose_method import Expose
from mcvirt.size_converter import SizeConverter


class Local(Base):
    """Provides operations to manage local hard drives, used by VMs"""

    MAXIMUM_DEVICES = 4
    CACHE_MODE = 'directsync'

    @property
    def disk_name(self):
        """Return disk name"""
        return self.base_volume_name

    @staticmethod
    def isAvailable(storage_factory, node_drdb):
        """Determine if local storage is available on the node"""
        return bool(storage_factory.get_all(available_on_local_node=True))

    def _get_data_volume(self):
        """Obtain the data volume object for the disk"""
        return self._get_volume(self.disk_name)

    @Expose(locking=True)
    def increase_size(self, increase_size):
        """Increases the size of a VM hard drive, given the size to increase the drive by"""
        self._get_registered_object('auth').assert_permission(
            PERMISSIONS.MODIFY_VM, self.vm_object
        )

        # Convert disk size to bytes
        increase_size = (increase_size
                         if isinstance(increase_size, int) else
                         SizeConverter.from_string(increase_size, storage=True).to_bytes())

        # Ensure disk exists
        self._ensure_exists()

        # Ensure VM is stopped
        if not self.vm_object.is_stopped:
            raise VmAlreadyStartedException('VM must be stopped before increasing disk size')

        # Ensure that VM has not been cloned and is not a clone
        if self.vm_object.getCloneParent() or self.vm_object.getCloneChildren():
            raise VmIsCloneException('Cannot increase the disk of a cloned VM or a clone.')

        # Obtain volume for the disk and resize
        volume = self._get_data_volume()
        volume.resize(increase_size, increase=True)

    def _check_exists(self):
        """Checks if a disk exists, which is required before any operations
        can be performed on the disk"""
        return self._get_data_volume().check_exists()

    def _removeStorage(self, local_only=False, remove_raw=True):
        """Removes the backing logical volume"""
        self._get_data_volume().delete()

    def get_size(self):
        """Gets the size of the disk (in MB)"""
        return self._get_data_volume().get_size()

    def clone(self, destination_vm_object):
        """Clone a VM, using snapshotting, attaching it to the new VM object"""
        self._ensure_exists()
        new_disk = Local(vm_object=destination_vm_object, driver=self.driver,
                         disk_id=self.disk_id,
                         storage_backend=self.storage_backend)
        self._register_object(new_disk)

        # Clone original volume to new volume
        self._get_data_volume().clone(new_disk._get_data_volume())

        new_disk.addToVirtualMachine(
            nodes=self._get_registered_object('cluster').get_nodes(include_local=True),
            get_remote_object_kwargs={'registered': False})
        return new_disk

    def create(self, size):
        """Creates a new disk image, attaches the disk to the VM and records the disk
        in the VM configuration"""
        self._get_data_volume().create(size)

    def activateDisk(self):
        """Starts the disk logical volume"""
        self._ensure_exists()
        self._get_data_volume().activate()

    def deactivateDisk(self):
        """Deactivates the disk loglcal volume"""
        self._get_data_volume().deactivate()

    def preMigrationChecks(self):
        """Perform pre-migration checks"""
        # @TODO Allow migration for shared disks - worth ensuring that the disks is actually
        # available on both nodes
        if not self.storage_backend.shared:
            raise CannotMigrateLocalDiskException(
                'VMs using local disks on a non-shared backend cannot be migrated')

    def _getDiskPath(self):
        """Returns the path of the raw disk image"""
        return self._get_data_volume().get_path()

    def _getDiskName(self):
        """Returns the name of a disk logical volume, for a given VM"""
        return self.disk_name

    def get_backup_source_volume(self):
        """Retrun the source volume for snapshotting for backeups"""
        return self._get_data_volume()

    def get_backup_snapshot_volume(self):
        """Return a volume object for the disk object"""
        return self._get_volume(self.disk_name + self.SNAPSHOT_SUFFIX)
