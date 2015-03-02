# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#

import base64
import time
import multiprocessing
import psutil
from connection_manager import CommunicationThreadingManager
from load_config import LoadConfig
import logging
import os
import json
import logging.config
logging.getLogger("sleekxmpp").setLevel(60)  # Disable sleekxmpp logging

def setup_logging(default_path=r'resource\logging.json', default_level=logging.INFO):
    """Setup logging configuration"""
    if not os.path.isdir('logging'):
        os.mkdir('logging')
    path = default_path
    if os.path.exists(path):
        with open(path, 'rt') as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)

setup_logging()
logger = logging.getLogger(__name__)
logger.info('Server started')
options = LoadConfig().get_options()

count = 0
for proc in psutil.process_iter():
    try:
        if proc.name() == "NL_chat_server.exe":
            count += 1
            if count > 1:
                logger.info('Server already running, exiting...')
                input('A server is already running on this computer.\nPress enter key to exit.')
                raise SystemExit
    except psutil.AccessDenied:
        pass
#options['modules_without_chat_states'].append('zoho')
incoming_queue = multiprocessing.Queue()  # Keeping these queues around in case a gui is needed.
outgoing_queue = multiprocessing.Queue()
root = ''
multiprocessing.freeze_support()
x = CommunicationThreadingManager(root, incoming_queue, outgoing_queue, options)

while True:
    if input('\nPress Q at any time to exit:\n') in ('q', 'Q'):
        print('Exiting')
        x.kill_all()
        break
raise SystemExit