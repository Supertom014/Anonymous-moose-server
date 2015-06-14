# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#


import json
from admin_debug_interface import AdminDebugInterface
from threading import Thread, Lock
from timeout_thread import TimeoutThreadDisableQueue, MultiTimeoutThreadQueue
import multiprocessing
from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA
import time
import base64
import logging
import html
logger = logging.getLogger(__name__)


class Dispatch(Thread):
    def __init__(self, kill_event, root, options, incoming_queue, outgoing_queue,
                 fb_queue_in, fb_queue_out, zoho_queue_in, zoho_queue_out, inter_com_queue_in, inter_com_queue_out):
        super().__init__()
        self.kill_event = kill_event
        self.root = root
        self.options = options
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self.fb_queue_in = fb_queue_in
        self.fb_queue_out = fb_queue_out
        self.zoho_queue_in = zoho_queue_in
        self.zoho_queue_out = zoho_queue_out
        self.inter_com_queue_in = inter_com_queue_in
        self.inter_com_queue_out = inter_com_queue_out
        self.service_status = []  # [{'name': service, 'status': status}, ...]
        self.address_client_list = []  # [{'service': 'asdf', 'address': 'asdf@asdf.net', 'UUID': 'uuid'}, ...]
        self.modules_without_chat_states = options['modules_without_chat_states']

        # {'lock':lock, 'list': [{'ID':-, 'address':-, 'text':-,'service':-, 'timeout_handle':-}, ...]}
        self.ring_queue = {'lock': Lock(), 'list': []}
        self.ring_counter = 0

        # Timed-out clients go in the grace_clients for n seconds.
        # All messages to these clients get redirected to a cache.
        # {'UUID': {'msg_cache':[], 'timeout_handle':-}, ...}
        self.grace_clients = {}

        self.time_event_queue = multiprocessing.Queue()

        # Contains only active clients
        self.active_clients = {'lock': Lock(), 'list': []}  # {'lock':lock, 'list': [uuid1, uuid2, ...]}

        # All clients, including implied disconnected clients. Excludes explicitly disconnected clients.
        self.clients = {'lock': Lock(), 'dict': {}}
        # {'lock':lock, 'dict': {uuid: {'timeout': handle, 'lock': semaphore_lock}, ...}}

        self.client_ciphers = {}  # [uuid: cipher_object, ...]
        self.alices_cypher = PKCS1_OAEP.new(RSA.importKey(options['alice_private_key']))

        # Stats
        self.messages_rejected = 0
        self.admin_debug_interface = AdminDebugInterface(self.service_status, self.clients, self.active_clients,
                                                         self.address_client_list, self.ring_queue)
        self.potential_admin = {'service': '', 'address': ''}
        self.admin = {'service': '', 'address': ''}

    def time_event_handler(self, time_event):
        getattr(self, time_event['name'])(time_event['arg'])
        return

    def update_status(self, msg):
        service, status = msg
        if status == "session_start":
            status = "Connected"
        add_new_entry = True
        for x in range(0, len(self.service_status)):
            if self.service_status[x]['name'] == service:
                self.service_status[x]['status'] = status
                add_new_entry = False
        if add_new_entry:
            self.service_status.append({'name': service, 'status': status})
        logger.info('Service status changed: %s, %s', service, status)
        self.send_status_to_clients()

    def update_active_client_timers(self, uuid):
        self.clients['lock'].acquire_lock()
        try:
            if self.clients['dict'][uuid]['timeout'].isAlive():
                logger.debug('Client alive update for: %s', uuid)
                self.clients['dict'][uuid]['timeout'].set_times_reset(10, 20)
            else:
                raise KeyError
        except KeyError:
            if uuid in self.grace_clients:
                self.grace_clients[uuid]['timeout_handle'].disable()
                msg = json.dumps({'type': 'msg', 'msg': self.grace_clients[uuid]['msg_cache'],
                                  'I/O': 'in', 'UUID': uuid})
                self.encrypt_and_send(msg, uuid)
                self.grace_clients.pop(uuid)
            logger.debug('Client alive thread creation for: %s', uuid)
            #  timeout = MultiTimeoutThread(lock, (10, 20), (self.probe_client, self.client_timed_out), uuid)
            callbacks = ("probe_client", "client_timed_out")
            timeout = MultiTimeoutThreadQueue(self.time_event_queue, (10,20), callbacks, uuid)
            timeout.daemon = True
            timeout.start()
            self.clients['dict'][uuid] = {'timeout': timeout}
        self.clients['lock'].release_lock()

    def probe_client(self, uuid):
        msg = json.dumps({'type': 'probe', 'UUID': uuid})
        logger.debug('Probe client: %s', uuid)
        self.encrypt_and_send(msg, uuid)

    def client_probeACK(self, msg):
        pass

    def client_timed_out(self, uuid):
        logger.info('Client timed out: %s', uuid)
        self.clients['lock'].acquire_lock()
        self.clients['dict'][uuid]['timeout'].disable()
        self.clients['lock'].release_lock()
        # TODO pop this off the list after the probe thread had sent 'probe' command.
        for association in self.address_client_list:
            if association['UUID'] == uuid:
                #  self.outgoing_dispatch((association['service'], association['address'],
                #                        self.options['messages']['client_dropped'], 'active'))
                logger.info('Client timed-out during conversation: %s', uuid)
        #  Start disconnect timer.
        timeout = TimeoutThreadDisableQueue(self.time_event_queue, 60, "client_disconnect", uuid)
        timeout.daemon = True
        timeout.start()
        #  Add client to grace_clients dict
        self.grace_clients.update({uuid:{'msg_cache': [], 'timeout_handle': timeout}})

    def send_status_to_clients(self):
        msg = json.dumps({'type': 'status', 'services': self.service_status})
        self.send_to_all_clients(msg)

    def send_to_all_clients(self, msg):
        self.active_clients['lock'].acquire_lock()
        for client_address in self.active_clients['list']:
            self.encrypt_and_send(msg, client_address)
        self.active_clients['lock'].release_lock()

    def send_ring_to_clients(self, msg, service):
        #self.ring_queue['lock'].acquire_lock()
        for x in range(0, len(self.ring_queue['list'])):
            if self.ring_queue['list'][x]['address'] == msg[1]:  # Already in the ring list
                self.ring_queue['list'][x]['text'].append(msg[2])
                return
        logger.info('Sending ring ID%d to clients', self.ring_counter)
        #lock = Lock()
        ring_counter = self.ring_counter
        #timeout = TimeoutThreadDisable(lock, 60, self.ring_timed_out, ring_counter)
        timeout = TimeoutThreadDisableQueue(self.time_event_queue, 60, "ring_timed_out", ring_counter)
        timeout.daemon = True
        timeout.start()
        self.ring_queue['list'].append({'ID': ring_counter, 'address': msg[1], 'text': [msg[2]],
                                        'service': service, 'timeout_handle': timeout})
        #self.ring_queue['lock'].release_lock()
        msg = json.dumps({'type': 'ring', 'group': '', 'ID': self.ring_counter, 'time': (time.time()+55)})
        self.send_to_all_clients(msg)
        self.ring_counter += 1

    def ring_timed_out(self, ring_id):
        logger.info('Ring timed out ID%d', ring_id)
        msg = json.dumps({'type': 'ringACKACK', 'ID': ring_id, 'UUID': ''})
        self.send_to_all_clients(msg)
        #self.ring_queue['lock'].acquire_lock()
        for x in range(0, len(self.ring_queue['list'])):
            if self.ring_queue['list'][x]['ID'] == ring_id:
                ring_item = self.ring_queue['list'].pop(x)
                self.outgoing_dispatch((ring_item['service'], ring_item['address'],
                                        self.options['messages']['ring_timed_out'], 'active'))
        #self.ring_queue['lock'].release_lock()

    def client_initialisation(self, msg):
        logger.info('Client Connected: %s', msg['UUID'])
        try:
            cipher_object = PKCS1_OAEP.new(RSA.importKey(bytes(msg['key'], encoding='utf')))
        except:
            cipher_object = False
        self.client_ciphers[msg['UUID']] = cipher_object
        self.add_to_clients(msg['UUID'])
        # To encrypt a message
        # encrypted_msg = self.client_ciphers[msg['UUID']].encrypt(bytes(message, encoding='utf'))
        # message = base64.standard_b64encode(encrypted_msg).decode('utf')

    def encrypt_and_send(self, msg, uuid):
        try:
            messages = []
            chars = len(msg)
            x = 0
            while True:
                if chars > 214:
                    messages.append(
                        base64.standard_b64encode(
                            self.client_ciphers[uuid].encrypt(bytes(msg[214*x:214*(x+1)], encoding='utf'))
                        ).decode('utf')
                    )
                    x += 1
                    chars -= 214
                else:
                    messages.append(
                        base64.standard_b64encode(
                            self.client_ciphers[uuid].encrypt(bytes(msg[214*x:len(msg)], encoding='utf'))
                        ).decode('utf')
                    )
                    break
            message = json.dumps({'messages': messages, 'UUID': uuid, 'to': 'bob'})
            self.inter_com_queue_out.put((message, uuid))
        except:
            logger.info("No uuid exists.")

    def decrypt_reconstruct(self, msg):
        # {'messages': messages, 'UUID': uuid, 'to': 'alice/bob'}
        # messages is a list of base64 encoded byte arrays.
        # They are individually encrypted blocks that combine into a json message.
        try:
            message = b''
            for part in msg['messages']:
                message += self.alices_cypher.decrypt(base64.b64decode(part))
            return json.loads(message.decode('utf'))
        except:
            logger.info('Unable to decrypt message from: %s', msg['UUID'])  # TODO add proper logger warning
            return False

    def client_disassociate_with_address(self, uuid):
        logger.info('Client disassociating: %s', uuid)
        for x in range(0, len(self.address_client_list)):
            if self.address_client_list[x]['UUID'] == uuid:
                self.address_client_list.pop(x)
                break

    def client_disconnect(self, uuid):
        logger.info('Client disconnecting: %s', uuid)
        for association in self.address_client_list:
            if association['UUID'] == uuid:
                self.outgoing_dispatch((association['service'], association['address'],
                                        self.options['messages']['client_dropped'], 'active'))
        self.client_disassociate_with_address(uuid)  # remove from active client list
        try:
            pass
            #self.client_ciphers.pop(uuid)
            # TODO pop this off the list after the probe thread had sent 'probe' command
        except KeyError:
            logger.warning('Client already disconnected: %s', uuid)
        self.active_clients['lock'].acquire_lock()
        if self.active_clients['list'].count(uuid) > 0:
            self.active_clients['list'].remove(uuid)
        self.active_clients['lock'].release_lock()

    def client_ringACK_associate_with_address(self, msg):
        logger.info('Client %s responded to ring ID%d', msg['UUID'], msg['ID'])
        #self.ring_queue['lock'].acquire_lock()
        ring_queue_len = len(self.ring_queue['list'])
        #self.ring_queue['lock'].release_lock()
        for x in range(0, ring_queue_len):
            #self.ring_queue['lock'].acquire_lock()
            if self.ring_queue['list'][x]['ID'] == msg['ID']:
                ring_item = self.ring_queue['list'].pop(x)
                ring_item['timeout_handle'].disable()
                self.address_client_list.append({'UUID': msg['UUID'], 'address': ring_item['address'],
                                                 'service': ring_item['service']})
                out_msg = json.dumps({'type': 'ringACKACK', 'ID': msg['ID'], 'UUID': msg['UUID']})
                self.send_to_all_clients(out_msg)
                if ring_item['service'] in self.modules_without_chat_states:
                    state = 'no_state'
                    out_msg = json.dumps({'type': 'chat_state', 'UUID': msg['UUID'], 'I/O': 'in', 'state': state})
                    self.encrypt_and_send(out_msg, msg['UUID'])
                for text in ring_item['text']:
                    out_msg = json.dumps({'type': 'msg', 'msg': [text], 'I/O': 'in', 'UUID': msg['UUID']})
                    self.encrypt_and_send(out_msg, msg['UUID'])
                #self.ring_queue['lock'].release_lock()
                logger.debug('client_ringACK_associate_with_address return')
                return
        #self.ring_queue['lock'].release_lock()
        return  # no matches found

    def send_full_autoreply(self, msg, service):
        logger.info('User turned away due to all clients being busy')
        user_address = msg[1]
        if service == 'Facebook':
            self.fb_queue_out.put((user_address, self.options['messages']['no_clients_available'], 'active'))

    def uuid_to_address_service(self, uuid) -> str:
        for x in range(0, len(self.address_client_list)):
            if self.address_client_list[x]['UUID'] == uuid:
                return self.address_client_list[x]['address'], self.address_client_list[x]['service']
        return None

    def inter_com_dispatch(self, msg):
        if msg['to'] != 'alice':
            logger.debug('Message bounced back')
            return
        msg = self.decrypt_reconstruct(msg)
        if not msg:
            logger.info('inter_com invalid message received')
            return

        if msg['type'] == 'probeACK':
            self.update_active_client_timers(msg['UUID'])
            return
        logger.info('inter_com dispatch type: %s', msg['type'])
        if msg['type'] == 'msg':
            if msg['I/O'] == 'out':
                self.update_active_client_timers(msg['UUID'])
                address, service = self.uuid_to_address_service(msg['UUID'])
                self.outgoing_dispatch((service, address, msg['msg'], 'active'))
        elif msg['type'] == 'ringACK':
            self.update_active_client_timers(msg['UUID'])
            self.client_ringACK_associate_with_address(msg)
        elif msg['type'] == 'key':
            self.update_active_client_timers(msg['UUID'])
            self.client_initialisation(msg)
            self.send_status_to_clients()
        elif msg['type'] == 'disassociate':
            self.update_active_client_timers(msg['UUID'])
            self.client_disassociate_with_address(msg['UUID'])
        elif msg['type'] == 'disconnect':
            self.client_disconnect(msg['UUID'])
        else:
            pass

    def add_to_clients(self, uuid):
        self.clients['lock'].acquire_lock()
        if uuid not in self.clients['dict']:
            self.clients['dict'].append(uuid)
        self.clients['lock'].release_lock()
        self.add_to_active_clients(uuid)

    def add_to_active_clients(self, uuid):
        self.active_clients['lock'].acquire_lock()
        if uuid not in self.active_clients['list']:
            self.active_clients['list'].append(uuid)
        self.active_clients['lock'].release_lock()

    def incoming_chat_state(self, msg):
        uuid = False
        for x in range(0, len(self.address_client_list)):  # incoming to clients
                if self.address_client_list[x]['address'] == msg['address']:
                    uuid = self.address_client_list[x]['UUID']
                    break
        if not uuid:
            return
        self.outgoing_chat_state(msg, uuid)
        
    def outgoing_chat_state(self, msg, uuid):
        state = msg['state']
        if state == 'active':
            state = 'idle'
        elif state == 'composing':
            state = 'typing'
        msg = json.dumps({'type': 'chat_state', 'UUID': uuid, 'I/O': 'in', 'state': state})
        self.encrypt_and_send(msg, uuid)

    def are_all_clients_full(self):
        matches = 0
        self.active_clients['lock'].acquire_lock()
        for x in range(0, len(self.active_clients['list'])):
            for y in range(0, len(self.address_client_list)):
                if self.active_clients['list'][x] == self.address_client_list[y]['UUID']:
                    matches += 1
        if matches < len(self.active_clients['list']):
            self.active_clients['lock'].release_lock()
            return False
        else:
            self.active_clients['lock'].release_lock()
            return True

    def filter_incoming_msg(self, service, msg):
        """A filter func for services that have identifiable info or buggy implementations"""
        if service == 'Zoho':  # Unescape HTML because the Zoho embeddable chat box is buggy.
            try:
                return html.unescape(msg)
            except:
                return 'Msg broke the html unescaper'
        elif service == 'Facebook':
            # Filter out messages with identifiable information
            if 'sent a sticker.\nhttps://www.facebook.com/messages/' in msg:
                return "User sent a sticker\n It's probably Pusheen"
        return msg

    def incoming_dispatch(self, msg, service):
        if type(msg) == dict:
            if msg['type'] == 'chat_state':
                self.incoming_chat_state(msg)
                return
        # A chat message = ('msg', from, text)
        if len(msg) == 2:  # Status message
            self.update_status(msg)
            return
        logger.debug('Message received from internet')
        if msg[0] == 'msg':
            # got an incoming message
            if msg[2] == 'debug interface':
                logger.info('Admin debug interface access attempt by: %s', msg[1])
                self.potential_admin['address'], self.potential_admin['service'] = msg[1], service
                self.outgoing_dispatch((service, msg[1], 'Password please...', 'active'))
                return
            elif msg[1] == self.potential_admin['address']:
                if msg[2] == 'admin password':
                    logger.info('Admin debug interface accessed by: %s', msg[1])
                    self.admin.update(self.potential_admin)
                    self.potential_admin['address'] = ''
                    logger.info('Admin updated to: %s', str(self.admin))
                    self.outgoing_dispatch((service, msg[1], "Enter commands(Hint:'help'):", 'active'))
                return
            elif msg[1] == self.admin['address']:
                logger.info('Admin debug command %s', msg[2])
                self.outgoing_dispatch((service, msg[1], self.admin_debug_interface.request(msg[2]), 'active'))
                return
            address = msg[1]
            found = False
            for x in range(0, len(self.address_client_list)):  # incoming to clients
                if self.address_client_list[x]['address'] == address:
                    uuid = self.address_client_list[x]['UUID']
                    logger.debug('Found match for '+hex(hash(msg[1]))+' from '+service+' to UUID:'+uuid)
                    found = True
                    filtered_msg = self.filter_incoming_msg(service, msg[2])
                    if uuid in self.grace_clients:
                        self.grace_clients[uuid]['msg_cache'].append(filtered_msg)
                    msg = json.dumps({'type': 'msg', 'msg': [filtered_msg], 'I/O': 'in', 'UUID': uuid})
                    self.encrypt_and_send(msg, uuid)
                    break
            if not found:
                if self.are_all_clients_full():  # Send reply
                    self.send_full_autoreply(msg, service)
                else:
                    self.outgoing_dispatch((service, msg[1], self.options['messages']['ringing'], 'active'))
                    self.send_ring_to_clients(msg, service)

    def outgoing_dispatch(self, msg):
        logger.debug('Message being sent to internet')
        service, user_address, msg, state = msg
        if service == 'Facebook':
            self.fb_queue_out.put((user_address, msg, state))
        elif service == 'Zoho':
            self.zoho_queue_out.put((user_address, msg, state))
        else:
            pass

    def run(self):
        while True:
            try:
                inter_com_in = self.inter_com_queue_in.get(timeout=0.1)
            except:  # TODO Narrow exception
                inter_com_in = False
            if inter_com_in:
                self.inter_com_dispatch(inter_com_in)
            try:
                fb_in = self.fb_queue_in.get(timeout=0.1)
            except:  # TODO Narrow exception
                fb_in = False
            if fb_in:
                self.incoming_dispatch(fb_in, 'Facebook')
            try:
                zoho_in = self.zoho_queue_in.get(timeout=0.1)
            except:  # TODO Narrow exception
                zoho_in = False
            if zoho_in:
                self.incoming_dispatch(zoho_in, 'Zoho')
            try:
                time_event = self.time_event_queue.get(timeout=0.1)
            except:  # TODO Narrow exception
                time_event = False
            if time_event:
                self.time_event_handler(time_event)

            if self.kill_event.is_set():
                logger.info('Thread ending :%s', 'Dispatch')
                break
        return