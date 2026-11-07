import os
import sys
import tempfile

# make `import atlas_preprocess` / `import app` work when pytest is started from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Never open real camera hardware in tests, and never create folders in the user's home: importing app.py creates
# its inbox folder, so point both folders at a throw-away directory first.
os.environ.setdefault("ATLAS_CAMERA", "none")
# The API tests run with the random placeholder (fast, needs neither PyTorch nor the model files).  test_models.py
# switches to the real ensemble where the weights are available.
os.environ.setdefault("ATLAS_MOCK_MODELS", "1")
_SCRATCH = tempfile.mkdtemp(prefix="atlas_tests_")
os.environ.setdefault("ATLAS_INBOX_DIR", os.path.join(_SCRATCH, "inbox"))
os.environ.setdefault("ATLAS_SCAN_DIR", os.path.join(_SCRATCH, "scans"))
