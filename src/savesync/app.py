"""
Syncs EmuDeck saves with your cloud storage provider.
"""
import argparse
import logging
import os
import pathlib
import shlex
import socket
import subprocess
import sys
import threading
import time

import pexpect
import yaml
import zenity
from schema import Schema, Optional, SchemaError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

schema = Schema(
    {
        "remote": str,
        "sync-cooldown": str,
        "rclone-args": [str],
        "unison-args": [str]
    }
)

default_schema = Schema(
    {
        Optional("remote", default="saves"): str,
        Optional("sync-cooldown", default="watch"): str,
        Optional("rclone-args", default=[]): [str],
        Optional("unison-args", default=[]): [str]
    }
)

conf: dict


def resource_dir():
    return pathlib.Path(__file__).parent.joinpath("resources")


def bin_dir():
    return resource_dir().joinpath("bin") \
        if os.environ.get("APPDIR") is None else pathlib.Path(os.environ.get("APPDIR")).joinpath("usr/bin")


def run_cmd(command):
    process = subprocess.Popen(command)
    try:
        process.wait()
    except KeyboardInterrupt:
        try:
            process.terminate()
        except OSError:
            pass
        process.wait()


rclone: str = bin_dir().joinpath("rclone").__str__()
unison: str = bin_dir().joinpath("unison").__str__()
should_check: bool = True


def is_connected():
    try:
        sock = socket.create_connection(("www.google.com", 80))
        if sock is not None:
            sock.close()
        return True
    except OSError:
        pass
    return False


def thread__network_check():
    mount = F"{pathlib.Path.home()}/Emulation/tools/savesync/mount"
    while is_connected() and should_check:
        time.sleep(2)
    if should_check:
        run_cmd(["fusermount", "-u", mount])


def run(args):
    global conf
    run_cmd(["mkdir", "-p", F"{pathlib.Path.home()}/Emulation/tools/savesync"])
    if not os.path.exists(F"{pathlib.Path.home()}/Emulation/tools/savesync/config.yml"):
        with open(F"{pathlib.Path.home()}/Emulation/tools/savesync/config.yml", "w+") as f:
            yaml.dump(default_schema.validate({}), f)
    with open(F"{pathlib.Path.home()}/Emulation/tools/savesync/config.yml", "r") as f:
        conf = yaml.load(f, Loader=yaml.Loader)
        try:
            schema.validate(conf)
        except SchemaError as e:
            print(e)
        if args["setup"] is not None:
            p = pexpect.spawn(rclone, ["config"])
            e = p.expect(["Current remotes:", "No remotes found, make a new one?"])
            if e == 0 and pexpect.spawn(rclone, ["listremotes"]).expect(["saves:", pexpect.EOF]) == 0:
                logger.error("You are already setup. remove from rclone config and try again")
            else:
                p.sendline("n")
                p.expect("name>")
                p.sendline(conf.get("remote", "saves"))
                match args["setup"]:
                    case "gdrive":
                        setup_gdrive(p)
                    case "dropbox":
                        setup_dropbox(p)
                    case "onedrive":
                        setup_onedrive(p)
                    case "box":
                        setup_box(p)
                    case "nextcloud":
                        setup_nextcloud(p)
                p.expect("Yes this is OK")
                p.sendline("y")
                p.expect("Edit existing remote")
                p.sendline("q")
        elif args["sync"] is not None:
            sync(args["sync"])


def main():
    parser = argparse.ArgumentParser(prog="savesync", description="Syncs EmuDeck saves with your cloud storage "
                                                                  "provider.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup", type=str, choices=["gdrive", "dropbox", "onedrive", "box", "nextcloud"],
                       help="Setup and login SaveSync for the specified provider")
    group.add_argument("--sync", type=str, help="Run sync service")
    args = vars(parser.parse_args())
    sys.path.insert(0, bin_dir().__str__())
    if is_connected():
        run(args)
    else:
        logger.error("No internet connection")


def sync(path_in: str):
    global should_check
    network_check = threading.Thread(target=thread__network_check)
    network_check.start()
    mount = F"{pathlib.Path.home()}/Emulation/tools/savesync/mount"
    run_cmd(["mkdir", "-p", mount])
    run_cmd([rclone, "mkdir", F"{conf.get('remote', 'saves')}:/Emulation/saves/"])
    run_cmd([rclone, "mount", F"{conf.get('remote', 'saves')}:/Emulation/saves/", mount, "--daemon"] +
            shlex.split(os.environ.get("RCLONE_ARGS", subprocess.list2cmdline(conf.get("rclone-args", "")))))
    run_cmd([unison, mount, path_in, "-repeat", str(conf.get("sync-cooldown", "watch")), "-batch", "-copyonconflict",
             "-prefer", "newer", "-links", "true", "-follow", "Name *"] +
            shlex.split(os.environ.get("UNISON_ARGS", subprocess.list2cmdline(conf.get("unison-args", "")))))
    run_cmd(["fusermount", "-u", mount])
    should_check = False
    network_check.join()


def setup_gdrive(p: pexpect.spawn):
    p.expect("Storage>")
    p.sendline("drive")
    p.expect("client_id>")
    p.sendline("")
    p.expect("client_secret>")
    p.sendline("")
    p.expect("scope>")
    p.sendline("drive")
    p.expect("root_folder_id>")
    p.sendline("")
    p.expect("service_account_file>")
    p.sendline("")
    p.expect("Edit advanced config?")
    p.sendline("n")
    p.expect("Use auto config?")
    p.sendline("y")
    p.expect("Configure this as a Shared Drive (Team Drive)?")
    p.sendline("n")


def setup_dropbox(p: pexpect.spawn):
    p.expect("Storage>")
    p.sendline("dropbox")
    p.expect("client_id>")
    p.sendline("")
    p.expect("client_secret>")
    p.sendline("")
    p.expect("Edit advanced config?")
    p.sendline("n")
    p.expect("Use auto config?")
    p.sendline("y")


def setup_onedrive(p: pexpect.spawn):
    p.expect("Storage>")
    p.sendline("onedrive")
    p.expect("client_id>")
    p.sendline("")
    p.expect("client_secret>")
    p.sendline("")
    p.expect("Choose national cloud region for OneDrive.")
    p.sendline("global")
    p.expect("Edit advanced config?")
    p.sendline("n")
    p.expect("Use auto config?")
    p.sendline("y")
    p.expect("Type of connection")
    p.sendline("onedrive")
    p.expect("Drive OK?")
    p.sendline("y")


def setup_box(p: pexpect.spawn):
    p.expect("Storage>")
    p.sendline("box")
    p.expect("client_id>")
    p.sendline("")
    p.expect("client_secret>")
    p.sendline("")
    p.expect("box_config_file>")
    p.sendline("")
    p.expect("access_token>")
    p.sendline("")
    p.expect("box_sub_type>")
    p.sendline("user")
    p.expect("Edit advanced config?")
    p.sendline("n")
    p.expect("Use auto config?")
    p.sendline("y")


def setup_nextcloud(p: pexpect.spawn):
    p.expect("Storage>")
    p.sendline("webdav")
    p.expect("url>")
    p.sendline(zenity.show(zenity.entry, text="Url to NextCloud server")[1])
    p.expect("vendor>")
    p.sendline("nextcloud")
    login = zenity.show(zenity.password, "username")[1]
    username = login.split("|")[0].replace("\\n", "")
    password = login.split("|")[1].replace("\\n", "")
    p.expect("user>")
    p.sendline(username)
    p.expect("Option pass")
    p.sendline("y")
    p.expect("Enter the password:")
    p.sendline(password)
    p.expect("Confirm the password:")
    p.sendline(password)
    p.expect("bearer_token>")
    p.sendline("")
    p.expect("Edit advanced config?")
    p.sendline("n")
