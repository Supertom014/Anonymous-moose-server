# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#

import json
import logging
import time
logger = logging.getLogger(__name__)

class AdminDebugInterface(object):
    def __init__(self, service_status, clients, active_clients, address_client_list, ring_queue):
        self.service_status = service_status  # [{'name': service, 'status': status}, ...]
        self.clients = clients  # [uuid1, uuid2, ...]
        self.active_clients = active_clients
        self.address_client_list = address_client_list  # [{'service': 'asdf', 'address': 'asdf@asdf.net', 'UUID': 'uuid'}, ...]
        self.ring_queue = ring_queue  # [{'ID':-, 'address':-, 'text':-,'service':-, 'timeout_handle':-}, ...]

    def request(self, msg):
        if msg == 'help':
            return "NL chat debug data. request commands: 'service_status'," \
                   " 'clients', 'active_clients', 'address_assoc' or 'ring_queue'. form types: 'text' or 'json_data'"
        try:
            request, return_data_form = msg.split(' ')
        except ValueError:
            return "Bad command! See 'help' for usage."

        if request == 'service_status':
            return self.service_status_to_form(return_data_form)
        elif request == 'clients':
            return self.connected_clients_to_form(return_data_form)
        elif request == 'active_clients':
            return self.active_clients_to_form(return_data_form)
        elif request == 'address_assoc':
            return self.address_client_list_to_form(return_data_form)
        elif request == 'ring_queue':
            return self.ring_queue_to_form(return_data_form)

    def service_status_to_form(self, form):
        if form == 'text':
            string = 'Service status:\n'
            for service in self.service_status:
                string += service['name']+': '+service['status']+'\n'
            return string
        elif form == 'json_data':
            return json.dumps(self.service_status)

    def connected_clients_to_form(self, form):
        if form == 'text':
            string = 'Connected clients:\n'
            for client in self.clients['dict'].keys():
                string += client+'\n'
            return string+'\n'
        elif form == 'json_data':
            return json.dumps(self.clients['dict'].keys())

    def active_clients_to_form(self, form):
        if form == 'text':
            string = 'Active clients:\n'
            for client in self.active_clients['list']:
                string += client+'\n'
            return string+'\n'
        elif form == 'json_data':
            return json.dumps(self.active_clients['list'])

    def address_client_list_to_form(self, form):
        if form == 'text':
            string = 'Address client associations:\n'
            for client_ass in self.address_client_list:
                string += 'UUID:'+client_ass['UUID']+'. Service:'+client_ass['service']+'.\tAddress:'+self.hash_str(client_ass['address'])+'.\n'
            return string+'\n'
        elif form == 'json_data':
            address_client_list = self.address_client_list
            for x in range(0, len(address_client_list)):
                address_client_list[x]['address'] = self.hash_str(address_client_list[x]['address'])
            return json.dumps(address_client_list)

    def ring_queue_to_form(self, form):
        if form == 'text':
            string = 'Ring queue:\n'
            for item in self.ring_queue['list']:
                string += 'ID:'+str(item['ID'])+'. Service:'+item['service']+'.\tAddress:'+self.hash_str(item['address'])+'.\n'
            return string+'\n'
        elif form == 'json_data':
            ring_queue = self.ring_queue['list']
            for x in range(0, len(ring_queue)):
                ring_queue[x]['address'] = self.hash_str(ring_queue[x]['address'])
                ring_queue[x].pop('text')
                ring_queue[x]['timeout_handle'] = hex(hash(ring_queue[x]['timeout_handle']))
            return json.dumps(ring_queue)

    def hash_str(self, arg):
        # Change the salt each hour
        salt = str(hash(str(time.gmtime()[3])))
        return hex(hash(str(arg)+salt))

if __name__ == '__main__':
    from threading import Thread
    service_status = [{'name': 'Facebook', 'status': 'middle'}]
    clients = {'list': ['uuid1', 'uuid2']}
    address_client_list = [{'service': 'asdf', 'address': 'asdf@asdf.net', 'UUID': 'uuid'}]
    ring_queue =[{'ID': 0, 'address': 'asdf@asdf.net', 'text': 'hi','service': 'Facebook', 'timeout_handle': Thread}]
    x = AdminDebugInterface(service_status, clients, address_client_list, ring_queue)
    print(x.request('help'))
    for command in ('ring_queue', 'address_assoc', 'active_clients', 'service_status'):
        for form in ('text', 'json_data'):
            print('Requesting %s %s'% (command, form))
            print(x.request(command+' '+form))