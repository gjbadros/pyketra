#!/usr/local/bin/python3

import logging
from pyketra import Ketra

_LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG)

# Hostname, access_token after an OAuth2 exchange
# N4 is 192.168.0.230 locally
v = Ketra('HOSTNAME', 'PASSWORD_FROM_KETRA_API')
v.load_json_db()
print(v.outputs)
