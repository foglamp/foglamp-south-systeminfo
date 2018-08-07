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
    async def get_network_traffic(time_stamp):
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
            network_traffic = {
                    "IP": interface_ip,
                    "networkPacketsReceived": network_calc[interface_name]["bytes_recd_after"] -
                                              network_calc[interface_name]["bytes_recd_before"],
                    "networkPacketsSent": network_calc[interface_name]["bytes_sent_after"] -
                                          network_calc[interface_name]["bytes_sent_before"],
            }
            await insert_reading("networkTraffic/"+interface_name, time_stamp, network_traffic)

        return network_traffic

    def get_subprocess_result(cmd):
        a = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outs, errs = a.communicate()
        if a.returncode != 0:
            raise OSError(
                'Error in executing command "{}". Error: {}'.format(cmd, errs.decode('utf-8').replace('\n', '')))
        d = [b for b in outs.decode('utf-8').split('\n') if b != '']
        return d

    async def get_system_info(time_stamp):
        data = {}

        # Get hostname
        hostname = get_subprocess_result(cmd='hostname')[0]
        await insert_reading("hostName", time_stamp, {"hostName": hostname})

        # Get platform info
        platform = get_subprocess_result(cmd='cat /proc/version')[0]
        await insert_reading("platform", time_stamp, {"platform": platform})

        # Get uptime, users
        uptime = get_subprocess_result(cmd='uptime')[0]
        uptime_info = uptime.split(',')[0]
        uptime_user_start = uptime.find('user') - 3
        await insert_reading("uptime", time_stamp, {"uptime": uptime_info.strip()})
        await insert_reading("users", time_stamp, {"users": int(uptime[uptime_user_start:][:3].strip())})

        # Get load average
        line_load = get_subprocess_result(cmd='cat /proc/loadavg')[0].split()
        load_average = {
                "loadAverageOverLast1min": float(line_load[0].strip()),
                "loadAverageOverLast5mins": float(line_load[1].strip()),
                "loadAverageOverLast15mins": float(line_load[2].strip())
        }
        await insert_reading("loadAverage", time_stamp, load_average)

        # Get processes count
        tasks_states = get_subprocess_result(cmd="ps -e -o state")
        processes = {
                "running": tasks_states.count("R"),
                "sleeping": tasks_states.count("S") + tasks_states.count("D"),
                "stopped": tasks_states.count("T") + tasks_states.count("t"),
                "paging": tasks_states.count("W"),
                "dead": tasks_states.count("X"),
                "zombie": tasks_states.count("Z")
            }
        await insert_reading("processes", time_stamp, processes)

        # Get CPU usage
        c3_mpstat = get_subprocess_result(cmd='mpstat')
        cpu_usage = {}
        col_heads = c3_mpstat[1].split()  # first line is the header row
        for line in c3_mpstat[2:]:  # second line onwards are value rows
            col_vals = line.split()
            cpu_usage.update({
                    col_heads[3]: float(col_vals[3].strip()),
                    col_heads[4]: float(col_vals[4].strip()),
                    col_heads[5]: float(col_vals[5].strip()),
                    col_heads[6]: float(col_vals[6].strip()),
                    col_heads[7]: float(col_vals[7].strip()),
                    col_heads[8]: float(col_vals[8].strip()),
                    col_heads[9]: float(col_vals[9].strip()),
                    col_heads[10]: float(col_vals[10].strip()),
                    col_heads[11]: float(col_vals[11].strip()),
                    col_heads[12]: float(col_vals[12].strip()),
            })
            await insert_reading("cpuUsage/"+col_vals[2], time_stamp, cpu_usage)

        # Get memory info
        c3_mem = get_subprocess_result(cmd='cat /proc/meminfo')
        mem_info = {}
        for line in c3_mem:
            line_a = line.split(':')
            line_vals = line_a[1].split()
            k = "{} {}".format(line_a[0], 'KB' if len(line_vals) > 1 else '').strip()
            v = int(line_vals[0].strip())
            mem_info.update({k : v})
        await insert_reading("memInfo", time_stamp, mem_info)

        # Get disk usage
        c3 = get_subprocess_result(cmd='df')
        col_heads = c3[0].split()  # first line is the header row
        for line in c3[1:]:  # second line onwards are value rows
            col_vals = line.split()
            disk_usage = {}
            disk_usage.update({
                    col_heads[1]: int(col_vals[1]),
                    col_heads[2]: int(col_vals[2]),
                    col_heads[3]: int(col_vals[3]),
                    col_heads[4]: int(col_vals[4].replace("%", "").strip()),
                    col_heads[5]: col_vals[5],
            })
            await insert_reading("diskUsage/"+col_vals[0], time_stamp, disk_usage)

        # Get Network and other info
        await get_network_traffic(time_stamp)

        # Paging and Swapping
        c6 = get_subprocess_result(cmd='vmstat -s')
        paging_swapping = {}
        for line in c6:
            if 'page' in line:
                a_line = line.strip().split("pages")
                paging_swapping.update({"pages{}".format(a_line[1]).replace(' ', ''): int(a_line[0])})
        await insert_reading("pagingAndSwappingEvents", time_stamp, paging_swapping)

        # Disk Traffic
        c4 = get_subprocess_result(cmd='iostat -xd 2 1')
        c5 = [i for i in c4[1:] if i.strip() != '']  # Remove all empty lines
        col_heads = c5[0].split()  # first line is header row
        for line in c5[1:]:  # second line onwards are value rows
            col_vals = line.split()
            disk_traffic = {}
            disk_traffic.update({
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
            })
            await insert_reading("diskTraffic/"+col_vals[0], time_stamp, disk_traffic)

        return data

    async def insert_reading(asset, time_stamp, data):
        data = {
            'asset': "{}/{}".format(handle['assetCode']['value'], asset),
            'timestamp': time_stamp,
            'key': str(uuid.uuid4()),
            'readings': data
        }
        await Ingest.add_readings(asset='{}'.format(data['asset']),
                                  timestamp=data['timestamp'], key=data['key'],
                                  readings=data['readings'])
    async def save_data():
        try:
            while True:
                time_stamp = utils.local_timestamp()
                await get_system_info(time_stamp)
                await asyncio.sleep(int(handle['sleepInterval']['value']))
        except OSError as ex:
            _LOGGER.exception("Encountered System Error: {}".format(str(ex)))
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
