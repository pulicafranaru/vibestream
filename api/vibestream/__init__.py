import os

VERSION = "1.1.1"
# Set in images built from main between releases: the commit's short hash.
BUILD = os.environ.get("VIBESTREAM_BUILD", "")
