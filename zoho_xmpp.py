# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#
# Based on the sleekxmpp echotest


import sleekxmpp
import logging
logger = logging.getLogger(__name__)

class ZohoXMPP(sleekxmpp.ClientXMPP):
    def __init__(self, jid, password, incoming_queue):
        sleekxmpp.ClientXMPP.__init__(self, jid, password)
        self.incoming_queue = incoming_queue
        self.register_plugin('xep_0004')  # Data Forms
        self.register_plugin('xep_0030')  # Service Discovery
        self.register_plugin('xep_0060')  # PubSub
        self.register_plugin('xep_0054')  # vcard-temp
        self.register_plugin('xep_0153')
        self.register_plugin('xep_0199', {'keepalive': True, 'frequency': 60})  # XMPP Ping
        self.register_plugin('xep_0085')  # Chat State Notifications

        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.process_message)
        self.add_event_handler("session_end", lambda: self.status_report("session_end"))
        self.add_event_handler("disconnected", lambda: self.status_report("disconnected"))
        self.add_event_handler("connected", lambda: self.status_report("connected"))
        self.add_event_handler('chatstate_composing', self._on_typing_message_cb)
        self.add_event_handler('chatstate_paused', self._on_typing_message_cb)
        self.add_event_handler('chatstate_active', self._on_typing_message_cb)
        self.add_event_handler('chatstate_inactive', self._on_typing_message_cb)
        self.add_event_handler('chatstate_gone', self._on_typing_message_cb)
        self.add_event_handler('failed_auth', self._on_failed_auth)

    def _on_typing_message_cb(self, message):
        self.incoming_queue.put({'type': 'chat_state', 'state': message['chat_state'], 'address': message['from']})
        logger.debug('User %s %s', str(message['from']), message['chat_state'])
        
    def start(self, event):
        self.send_presence()
        self.get_roster()
        self.status_report("session_start")

    def _on_failed_auth(self, direct):
        logger.warning("Authentication failed")
        self.status_report('failed_auth')

    def status_report(self, arg):
        self.incoming_queue.put(('Zoho', arg))
        if arg == 'disconnected' or arg == 'session_end':
            if self.connect(('zchat.zoho.com', 5222)):
                self.process()
            self.incoming_queue.put(('Zoho', 'Reconnecting...'))
    
    def process_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            try:
                self.incoming_queue.put(('msg', msg['from'], msg['body']))
            except:  # TODO Narrow exception
                print(__name__+' put msg queue fail')
            
    def reply_message(self, user_id, text, state='active'):
        # print(__name__, user_id, text)
        #self.send_message(mto=user_id, mbody=text, mtype='chat')
        from sleekxmpp.xmlstream import register_stanza_plugin
        from sleekxmpp.plugins.xep_0085.stanza import ChatState
        msg = self.make_message(mto=user_id, mbody=text, mtype='chat', mfrom=self.jid)
        register_stanza_plugin(msg, ChatState)
        msg['chat_state'] = state
        #print('Sending message with:',msg['chat_state'])
        msg.send()
                

if __name__ == '__main__':
    import multiprocessing
    q = multiprocessing.Queue()
    msglist = []
    lengthofmsgs = []
    jid = "nightline\\40lancaster.ac.uk@zoho.com"
    password = input('Password: ')
    XMPP_zoho = ZohoXMPP(jid, password, q)
    
    # Connect to the XMPP server and start processing XMPP stanzas.
    print("beginning zoho connect")
    if XMPP_zoho.connect(('zchat.zoho.com', 5222)):
        XMPP_zoho.process()
        print("Connected to Zoho")
    else:
        print("Unable to connect to Zoho")
    while True:
        try:
            print(q.get(timeout=1))
            print('test loop')
        except:  # TODO Narrow exception
            pass