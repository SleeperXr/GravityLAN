"""Tests for hostname resolution helpers (app/scanner/hostname.py)."""

import sys

import pytest

import app.scanner.hostname as hostname


# --- is_ip_like -------------------------------------------------------------

def test_is_ip_like_empty_is_true():
    assert hostname.is_ip_like(None) is True
    assert hostname.is_ip_like("") is True


def test_is_ip_like_ip_and_placeholders():
    assert hostname.is_ip_like("192.168.1.1") is True
    assert hostname.is_ip_like("unbekannt") is True
    assert hostname.is_ip_like("unknown") is True


def test_is_ip_like_real_hostname():
    assert hostname.is_ip_like("my-router") is False
    assert hostname.is_ip_like("printer.local") is False


# --- mask_ip ----------------------------------------------------------------

def test_mask_ip_masks_host_part():
    assert hostname.mask_ip("192.168.1.42") == "192.168.x.x"


def test_mask_ip_handles_malformed():
    assert hostname.mask_ip(None) == ""
    assert hostname.mask_ip("abc") == "x.x.x.x"


# --- _parse_ping_hostname ---------------------------------------------------

def test_parse_ping_hostname_extracts():
    out = (
        "Windows IP Configuration\n\n"
        "Pinging my-router [192.168.1.1] with 32 bytes of data:\n"
        "Reply from 192.168.1.1: bytes=32 time<1ms TTL=64\n"
    )
    assert hostname._parse_ping_hostname(out, "192.168.1.1") == "my-router"


def test_parse_ping_hostname_ignores_own_ip():
    assert hostname._parse_ping_hostname("Pinging 192.168.1.1 [192.168.1.1]", "192.168.1.1") is None


def test_parse_ping_hostname_no_match():
    assert hostname._parse_ping_hostname("no useful output", "10.0.0.1") is None


# --- _try_nmap --------------------------------------------------------------

def test_try_nmap_parses_report(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "Nmap scan report for nas.local (192.168.1.50)\nHost is up.\n"

    monkeypatch.setattr(hostname.subprocess, "run", lambda *a, **k: FakeResult())
    assert hostname._try_nmap("192.168.1.50") == "nas.local"


def test_try_nmap_ignores_ip_like_name(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "Nmap scan report for 192.168.1.50 (192.168.1.50)\n"

    monkeypatch.setattr(hostname.subprocess, "run", lambda *a, **k: FakeResult())
    assert hostname._try_nmap("192.168.1.50") is None


def test_try_nmap_nonzero_exit(monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(hostname.subprocess, "run", lambda *a, **k: FakeResult())
    assert hostname._try_nmap("192.168.1.50") is None


def test_try_nmap_error_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("nmap missing")

    monkeypatch.setattr(hostname.subprocess, "run", boom)
    assert hostname._try_nmap("192.168.1.50") is None


# --- _resolve_shell ---------------------------------------------------------

def test_resolve_shell_linux_delegates(monkeypatch):
    monkeypatch.setattr(hostname.sys, "platform", "linux")
    monkeypatch.setattr(hostname, "_resolve_linux_shell", lambda ip: "linux-name")
    assert hostname._resolve_shell("192.168.1.1") == "linux-name"


def test_resolve_shell_win32_delegates(monkeypatch):
    monkeypatch.setattr(hostname.sys, "platform", "win32")
    monkeypatch.setattr(hostname, "_resolve_ping_win32", lambda ip: "win-name")
    assert hostname._resolve_shell("192.168.1.1") == "win-name"
