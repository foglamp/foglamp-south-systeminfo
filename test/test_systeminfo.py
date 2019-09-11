# -*- coding: utf-8 -*-

# FLEDGE_BEGIN
# See: http://fledge.readthedocs.io/
# FLEDGE_END

from unittest.mock import patch
import pytest

from python.fledge.plugins.south.systeminfo import systeminfo

__author__ = "Amarendra K Sinha"
__copyright__ = "Copyright (c) 2018 Dianomic Systems"
__license__ = "Apache 2.0"
__version__ = "${VERSION}"

config = systeminfo._DEFAULT_CONFIG

def test_plugin_contract():
    # Evaluates if the plugin has all the required methods
    assert callable(getattr(systeminfo, 'plugin_info'))
    assert callable(getattr(systeminfo, 'plugin_init'))
    assert callable(getattr(systeminfo, 'plugin_poll'))
    assert callable(getattr(systeminfo, 'plugin_shutdown'))
    assert callable(getattr(systeminfo, 'plugin_reconfigure'))


def test_plugin_info():
    assert systeminfo.plugin_info() == {
        'name': 'System Info plugin',
        'version': '1.5.0',
        'mode': 'poll',
        'type': 'south',
        'interface': '1.0',
        'config': config
    }


def test_plugin_init():
    assert systeminfo.plugin_init(config) == config


@pytest.mark.skip(reason="To be implemented")
def test_plugin_poll():
    pass


@pytest.mark.skip(reason="To be implemented")
def test_plugin_reconfigure():
    pass


def test_plugin_shutdown():
    with patch.object(systeminfo._LOGGER, 'info') as patch_logger_info:
        systeminfo.plugin_shutdown(config)
    patch_logger_info.assert_called_once_with('system info plugin shut down.')
