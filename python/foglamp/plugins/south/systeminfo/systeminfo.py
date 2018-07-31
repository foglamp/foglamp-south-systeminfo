# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END

""" Module for System Info async plugin """

import asyncio
import copy
import uuid
import datetime
import os
import glob
import sys
import shutil
import json
import fnmatch
import subprocess
from foglamp.services.core.connect import *
from foglamp.common import logger
from foglamp.plugins.common import utils
from foglamp.services.south import exceptions
from foglamp.services.south.ingest import Ingest


__author__ = "Amarendra K Sinha"
__copyright__ = "Copyright (c) 2018 Dianomic Systems"
__license__ = "Apache 2.0"
__version__ = "${VERSION}"


_DEFAULT_CONFIG = {
    'plugin': {
        'description': 'System info async plugin',
        'type': 'string',
        'default': 'systeminfo'
    },
    'assetCode': {
        'description': 'Asset Code',
        'type': 'string',
        'default': "system"
    },
    'sleepInterval': {
        'description': 'Sleep Interval, in seconds, between two System info gathering',
        'type': 'integer',
        'default': "30"
    }
}
_LOGGER = logger.setup(__name__, level=20)


def plugin_info():
    """ Returns information about the plugin.
    Args:
    Returns:
        dict: plugin information
    Raises:
    """

    return {
        'name': 'System Info plugin',
        'version': '1.0',
        'mode': 'async',
        'type': 'south',
        'interface': '1.0',
        'config': _DEFAULT_CONFIG
    }


def plugin_init(config):
    """ Initialise the plugin.
    Args:
        config: JSON configuration document for the South device configuration category
    Returns:
        data: JSON object to be used in future calls to the plugin
    Raises:
    """
    data = copy.deepcopy(config)
    return data


def plugin_start(handle):
    """ Extracts data from the system info and returns it in a JSON document as a Python dict.
    Available for async mode only.

    Args:
        handle: handle returned by the plugin initialisation call
    Returns:
        a system info reading in a JSON document, as a Python dict, if it is available
        None - If no reading is available
    Raises:
        TimeoutError
    """
    def get_system_info():
        # Details of machine resources, memory size, amount of available memory, storage size and amount of free storage
        total, used, free = shutil.disk_usage("/")
        memory = subprocess.Popen('free -h', shell=True, stdout=subprocess.PIPE).stdout.readlines()[1].split()[1:]
        data = {
            "platform": sys.platform,
            "totalMemory": memory[0].decode(),
            "usedMemory": memory[1].decode(),
            "freeMemory": memory[2].decode(),
            "totalDiskSpace_MB": int(total / (1024 * 1024)),
            "usedDiskSpace_MB": int(used / (1024 * 1024)),
            "freeDiskSpace_MB": int(free / (1024 * 1024)),
        }

        # A PS listing of al the python applications running on the machine
        a = subprocess.Popen(
            'ps -eaf', shell=True, stdout=subprocess.PIPE).stdout.readlines()[:-2]  # remove ps command
        c = [b.decode() for b in a]  # Since "a" contains return value in bytes, convert it to string
        data.update({
            "numberOProcessesRunning": c
        })

        # Get Network and other info
        data.update({
            "numberOfNetworkPacketsReceived" : None,
            "numberOfNetworkPacketsSent": None,
            "cpuUsage": None,
            "numberOfPagingAndSwappingEvents": None,
            "diskTraffic": None
        })

        return data

    async def save_data():
        try:
            while True:
                # TODO: Use utils.local_timestamp() and this will be used once v1.3 debian package release
                # https://github.com/foglamp/FogLAMP/commit/66dead988152cd3724eba6b4288b630cfa6a2e30
                time_stamp = str(datetime.datetime.now(datetime.timezone.utc).astimezone())  # utils.local_timestamp()
                data = {
                    'asset': 'systeminfo',
                    'timestamp': time_stamp,
                    'key': str(uuid.uuid4()),
                    'readings': {
                        handle['assetCode']['value']: get_system_info()
                    }
                }

                await Ingest.add_readings(asset='{}'.format(data['asset']),
                                          timestamp=data['timestamp'], key=data['key'],
                                          readings=data['readings'])

                await asyncio.sleep(int(handle['sleepInterval']['value']))

        except asyncio.CancelledError:
            pass

        except (Exception, RuntimeError) as ex:
            _LOGGER.exception("System Info exception: {}".format(str(ex)))
            raise exceptions.DataRetrievalError(ex)

    asyncio.ensure_future(save_data())


def plugin_reconfigure(handle, new_config):
    pass


def _plugin_stop(handle):
    """ Stops the plugin doing required cleanup, to be called prior to the South device service being shut down.

    Args:
        handle: handle returned by the plugin initialisation call
    Returns:
        None
    """
    _LOGGER.info('system info disconnected.')


def plugin_shutdown(handle):
    """ Shutdowns the plugin doing required cleanup, to be called prior to the South device service being shut down.

    Args:
        handle: handle returned by the plugin initialisation call
    Returns:
        plugin stop
    """
    _plugin_stop(handle)
    _LOGGER.info('system info plugin shut down.')
