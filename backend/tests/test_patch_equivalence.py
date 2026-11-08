"""Package update queries and the update stream behave as before the patch_service refactor.

Frozen copies of _query_apt_updates, the dnf/yum parsers and run_ssh_command_stream as of
0.7.0-rc.7 run next to the live functions against scripted SSH channels: output chunks, sudo
prompts (late, repeated, doubled in one chunk, split over two), idle ticks, data after exit, hangs until the
deadline and failing exit codes. Results, what was sent to the host and the streamed output
must match exactly.
"""

import asyncio
import inspect
import itertools
import re
import shlex
from types import SimpleNamespace

import pytest

import app.services.patch_service as ps

PROMPT = "SUDOPROMPT:"


# --- scripted SSH doubles ------------------------------------------------------------

class FakeChannel:
    """Steps: bytes (data ready), "idle" (nothing this tick), "exit" (exit status ready from now on)."""

    def __init__(self, steps, exit_code=0, exits=True):
        self.steps = list(steps)
        self.exit_code = exit_code
        self.exits = exits
        self.exited = False
        self.sent, self.closed, self.cmd = [], False, None

    def set_combine_stderr(self, _value):
        pass

    def exec_command(self, cmd):
        self.cmd = cmd

    def recv_ready(self):
        if self.steps and isinstance(self.steps[0], bytes):
            return True
        if self.steps and self.steps[0] == "idle":
            self.steps.pop(0)
        elif self.steps and self.steps[0] == "exit":
            self.steps.pop(0)
            self.exited = True
        return False

    def exit_status_ready(self):
        return self.exited or (self.exits and not self.steps)

    def recv(self, _n):
        return self.steps.pop(0)

    def send(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True

    def recv_exit_status(self):
        return self.exit_code


class FakeClient:
    def __init__(self, channel, outputs):
        self.channel = channel
        self.outputs = outputs
        self.commands = []

    def get_transport(self):
        return SimpleNamespace(open_session=lambda: self.channel)

    def exec_command(self, cmd, timeout=None):
        self.commands.append(cmd)
        out = self.outputs.get(cmd, "")
        return None, SimpleNamespace(read=lambda: out.encode()), None

    def close(self):
        pass


class FakeClock:
    """time.monotonic advances half a second per call, time.sleep returns at once."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += 0.5
        return self.now

    def sleep(self, _seconds):
        pass


@pytest.fixture(autouse=True)
def fast_clock(monkeypatch):
    monkeypatch.setattr(ps, "time", FakeClock())
    real_sleep = asyncio.sleep

    async def no_wait(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(ps, "asyncio", SimpleNamespace(sleep=no_wait, to_thread=asyncio.to_thread))


# --- frozen copies (0.7.0-rc.7) ----------------------------------------------------------

def _old_query_apt_updates(client, result, host_ip, ssh_user, ssh_password):
    needs_sudo = ssh_user != "root"
    if not needs_sudo:
        update_cmd = "apt-get update"
    elif ssh_password:
        update_cmd = "sudo -S -p 'SUDOPROMPT:' apt-get update"
    else:
        update_cmd = "sudo -n apt-get update"

    chan = client.get_transport().open_session()
    chan.set_combine_stderr(True)
    chan.exec_command(update_cmd)

    update_output = ""
    password_sent = False
    sudo_rejected = False
    update_deadline = ps.time.monotonic() + 90
    while ps.time.monotonic() < update_deadline:
        if chan.recv_ready():
            chunk = chan.recv(4096).decode("utf-8", errors="replace")
            update_output += chunk
            if needs_sudo and ssh_password and PROMPT in chunk:
                if not password_sent:
                    ps.time.sleep(0.05)
                    chan.send(f"{ssh_password}\n")
                    password_sent = True
                    chunk = chunk.replace(PROMPT, "", 1)
                if PROMPT in chunk or update_output.count(PROMPT) >= 2:
                    sudo_rejected = True
                    chan.close()
                    break
            elif password_sent and update_output.count(PROMPT) >= 2:
                sudo_rejected = True
                chan.close()
                break
        elif chan.exit_status_ready():
            while chan.recv_ready():
                update_output += chan.recv(4096).decode("utf-8", errors="replace")
            break
        ps.time.sleep(0.1)

    update_exit = None if sudo_rejected else (chan.recv_exit_status() if chan.exit_status_ready() else None)
    if sudo_rejected:
        result["sudo_rejected"] = True
        result["error"] = (
            f"Sudo password rejected on {host_ip} for user '{ssh_user}'. "
            "Please check your SSH/sudo password or enable passwordless sudo."
        )
    elif update_exit != 0:
        hint = " Set an SSH password or enable passwordless sudo to refresh package lists." if needs_sudo and not ssh_password else ""
        result["error"] = "apt-get update failed (exit %s).%s" % (
            update_exit if update_exit is not None else "timeout", hint,
        )

    _, stdout, _ = client.exec_command("apt list --upgradable 2>/dev/null", timeout=15)
    output = stdout.read().decode("utf-8")
    for line in output.splitlines():
        if "upgradable from" in line:
            match = re.match(r"^([^/]+)/([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+\[upgradable from:\s+([^\]]+)\]", line)
            if match:
                pkg_name, suite, new_ver, arch, old_ver = match.groups()
                result["packages"].append({
                    "package": pkg_name, "current_version": old_ver, "new_version": new_ver, "repo": suite
                })

    _, stdout, _ = client.exec_command("which do-release-upgrade", timeout=5)
    if stdout.read().decode().strip():
        _, stdout, _ = client.exec_command("do-release-upgrade -c", timeout=10)
        out_upgrade = stdout.read().decode("utf-8")
        for line in out_upgrade.splitlines():
            if "New release" in line and "available" in line:
                parts = line.split("'")
                if len(parts) >= 3:
                    result["major_upgrade_available"] = parts[1]


def _old_query_dnf_updates(client, result):
    _, stdout, _ = client.exec_command("dnf check-update --quiet", timeout=20)
    output = stdout.read().decode("utf-8")
    upgrades, pkg_names = [], []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("Last metadata"):
            pkg_name = parts[0].rsplit(".", 1)[0]
            upgrades.append({"package": pkg_name, "new_version": parts[1], "repo": parts[2], "current_version": "Installed"})
            pkg_names.append(pkg_name)
    if pkg_names:
        quoted_pkgs = " ".join(shlex.quote(p) for p in pkg_names[:100])
        batch_cmd = f"rpm -q --qf '%{{NAME}} %{{VERSION}}-%{{RELEASE}}\\n' {quoted_pkgs}"
        _, stdout_rpm, _ = client.exec_command(batch_cmd, timeout=10)
        rpm_output = stdout_rpm.read().decode("utf-8")
        version_map = {}
        for line in rpm_output.splitlines():
            subparts = line.split()
            if len(subparts) == 2:
                version_map[subparts[0]] = subparts[1]
        for item in upgrades:
            if item["package"] in version_map:
                item["current_version"] = version_map[item["package"]]
    result["packages"] = upgrades


def _old_query_yum_updates(client, result):
    _, stdout, _ = client.exec_command("yum check-update --quiet", timeout=20)
    output = stdout.read().decode("utf-8")
    upgrades = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            pkg_name = parts[0].rsplit(".", 1)[0]
            upgrades.append({"package": pkg_name, "new_version": parts[1], "repo": parts[2], "current_version": "Installed"})
    result["packages"] = upgrades


async def _old_run_ssh_command_stream(*, host_ip, ssh_user, ssh_password=None, ssh_key=None, ssh_port=22,
                                      command, output_callback, ssh_key_passphrase=None,
                                      pinned_host_key=None, tofu_policy=None):
    client = ps._build_client(pinned_host_key=pinned_host_key, tofu_policy=tofu_policy)
    try:
        connect_kwargs, err = ps._build_connect_kwargs(host_ip, ssh_user, ssh_port, ssh_password, ssh_key, ssh_key_passphrase)
        if err:
            return False, err
        needs_sudo = ssh_user != "root"
        if not needs_sudo:
            run_cmd = command
        elif ssh_password:
            run_cmd = f"sudo -S -p '{PROMPT}' sh -c {shlex.quote(command)}"
        else:
            run_cmd = f"sudo -n sh -c {shlex.quote(command)}"

        channel = await ps.asyncio.to_thread(ps._open_command_channel, client, connect_kwargs, host_ip, run_cmd)
        if channel is None:
            return False, "Failed to get SSH transport channel."

        password_sent = False
        sudo_rejected = False
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    break
                if needs_sudo and ssh_password and PROMPT in chunk:
                    if not password_sent:
                        await ps.asyncio.sleep(0.05)
                        channel.send(f"{ssh_password}\n")
                        password_sent = True
                        chunk = chunk.replace(PROMPT, "", 1)
                    if PROMPT in chunk:
                        sudo_rejected = True
                        chunk = chunk.replace(PROMPT, "")
                if chunk:
                    result = output_callback(chunk)
                    if inspect.isawaitable(result):
                        await result
                if sudo_rejected:
                    channel.close()
                    return False, f"Sudo password rejected on {host_ip} for user '{ssh_user}'. Please check your SSH/sudo password."
            elif channel.exit_status_ready():
                if not channel.recv_ready():
                    break
            await ps.asyncio.sleep(0.1)

        exit_code = await ps.asyncio.to_thread(channel.recv_exit_status)
        if exit_code == 0:
            return True, "Success"
        return False, f"Command exited with code {exit_code}"
    except Exception as e:
        return False, str(e)
    finally:
        client.close()


# --- scenarios -----------------------------------------------------------------------

USERS = [("root", None), ("root", "pw"), ("oliver", None), ("oliver", "pw")]

UPDATE_SCRIPTS = [
    ([b"Hit:1 http://archive jammy InRelease\n", b"Reading package lists... Done\n"], 0, True),
    ([b"SUDOPROMPT:", "idle", b"Reading package lists... Done\n"], 0, True),
    (["idle", "idle", b"SUDOPROMPT:", b"Done\n"], 0, True),
    ([b"SUDOPROMPT:", b"Sorry, try again.\nSUDOPROMPT:"], 0, True),
    ([b"SUDOPROMPT:SUDOPROMPT:"], 0, True),
    ([b"SUDOPROMPT:", "idle", b"Sorry\n", b"SUDOPROMPT:"], 1, True),
    ([b"E: The repository is not signed.\n"], 100, True),
    ([b"working\n", "exit", b"late output\n"], 0, True),
    ([b"working\n", "exit"], 1, True),
    ([], 0, False),  # hangs until the deadline
    ([b"sudo: a password is required\n"], 1, True),
]

UPGRADABLE = [
    "",
    "Listing... Done\n"
    "curl/jammy-updates 7.81.0-1ubuntu1.16 amd64 [upgradable from: 7.81.0-1ubuntu1.15]\n"
    "libssl3/jammy-security,jammy-updates 3.0.2-0ubuntu1.15 amd64 [upgradable from: 3.0.2-0ubuntu1.14]\n"
    "broken line [upgradable from: x\n"
    "plain-package 1.0 all\n",
]

RELEASE = [
    ("", ""),
    ("/usr/bin/do-release-upgrade", "Checking for a new Ubuntu release\nNew release '24.04.1 LTS' available.\nRun 'do-release-upgrade'\n"),
    ("/usr/bin/do-release-upgrade", "No new release found.\n"),
    ("/usr/bin/do-release-upgrade", "New release available but no quotes\n"),
]


def _apt_outputs(listing, which, release_check):
    return {"apt list --upgradable 2>/dev/null": listing, "which do-release-upgrade": which, "do-release-upgrade -c": release_check}


def _run_apt(fn, script, user, password, outputs):
    steps, code, exits = script
    chan = FakeChannel(steps, code, exits)
    client = FakeClient(chan, outputs)
    result = {"patch_manager": "apt", "packages": [], "major_upgrade_available": None}
    fn(client, result, "192.0.2.5", user, password)
    return result, chan.cmd, chan.sent, chan.closed, client.commands


def _live_query_apt_updates(client, result, host_ip, ssh_user, ssh_password):
    ps._query_apt_updates(client, result, ps._SshLogin(host_ip, ssh_user, ssh_password=ssh_password))


def test_apt_query_matches_for_every_update_run_listing_and_release_check():
    diffs, count = [], 0
    for script, (user, password), listing, (which, release_check) in itertools.product(UPDATE_SCRIPTS, USERS, UPGRADABLE, RELEASE):
        outputs = _apt_outputs(listing, which, release_check)
        before = _run_apt(_old_query_apt_updates, script, user, password, outputs)
        now = _run_apt(_live_query_apt_updates, script, user, password, outputs)
        count += 1
        if before != now:
            diffs.append((script, user, password, before, now))
    assert count == len(UPDATE_SCRIPTS) * len(USERS) * len(UPGRADABLE) * len(RELEASE)
    assert diffs[:2] == []


# Every way a prompt can land on the wire: whole, doubled, split over two reads, nested so
# that removing it leaves another one, plus empty reads, idle ticks and data after exit.
PROMPT_STEPS = [
    b"SUDOPROMPT:", b"SUDOPROMPT:SUDOPROMPT:", b"SUDO", b"PROMPT:", b"SUDOSUDOPROMPT:PROMPT:",
    b"", b"text\n", "idle", "exit",
]


def _prompt_scripts(longest):
    for length in range(longest + 1):
        yield from itertools.product(PROMPT_STEPS, repeat=length)


def test_apt_query_matches_for_every_way_a_prompt_can_arrive():
    outputs = _apt_outputs("", "", "")
    diffs = []
    for steps, (user, password) in itertools.product(_prompt_scripts(4), USERS):
        script = (list(steps), 1, True)
        before = _run_apt(_old_query_apt_updates, script, user, password, outputs)
        now = _run_apt(_live_query_apt_updates, script, user, password, outputs)
        if before != now:
            diffs.append((steps, user, password, before, now))
    assert diffs[:2] == []


def test_a_second_prompt_split_across_two_reads_is_a_rejection():
    chan = FakeChannel([b"SUDOPROMPT:", b"Sorry\nSUDO", b"PROMPT:", b"never read\n"])
    assert ps._read_apt_update(chan, "pw") == ("SUDOPROMPT:Sorry\nSUDOPROMPT:", True)
    assert chan.sent == ["pw\n"]
    assert chan.closed
    assert chan.steps == [b"never read\n"]


def test_a_first_prompt_split_across_two_reads_goes_unanswered():
    chan = FakeChannel([b"SUDO", b"PROMPT:", b"Done\n"])
    assert ps._read_apt_update(chan, "pw") == ("SUDOPROMPT:Done\n", False)
    assert chan.sent == []
    assert not chan.closed


def test_without_a_password_a_prompt_is_only_text():
    chan = FakeChannel([b"SUDOPROMPT:", b"SUDOPROMPT:"])
    assert ps._read_apt_update(chan, None) == ("SUDOPROMPT:SUDOPROMPT:", False)
    assert chan.sent == []
    assert not chan.closed


CHECK_UPDATE = [
    "",
    "Last metadata expiration check: 0:15:32 ago on Fri Jul 17 09:00:00 2026.\n\n"
    "curl.x86_64               7.81.0-1.fc39             updates\n"
    "libssl.x86_64             3.0.2-1.fc39              updates\n"
    "kernel-core.x86_64        6.8.9-300.fc40            updates-testing\n"
    "short line\n"
    "noarch-only               1.0                        base   extra\n",
    "Obsoleting Packages\nfoo.noarch 1 base\n",
]
RPM_Q = ["", "curl 7.81.0-1.fc38\nlibssl 3.0.2-1.fc38\nweird line here\n", "package kernel-core is not installed\n"]


@pytest.mark.parametrize(("check_update", "rpm_q"), list(itertools.product(CHECK_UPDATE, RPM_Q)))
def test_dnf_and_yum_parsing_match(check_update, rpm_q):
    def outputs_with_rpm():
        # The rpm batch command depends on the package names; answer any rpm -q with rpm_q
        class Outputs(dict):
            def get(self, cmd, default=""):
                return rpm_q if cmd.startswith("rpm -q") else super().get(cmd, default)
        return Outputs({"dnf check-update --quiet": check_update, "yum check-update --quiet": check_update})

    for old, new in ((_old_query_dnf_updates, ps._query_dnf_updates), (_old_query_yum_updates, ps._query_yum_updates)):
        results = []
        for fn in (old, new):
            client = FakeClient(None, outputs_with_rpm())
            result = {"packages": []}
            fn(client, result)
            results.append((result, client.commands))
        assert results[0] == results[1]


STREAM_SCRIPTS = [
    ([b"Reading package lists...\n", b"Done\n"], 0),
    ([b"SUDOPROMPT:", b"Reading package lists... Done\r\n"], 0),
    (["idle", "idle", b"SUDOPROMPT:", "idle", b"output\n"], 0),
    ([b"SUDOPROMPT:", b"Sorry, try again.\nSUDOPROMPT:"], 1),
    ([b"before SUDOPROMPT:SUDOPROMPT: after"], 1),
    ([b"line\n", b"", b"never read\n"], 0),  # an empty chunk is EOF
    ([b"E: dpkg was interrupted\n"], 100),
    ([b"working\n", "exit"], 0),
    ([b"SUDOPROMPT:"], 0),
]


async def _run_stream(fn, monkeypatch, script, user, password, async_cb):
    steps, code = script
    chan = FakeChannel(steps, code)
    monkeypatch.setattr(ps, "_build_client", lambda **_kw: FakeClient(chan, {}))
    monkeypatch.setattr(ps, "_build_connect_kwargs", lambda *_a: ({}, None))

    def open_channel(_client, _kwargs, _ip, run_cmd):
        chan.exec_command(run_cmd)
        return chan

    monkeypatch.setattr(ps, "_open_command_channel", open_channel)
    received = []

    if async_cb:
        async def callback(text):
            received.append(text)
    else:
        callback = received.append

    outcome = await fn(host_ip="192.0.2.5", ssh_user=user, ssh_password=password,
                       command="DEBIAN_FRONTEND=noninteractive apt-get -y upgrade $(echo x)", output_callback=callback)
    return outcome, chan.cmd, chan.sent, chan.closed, received


@pytest.mark.asyncio
async def test_update_stream_matches_for_every_script_user_and_callback(monkeypatch):
    diffs = []
    for script, (user, password), async_cb in itertools.product(STREAM_SCRIPTS, USERS, (False, True)):
        before = await _run_stream(_old_run_ssh_command_stream, monkeypatch, script, user, password, async_cb)
        now = await _run_stream(ps.run_ssh_command_stream, monkeypatch, script, user, password, async_cb)
        if before != now:
            diffs.append((script, user, password, async_cb, before, now))
    assert diffs[:2] == []


@pytest.mark.asyncio
async def test_update_stream_matches_for_every_way_a_prompt_can_arrive(monkeypatch):
    diffs = []
    for steps, (user, password) in itertools.product(_prompt_scripts(3), USERS):
        script = (list(steps), 1)
        before = await _run_stream(_old_run_ssh_command_stream, monkeypatch, script, user, password, False)
        now = await _run_stream(ps.run_ssh_command_stream, monkeypatch, script, user, password, False)
        if before != now:
            diffs.append((steps, user, password, before, now))
    assert diffs[:2] == []


@pytest.mark.asyncio
async def test_update_stream_reports_a_missing_channel_and_connect_errors(monkeypatch):
    for fn in (_old_run_ssh_command_stream, ps.run_ssh_command_stream):
        monkeypatch.setattr(ps, "_build_client", lambda **_kw: FakeClient(None, {}))
        monkeypatch.setattr(ps, "_build_connect_kwargs", lambda *_a: ({}, "no key"))
        assert await fn(host_ip="h", ssh_user="root", command="x", output_callback=print) == (False, "no key")

        monkeypatch.setattr(ps, "_build_connect_kwargs", lambda *_a: ({}, None))
        monkeypatch.setattr(ps, "_open_command_channel", lambda *_a: None)
        assert await fn(host_ip="h", ssh_user="root", command="x", output_callback=print) == (
            False, "Failed to get SSH transport channel.")

        def boom(*_a):
            raise OSError("connection refused")

        monkeypatch.setattr(ps, "_open_command_channel", boom)
        assert await fn(host_ip="h", ssh_user="root", command="x", output_callback=print) == (False, "connection refused")
