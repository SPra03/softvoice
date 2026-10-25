import os

from softvoice import autostart, instance


def test_login_item_runs_the_app_and_comes_back_only_after_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "APP_LOG", tmp_path / "app.log")
    d = autostart.plist(["--hands-free"])
    assert d["Label"] == autostart.LABEL
    assert d["ProgramArguments"][-2:] == ["app", "--hands-free"]
    assert d["RunAtLoad"] is True
    assert d["KeepAlive"] == {"SuccessfulExit": False}
    assert d["StandardOutPath"] == str(tmp_path / "app.log")


def test_second_app_sees_the_first_and_the_lock_goes_with_it(tmp_path, monkeypatch):
    monkeypatch.setattr(instance, "APP_PID_PATH", tmp_path / "app.pid")
    assert instance.claim() is None  # ours
    assert instance.running_pid() == os.getpid()
    assert instance.claim() == os.getpid()  # a second claim is told who has it
    instance.release()
    assert instance.running_pid() is None
