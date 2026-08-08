# -*- coding: utf-8 -*-
"""wa_login 配对码登录 + providers config-schema 按 kind 出模板 的单测。

wa_login 的 Popen 全程 mock，不真正启动 node 进程；
WA_CHECK_DIR 指向 tmp_path，避免触碰真实会话目录。
"""

import pytest

from app import wa_login
from app.api import providers as providers_api
from fastapi import HTTPException


class _FakeStdout:
    def readline(self):
        return b""


class _FakeProc:
    """最小 Popen 替身：立即退出的空输出进程。"""

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.stdout = _FakeStdout()
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass


@pytest.fixture()
def wa_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(wa_login, "WA_CHECK_DIR", tmp_path)
    monkeypatch.setattr(wa_login.subprocess, "Popen", _FakeProc)
    wa_login._sessions.clear()
    yield tmp_path
    wa_login._sessions.clear()


# ---------- 手机号校验 ----------

def test_validate_pairing_phone_ok():
    assert wa_login.validate_pairing_phone("8613800138000") == "8613800138000"


@pytest.mark.parametrize("bad", ["", None, "+8613800138000", "1234567",
                                 "861380013800012345", "abc12345678"])
def test_validate_pairing_phone_bad(bad):
    with pytest.raises(wa_login.LoginError) as ei:
        wa_login.validate_pairing_phone(bad)
    assert ei.value.status_code == 422


# ---------- start_login pairing ----------

def test_start_login_pairing_cmd(wa_dir):
    wa_login.start_login("t1", method="pairing", phone="8613800138000")
    sess = wa_login._sessions["t1"]
    cmd = sess["proc"].cmd
    assert "--pairing=8613800138000" in cmd
    assert "--auth=t1" in cmd
    assert sess["method"] == "pairing"


def test_start_login_pairing_requires_phone(wa_dir):
    with pytest.raises(wa_login.LoginError) as ei:
        wa_login.start_login("t1", method="pairing", phone=None)
    assert ei.value.status_code == 422


def test_start_login_bad_method(wa_dir):
    with pytest.raises(wa_login.LoginError) as ei:
        wa_login.start_login("t1", method="sms")
    assert ei.value.status_code == 422


def test_start_login_qr_unchanged(wa_dir):
    """qr 方式（默认）不拼 --pairing，行为与历史一致。"""
    wa_login.start_login("t2")
    sess = wa_login._sessions["t2"]
    assert not any(a.startswith("--pairing=") for a in sess["proc"].cmd)
    assert sess["method"] == "qr"


def test_start_login_pairing_clears_stale_code(wa_dir):
    """启动 pairing 登录前删除旧配对码文件，防串码。"""
    stale = wa_dir / "pairing-auth_info-t3.txt"
    stale.write_text("OLDCODE1", encoding="utf-8")
    wa_login.start_login("t3", method="pairing", phone="8613800138000")
    assert not stale.exists()


# ---------- get_state / pairing_code ----------

def test_get_state_pairing_reads_code_file(wa_dir):
    wa_login.start_login("t4", method="pairing", phone="8613800138000")
    # 进程已退出（fake），模拟 check.js 落盘配对码
    (wa_dir / "pairing-auth_info-t4.txt").write_text(
        "ABCD1234", encoding="utf-8")
    st = wa_login.get_state("t4")
    assert st["method"] == "pairing"
    assert st["pairing_code"] == "ABCD1234"


def test_get_state_qr_no_pairing_code(wa_dir):
    wa_login.start_login("t5")
    st = wa_login.get_state("t5")
    assert st["method"] == "qr"
    assert st["pairing_code"] is None


def test_get_state_no_session(wa_dir):
    st = wa_login.get_state("ghost")
    assert st["state"] == "idle"
    assert st["method"] is None
    assert st["pairing_code"] is None


# ---------- delete_account 清理 pairing 文件 ----------

def test_delete_account_removes_pairing_file(wa_dir):
    auth = wa_dir / "auth_info-t6"
    auth.mkdir()
    pairing = wa_dir / "pairing-auth_info-t6.txt"
    pairing.write_text("ABCD1234", encoding="utf-8")
    out = wa_login.delete_account("t6")
    assert not pairing.exists()
    assert "pairing-auth_info-t6.txt" in out["removed"]


# ---------- config-schema 按 kind ----------

def test_config_schema_apify():
    out = providers_api.config_schema(kind="apify")
    assert out["kind"] == "apify"
    assert "api_token" in out["provider_config_structure"]


def test_config_schema_default_qingguo():
    out = providers_api.config_schema()
    assert out["kind"] == "qingguo"
    assert "key" in out["provider_config_structure"]
    assert "tunnel_cache_path" in out  # 历史字段保留


def test_config_schema_unknown_kind():
    with pytest.raises(HTTPException) as ei:
        providers_api.config_schema(kind="foo")
    assert ei.value.status_code == 422
