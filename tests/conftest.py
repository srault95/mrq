from __future__ import print_function
from future import standard_library
standard_library.install_aliases()
from builtins import range
from builtins import str
from builtins import object
from past.builtins import basestring
import pytest
import os
try:
    import subprocess32 as subprocess
except:
    import subprocess
import sys
import psutil
import time
import re
import json
import urllib.request, urllib.error, urllib.parse

sys.path.append(os.getcwd())

from mrq.job import Job, queue_raw_jobs, queue_jobs
from mrq.queue import Queue
from mrq.config import get_config
from mrq.utils import wait_for_net_service
from mrq.context import connections, set_current_config, get_current_config

curent_config = get_config(sources=("env"))
curent_config["mongodb_jobs"] = "mongodb://mongodb/mrq_test"
curent_config["redis"] = "redis://redis:6379"

set_current_config(curent_config) #get_config(sources=("env")))

os.system("rm -rf dump.rdb")

from pprint import pprint
pprint(get_config(sources=("env")))

class ProcessFixture(object):

    def __init__(self, request, cmdline=None, wait_port=None, quiet=False):
        self.request = request
        self.cmdline = cmdline
        self.process = None
        self.wait_port = wait_port
        self.quiet = quiet
        self.stopped = False

        self.request.addfinalizer(self.stop)

    def start(self, cmdline=None, env=None, expected_children=0):

        self.stopped = False
        self.process_children = []

        if not cmdline:
            cmdline = self.cmdline
        if env is None:
            env = {}

        # Kept from parent env
        for env_key in ["PATH", "GEVENT_LOOP", "VIRTUAL_ENV"]:
            if os.environ.get(env_key) and not env.get(env_key):
                env[env_key] = os.environ.get(env_key)

        if self.quiet:
            stdout = open(os.devnull, 'w')
        else:
            stdout = None

        self.cmdline = cmdline
        # print cmdline
        self.process = subprocess.Popen(re.split(r"\s+", cmdline) if isinstance(cmdline, basestring) else cmdline,
                                        shell=False, close_fds=True, env=env, cwd=os.getcwd(), stdout=stdout)

        if self.quiet:
            stdout.close()

        # Wait for children to start
        if expected_children > 0:
            psutil_process = psutil.Process(self.process.pid)

            # print "Expecting %s children, got %s" % (expected_children,
            # psutil_process.get_children(recursive=False))
            while True:
                self.process_children = psutil_process.get_children(
                    recursive=True)
                if len(self.process_children) >= expected_children:
                    break
                time.sleep(0.1)

        if self.wait_port:
            wait_for_net_service("127.0.0.1", int(self.wait_port), poll_interval=0.01)

    def stop(self, force=False, timeout=None, block=True, sig=15):

        # Call this only one time.
        if self.stopped and not force:
            return
        self.stopped = True

        if self.process is not None:

            os.kill(self.process.pid, sig)

            # When sending a sigkill to the process, we also want to kill the
            # children in case of supervisord usage
            if sig == 9 and len(self.process_children) > 0:
                for c in self.process_children:
                    c.send_signal(sig)

            if not block:
                return

            for _ in range(2000):

                try:
                    p = psutil.Process(self.process.pid)
                    if p.status == "zombie":
                        # print "process %s zombie OK" % self.cmdline
                        return
                except psutil.NoSuchProcess:
                    # print "process %s exit OK" % self.cmdline
                    return

                time.sleep(0.01)

            assert False, "Process '%s' was still in state %s after 20 seconds..." % (
                self.cmdline, p.status)


class WorkerFixture(ProcessFixture):

    def __init__(self, request, **kwargs):
        ProcessFixture.__init__(self, request, cmdline=kwargs.get("cmdline"))

        #self.fixture_mongodb = kwargs["mongodb"]
        #self.fixture_redis = kwargs["redis"]

        self.started = False

    def start(self, flush=True, deps=True, trace=True, **kwargs):

        self.started = True

        if deps:
            self.start_deps(flush=flush)

        processes = 0
        m = re.search(r"--processes (\d+)", kwargs.get("flags", ""))
        if m:
            processes = int(m.group(1))

        cmdline = "python mrq/bin/mrq_worker.py --mongodb_logs_size 0 %s %s %s %s" % (
            "--admin_port 20020" if (processes <= 1) else "",
            "--trace_io --trace_greenlets" if trace else "",
            kwargs.get("flags", ""),
            kwargs.get("queues", "high default low")
        )

        # +1 because of supervisord itself
        if processes > 0:
            processes += 1

        print(cmdline)
        ProcessFixture.start(self, cmdline=cmdline, env=kwargs.get("env"), expected_children=processes)

    def start_deps(self, flush=True):

        #self.fixture_mongodb.start()
        #self.fixture_redis.start()

        # Will auto-connect
        connections.reset()

        self.mongodb_jobs = connections.mongodb_jobs
        self.mongodb_logs = connections.mongodb_logs
        self.redis = connections.redis

        #if flush:
        #    self.fixture_mongodb.flush()
        #    self.fixture_redis.flush()

    def stop(self, deps=True, sig=2, **kwargs):

        if self.started:
            ProcessFixture.stop(self, sig=sig, **kwargs)

        if deps:
            self.stop_deps(**kwargs)

    def stop_deps(self, **kwargs):
        pass
        #self.fixture_mongodb.stop(sig=2, **kwargs)
        #self.fixture_redis.stop(sig=2, **kwargs)

    def wait_for_tasks_results(self, job_ids, block=True, accept_statuses=["success"]):

        if not block:
            return job_ids

        results = []

        for job_id in job_ids:
            job = Job(job_id).wait(poll_interval=0.01)
            assert job.get("status") in accept_statuses, "Job had status %s, not in %s. Dump: %s" % (
                job.get("status"), accept_statuses, job)

            results.append(job.get("result"))

        return results

    def send_raw_tasks(self, queue, params_list, start=True, block=True):
        if not self.started and start:
            self.start()

        queue_raw_jobs(queue, params_list)

        if block:
            # Wait for the queue to be empty. Might be error-prone when tasks
            # are in-memory between the 2
            q = Queue(queue)
            while q.size() > 0 or self.mongodb_jobs.mrq_jobs.find({"status": "started"}).count() > 0:
                # print "S", q.size(),
                # self.mongodb_jobs.mrq_jobs.find({"status":
                # "started"}).count()
                time.sleep(0.1)

    def send_tasks(self, path, params_list, block=True, queue=None, accept_statuses=["success"], start=True):
        if not self.started and start:
            self.start()

        job_ids = queue_jobs(path, params_list, queue=queue)

        return self.wait_for_tasks_results(job_ids, block=block, accept_statuses=accept_statuses)

    def send_task(self, path, params, **kwargs):
        return self.send_tasks(path, [params], **kwargs)[0]

    def send_task_cli(self, path, params, queue=None, **kwargs):

        cli = ["python", "mrq/bin/mrq_run.py", "--quiet"]
        if queue:
            cli += ["--queue", queue]
        cli += [path, json.dumps(params)]

        out = subprocess.check_output(cli).strip()
        if not queue:
            return json.loads(out.decode('utf-8'))
        return out

    def get_report(self, with_memory=False):
        wait_for_net_service("127.0.0.1", 20020, poll_interval=0.01)
        f = urllib.request.urlopen("http://127.0.0.1:20020/report%s" % ("_mem" if with_memory else ""))
        data = json.loads(f.read().decode('utf-8'))
        f.close()
        return data


class RedisFixture(ProcessFixture):

    def flush(self):
        connections.redis.flushall()

        # Empty local known_queues cache too
        Queue.known_queues = {}


class MongoFixture(ProcessFixture):

    def flush(self):
        for mongodb in (connections.mongodb_jobs, connections.mongodb_logs):
            if mongodb:
                for c in mongodb.collection_names():
                    if not c.startswith("system."):
                        mongodb.drop_collection(c)


@pytest.fixture(scope="function")
def httpstatic(request):
    return ProcessFixture(request, "/usr/sbin/nginx -c /app/tests/fixtures/httpstatic/nginx.conf", wait_port=8081)


@pytest.fixture(scope="function")
def mongodb(request):
    cmd = "mongod --smallfiles --noprealloc --nojournal"
    if os.environ.get("STACK_STARTED"):
        cmd = "sleep 1h"
    return MongoFixture(request, cmd, wait_port=27017, quiet=True)


@pytest.fixture(scope="function")
def mongodb_with_journal(request):
    cmd = "mongod --smallfiles --noprealloc"
    if os.environ.get("STACK_STARTED"):
        cmd = "sleep 1h"
    return MongoFixture(request, cmd, wait_port=27017, quiet=True)


@pytest.fixture(scope="function")
def redis(request):
    cmd = "redis-server"
    if os.environ.get("STACK_STARTED"):
        cmd = "sleep 1h"
    return RedisFixture(request, cmd, wait_port=6379, quiet=True)


@pytest.fixture(scope="function")
def worker(request): #, mongodb, redis

    return WorkerFixture(request)#, mongodb=mongodb, redis=redis)


@pytest.fixture(scope="function")
def worker_mongodb_with_journal(request, mongodb_with_journal, redis):

    return WorkerFixture(request, mongodb=mongodb_with_journal, redis=redis)
