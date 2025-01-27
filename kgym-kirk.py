# kgym-kirk.py
import os
import json
import subprocess as sp
from google.cloud import storage
from google.cloud.storage import transfer_manager
from concurrent.futures import ProcessPoolExecutor as Pool
from concurrent.futures import Future
import argparse
from time import sleep
from random import random

class LTPJob:

    def __init__(
        self,
        bug_id: str,
        tag: str,
        kgym_storage_bucket: storage.Bucket,
        kgym_storage_prefix: str,
        work_dir: str,
        stdout_fp,
        ltp_repo_url: str,
        ltp_branch: str,
        suites: list[str]
    ):
        self.bug_id = bug_id
        self.tag = tag
        self.kgym_storage_bucket = kgym_storage_bucket
        self.kgym_storage_prefix = kgym_storage_prefix
        self.work_dir = os.path.join(work_dir, bug_id, tag)
        self.stdout_fp = stdout_fp
        self.ltp_repo_url = ltp_repo_url
        self.ltp_branch = ltp_branch
        self.suites = suites

    def clean(self):
        sp.Popen([
            'sudo', 'rm', '-rf',
            os.path.join(self.work_dir, 'kcache'),
            os.path.join(self.work_dir, 'kcache.tar.zstd'),
            os.path.join(self.work_dir, 'image.tar.gz'),
            os.path.join(self.work_dir, 'disk.raw'),    
            os.path.join(self.work_dir, 'ltp-deliverable'),
            os.path.join(self.work_dir, 'mnt'),
            os.path.join(self.work_dir, 'report.json'),
            os.path.join(self.work_dir, 'kernel')
        ], stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp).wait()

    def pull(self):
        # kcache;
        kcache_local_path = os.path.join(self.work_dir, 'kcache.tar.zstd')
        blob = self.kgym_storage_bucket.blob(os.path.join(self.kgym_storage_prefix, 'kcache.tar.zstd'))
        transfer_manager.download_chunks_concurrently(blob, kcache_local_path)
        kcache_checkout = os.path.join(self.work_dir, 'kcache')
        os.makedirs(kcache_checkout)
        proc = sp.Popen(
            ['tar', '-x', '--use-compress-program=zstdmt',
            '-f', kcache_local_path, '-C', kcache_checkout],
            stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL
        )
        code = proc.wait()
        if code == 0:
            self.kcache_checkout = kcache_checkout
        else:
            raise SystemError('Failed to untar kcache')
        # vm image;
        src_image_path = os.path.abspath('./ltp.raw')
        vm_image_path = os.path.join(self.work_dir, 'disk.raw')
        proc = sp.Popen(
            ['cp', src_image_path, './disk.raw'],
            stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL,
            cwd=self.work_dir
        )
        code = proc.wait()
        if code == 0:
            self.vm_image_path = vm_image_path
        else:
            raise SystemError('Failed to copy the LTP userspace image')
        # kernel.config
        kernel_config_path = os.path.join(self.work_dir, 'kernel.config')
        blob = self.kgym_storage_bucket.blob(os.path.join(self.kgym_storage_prefix, 'kernel.config'))
        transfer_manager.download_chunks_concurrently(blob, kernel_config_path)
        self.kernel_config_path = kernel_config_path
        # kernel
        kernel_path = os.path.join(self.work_dir, 'kernel')
        blob = self.kgym_storage_bucket.blob(os.path.join(self.kgym_storage_prefix, 'kernel'))
        transfer_manager.download_chunks_concurrently(blob, kernel_path)
        self.kernel_path = kernel_path

    def build_ltp(self):
        ltp_dir = os.path.join(self.work_dir, 'ltp-deliverable')
        os.makedirs(ltp_dir)

        docker_proc = sp.Popen([
            'docker', 'run', '--rm',
            '--mount', f'type=bind,src={os.path.abspath(self.kcache_checkout)},dst=/opt/ltp-build/linux',
            '--mount', f'type=bind,src={os.path.abspath(ltp_dir)},dst=/opt/ltp-build/ltp-deliverable',
            '-e', f'LTP_REPO={self.ltp_repo_url}',
            '-e', f'LTP_BRANCH={self.ltp_branch}',
            'kaloronahuang/ltp-builder'
        ], stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = docker_proc.wait()
        if code == 0:
            self.ltp_dir = os.path.join(ltp_dir, 'opt', 'ltp')
        else:
            raise SystemError('Docker failed to compile LTP')

    def setup_vm_image(self):
        # kernel gets overwhelmed;
        sleep(random() * 20)
        # mount;
        proc = sp.Popen(['sudo', 'losetup', '-fP', '--show', self.vm_image_path], stdin=sp.DEVNULL, stdout=sp.PIPE, stderr=sp.DEVNULL)
        out, _ = proc.communicate()
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to mount')
        dev = out.decode('utf-8').strip()
        # mount dir;
        mnt_dir = os.path.join(self.work_dir, 'mnt')
        os.makedirs(mnt_dir)
        proc = sp.Popen(['sudo', 'mount', dev + 'p1', mnt_dir], stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to mount to directory', code)
        # copy config;
        proc = sp.Popen(
            ['sudo', 'cp', self.kernel_config_path, os.path.join(mnt_dir, 'boot', 'kernel.config')],
            stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp
        )
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to copy')
        # copy kernel;
        proc = sp.Popen(
            ['sudo', 'cp', self.kernel_path, os.path.join(mnt_dir, 'vmlinuz')],
            stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp
        )
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to copy')
        # copy ltp;
        proc = sp.Popen(
            ['sudo', 'cp', '-r', self.ltp_dir, os.path.join(mnt_dir, 'opt', 'ltp')],
            stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp
        )
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to copy')
        # make bash setting;
        proc = sp.Popen(
            f'echo "set enable-bracketed-paste off" | sudo tee -a {os.path.join(mnt_dir, "etc/inputrc")}',
            shell=True, stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp
        )
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to echo')
        # umount;
        proc = sp.Popen(['sudo', 'umount', mnt_dir], stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to umount the directory')
        # umount loop;
        proc = sp.Popen(['sudo', 'losetup', '-d', dev], stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to umount loop device')

    def prepare(self):
        self.pull()
        self.build_ltp()
        self.setup_vm_image()

    def run(self) -> dict:
        self.clean()
        os.makedirs(self.work_dir, exist_ok=True)
        self.pull()
        self.build_ltp()
        self.setup_vm_image()

        report_path = os.path.join(self.work_dir, 'report.json')
        kirk_proc = sp.Popen([
            './kirk',
            '--framework', 'ltp',
            '--sut', f'qemu:image={self.vm_image_path}:user=root:smp=2,sockets=2,cores=1:ram=8G',
            '--run-suite', *self.suites,
            '--json-report', report_path,
            '--tmp-dir', self.work_dir
        ], stdin=sp.DEVNULL, stdout=self.stdout_fp, stderr=sp.STDOUT)
        code = kirk_proc.wait()
        if code != 0:
            self.clean()
            raise SystemError(f'kirk exit code: {code}')

        with open(report_path) as fp:
            report = json.load(fp)
        self.clean()
        return report

def run_ltp(bug_id: str, tag: str, bucket_name: str, kgym_storage_prefix: str, work_dir_root: str, ltp_repo_url: str, ltp_branch: str, suites: list[str]) -> dict:
    work_dir = os.path.join(work_dir_root, bug_id, tag)
    os.makedirs(work_dir, exist_ok=True)
    stdout_fp = open(os.path.join(work_dir, 'stdout.txt'), 'w', buffering=1)
    try:
        client = storage.Client()
        job = LTPJob(bug_id, tag, client.bucket(bucket_name), kgym_storage_prefix, work_dir_root, stdout_fp, ltp_repo_url, ltp_branch, suites)
        return { bug_id: { tag: { 'status': 'success', 'result': job.run() } } }
    except Exception:
        from traceback import format_exc
        return { bug_id: { tag: { 'status': 'exception', 'result': format_exc() } } }

class KirkCluster:

    def __init__(self, nproc: int, ltp_repo_url: str, ltp_branch: str, suites: list[str]):
        self.nproc = nproc
        self.work_dir = 'work_dir'
        self.ltp_repo_url = ltp_repo_url
        self.ltp_branch = ltp_branch
        os.makedirs(self.work_dir, exist_ok=True)
        self.scoreboard_path = os.path.join(self.work_dir, 'scoreboard.json')
        if not os.path.exists(self.scoreboard_path):
            with open(self.scoreboard_path, 'w') as fp:
                fp.write('{}')
        with open(self.scoreboard_path) as fp:
            self.scoreboard: dict = json.load(fp)
        self.suites = suites

    def load_scoreboard(self):
        with open(self.scoreboard_path) as fp:
            self.scoreboard = json.load(fp)

    def save_scoreboard(self):
        with open(self.scoreboard_path, 'w') as fp:
            json.dump(self.scoreboard, fp, indent=4)

    def submit_ltp_task_result(self, future: Future):
        pdict = future.result()
        bug_id = (list(pdict.keys()))[0]
        tag = (list(pdict[bug_id].keys()))[0]
        status = pdict[bug_id][tag].get('status', 'undefined')
        if bug_id not in self.scoreboard:
            self.scoreboard[bug_id] = dict()
        self.scoreboard[bug_id][tag] = pdict[bug_id][tag]
        self.save_scoreboard()
        print(f'LTP task finished: {bug_id} at {tag}, {status}')

    def main(self, args):
        with open(args.filename) as fp:
            kernels = json.load(fp)
        if args.cont:
            kernels_to_run = []
            for k in kernels:
                bug_id = k['bug-id']
                tag = k['tag']
                verd = True
                if tag in self.scoreboard.get(bug_id, dict()):
                    if self.scoreboard[bug_id][tag].get('status', 'undefined') == 'success':
                        verd = False
                if verd:
                    kernels_to_run.append(k)
        else:
            kernels_to_run = kernels
        with Pool(self.nproc) as executor:
            # [ { "bug-id": "", "tag": "", "kgym-bucket-name": "", "kgym-storage-prefix": "" } ]
            for test_job in kernels_to_run:
                executor.submit(
                    run_ltp, test_job['bug-id'], test_job['tag'], test_job['kgym-bucket-name'],
                    test_job['kgym-storage-prefix'], 'work_dir', self.ltp_repo_url, self.ltp_branch,
                    self.suites
                ).add_done_callback(self.submit_ltp_task_result)

if __name__ == '__main__':
    parser = argparse.ArgumentParser('kirk Cluster')

    parser.add_argument('-f', '--filename')
    parser.add_argument('-n', '--nproc', help='Number of processes in the pool', default=4, type=int)
    parser.add_argument('-c', '--cont', action='store_true', help='Continue, skip previously ran jobs')
    parser.add_argument('-r', '--repo', default='https://github.com/kaloronahuang/ltp.git', type=str, help='The LTP repo to clone')
    parser.add_argument('-b', '--branch', default='kgym/main', help='The LTP repo branch to checkout')
    parser.add_argument('-s', '--suites', nargs='*', default=['syscalls'], help='List of suites to run')

    args = parser.parse_args()

    cluster = KirkCluster(args.nproc, args.repo, args.branch, args.suites)
    cluster.main(args)
