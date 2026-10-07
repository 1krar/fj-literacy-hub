"""Small, work-conserving queue; one assignee per question, no model routing call."""
from concurrent.futures import ThreadPoolExecutor
import threading


class Dispatcher:
    def __init__(self, names, api_names=(), api_limit=6):
        self.condition = threading.Condition(threading.RLock())
        self.api_names = set(api_names)
        self.api_limit = api_limit
        self.active = {name: 0 for name in names}
        self.pools = {name: ThreadPoolExecutor(max_workers=api_limit if name in self.api_names else 1) for name in names}
        self.busy = set()
        self.ready = {name: True for name in names}
        self.pending = []
        self.sequence = 0
        self.closed = False

    def enqueue(self, candidates, assign, work, priority=10):
        with self.condition:
            if self.closed:
                raise RuntimeError('助手正在关闭，请重新启动后提交')
            self.sequence += 1
            self.pending.append((priority, self.sequence, tuple(candidates), assign, work))
            self._dispatch()

    def set_ready(self, name, ready):
        with self.condition:
            self.ready[name] = ready
            self._dispatch()

    def _dispatch(self):
        for item in sorted(self.pending, key=lambda item: item[:2]):
            candidates, assign, work = item[2:]
            api_active = sum(self.active[name] for name in self.api_names)
            name = next((name for name in candidates if self.ready.get(name) and
                         ((name in self.api_names and api_active < self.api_limit) or
                          (name not in self.api_names and not self.active.get(name)))), None)
            if name is None:
                continue
            self.pending.remove(item)
            self.busy.add(name)
            self.active[name] += 1
            assign(name)
            self.pools[name].submit(self._run, name, work)
        self.condition.notify_all()

    def _run(self, name, work):
        try:
            work(name)
        finally:
            with self.condition:
                self.active[name] -= 1
                if not self.active[name]:
                    self.busy.discard(name)
                self._dispatch()

    def snapshot(self):
        with self.condition:
            return {'models': {name: {'busy': name in self.busy, 'active': self.active[name],
                                     'capacity': self.api_limit if name in self.api_names else 1,
                                     'ready': self.ready.get(name, False)} for name in self.pools},
                    'api_active': sum(self.active[name] for name in self.api_names),
                    'api_limit': self.api_limit, 'waiting': len(self.pending)}

    def wait_idle(self):
        with self.condition:
            self.condition.wait_for(lambda: not self.pending and not self.busy)
        # Include retained-tab cleanup already submitted to the provider lanes.
        for pool in self.pools.values():
            pool.submit(lambda: None).result()

    def shutdown(self, wait=True):
        with self.condition:
            self.closed = True
            if not wait:
                self.pending.clear()
            self.condition.notify_all()
        if wait:
            self.wait_idle()
        for pool in self.pools.values():
            pool.shutdown(wait=wait)
