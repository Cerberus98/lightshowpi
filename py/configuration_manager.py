#!/usr/bin/env python
#
# Licensed under the BSD license.  See full license in LICENSE file.
# http://www.lightshowpi.com/
#
# Author: Todd Giles (todd@lightshowpi.com)
#
# TODO(todd): Refactor the configuration manager into a configuration manager class (to remove
#             the extensive use of globals currently used).
# TODO(todd): Add a main and allow running configuration manager alone to view the current
#             configuration, and potentially edit it.


"""Configuration management for the lightshow.

Configuration files are all located in the <homedir>/config directory. This file contains tools to
manage these configuration files.
"""

import ConfigParser
import ast
import datetime
import fcntl
import logging
import os
import os.path
import sys
import warnings
import json

# The home directory and configuration directory for the application.
HOME_DIR = os.getenv("SYNCHRONIZED_LIGHTS_HOME")
if not HOME_DIR:
    print("Need to setup SYNCHRONIZED_LIGHTS_HOME environment variable, "
          "see readme")
    sys.exit()
CONFIG_DIR = HOME_DIR + '/config'
LOG_DIR = HOME_DIR + '/logs'

# Load configuration file, loads defaults from config directory, and then
# overrides from the same directory cfg file, then from /home/pi/.lights.cfg
# and then from ~/.lights.cfg (which will be the root's home).
CONFIG = ConfigParser.RawConfigParser(allow_no_value=True)
CONFIG.readfp(open(CONFIG_DIR + '/defaults.cfg'))
CONFIG.read([CONFIG_DIR + '/overrides.cfg', '/home/pi/.lights.cfg',
             os.path.expanduser('~/.lights.cfg')])


def _as_list(list_str, delimiter=','):
    """Return a list of items from a delimited string (after stripping whitespace).

    :param list_str: string to turn into a list
    :type list_str: str

    :param delimiter: split the string on this
    :type delimiter: str

    :return: string converted to a list
    :rtype: list
    """
    return [str.strip(item) for item in list_str.split(delimiter)]

# Retrieve hardware configuration
_HARDWARE_CONFIG = dict()


def hardware():
    """Retrieves the hardware configuration

    loading and parsing it from a file if necessary.

    :return: _HARDWARE_CONFIG
    :rtype: dict
    """

    global _HARDWARE_CONFIG
    if len(_HARDWARE_CONFIG) == 0:
        _HARDWARE_CONFIG = dict(CONFIG.items('hardware'))

        # Devices
        devices = dict()

        try:
            devices = json.loads(_HARDWARE_CONFIG['devices'])
        except Exception as error:
            logging.error("devices not defined or not in JSON format."
                          + str(error))

        _HARDWARE_CONFIG["devices"] = {d.lower(): v
                                       for d,v in devices.iteritems()}

    return _HARDWARE_CONFIG

# Retrieve light show configuration
_LIGHTSHOW_CONFIG = dict()


def lightshow():
    """Retrieve the lightshow configuration

    loading and parsing it from a file as necessary.

    :return: _LIGHTSHOW_CONFIG
    :rtype: dict
   """
    global _LIGHTSHOW_CONFIG
    if len(_LIGHTSHOW_CONFIG) == 0:
        _LIGHTSHOW_CONFIG = dict(CONFIG.items('lightshow'))

        _LIGHTSHOW_CONFIG['audio_in_channels'] = \
            CONFIG.getint('lightshow', 'audio_in_channels')
        _LIGHTSHOW_CONFIG['audio_in_sample_rate'] = \
            CONFIG.getint('lightshow', 'audio_in_sample_rate')

        # setup up preshow
        preshow = None
        if (CONFIG.get('lightshow',
                       'preshow_configuration') and
                not CONFIG.get('lightshow', 'preshow_script')):

            try:
                preshow = \
                    json.loads(_LIGHTSHOW_CONFIG['preshow_configuration'])
            except (ValueError, TypeError) as error:
                logging.error("Preshow_configuration not defined or not in "
                              "JSON format." + str(error))
        else:
            if os.path.isfile(_LIGHTSHOW_CONFIG['preshow_script']):
                preshow = _LIGHTSHOW_CONFIG['preshow_script']

        _LIGHTSHOW_CONFIG['preshow'] = preshow

        # setup postshow
        postshow = None
        if (CONFIG.get('lightshow',
                       'postshow_configuration') and
                not CONFIG.get('lightshow', 'postshow_script')):
            try:
                postshow = \
                    json.loads(_LIGHTSHOW_CONFIG['postshow_configuration'])
            except (ValueError, TypeError) as error:
                logging.error("Postshow_configuration not "
                              "defined or not in JSON format." + str(error))
        else:
            if os.path.isfile(_LIGHTSHOW_CONFIG['postshow_script']):
                postshow = _LIGHTSHOW_CONFIG['postshow_script']
        _LIGHTSHOW_CONFIG['postshow'] = postshow

    return _LIGHTSHOW_CONFIG


_SMS_CONFIG = dict()
_WHO_CAN = dict()


def sms():
    """Retrieves and validates sms configuration

    :return: _SMS_CONFIG
    :rtype: dict
    """
    global _SMS_CONFIG, _WHO_CAN
    if len(_SMS_CONFIG) == 0:
        _SMS_CONFIG = dict(CONFIG.items('sms'))
        _WHO_CAN = dict()
        _WHO_CAN['all'] = set()

        # Commands
        _SMS_CONFIG['commands'] = _as_list(_SMS_CONFIG['commands'])

        for cmd in _SMS_CONFIG['commands']:
            try:
                _SMS_CONFIG[cmd + '_aliases'] = _as_list(_SMS_CONFIG[cmd + '_aliases'])
            except KeyError:
                _SMS_CONFIG[cmd + '_aliases'] = []

            _WHO_CAN[cmd] = set()

        # Groups / Permissions
        _SMS_CONFIG['groups'] = _as_list(_SMS_CONFIG['groups'])
        _SMS_CONFIG['throttled_groups'] = dict()
        
        for group in _SMS_CONFIG['groups']:
            try:
                _SMS_CONFIG[group + '_users'] = _as_list(_SMS_CONFIG[group
                                                                     + '_users'])
            except KeyError:
                _SMS_CONFIG[group + '_users'] = []
                
            try:
                _SMS_CONFIG[group + '_commands'] = _as_list(_SMS_CONFIG[group
                                                                        + '_commands'])
            except KeyError:
                _SMS_CONFIG[group + '_commands'] = []
                
            for cmd in _SMS_CONFIG[group + '_commands']:
                for user in _SMS_CONFIG[group + '_users']:
                    _WHO_CAN[cmd].add(user)

            # Throttle
            try:
                throttled_group_definitions = _as_list(_SMS_CONFIG[group
                                                                   + '_throttle'])
                throttled_group = dict()
                
                for definition in throttled_group_definitions:
                    definition = definition.split(':')
                    
                    if len(definition) != 2:
                        warnings.warn(group + "_throttle definitions should "
                                              "be in the form "
                                      + "[command]:<limit> - "
                                      + ":".join(definition))
                        continue
                    
                    throttle_command = definition[0]
                    throttle_limit = int(definition[1])
                    throttled_group[throttle_command] = throttle_limit
                    
                _SMS_CONFIG['throttled_groups'][group] = throttled_group
            except KeyError: 
                warnings.warn("Throttle definition either does not exist or "
                              "is configured incorrectly for group: " + group)

        # Blacklist
        _SMS_CONFIG['blacklist'] = _as_list(_SMS_CONFIG['blacklist'])

    return _SMS_CONFIG


_SONG_LIST = []


def songs():
    """Retrieve the song list

    :return: a list of songs
    :rtype: list
    """
    if len(_SONG_LIST) == 0:
        pass  # TODO(todd): Load playlist if not already loaded, also refactor
        #                   the code that loads the playlist in check_sms and
        #                   synchronzied_lights such that we don't duplicate it
        #                   there.
    return _SONG_LIST


def set_songs(song_list):
    """Sets the list of songs

    if loaded elsewhere, as is done by check_sms for example

    :param song_list: a list of songs
    :type song_list: list
    """
    global _SONG_LIST
    _SONG_LIST = song_list


##############################
# Application State Utilities
##############################

# Load application state configuration file from CONFIG directory.
STATE = ConfigParser.RawConfigParser()
STATE_SECTION = 'do_not_modify'
STATE_FILENAME = CONFIG_DIR + '/state.cfg'

# Ensure state file has been created
if not os.path.isfile(STATE_FILENAME):
    open(STATE_FILENAME, 'a').close()


def load_state():
    """Force the state to be reloaded form disk."""
    with open(STATE_FILENAME) as state_fp:
        fcntl.lockf(state_fp, fcntl.LOCK_SH)
        STATE.readfp(state_fp, STATE_FILENAME)
        fcntl.lockf(state_fp, fcntl.LOCK_UN)


load_state()  # Do an initial load


def get_state(name, default=''):
    """
    Get application state

    Return the value of a specific application state variable, or the specified
    default if not able to load it from the state file

    :param name: option to load from state file
    :type name: str

    :param default: return if not able to load option from state file
    :type default: str

    :return: the current state
    :rtype: str
    """
    try:
        return STATE.get(STATE_SECTION, name)
    except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
        return default


def update_state(name, value):
    """Update the application state (name / value pair)

    :param name: option name to update
    :type name: str

    :param value: value to update option name to
    :type value: str
    """
    value = str(value)
    logging.info('Updating application state {%s: %s}', name, value)

    try:
        STATE.add_section(STATE_SECTION)
    except ConfigParser.DuplicateSectionError:
        pass  # Ok, it's already there

    STATE.set(STATE_SECTION, name, value)

    with open(STATE_FILENAME, 'wb') as state_fp:
        fcntl.lockf(state_fp, fcntl.LOCK_EX)
        STATE.write(state_fp)
        fcntl.lockf(state_fp, fcntl.LOCK_UN)


def has_permission(user, cmd):
    """Returns True if a user has permission to execute the given command
    :param user: the user trying to execute the command
    :type user: str

    :param cmd: the command at question
    :type cmd: str

    :return: user has permission
    :rtype: bool
    """
    blacklisted = user in sms()['blacklist']

    return not blacklisted and (user in _WHO_CAN['all']
                                or 'all' in _WHO_CAN[cmd]
                                or user in _WHO_CAN[cmd])


def is_throttle_exceeded(cmd, user):
    """Returns True if the throttle has been exceeded and False otherwise

    :param cmd: the command at question
    :type cmd: str

    :param user: the user trying to execute the command
    :type user: str

    :return: has throttle been exceeded
    :rtype: bool
    """
    # Load throttle STATE
    load_state()
    throttle_state = ast.literal_eval(get_state('throttle', '{}'))
    process_command_flag = -1

    # Analyze throttle timing
    current_timestamp = datetime.datetime.now()
    throttle_timelimit = _SMS_CONFIG['throttle_time_limit_seconds']
    throttle_starttime = datetime.datetime.strptime(
        throttle_state['throttle_timestamp_start'], '%Y-%m-%d %H:%M:%S.%f') \
        if "throttle_timestamp_start" in throttle_state else current_timestamp
    throttle_stoptime = \
        throttle_starttime + datetime.timedelta(seconds=int(throttle_timelimit))

    # Compare times and see if we need to reset the throttle STATE
    if (current_timestamp == throttle_starttime) or \
            (throttle_stoptime < current_timestamp):
        # There is no time recorded or the time has
        # expired reset the throttle STATE
        throttle_state = dict()
        throttle_state['throttle_timestamp_start'] = str(current_timestamp)
        update_state('throttle', str(throttle_state))

    # ANALYZE THE THROTTLE COMMANDS AND LIMITS
    all_throttle_limit = -1
    cmd_throttle_limit = -1

    # Check to see what group belongs to starting with the first group declared
    throttled_group = None
    for group in _SMS_CONFIG['groups']:
        userlist = _SMS_CONFIG[group + "_users"]

        if user in userlist:
            # The user belongs to this group, check if there
            # are any throttle definitions
            if group in _SMS_CONFIG['throttled_groups']:
                # The group has throttle commands defined,
                # now check if the command is defined
                throttled_commands = _SMS_CONFIG['throttled_groups'][group]

                # Check if all command exists
                if "all" in throttled_commands:
                    all_throttle_limit = int(throttled_commands['all'])

                # Check if the command passed is defined
                if cmd in throttled_commands:
                    cmd_throttle_limit = int(throttled_commands[cmd])

                # A throttle definition was found,
                # we no longer need to check anymore groups
                if all_throttle_limit != -1 or cmd_throttle_limit != -1:
                    throttled_group = group
                    break

    # Process the throttle settings that were found for the throttled group
    if not throttled_group:
        # No throttle limits were found for any group
        return False
    else:
        # Throttle limits were found, check them against throttle STATE limits
        if throttled_group in throttle_state:
            group_throttle_state = throttle_state[throttled_group]
        else:
            group_throttle_state = dict()
            
        if cmd in group_throttle_state:
            group_throttle_cmd_limit = int(group_throttle_state[cmd]) 
        else:
            group_throttle_cmd_limit = 0

    # Check to see if we need to apply "all"
    if all_throttle_limit != -1:
        groupthrottlealllimit = \
            int(group_throttle_state['all']) if 'all' in group_throttle_state else 0

        # Check if "all" throttle limit has been reached
        if groupthrottlealllimit < all_throttle_limit:
            # Not Reached, bump throttle and record
            groupthrottlealllimit += 1
            group_throttle_state['all'] = groupthrottlealllimit
            throttle_state[throttled_group] = group_throttle_state
            process_command_flag = False
        else:
            # "all" throttle has been reached we
            # dont want to process anything else
            return True

    # Check to see if we need to apply "cmd"
    if cmd_throttle_limit != -1:
        if group_throttle_cmd_limit < cmd_throttle_limit:
            # Not reached, bump throttle
            group_throttle_cmd_limit += 1
            group_throttle_state[cmd] = group_throttle_cmd_limit
            throttle_state[throttled_group] = group_throttle_state
            process_command_flag = False

    # Record the updatedthrottle STATE and return
    update_state('throttle', throttle_state)

    return process_command_flag
