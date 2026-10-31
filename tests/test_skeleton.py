import importlib
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_app_package_importable():
    importlib.import_module("app")


def test_skeleton_dirs_exist():
    for d in ["app", "static/app", "static/admin", "scripts", "contract", "tests/js"]:
        assert (ROOT / d).is_dir(), d


def test_dependencies_importable():
    import fastapi
    import httpx
    import jsonschema
    import openpyxl
    import PIL
    import pydantic
    import uvicorn
