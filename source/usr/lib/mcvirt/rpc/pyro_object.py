# Copyright (c) 2016 - I.T. Dev Ltd
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

class PyroObject(object):
    """Base class for providing Pyro-based methods for objects"""

    @property
    def _pyro_initialised(self):
        """Determines if object is registered with the Pyro deamon"""
        return ('_pyroDaemon' in self.__dict__.keys())

    def _register_object(self, local_object):
        """Registers an object with the pyro daemon"""
        if self._pyro_initialised:
            self._pyroDaemon.register(local_object)

    def _convert_remote_object(self, remote_object):
        """Returns a local instance of a remote object"""
        # Ensure that object is a remote object
        if self._pyro_initialised:
            # Obtain daemon instance of object
            return self._pyroDaemon.objectsById[remote_object._pyroUri.object]
        else:
            return remote_object
