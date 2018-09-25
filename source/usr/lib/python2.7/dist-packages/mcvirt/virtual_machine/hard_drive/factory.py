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

import Pyro4

from mcvirt.exceptions import (UnknownStorageTypeException, HardDriveDoesNotExistException,
                               InsufficientSpaceException, StorageBackendNotAvailableOnNode,
                               UnknownStorageBackendException)
from mcvirt.virtual_machine.hard_drive.local import Local
from mcvirt.virtual_machine.hard_drive.drbd import Drbd
from mcvirt.virtual_machine.hard_drive.base import Base
from mcvirt.auth.permissions import PERMISSIONS
from mcvirt.rpc.pyro_object import PyroObject
from mcvirt.utils import get_hostname
from mcvirt.rpc.expose_method import Expose


class Factory(PyroObject):
    """Provides a factory for creating hard drive/hard drive config objects"""

    STORAGE_TYPES = [Local, Drbd]
    DEFAULT_STORAGE_TYPE = 'Local'
    OBJECT_TYPE = 'hard disk'
    HARD_DRIVE_CLASS = Base
    CACHED_OBJECTS = {}

    @Expose()
    def getObject(self, vm_object, disk_id, **config):
        """Returns the storage object for a given disk"""
        vm_object = self._convert_remote_object(vm_object)

        # Obtain VM config and initialise storage type value
        vm_config = vm_object.get_config_object().get_config()
        storage_type = None

        # Default to storage type in vm config, if defined
        if vm_config['storage_type']:
            storage_type = vm_config['storage_type']

        # If the storage type as been overriden in the VM config,
        # use this and remove from overrides
        if 'storage_type' in config:
            if storage_type is None:
                storage_type = config['storage_type']
            del config['storage_type']

        # Create cache key, based on name of VM, disk ID and storage type
        storage_type_key = storage_type or ''
        cache_key = (vm_object.get_name(), disk_id, storage_type_key)

        # If configuring overrides have been used, do not cache the object.
        disable_cache = (len(config))

        # If cache is disabled, remove object from cache and return the object directly.
        # Otherwise, if object is not in object cache, create it.
        if disable_cache:
            if cache_key in Factory.CACHED_OBJECTS:
                del Factory.CACHED_OBJECTS[cache_key]
        if cache_key not in Factory.CACHED_OBJECTS:
            hard_drive_object = self.getClass(storage_type)(
                vm_object=vm_object, disk_id=disk_id, **config)
            self._register_object(hard_drive_object)
            if disable_cache:
                return hard_drive_object
            Factory.CACHED_OBJECTS[cache_key] = hard_drive_object

        # If cache is not disabled, return the cached object
        return Factory.CACHED_OBJECTS[cache_key]

    @Expose()
    def ensure_hdd_valid(self, size, storage_type, nodes, storage_backend):
        """Ensures the HDD can be created on all nodes, and returns the storage type to be used."""

        # Ensure that, if storage type is specified, that it's in the list of available storage
        # backends for this node
        # @TODO IF a storage type has been specified, which does not support DBRD, then
        # we can assume that Local storage is used.
        available_storage_types = self._getAvailableStorageTypes()
        if storage_type:
            if (storage_type not in
                    [available_storage.__name__ for available_storage in available_storage_types]):
                raise UnknownStorageTypeException('%s is not supported by node %s' %
                                                  (storage_type, get_hostname()))
        else:
            # Otherwise, if no storage type has been defined, ensure that there is only
            # 1 avilable storage type.
            if len(available_storage_types) > 1:
                raise UnknownStorageTypeException('Storage type must be specified')
            elif len(available_storage_types) == 1:
                storage_type = available_storage_types[0].__name__
            else:
                raise UnknownStorageTypeException('There are no storage types available')

        # If storage backend has been defined, ensure it is available on the current node
        if storage_backend:
            storage_backend.ensure_available_on_node()

        # Otherwise, if storage backend has not been defined, ensure that
        # there is only one available for the given storage type and nodes selected
        else:
            storage_factory = self._get_registered_object('storage_factory')
            available_storage_backends = storage_factory.get_all(
                nodes=nodes, drbd=(storage_type == Drbd.__name__)
            )
            if len(available_storage_backends) > 1:
                raise UnknownStorageBackendException('Storage backend must be specified')
            elif len(available_storage_backends) == 1:
                storage_backend = available_storage_backends[0]
            else:
                raise UnknownStorageBackendException('There are no available storage backends')

        free = storage_backend.get_free_space()
        if free < size:
            raise InsufficientSpaceException('Attempted to create a disk with %i MiB, but there '
                                             'is only %i MiB of free space available on node %s.' %
                                             (size, free, get_hostname()))

        if self._is_cluster_master:
            def remote_command(remote_connection):
                remote_storage_factory = remote_connection.get_connection('storage_factory')
                remote_storage_backend = remote_storage_factory.get_object(
                    name=storage_backend.name
                )
                hard_drive_factory = remote_connection.get_connection('hard_drive_factory')
                hard_drive_factory.ensure_hdd_valid(size=size, storage_type=storage_type,
                                                    nodes=nodes,
                                                    storage_backend=remote_storage_backend)

            cluster = self._get_registered_object('cluster')
            remote_nodes = [node for node in nodes if node != cluster.get_local_hostname()]
            cluster.run_remote_command(callback_method=remote_command, nodes=remote_nodes)

        return storage_type

    @Expose(locking=True)
    def create(self, vm_object, size, storage_type, driver, storage_backend=None):
        """Performs the creation of a hard drive, using a given storage type"""
        vm_object = self._convert_remote_object(vm_object)

        # Ensure that the user has permissions to add create storage
        self._get_registered_object('auth').assert_permission(
            PERMISSIONS.MODIFY_VM,
            vm_object
        )

        nodes = vm_object.getAvailableNodes()
        storage_type = self.ensure_hdd_valid(size, storage_type, nodes, storage_backend)

        # Ensure the VM storage type matches the storage type passed in
        if vm_object.getStorageType():
            if storage_type and storage_type != vm_object.getStorageType():
                raise UnknownStorageTypeException(
                    'Storage type does not match VMs current storage type'
                )

        hdd_object = self.getClass(storage_type)(vm_object=vm_object, driver=driver,
                                                 storage_backend=storage_backend)
        self._register_object(hdd_object)
        hdd_object.create(size=size)
        return hdd_object

    def _getAvailableStorageTypes(self):
        """Returns a list of storage types that are available on the node"""
        available_storage_types = []
        storage_factory = self._get_registered_object('storage_factory')
        node_drbd = self._get_registered_object('node_drbd')
        for storage_type in self.STORAGE_TYPES:
            if storage_type.isAvailable(storage_factory, node_drbd):
                available_storage_types.append(storage_type)
        return available_storage_types

    def getStorageTypes(self):
        """Returns the available storage types that MCVirt provides"""
        return self.STORAGE_TYPES

    def getClass(self, storage_type):
        """Obtains the hard drive class for a given storage type"""
        for hard_drive_class in self.getStorageTypes():
            if (storage_type == hard_drive_class.__name__):
                return hard_drive_class
        raise UnknownStorageTypeException(
            'Attempted to initialise an unknown storage type: %s' %
            (storage_type)
        )

    @Expose()
    def getDrbdObjectByResourceName(self, resource_name):
        """Obtains a hard drive object for a Drbd drive, based on the resource name"""
        node_drbd = self._get_registered_object('node_drbd')
        for hard_drive_object in node_drbd.get_all_drbd_hard_drive_object():
            if hard_drive_object.resource_name == resource_name:
                return hard_drive_object
        raise HardDriveDoesNotExistException(
            'Drbd hard drive with resource name \'%s\' does not exist' %
            resource_name
        )
