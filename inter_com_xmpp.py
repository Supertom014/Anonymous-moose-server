# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#
# Based on the sleekxmpp echotest


import sleekxmpp
import json
import logging
logger = logging.getLogger(__name__)


class InterComXMPP(sleekxmpp.ClientXMPP):
    def __init__(self, jid, password, incoming_queue):
        sleekxmpp.ClientXMPP.__init__(self, jid, password)
        self.jid = jid
        self.incoming_queue = incoming_queue
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.process_message)
        self.add_event_handler("session_end", lambda: self.status_report("session_end"))
        self.add_event_handler("disconnected", lambda: self.status_report("disconnected"))
        self.add_event_handler("connected", lambda: self.status_report("connected"))

        self.register_plugin('xep_0030')  # Service Discovery
        self.register_plugin('xep_0004')  # Data Forms
        self.register_plugin('xep_0060')  # PubSub
        self.register_plugin('xep_0199')  # XMPP Ping
        self.register_plugin('xep_0085')  # Chat State Notifications
        
    def start(self, event):
        self.send_presence()
        self.get_roster(block=True)

        # x = []
        # print(self.client_roster)
        # for client in self.client_roster:
        #    x.append(client)
        # self.incoming_queue.put(x)
        self.status_report("session_start")

    
    def status_report(self, arg):
        logger.info('intercom connection status changed: %s', arg)
        if arg == 'disconnected' or arg == 'session_end':
            if self.connect():
                self.process()

    def process_message(self, msg):
        logger.debug('inter_com from: %s', msg['from'])
        if msg['type'] in ('chat', 'normal'):
            try:
                self.incoming_queue.put(json.loads(msg['body']))
            except:
                logger.info('inter_com invalid message received')

    def reply_message(self, text, username, uuid):
        msg = self.make_message(mto=username+'/'+uuid, mbody=text, mtype='chat', mfrom=self.jid)
        msg.send()
