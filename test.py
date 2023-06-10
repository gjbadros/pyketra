#!/usr/bin/env python3

import logging
from os import environ
from pyketra import Ketra

_LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG)

# Hostname, access_token after an OAuth2 exchange
# N4 is 192.168.2.72 locally
#v = Ketra('HOSTNAME', 'PASSWORD_FROM_KETRA_API', 'Pool house kitchen')
v = Ketra(environ['KETRA_HOSTNAME'], environ['KETRA_API_PASSWORD'], 'Pool house kitchen')
v.load_json_db(True)
print(v.outputs)
x = v.outputs[0]
print(x)
print("RGB = " + str(x.rgb))
print("HS = " + str(x.hs))
