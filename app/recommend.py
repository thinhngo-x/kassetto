"""Compatibility shim: the recommender lives in the recsys package (see recsys/__init__.py).
`import recommend as rec` keeps working for app.py, library.py, spotify.py and tools."""
from recsys import *  # noqa: F401,F403
from recsys import _tokens, _lb, _bandit_key  # noqa: F401
from recsys.core import USER, LOCK, OWNER, DB  # noqa: F401
from recsys.sound import EMB  # noqa: F401
