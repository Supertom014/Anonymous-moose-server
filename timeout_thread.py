# Copyright (C) 2015  Thomas Wilson, email:supertwilson@Sourceforge.net
#
#    This module is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License Version 3 as published by
#    the Free Software Foundation see <http://www.gnu.org/licenses/>.
#

from threading import Thread
import multiprocessing
import queue


class TimeoutThread(Thread):
    def __init__(self, seconds, callback, callback_arg):
        super().__init__()
        self.seconds = seconds
        self.callback = callback
        self.callback_arg = callback_arg

    def run(self):
        import time
        while True:
            time.sleep(1)
            self.seconds -= 1
            if self.seconds == 0:
                break
        self.callback(self.callback_arg)
        return

# Only used in dispatch.py
class TimeoutThreadDisable(Thread):
    def __init__(self, lock, seconds, callback, callback_arg):
        super().__init__()
        self.lock = lock
        self.seconds = seconds
        self.callback = callback
        self.callback_arg = callback_arg

    def disable(self):
        self.callback = lambda x: 0

    def run(self):
        import time
        while True:
            time.sleep(1)
            self.seconds -= 1
            if self.seconds == 0:
                break
        self.lock.acquire_lock()
        self.callback(self.callback_arg)
        self.lock.release_lock()
        return


class TimeoutThreadDisableQueue(Thread):
    def __init__(self, out_queue, seconds, callback_name, callback_arg):
        super().__init__()
        self.out_queue = out_queue
        self.in_queue = multiprocessing.Queue()
        self.seconds = seconds
        self.callback_name = callback_name
        self.callback_arg = callback_arg

    def disable(self):
        self.in_queue.put("disable")

    def run(self):
        import time
        while True:
            time.sleep(1)
            self.seconds -= 1
            if self.seconds == 0:
                break
        incoming = ""
        try:
            incoming = self.in_queue.get_nowait()
        except(queue.Empty):
            pass
        if(incoming == "disable"):  # Quit before sending item to queue
            return
        self.out_queue.put({'name':self.callback_name, 'arg':self.callback_arg})
        return

# Only used in dispatch.py
class MultiTimeoutThread(Thread):
    def __init__(self, lock, seconds, callbacks, callback_arg):
        super().__init__()
        self.lock = lock
        self.seconds = list(seconds)
        self.callbacks = list(callbacks)
        self.callback_arg = callback_arg
        self.kill = False
        self.called_callback = [False]*len(callbacks)

    def disable(self):
        self.kill = True
        for x in range(0, len(self.callbacks)):
            self.callbacks[x] = lambda: 0

    def set_times(self, *seconds):
        self.seconds = list(seconds)
        self.called_callback = [False] * len(seconds)

    def exit_check(self):
        count = 0
        self.lock.acquire_lock()
        for value in self.called_callback:
            if value:
                count += 1
        if count == len(self.called_callback):
            self.lock.release_lock()
            return True
        else:
            self.lock.release_lock()
        return False

    def run(self):
        import time
        while True:
            time.sleep(1)
            if self.kill or self.exit_check():
                break
            for x in range(0, len(self.seconds)):
                self.lock.acquire_lock()
                self.seconds[x] -= 1
                if self.seconds[x] <= 0 and not self.called_callback[x]:
                    self.lock.release_lock()
                    self.callbacks[x](self.callback_arg)
                    self.called_callback[x] = True
                else:
                    self.lock.release_lock()
        return

class MultiTimeoutThreadQueue(Thread):
    def __init__(self, out_queue, seconds, callback_names, callback_arg):
        super().__init__()
        self.in_queue = multiprocessing.Queue()
        self.out_queue = out_queue
        self.seconds = list(seconds)
        self.callback_names = list(callback_names)
        self.callback_arg = callback_arg
        self.called_callback = [False]*len(callback_names)
        #for name in callback_names:
        #    self.called_callback.update({name:{'time': seconds}})

    def disable(self):
        self.in_queue.put({"disable": True})

    def set_times_reset(self, *seconds):
        self.in_queue.put({"times": seconds})

    def exit_check(self):
        count = 0
        for value in self.called_callback:
            if value:
                count += 1
        if count == len(self.called_callback):
            return True
        return False

    def run(self):
        import time
        while True:
            time.sleep(1)
            exit_thread = False
            incoming = {}
            try:
                incoming = self.in_queue.get_nowait()
            except queue.Empty:
                pass
            if "times" in incoming:
                self.seconds = list(incoming["times"])
                self.called_callback = [False] * len(incoming["times"])
            if "disable" in incoming:
                exit_thread = incoming["disable"]

            if exit_thread or self.exit_check():
                break
            for x in range(0, len(self.seconds)):
                self.seconds[x] -= 1
                if self.seconds[x] <= 0 and not self.called_callback[x]:
                    self.out_queue.put({'name':self.callback_names[x], 'arg':self.callback_arg})
                    self.called_callback[x] = True
        return

if __name__ == '__main__':
    import time
    from threading import Lock
    lock = Lock()
    if True:
        def semi(arg):
            print(arg, 'semi timeout')

        def full(arg):
            print(arg, 'full timeout')

        y = MultiTimeoutThread(lock, (3, 5), (semi, full), 'Multi timer test:')
        y.daemon = True
        y.start()
        print(y.isAlive())
        print('made thread')
        #lock.acquire_lock()
        #y.disable()
        #lock.release_lock()
        time.sleep(5)
        #print('setting time')
        #y.set_time(10)
        time.sleep(30)

    if False:
        x = TimeoutThread(5, print, 'Yo')
        x.daemon = True
        x.start()
        print('made thread')
        time.sleep(10)
