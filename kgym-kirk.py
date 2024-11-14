# kgym-kirk.py
import os
import sys
import json
import subprocess as sp
from google.cloud import storage
from google.cloud.storage import transfer_manager
from concurrent.futures import ProcessPoolExecutor as Pool
from concurrent.futures import Future
import argparse
from contextlib import redirect_stdout

class LTPJob:

    def __init__(
        self,
        bug_id: str,
        tag: str,
        kgym_storage_bucket: storage.Bucket,
        kgym_storage_prefix: str,
        work_dir: str,
        stdout_fp
    ):
        self.bug_id = bug_id
        self.tag = tag
        self.kgym_storage_bucket = kgym_storage_bucket
        self.kgym_storage_prefix = kgym_storage_prefix
        self.work_dir = os.path.join(work_dir, bug_id, tag)
        self.stdout_fp = stdout_fp

    def clean(self):
        sp.Popen([
            'sudo', 'rm', '-rf',
            os.path.join(self.work_dir, 'kcache'),
            os.path.join(self.work_dir, 'kcache.tar.zstd'),
            os.path.join(self.work_dir, 'image.tar.gz'),
            os.path.join(self.work_dir, 'disk.raw'),
            os.path.join(self.work_dir, 'ltp-deliverable'),
            os.path.join(self.work_dir, 'mnt')
        ], stdout=self.stdout_fp, stderr=self.stdout_fp).wait()

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
        vm_image_path = os.path.join(self.work_dir, 'image.tar.gz')
        blob = self.kgym_storage_bucket.blob(os.path.join(self.kgym_storage_prefix, 'image.tar.gz'))
        transfer_manager.download_chunks_concurrently(blob, vm_image_path)
        vm_image_path = os.path.join(self.work_dir, 'disk.raw')
        proc = sp.Popen(
            ['tar', 'xvf', 'image.tar.gz'],
            stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL,
            cwd=self.work_dir
        )
        code = proc.wait()
        if code == 0:
            self.vm_image_path = vm_image_path
        else:
            raise SystemError('Failed to untar image')
    
    def build_ltp(self):
        ltp_dir = os.path.join(self.work_dir, 'ltp-deliverable')
        os.makedirs(ltp_dir)

        docker_proc = sp.Popen([
            'docker', 'run', '--rm',
            '--mount', f'type=bind,src={os.path.abspath(self.kcache_checkout)},dst=/opt/ltp-build/linux',
            '--mount', f'type=bind,src={os.path.abspath(ltp_dir)},dst=/opt/ltp-build/ltp-deliverable',
            'kaloronahuang/ltp-builder'
        ], stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = docker_proc.wait()
        if code == 0:
            self.ltp_dir = os.path.join(ltp_dir, 'opt', 'ltp')
        else:
            raise SystemError('Docker failed to compile LTP')

    def setup_vm_image(self):
        # enlarge with qemu util;
        proc = sp.Popen(
            ['qemu-img', 'resize', self.vm_image_path, '10G'],
            stdout=self.stdout_fp, stderr=self.stdout_fp
        )
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to resize VM image')
        # mount;
        proc = sp.Popen(['sudo', 'losetup', '-fP', '--show', self.vm_image_path], stdout=sp.PIPE, stderr=sp.DEVNULL)
        out, _ = proc.communicate()
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to mount')
        dev = out.decode('utf-8').strip()
        # grow fs;
        proc = sp.Popen(['sudo', 'growpart', dev, '1'], stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to grow fs')
        # mount dir;
        mnt_dir = os.path.join(self.work_dir, 'mnt')
        os.makedirs(mnt_dir)
        proc = sp.Popen(['sudo', 'mount', dev + 'p1', mnt_dir], stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to mount to directory')
        # resize2fs resize;
        proc = sp.Popen(['sudo', 'resize2fs', dev + 'p1'], stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to resize fs')
        # copy ltp;
        proc = sp.Popen(
            ['sudo', 'cp', '-r', self.ltp_dir, os.path.join(mnt_dir, 'opt', 'ltp')],
            stdout=self.stdout_fp, stderr=self.stdout_fp
        )
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to copy')
        # make bash setting;
        proc = sp.Popen(
            f'echo "set enable-bracketed-paste off" | sudo tee -a {os.path.join(mnt_dir, "etc/inputrc")}',
            shell=True, stdout=self.stdout_fp, stderr=self.stdout_fp
        )
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to echo')
        # umount;
        proc = sp.Popen(['sudo', 'umount', mnt_dir], stdout=self.stdout_fp, stderr=self.stdout_fp)
        code = proc.wait()
        if code != 0:
            raise SystemError('Failed to umount the directory')
        # umount loop;
        proc = sp.Popen(['sudo', 'losetup', '-d', dev], stdout=self.stdout_fp, stderr=self.stdout_fp)
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
        import libkirk.main
        report_path = os.path.join(self.work_dir, 'report.json')
        with redirect_stdout(self.stdout_fp):
            libkirk.main.run([
                '--framework', 'ltp',
                '--sut', f'qemu:image={self.vm_image_path}:user=root:smp=2,sockets=2,cores=1:ram=8G',
                '--run-suite', 'syscalls',
                '--json-report', report_path
            ])
        with open(report_path) as fp:
            report = json.load(fp)
        self.clean()
        return report

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

def run_ltp(bug_id: str, tag: str, bucket_name: str, kgym_storage_prefix: str, work_dir_root: str) -> dict:
    work_dir = os.path.join(work_dir_root, bug_id, tag)
    os.makedirs(work_dir, exist_ok=True)
    stdout_fp = open(os.path.join(work_dir, 'stdout.txt'), 'w')
    try:
        client = storage.Client()
        job = LTPJob(bug_id, tag, client.bucket(bucket_name), kgym_storage_prefix, work_dir_root, stdout_fp)
        return { bug_id: { tag: { 'status': 'success', 'result': job.run() } } }
    except Exception:
        from traceback import format_exc
        return { bug_id: { tag: { 'status': 'exception', 'result': format_exc() } } }

class KirkCluster:

    def __init__(self, nproc: int):
        self.nproc = nproc
        self.work_dir = 'work_dir'
        os.makedirs(self.work_dir, exist_ok=True)
        self.scoreboard_path = os.path.join(self.work_dir, 'scoreboard.json')
        if not os.path.exists(self.scoreboard_path):
            with open(self.scoreboard_path, 'w') as fp:
                fp.write('{}')
        with open(self.scoreboard_path) as fp:
            self.scoreboard: dict = json.load(fp)

    def load_scoreboard(self):
        with open(self.scoreboard_path) as fp:
            self.scoreboard = json.load(fp)

    def save_scoreboard(self):
        with open(self.scoreboard_path, 'w') as fp:
            json.dump(self.scoreboard, fp)

    def submit_ltp_task_result(self, future: Future):
        self.scoreboard.update(future.result())
        self.save_scoreboard()

    def main(self, args):
        with open(args.filename) as fp:
            kernels = json.load(fp)
        with Pool(self.nproc) as executor:
            # [ { "bug-id": "", "tag": "", "kgym-bucket-name": "", "kgym-storage-prefix": "" } ]
            for test_job in kernels:
                executor.submit(
                    run_ltp, test_job['bug-id'], test_job['tag'], test_job['kgym-bucket-name'],
                    test_job['kgym-storage-prefix'], 'work_dir'
                ).add_done_callback(self.submit_ltp_task_result)

if __name__ == '__main__':
    parser = argparse.ArgumentParser('kirk Cluster')

    parser.add_argument('filename')
    parser.add_argument('-n', '--nproc', help='Number of processes in the pool', default=4, type=int)

    args = parser.parse_args(['-n', '2', 'kgym-input/syz-279-ltp-cluster-input-test.json'])

    cluster = KirkCluster(args.nproc)
    cluster.main(args)
