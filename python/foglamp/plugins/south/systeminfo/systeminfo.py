# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END

""" Module for System Info async plugin """

import time
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
import socket
import fcntl
import struct
import array
import sys

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
    def get_network_traffic():
        def all_interfaces():
            """http: // code.activestate.com / recipes / 439093 /  # c8"""
            is_64bits = sys.maxsize > 2 ** 32
            struct_size = 40 if is_64bits else 32
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            max_possible = 8  # initial value
            while True:
                _bytes = max_possible * struct_size
                names = array.array('B')
                for i in range(0, _bytes):
                    names.append(0)
                outbytes = struct.unpack('iL', fcntl.ioctl(
                    s.fileno(),
                    0x8912,  # SIOCGIFCONF
                    struct.pack('iL', _bytes, names.buffer_info()[0])
                ))[0]
                if outbytes == _bytes:
                    max_possible *= 2
                else:
                    break
            namestr = names.tostring()
            ifaces = []
            for i in range(0, outbytes, struct_size):
                iface_name = bytes.decode(namestr[i:i + 16]).split('\0', 1)[0]
                iface_addr = socket.inet_ntoa(namestr[i + 20:i + 24])
                ifaces.append((iface_name, iface_addr))

            return ifaces

        def interface_transmission(dev, direction):
            """Return the transmisson rate of a interface under linux
            https://stackoverflow.com/a/41448191
            """
            path = "/sys/class/net/{}/statistics/{}_bytes".format(dev, direction)
            f = open(path, "r")
            bytes_collected = int(f.read())
            f.close()
            return bytes_collected

        network_interfaces = all_interfaces()
        network_traffic = []
        network_calc = {}
        for interface_name, interface_ip in network_interfaces:
            network_calc[interface_name] = {}
            network_calc[interface_name]["bytes_recd_before"] = interface_transmission(interface_name, "rx")
            network_calc[interface_name]["bytes_sent_before"] = interface_transmission(interface_name, "tx")

        timestep = int(handle['sleepInterval']['value'])  # seconds
        time.sleep(timestep)

        for interface_name, interface_ip in network_interfaces:
            network_calc[interface_name]["bytes_recd_after"] = interface_transmission(interface_name, "rx")
            network_calc[interface_name]["bytes_sent_after"] = interface_transmission(interface_name, "tx")

        for interface_name, interface_ip in network_interfaces:
            network_traffic.append({
                interface_name: {
                    "IP": interface_ip,
                    "numberOfNetworkPacketsReceived": network_calc[interface_name]["bytes_recd_after"] -
                                                      network_calc[interface_name]["bytes_recd_before"],
                    "numberOfNetworkPacketsSent": network_calc[interface_name]["bytes_sent_after"] -
                                                  network_calc[interface_name]["bytes_sent_before"],
                }
            })
        return network_traffic

    def get_system_info():
        data = {}
        hostname = str(subprocess.Popen('hostname', shell=True, stdout=subprocess.PIPE).stdout.readlines()[0],
                       'utf-8').replace('\n', '')
        data.update({
            "hostname": hostname
        })

        load_average = subprocess.Popen('top -n1 -b', shell=True, stdout=subprocess.PIPE).stdout.readlines()[:5]
        c2 = [str(b, 'utf-8').replace('\n', '') for b in
              load_average]  # Since "load_average" contains return value in bytes, convert it to string
        data.update({
            "loadAverage": c2[0],
            "tasksRunning": c2[1],
            "cpuUsage": c2[2],
            "memoryUsage": c2[3],
            "swapMemory": c2[4]
        })

        df = subprocess.Popen('df', shell=True, stdout=subprocess.PIPE).stdout.readlines()
        c3 = [str(b, 'utf-8').replace('\n', '') for b in
              df]  # Since "df" contains return value in bytes, convert it to string
        disk_usage = []
        col_heads = c3[0].split()
        for line in c3[1:]:
            col_vals = line.split()
            disk_usage.append({
                col_heads[0]: col_vals[0],
                col_heads[1]: col_vals[1],
                col_heads[2]: col_vals[2],
                col_heads[3]: col_vals[3],
                col_heads[4]: col_vals[4],
                col_heads[5]: col_vals[5],
            })
        data.update({
            "diskUsage": disk_usage
        })

        no_of_processes = str(
            subprocess.Popen('ps -eaf | wc -l', shell=True, stdout=subprocess.PIPE).stdout.readlines()[0],
            'utf-8').replace('\n', '')
        data.update({
            "numberOProcessesRunning": no_of_processes
        })

        # Get Network and other info
        data.update({
            "networkTraffic": get_network_traffic()
        })

        # Paging and Swapping
        vmstat = subprocess.Popen('vmstat -s', shell=True, stdout=subprocess.PIPE).stdout.readlines()
        c6 = [str(b, 'utf-8').replace('\n', '') for b in
              vmstat]  # Since "vmstat" contains return value in bytes, convert it to string
        paging_swapping = []
        for line in c6:
            if 'page' in line:
                paging_swapping.append(line)
        data.update({
            "numberOfPagingAndSwappingEvents": paging_swapping
        })

        # Disk Traffic
        iostat = subprocess.Popen('iostat', shell=True, stdout=subprocess.PIPE).stdout.readlines()
        c4 = [str(b, 'utf-8').replace('\n', '') for b in
              iostat]  # Since "iostat" contains return value in bytes, convert it to string
        c5 = c4[5:]
        disk_traffic = []
        col_heads = c5[0].split()
        for line in c5[1:]:
            if line == '':
                continue
            col_vals = line.split()
            disk_traffic.append({
                col_heads[0]: col_vals[0],
                col_heads[1]: col_vals[1],
                col_heads[2]: col_vals[2],
                col_heads[3]: col_vals[3],
                col_heads[4]: col_vals[4],
                col_heads[5]: col_vals[5],
            })
        data.update({
            "platform": c4[0],
            "diskTraffic": disk_traffic
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

                # await asyncio.sleep(int(handle['sleepInterval']['value']))

        except asyncio.CancelledError:
            pass

        except (Exception, RuntimeError) as ex:
            _LOGGER.exception("System Info exception: {}".format(str(ex)))
            raise exceptions.DataRetrievalError(ex)

    asyncio.ensure_future(save_data())


def plugin_reconfigure(handle, new_config):
    """ Reconfigures the plugin

    it should be called when the configuration of the plugin is changed during the operation of the South device service;
    The new configuration category should be passed.

    Args:
        handle: handle returned by the plugin initialisation call
        new_config: JSON object representing the new configuration category for the category
    Returns:
        new_handle: new handle to be used in the future calls
    Raises:
    """
    _LOGGER.info("Old config for systeminfo plugin {} \n new config {}".format(handle, new_config))

    # Find diff between old config and new config
    diff = utils.get_diff(handle, new_config)

    # Plugin should re-initialize and restart if key configuration is changed
    if 'sleepInterval' in diff or 'assetCode' in diff:
        new_handle = plugin_init(new_config)
        new_handle['restart'] = 'yes'
        _LOGGER.info("Restarting systeminfo plugin due to change in configuration keys [{}]".format(', '.join(diff)))
    else:
        new_handle = copy.deepcopy(handle)
        new_handle['restart'] = 'no'
    return new_handle


def plugin_shutdown(handle):
    """ Shutdowns the plugin doing required cleanup, to be called prior to the South device service being shut down.

    Args:
        handle: handle returned by the plugin initialisation call
    Returns:
    """
    _LOGGER.info('system info plugin shut down.')
