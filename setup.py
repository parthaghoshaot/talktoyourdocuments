from setuptools import setup

APP = ["launcher.py"]
DATA_FILES = [
    ("", ["app.py"]),
]

OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "streamlit",
        "fitz",
        "docx",
        "pptx",
        "openpyxl",
        "dotenv",
    ],
    "includes": [
        "openai",
        "google.genai",
    ],
    "plist": {
        "CFBundleName": "TalkToData",
        "CFBundleDisplayName": "TalkToData",
        "CFBundleIdentifier": "local.talktodata.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
