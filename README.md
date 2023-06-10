pyketra
=======
A simple Python library for controlling a Ketra-brand system for lighting, etc.


Authors
-------
Greg Badros (gjbadros on github) built this package for the Vantage Controller lighting systems.



Installation
------------

Get the source from github, or use from pypi.


Example
-------
    import pyketra

    v = Ketra("192.168.0.x", "xxxxxx", 'Home')
    v.load_json_db(True)
    print v.outputs
    # use v to control lights


License
-------
This code is released under the MIT license.
