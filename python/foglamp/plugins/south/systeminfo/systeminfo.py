# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END

""" Module for System Info async plugin """

import time
import asyncio
import copy
import uuid
import sys
import subprocess
import socket
import fcntl
import struct
import array

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
    },
    'networkSnifferPeriod': {
        'description': 'Interval, in seconds, for which network traffic is measured',
        'type': 'integer',
        'default': "2"
    }
}
_LOGGER = logger.setup(__name__, level=logger.logging.INFO)


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
        def get_all_network_interfaces():
            """ Get all network interfaces in a list of tuple interface name, interface ip.
                This code was create with help from http://code.activestate.com/recipes/439093/#c8
            """
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

        network_interfaces = get_all_network_interfaces()
        network_traffic = {}
        network_calc = {}
        for interface_name, interface_ip in network_interfaces:
            network_calc[interface_name] = {}
            network_calc[interface_name]["bytes_recd_before"] = interface_transmission(interface_name, "rx")
            network_calc[interface_name]["bytes_sent_before"] = interface_transmission(interface_name, "tx")

        timestep = int(handle['networkSnifferPeriod']['value'])  # seconds
        time.sleep(timestep)

        for interface_name, interface_ip in network_interfaces:
            network_calc[interface_name]["bytes_recd_after"] = interface_transmission(interface_name, "rx")
            network_calc[interface_name]["bytes_sent_after"] = interface_transmission(interface_name, "tx")

        for interface_name, interface_ip in network_interfaces:
            network_traffic.update({
                interface_name: {
                    "IP": interface_ip,
                    "networkPacketsReceived": network_calc[interface_name]["bytes_recd_after"] -
                                              network_calc[interface_name]["bytes_recd_before"],
                    "networkPacketsSent": network_calc[interface_name]["bytes_sent_after"] -
                                          network_calc[interface_name]["bytes_sent_before"],
                }
            })
        return network_traffic

    def get_subprocess_result(cmd):
        a = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.readlines()
        # Since "a" contains return value in bytes, convert it to string
        c = [str(b, 'utf-8').replace('\n', '') for b in a]
        return c

    def get_system_info():
        data = {}
        hostname = get_subprocess_result(cmd='hostname')[0]
        data.update({
            "hostName": hostname
        })

        # Generic search a list for an item starting with the given string. Return item stripped of
        # the search string if success else return None
        list_search = lambda x, xlist: next((y[len(x):] for y in xlist if y.startswith(x)), None)

        # Get uptime, load, tasks, cpu usage, memory, swap memory information
        c2 = get_subprocess_result(cmd='top -n1 -b')[:5]
        top_line = list_search("top - ", c2).split(',')
        load_average = {
                "uptime": top_line[0]+', '+top_line[1],
                "user(s)": int((top_line[2].strip().split())[0]),
                "loadAverageOverLast1min": float((top_line[3])[-5:].strip()),
                "loadAverageOverLast5min": float(top_line[4]),
                "loadAverageOverLast15min": float(top_line[5])
        }

        tasks_line = list_search("Tasks: ", c2).split(',')
        tasks = {}
        for task in tasks_line:
            t_item = task.split()
            tasks.update({t_item[1]: int(t_item[0])})

        cpus_line = list_search("%Cpu(s): ", c2).split(',')
        cpus = {}
        for cpu in cpus_line:
            c_item = cpu.split()
            cpus.update({c_item[1]: float(c_item[0])})

        memories_line = list_search("KiB Mem : ", c2).split(',')
        memories = {}
        for memory in memories_line:
            m_item = memory.split()
            memories.update({m_item[1]: int(m_item[0])})

        swaps_line = list_search("KiB Swap: ", c2).replace('.', ',').split(',')
        swaps = {}
        for swap in swaps_line:
            s_item = swap.split()
            swaps.update({s_item[1]: int(s_item[0])})

        data.update({
            "loadAverage": load_average,
            "tasksRunning": tasks,
            "cpuUsage": cpus,
            "memoryUsage(KB)": memories,
            "swapMemory(KB)": swaps
        })

        # Get disk usage
        c3 = get_subprocess_result(cmd='df')
        disk_usage = {}
        col_heads = c3[0].split()
        for line in c3[1:]:
            col_vals = line.split()
            disk_usage.update({
                col_vals[0]: {
                    col_heads[1]: int(col_vals[1]),
                    col_heads[2]: int(col_vals[2]),
                    col_heads[3]: int(col_vals[3]),
                    col_heads[4]: col_vals[4],
                    col_heads[5]: col_vals[5],
                }
            })
        data.update({
            "diskUsage": disk_usage
        })

        # Get number of processes
        no_of_processes = get_subprocess_result(cmd='ps -eaf | wc -l')[0]
        data.update({
            "processesRunning": int(no_of_processes)
        })

        # Get Network and other info
        data.update({
            "networkTraffic": get_network_traffic()
        })

        # Paging and Swapping
        c6 = get_subprocess_result(cmd='vmstat -s')
        paging_swapping = {}
        for line in c6:
            if 'page' in line:
                a_line = line.strip().split("pages")
                paging_swapping.update({"pages{}".format(a_line[1]).replace(' ', ''): int(a_line[0])})
        data.update({
            "pagingAndSwappingEvents": paging_swapping
        })

        # Disk Traffic
        c4 = get_subprocess_result(cmd='iostat -xd 2 1')
        c5 = [i for i in c4[1:] if i.strip() != '']  # Remove all empty lines
        disk_traffic = {}
        col_heads = c5[0].split()
        for line in c5[1:]:
            col_vals = line.split()
            disk_traffic.update({
                col_vals[0]: {
                    col_heads[1]: float(col_vals[1]),
                    col_heads[2]: float(col_vals[2]),
                    col_heads[3]: float(col_vals[3]),
                    col_heads[4]: float(col_vals[4]),
                    col_heads[5]: float(col_vals[5]),
                    col_heads[6]: float(col_vals[6]),
                    col_heads[7]: float(col_vals[7]),
                    col_heads[8]: float(col_vals[8]),
                    col_heads[9]: float(col_vals[9]),
                    col_heads[10]: float(col_vals[10]),
                    col_heads[11]: float(col_vals[11]),
                    col_heads[12]: float(col_vals[12]),
                    col_heads[13]: float(col_vals[13])
                }
            })
        data.update({
            "platform": c4[0],  # Linux 4.15.0-29-generic (asinha-ThinkPad-E450) 	Monday 06 August 2018 	_x86_64_	(4 CPU)
            "diskTraffic": disk_traffic
        })
        return data

    async def save_data():
        try:
            while True:
                time_stamp = utils.local_timestamp()
                data = {
                    'asset': handle['assetCode']['value'],
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
    if 'sleepInterval' in diff or 'assetCode' in diff or 'networkSnifferPeriod' in diff:
        new_handle = plugin_init(new_config)
        new_handle['restart'] = 'yes'
        _LOGGER.info("Restarting systeminfo plugin due to change in configuration keys [{}]".format(', '.join(diff)))
    else:
        new_handle = copy.deepcopy(new_config)
        new_handle['restart'] = 'no'
    return new_handle


def plugin_shutdown(handle):
    """ Shutdowns the plugin doing required cleanup, to be called prior to the South device service being shut down.

    Args:
        handle: handle returned by the plugin initialisation call
    Returns:
    """
    _LOGGER.info('system info plugin shut down.')
