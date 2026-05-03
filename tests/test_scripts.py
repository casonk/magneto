from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_shell_scripts_parse():
    result = subprocess.run(
        [
            "bash",
            "-n",
            str(REPO_ROOT / "scripts" / "transmission_vpn_guard.sh"),
            str(REPO_ROOT / "scripts" / "install_transmission_vpn_guard.sh"),
            str(REPO_ROOT / "scripts" / "apply_transmission_vpn_guard.sh"),
            str(REPO_ROOT / "scripts" / "apply_magneto_stack.sh"),
            str(REPO_ROOT / "scripts" / "diagnose_transmission_vpn.sh"),
            str(REPO_ROOT / "scripts" / "run_tachometer_profile.sh"),
            str(REPO_ROOT / "scripts" / "apply_host_setup.sh"),
            str(REPO_ROOT / "scripts" / "install_transmission_daemon_backend.sh"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_vpn_guard_render_restricts_transmission_to_vpn_interface():
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "transmission_vpn_guard.sh"),
            "render",
            "--uid",
            "1234",
            "--vpn-interface",
            "nordlynx",
            "--rpc-port",
            "9091",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'meta skuid 1234 oifname "nordlynx" counter accept' in result.stdout
    assert "meta skuid 1234 meta mark 0xe1f1 udp dport 51820 counter accept" in result.stdout
    assert (
        'meta skuid 1234 oifname "lo" ip daddr 127.0.0.53 udp dport 53 counter accept'
        in result.stdout
    )
    assert (
        'meta skuid 1234 oifname "lo" ip daddr 127.0.0.53 tcp dport 53 counter accept'
        in result.stdout
    )
    assert 'meta skuid 1234 oifname "lo" tcp sport 9091 counter accept' in result.stdout
    assert "reject with icmpx type admin-prohibited" in result.stdout


def test_vpn_guard_render_can_disable_loopback_dns():
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "transmission_vpn_guard.sh"),
            "render",
            "--uid",
            "1234",
        ],
        env={"ALLOW_LOOPBACK_DNS": "0"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "dport 53" not in result.stdout
    assert 'meta skuid 1234 oifname "lo" tcp sport 9091 counter accept' in result.stdout


def test_vpn_guard_render_can_disable_vpn_transport_allowance():
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "transmission_vpn_guard.sh"),
            "render",
            "--uid",
            "1234",
            "--no-vpn-transport",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "udp dport 51820" not in result.stdout


def test_vpn_guard_render_can_log_rejects():
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "transmission_vpn_guard.sh"),
            "render",
            "--uid",
            "1234",
            "--log-rejects",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'log prefix "magneto-transmission-reject "' in result.stdout


def test_vpn_guard_render_can_allow_local_dns_when_requested():
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "transmission_vpn_guard.sh"),
            "render",
            "--uid",
            "1234",
            "--allow-local-dns",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'meta skuid 1234 oifname "lo" counter accept' in result.stdout


def test_vpn_guard_missing_user_fails_before_rendering_blank_uid():
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "transmission_vpn_guard.sh"),
            "render",
            "--transmission-user",
            "definitely_missing_transmission_user",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "user not found" in result.stderr
    assert "meta skuid  " not in result.stdout
