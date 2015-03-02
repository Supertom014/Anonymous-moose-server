# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#


import time
from threading import Thread
from fb_xmpp import FBXMPP
from zoho_xmpp import ZohoXMPP
from inter_com_xmpp import InterComXMPP
from dispatch import Dispatch
from timeout_thread import TimeoutThread
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os
import logging
logger = logging.getLogger(__name__)


class CommunicationThreadingManager(object):
    """Manages the communication threads"""
    def __init__(self, root, incoming_queue, outgoing_queue, options):
        import multiprocessing
        self.root = root
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self.options = options
        self.kill_event = multiprocessing.Event()
        self.fb_queue_in = multiprocessing.Queue()
        self.fb_queue_out = multiprocessing.Queue()
        self.zoho_queue_in = multiprocessing.Queue()
        self.zoho_queue_out = multiprocessing.Queue()
        self.inter_com_queue_in = multiprocessing.Queue()
        self.inter_com_queue_out = multiprocessing.Queue()
        self.Intercommunication_handle = InterCommunication(self.kill_event, self.inter_com_queue_in,
                                                            self.inter_com_queue_out, self.options)
        self.FB_thread_handle = FBThread(self.kill_event, self.fb_queue_in, self.fb_queue_out, self.options)
        self.zoho_thread_handle = ZohoThread(self.kill_event, self.zoho_queue_in, self.zoho_queue_out, self.options)
        self.dispatch_thread_handle = Dispatch(self.kill_event, self.root, self.options,
                                               self.incoming_queue, self.outgoing_queue, self.fb_queue_in,
                                               self.fb_queue_out, self.zoho_queue_in, self.zoho_queue_out,
                                               self.inter_com_queue_in, self.inter_com_queue_out)
        self.email_log_timer = EmailLogTimer(self.kill_event, self.options)
        self.start_communication_threads()

    def kill_all(self):
        """Stop all running communication threads"""
        self.kill_event.set()  # Send kill signal to threads
        self.Intercommunication_handle.join()
        self.FB_thread_handle.join()
        self.zoho_thread_handle.join()
        self.dispatch_thread_handle.join()
        self.email_log_timer.join()

    def start_communication_threads(self):
        """Starts the communication threads."""
        self.dispatch_thread_handle.daemon = True
        self.dispatch_thread_handle.start()
        # Staggered starts are used for cx_freeze compatibility with sleekxmpp.
        self.Intercommunication_handle.daemon = True
        self.Intercommunication_handle.start()
        self.FB_thread_handle.daemon = True
        TimeoutThread(1, lambda x: x.start(), self.FB_thread_handle).start()
        self.zoho_thread_handle.daemon = True
        TimeoutThread(2, lambda x: x.start(), self.zoho_thread_handle).start()
        self.email_log_timer.daemon = True
        self.email_log_timer.start()


class InterCommunication(Thread):
    def __init__(self, kill_event, incoming_queue, outgoing_queue, options):
        super().__init__()
        self.kill_event = kill_event
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self.username = options['accounts']['inter_com']['username']
        self.password = options['accounts']['inter_com']['password']

    def run(self):
        inter_com = InterComXMPP(self.username, self.password, self.incoming_queue)
        if inter_com.connect():
            inter_com.process()
            logger.info('Connected to: %s', 'inter_com')
        else:
            logger.info('Unable to connect to: %s', 'inter_com')
        while True:  # main thread loop
            msg_to_process = False
            try:
                msg, uuid = self.outgoing_queue.get(timeout=0.1)
                msg_to_process = True
            except:  # TODO Narrow exception
                pass
            if msg_to_process:
                inter_com.reply_message(msg, self.username, uuid)
            if self.kill_event.is_set():
                inter_com.disconnect()
                logger.info('Thread ending: %s', 'inter_com')
                break
        return


class FBThread(Thread):
    def __init__(self, kill_event, incoming_queue, outgoing_queue, options):
        super().__init__()
        self.kill_event = kill_event
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self.options = options
        
    def run(self):
        fb_msger = FBXMPP(self.options['accounts']['facebook']['username'],
                          self.options['accounts']['facebook']['password'], self.incoming_queue)
        if fb_msger.connect():
            fb_msger.process()
            logger.info('Connected to: %s', 'Facebook')
        else:
            logger.info('Unable to connect to: %s', 'Facebook')
        while True:  # main thread loop
            msg_to_send = False
            try:
                user_id, msg, state = self.outgoing_queue.get(timeout=0.1)
                msg_to_send = True
            except:  # TODO Narrow exception
                pass
            if msg_to_send:
                fb_msger.reply_message(user_id, msg, state)
            if self.kill_event.is_set():
                fb_msger.disconnect()
                logger.info('Thread ending: %s', 'Facebook')
                break
        return

class ZohoThread(Thread):
    def __init__(self, kill_event, incoming_queue, outgoing_queue, options):
        super().__init__()
        self.kill_event = kill_event
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self.options = options
        
    def run(self):
        username = self.options['accounts']['zoho']['username'].replace('\\\\', '\\')
        zoho_msger = ZohoXMPP(username,
                              self.options['accounts']['zoho']['password'],
                              self.incoming_queue)
        if zoho_msger.connect(('zchat.zoho.com', 5222)):
            zoho_msger.process()
            logger.info('Connected to: %s', 'Zoho')
        else:
            logger.info('Unable to connect to: %s', 'Zoho')
        
        while True:  # main thread loop
            msg_to_send = False
            try:
                user_id, msg, state = self.outgoing_queue.get(timeout=0.1)
                msg_to_send = True
            except:  # TODO Narrow exception
                pass
            if msg_to_send:
                zoho_msger.reply_message(user_id, msg, state)
            if self.kill_event.is_set():
                zoho_msger.disconnect()
                logger.info('Thread ending: %s', 'Zoho')
                break
        return


class EmailLogTimer(Thread):
    def __init__(self, kill_event, options):
        super().__init__()
        self.kill_event = kill_event
        self.options = options

    def mail(self, smtp_server, smtp_port, username, password, to, subject, text):
        msg = MIMEMultipart()
        msg['From'] = username
        msg['To'] = to
        msg['Subject'] = subject
        for file in ("info.log", "errors.log"):
            try:
                msg.attach(MIMEApplication(open(os.getcwd()+"\\logging\\"+file, "rb").read(),
                                           Content_Disposition='attachment; filename="%s"' % file))
            except:
                text += "\nCan not attach file '%s'." % file
                msg.attach(MIMEText(text))
        try:
            mailServer = smtplib.SMTP(smtp_server, int(smtp_port))
            mailServer.ehlo()
            mailServer.starttls()
            mailServer.ehlo()
            mailServer.login(username, password)
            mailServer.sendmail(username, to, msg.as_string())
            # Should be mailServer.quit(), but that crashes...
            mailServer.close()
        except:
            logger.info("Incorrect logging email details.")

    def run(self):
        logger.info('Started: %s', 'emailLogTimer')
        hour, minute = self.options['logging']['time'].split(':')
        while True:  # main thread loop
            current_time = time.localtime()
            if current_time.tm_hour == int(hour) and current_time.tm_min == int(minute):
                subject = 'Logging: '
                time_tuple = time.ctime().split()[0:3]
                for y in range(0, len(time_tuple)):
                    if y == len(time_tuple)-1:
                        subject += time_tuple[y]
                    else:
                        subject += time_tuple[y]+' '
                logger.info("Sending log file to: %s", self.options['logging']['sendto'])
                self.mail(self.options['logging']['smtp_server'],
                          self.options['logging']['smtp_port'],
                          self.options['logging']['username'],
                          self.options['logging']['password'],
                          self.options['logging']['sendto'],
                          subject,
                          "Logs here!"
                )
                time.sleep(60*2)
            if self.kill_event.is_set():
                logger.info('Thread ending: %s', 'emailLogTimer')
                break
            time.sleep(30)
        return