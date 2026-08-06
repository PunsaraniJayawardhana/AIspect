from backend.main import app


def test_app_imports():
    assert app.title == "AIspect API"
