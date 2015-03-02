# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#

import configparser
import zipfile
import logging
logger = logging.getLogger(__name__)

class ConfigLoader(object):
    def __init__(self, config_string):
        self.accounts = {}
        self.logging_info = {}
        self.messages = {}
        self.misc = {}
        self.config = configparser.ConfigParser()
        self.config.read_string(config_string)
        for section in self.config.sections():
            if section.split(' ')[0] == 'account':
                try:
                    self.accounts.update({
                        section.split(' ')[1]: {
                            'username': self.config.get(section, 'username'),
                            'password': self.config.get(section, 'password')
                        }
                    })
                except:
                    logger.critical("Error in config.ini '%s' account", section)
            elif section == 'logging email':
                for pair in self.config.items(section):
                    self.logging_info.update({pair[0]: pair[1]})
            elif section == 'messages':
                for pair in self.config.items(section):
                    self.messages.update({pair[0]: bytes(pair[1], encoding='utf').decode("unicode_escape")})
            elif section == 'misc':
                for pair in self.config.items(section):
                    if pair[0] in ('modules_without_chat_states'):
                        self.misc.update({pair[0]: [pair[1]]})
                    else:
                        self.misc.update({pair[0]: pair[1]})

    def get_accounts(self):
        return self.accounts

    def get_logging_info(self):
        return self.logging_info

    def get_messages(self):
        return self.messages

    def get_misc(self):
        return self.misc


class LoadConfig(object):
    def __init__(self, options={}):
        settings_zip_object = None
        try:
            settings_zip_object = zipfile.ZipFile('resource/settings.zip')
            run = True
        except:  # TODO Narrow exception
            run = False
        if run:
            namelist = settings_zip_object.namelist()
            for name in namelist:
                if name == 'settings.ini':
                    config_string = settings_zip_object.open(name, mode='r', pwd=bytes('thomas', encoding='utf-8')).read().decode(encoding='utf-8')
                    c = ConfigLoader(config_string)
                    options.update({'messages': c.get_messages(), 'logging':c.get_logging_info(), 'accounts': c.get_accounts()})
                    options.update(c.get_misc())
                elif name == 'rsakey.pem':
                    key = settings_zip_object.open(name, mode='r', pwd=bytes('thomas', encoding='utf-8')).read().decode(encoding='utf-8')
                    options.update({'alice_private_key': key})
        self.options = options

    def get_options(self):
        return self.options




if __name__ == '__main__':
    c = LoadConfig()
    print(c.get_options())