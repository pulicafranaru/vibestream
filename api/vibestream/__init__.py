import os

VERSION = "1.0.0"
# Set in images built from main between releases: the commit's short hash.
BUILD = os.environ.get("VIBESTREAM_BUILD", "")
