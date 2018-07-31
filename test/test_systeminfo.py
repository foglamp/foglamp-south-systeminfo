# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END

from unittest.mock import patch
import pytest

from python.foglamp.plugins.south.systeminfo import systeminfo

__author__ = "Amarendra K Sinha"
__copyright__ = "Copyright (c) 2018 Dianomic Systems"
__license__ = "Apache 2.0"
__version__ = "${VERSION}"

config = systeminfo._DEFAULT_CONFIG

def test_plugin_contract():
    # Evaluates if the plugin has all the required methods
    assert callable(getattr(systeminfo, 'plugin_info'))
    assert callable(getattr(systeminfo, 'plugin_init'))
    assert callable(getattr(systeminfo, 'plugin_start'))
    assert callable(getattr(systeminfo, 'plugin_shutdown'))
    assert callable(getattr(systeminfo, 'plugin_reconfigure'))


def test_plugin_info():
    assert systeminfo.plugin_info() == {
        'name': 'System Info plugin',
        'version': '1.0',
        'mode': 'async',
        'type': 'south',
        'interface': '1.0',
        'config': config
    }


def test_plugin_init():
    assert systeminfo.plugin_init(config) == config


@pytest.mark.skip(reason="To be implemented")
def test_plugin_start():
    pass


@pytest.mark.skip(reason="To be implemented")
def test_plugin_reconfigure():
    pass


def test__plugin_stop():
    with patch.object(systeminfo._LOGGER, 'info') as patch_logger_info:
        systeminfo._plugin_stop(config)
    patch_logger_info.assert_called_once_with('systeminfo disconnected.')


def test_plugin_shutdown():
    with patch.object(systeminfo, "_plugin_stop", return_value="") as patch_stop:
        with patch.object(systeminfo._LOGGER, 'info') as patch_logger_info:
            systeminfo.plugin_shutdown(config)
        patch_logger_info.assert_called_once_with('systeminfo plugin shut down.')
    patch_stop.assert_called_once_with(config)
