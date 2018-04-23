"""
Ketra Controller module for interacting with a Ketra N4 module for LED Lighting
Basic operations for enumerating and controlling the loads are supported.

Author: Greg J. Badros

Based on pyvantage which was written by Greg but was based on
pylutron written by Dima Zavin

To use with home assistant and its virtual python environment, you need to:

$ cd .../path/to/home-assistant/
$ pip3 install --upgrade .../path/to/pyketra

Then the component/ketra.py and its require line will work.

"""

__Author__ = "Greg J. Badros"
__copyright__ = "Copyright 2018, Greg J. Badros"
 # Dima Zavin wrote pylutron on which this is based

import logging
import threading
import time
import base64
import re
import json
import requests
import socket
from math import log
from urllib.parse import quote
from colormath.color_objects import LabColor, xyYColor, sRGBColor
from colormath.color_conversions import convert_color

_LOGGER = logging.getLogger(__name__)

def xml_escape(s):
  answer = s.replace("<", "&lt;")
  answer = answer.replace("&", "&amp;")
  return answer


# From http://www.tannerhelland.com/4435/convert-temperature-rgb-algorithm-code/
# returns [red, green, blue]
def cctKelvin_to_rgbColor(kelvin):
  temp = kelvin/100
  
  # calc red
  if temp <= 66:
    red = 255
  else:
    red = temp - 60
    red = 329.698727446 * (red ** -0.1332047592)
    if red < 0:
      red = 0
    elif red > 255:
      red = 255

  # calc green
  if temp <= 66:
    green = temp
    green = 99.4708025861 * log(green) - 161.1195681661
  else:
    green = temp - 60
    green = 288.1221695283 * (green ** -0.0755148492)
  if green < 0:
    green = 0
  elif green > 255:
    green = 255
  
  # calc blue
  if temp >= 66:
    blue = 255
  else:
    if temp <=19:
      blue = 0
    else:
      blue = temp - 10
      blue = 138.5177312231 * log(blue) - 305.0447927307
      if blue < 0:
        blue = 0
      elif blue > 255:
        blue = 255

  return [red, green, blue]


# return [x,y]
def cctKelvin_to_xyColor(kelvin):
  [red, green, blue] = cctKelvin_to_rgbColor(kelvin)
  _LOGGER.info("kelvin %s converts to %d,%d,%d" % (kelvin, red, green, blue))
  srgb = sRGBColor(red, green, blue)
  xyY = convert_color(srgb, xyYColor)
  return [xyY.xyy_x, xyY.xyy_y]


# ===================================================================================
# Support function to get the local IP address for N4 discovery
# ===================================================================================
def getMyIpAddress():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 0))
    outgoing_ip_address = s.getsockname()[0]
    return outgoing_ip_address

# ===================================================================================
# Support function to discover an N4 device given its serial number
# ===================================================================================
def discoverN4Device(n4SerialNumber):
    print("Discovering N4 with serial number " + n4SerialNumber)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    outgoing_ip_address = getMyIpAddress()
    print("Using local interface " + outgoing_ip_address)
    sock.bind((outgoing_ip_address, 0))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)
    for m in range(5):
        time.sleep(.1)
        try:
            sock.sendto("*", ('255.255.255.255', 4934))
        except (socket.error, e):
            print (ip, e)
        
        t_end = time.time() + 1
        while time.time() < t_end:
            try:
                data, addr = sock.recvfrom(1024)
                response = dict([s.split("=") for s in data.splitlines()])
                response["address"] = str(addr[0])
                if (response["serial"] == n4SerialNumber):
                    print("Found N4 at address " + response["address"])
                    return response["address"]
            except socket.error:
                pass
    return None

class KetraException(Exception):
  """Top level module exception."""
  pass


class IDExistsError(KetraException):
  """Asserted when there's an attempt to register a duplicate integration id."""
  pass


class ConnectionExistsError(KetraException):
  """Raised when a connection already exists (e.g. user calls connect() twice)."""
  pass


class KetraConnection(threading.Thread):
  """Encapsulates the connection to the Ketra controller."""

  def __init__(self, host, password):
    """Initializes the ketra connection, doesn't actually connect."""
    threading.Thread.__init__(self)

    self._host = host
    self._password = password
    self._done = False

    self.setDaemon(True)


  # KetraConnection
  def run(self):
    """Main thread function to maintain connection and receive remote status."""
    _LOGGER.info("Started")
    while True:
      sleep(10)


class KetraJsonDbParser(object):
  """The parser for Ketra JSON database.

  The database describes all the rooms (Area), keypads (Device), and switches
  (Output). We handle the most relevant features, but some things like LEDs,
  etc. are not implemented."""

  def __init__(self, ketra, json_db):
    """Initializes the JSON parser, takes the JSON data as structured object."""
    self._ketra = ketra
    self._json_db = json_db
    self.outputs = []
    self.id_to_area = {}
    self.id_to_load = {}
    self.id_to_keypad = {}
    self.id_to_button = {}
    
    self.project_name = None

  def parse(self):
    """Main entrypoint into the parser. It interprets and creates all the
    relevant Ketra objects and stuffs them into the appropriate hierarchy."""

    area = self._parse_area("Ketra_Area") # FIXME: maybe do this off the N4 ip or hostname
    _LOGGER.info("area = " + str(area))
    self.id_to_area[area.id] = area

    for load_json in self._json_db:
      output = self._parse_output(load_json)
      if output is None:
        continue
      self.outputs.append(output)
      self.id_to_load[output.id] = output
      _LOGGER.info("output = " + str(output))
      self.id_to_area[output.area].add_output(output)

    return True

  def _parse_area(self, hostname):
    """Parses an Area tag, which is effectively a room, depending on how the
    Ketra controller programming was done."""
    area = Area(self._ketra,
                name=hostname,
                parent=None,
                id=hostname,
                note='')
    return area

  def _parse_output(self, output_json):
    """Parses a load, which is generally a switch controlling a set of
    lights/outlets, etc."""
    out_name = output_json['Name']
    if out_name:
      out_name = out_name.strip()
    else:
      _LOGGER.info("Using dname = " + out_name)
    area_id = 'Ketra_Area'  # FIXME

#    area_name = self.id_to_area[area_id].name
    load_type = "Ketra"

    output = Output(self._ketra,
                    name=out_name,
                    area=area_id,
                    output_type='light',
                    load_type=load_type,
                    id=output_json['Id'])
    return output

  def _parse_keypad(self, keypad_json):
    """Parses a keypad device."""
    area_id = int(keypad_json.find('Area').text)
    keypad = Keypad(self._ketra,
                    name=keypad_json.find('Name').text,
                    area=area_id,
                    id=int(keypad_json.get('ID')))
    return keypad

  def _parse_button(self, component_json):
    """Parses a button device that part of a keypad."""
    button_json = component_json.find('Button')
    name = button_json.get('Engraving')
    button_type = button_json.get('ButtonType')
    direction = button_json.get('Direction')
    # Hybrid keypads have dimmer buttons which have no engravings.
    if button_type == 'SingleSceneRaiseLower':
      name = 'Dimmer ' + direction
    if not name:
      name = "Unknown Button"
    button = Button(self._ketra,
                    name=name,
                    num=int(component_json.get('ComponentNumber')),
                    button_type=button_type,
                    direction=direction)
    return button

class Ketra(object):
  """Main Ketra Controller class.

  This object owns the connection to the controller, the rooms that exist in the
  network, handles dispatch of incoming status updates, etc.
  """

  # See ketra host commands reference (you may need to be a dealer/integrator for access)
  OP_RESPONSE = 'R:'        # Response lines come back from Ketra with this prefix
  OP_STATUS = 'S:'          # Status report lines come back from Ketra with this prefix

  def __init__(self, host, password):
    """Initializes the Ketra object. No connection is made to the remote
    device."""
    self._host = host
    self._password = password
    self._name = None
    self._conn = KetraConnection(host, password)
    self._ids = {}
    self._names = {}   # maps from unique name to id
    self._subscribers = {}
    self._id_to_area = {}  # copied out from the parser
    self._id_to_load = {}  # copied out from the parser
    self._r_cmds = [ 'LOGIN', 'LOAD', 'STATUS', 'GETLOAD' ]
    self._s_cmds = [ 'LOAD', 'TASK', 'LED' ]

  def subscribe(self, obj, handler):
    """Subscribes to status updates of the requested object.

    The handler will be invoked when the controller sends a notification
    regarding changed state. The user can then further query the object for the
    state itself."""
    self._subscribers[obj] = handler

  #TODO: cleanup this awful logic
  def register_id(self, cmd_type, obj):
    """Registers an object (through its id [ketra id]) to receive update
    notifications. This is the core mechanism how Output and Keypad objects get
    notified when the controller sends status updates."""
    ids = self._ids.setdefault(cmd_type, {})
    if obj.id in ids:
      raise IDExistsError("ID exists %s" % obj.id)
    self._ids[cmd_type][obj.id] = obj
    obj.name = obj.name.title().strip()
    if obj.name in self._names:
      area = self._id_to_area.get(int(obj.area))
      oldname = obj.name
      newname = obj.name
#      newname = "%s %s" % (area.name.title().strip(), obj.name)
#      obj.name = newname
      i = 2
      while obj.name in self._names:
        obj.name = newname + " " + str(i)
        i += 1
      _LOGGER.warning("Repeated name `%s' in area %s - using %s" % (oldname, area.name, obj.name))
    self._names[obj.name] = obj.id

  def connect(self):
    """Connects to the Ketra controller to send and receive commands and status"""
    self._conn.connect()

  def load_json_db(self, disable_cache):
    """Load the Ketra database from the server."""
    filename = self._host + "_ketraconfig.txt"
    json_db = ""
    try:
      if not disable_cache:
        f = open(filename, "r")
        json_db = json.loads(f.read())['Content']
        f.close()
        _LOGGER.warning("read cached ketra configuration file " + filename)
      else:
        raise Exception("nocache")
    except Exception as e:
      _LOGGER.error("Exception = " + str(e))
      groupsUrl = 'https://' + self._host + '/ketra.cgi/api/v1/groups'
      r = requests.get(groupsUrl, auth=('', self._password), verify=False)
      # convert the response into a JSON object
      responseEnvelope = r.json()
      # pull the relevant content out of the response envelope
      json_db = responseEnvelope['Content']
      try:
        f = open(filename, "w")
        f.write(r.content.decode('utf-8'))
        f.close()
        _LOGGER.info("wrote file " + filename)
      except Exception as e:
        _LOGGER.warning("Exception = " + str(e))
        _LOGGER.warning("could not save " + filename)
    
    _LOGGER.info("Loaded json db")
    # print(json_db[0:10000])

    parser = KetraJsonDbParser(ketra=self, json_db=json_db)
    self._id_to_area = parser.id_to_area
    self._name = parser.project_name
    self._outputs = parser.outputs
    self._id_to_load = parser.id_to_load
    assert(parser.parse())     # throw our own exception
   
    _LOGGER.info('Found Ketra project: %s, %d areas and %d loads' % (
        self._name, len(self._id_to_area.keys()), len(self._id_to_load.keys())))

    return True

  @property
  def outputs(self):
    """Return the full list of outputs in the controller."""
    return self._outputs

  

class _RequestHelper(object):
  """A class to help with sending queries to the controller and waiting for
  responses.

  It is a wrapper used to help with executing a user action
  and then waiting for an event when that action completes.

  The user calls request() and gets back a threading.Event on which they then
  wait.

  If multiple clients of a ketra object (say an Output) want to get a status
  update on the current brightness (output level), we don't want to spam the
  controller with (near)identical requests. So, if a request is pending, we
  just enqueue another waiter on the pending request and return a new Event
  object. All waiters will be woken up when the reply is received and the
  wait list is cleared.

  NOTE: Only the first enqueued action is executed as the assumption is that the
  queries will be identical in nature.
  """

  def __init__(self):
    """Initialize the request helper class."""
    self.__lock = threading.Lock()
    self.__events = []

  def request(self, action):
    """Request an action to be performed, in case one."""
    ev = threading.Event()
    first = False
    with self.__lock:
      if len(self.__events) == 0:
        first = True
      self.__events.append(ev)
    if first:
      action()
    return ev

  def notify(self):
    with self.__lock:
      events = self.__events
      self.__events = []
    for ev in events:
      ev.set()


class KetraEntity(object):
  """Base class for all the Ketra objects we'd like to manage. Just holds basic
  common info we'd rather not manage repeatedly."""

  def __init__(self, ketra, name, area, id):
    """Initializes the base class with common, basic data."""
    self._ketra = ketra
    self._name = name
    self._area = area
    self._id = id

  @property
  def name(self):
    """Returns the entity name (e.g. Pendant)."""
    return self._name

  @name.setter
  def name(self, value):
    """Sets the entity name to value."""
    self._name = value

  @property
  def id(self):
    """The ketra integration id"""
    return self._id

  @property
  def area(self):
    """The area id"""
    return self._area


class Output(KetraEntity):
  """This is the output entity in Ketra universe. This generally refers to a
  switched/dimmed load, e.g. light fixture, outlet, etc."""
  CMD_TYPE = 'LOAD'
  ACTION_ZONE_LEVEL = 1
  _wait_seconds = 0.5  # TODO:move this to a parameter

  def __init__(self, ketra, name, area, output_type, load_type, id):
    """Initializes the Output."""
    super(Output, self).__init__(ketra, name, area, id)
    self._output_type = output_type
    self._load_type = load_type
    self._level = 0
    self._rgb = [ None, None, None ]
    self._xy = [ None, None ]
    self._cct = None
    self._query_waiters = _RequestHelper()

    self._ketra.register_id(Output.CMD_TYPE, self)

  def __str__(self):
    """Returns a pretty-printed string for this object."""
    return 'Output name: "%s" area: %s type: "%s" load: "%s" id: %s %s' % (
        self._name, self._area, self._output_type, self._load_type, self._id, ("(dim)" if self.is_dimmable else ""))

  def __repr__(self):
    """Returns a stringified representation of this object."""
    return str({'name': self._name, 'area': self._area,
                'type': self._load_type, 'load': self._load_type,
                'id': self._id})

  def __do_query_level(self):
    """Helper to perform the actual query the current dimmer level of the
    output. For pure on/off loads the result is either 0.0 or 100.0."""
    lightURL = 'https://' + self._ketra._host + '/ketra.cgi/api/v1/Groups/' + quote(self._name)
    r = requests.get(lightURL, auth=('', self._ketra._password), verify=False)
    content = r.json()['Content']
    state = content['State']
    self._level = state['Brightness']
    return True
    

  def last_level(self):
    """Returns last cached value of the output level, no query is performed."""
    return self._level

  @property
  def level(self):
    """Returns the current output level by querying the remote controller."""
#    ev = self._query_waiters.request(self.__do_query_level)
#    ev.wait(self._wait_seconds)
    return self._level

  def _set_state(self, dict):
    lightURL = 'https://' + self._ketra._host + '/ketra.cgi/api/v1/Groups/' + quote(self._name) + "/State"
    _LOGGER.warning("Sending Ketra " + json.dumps(dict))
    # TODO: make an option to do NOOP sends -- for now just comment out if you don't want to hit
    # the Ketra N4 with the request
    if False:
      r = requests.put(lightURL, data=json.dumps(dict), auth=('', self._ketra._password), verify=False)
    else:
      _LOGGER.warning("NOT ACTUALLY MAKING REQUEST TO KETRA N4")
    
  
  @level.setter
  def level(self, new_level):
    """Sets the new brightness level."""
    if self._level == new_level:
      return
    self._set_state({ "Brightness": new_level,
                      "PowerOn": True, 
                      "TransitionTime": 1000, 
                      "TransitionComplete": True })
    self._level = new_level

  @property
  def rgb(self):
    """Returns current RGB of the lamp."""
    return self._rgb

  @rgb.setter
  def rgb(self, new_rgb):
    """Sets new RGB levels."""
    if self._rgb == new_rgb:
      return
    srgb = sRGBColor(*new_rgb)
    xyY = convert_color(srgb, xyYColor)
    self._set_state({ "PowerOn": True, 
                      "xChromaticity": xyY.xyy_x,
                      "yChromaticity": xyY.xyy_y, 
                      "TransitionTime": 1000, 
                      "TransitionComplete": True })
    self._rgb = new_rgb

  @property
  def xy(self):
    """Returns current XY of the lamp."""
    return self._xy

  @xy.setter
  def xy(self, new_xy):
    """Sets new XY levels."""
    if self._xy == new_xy:
      return
    self._set_state({ "PowerOn": True, 
                      "xChromaticity": new_xy[0],
                      "yChromaticity": new_xy[1], 
                      "TransitionTime": 1000, 
                      "TransitionComplete": True })
    self._xy = new_xy

  @property
  def cct(self):
    """Returns current CCT (coordinated color temperature) of the lamp."""
    return self._cct

  @cct.setter
  def cct(self, new_cct):
    if (self._cct == new_cct):
      return
    [x,y] = cctKelvin_to_xyColor(new_cct)
    self._set_state({ "PowerOn": True,
                      "xChromaticity": x,
                      "yChromaticity": y,
                      "TransitionTime": 1000,
                      "TransitionComplete": True })
    self._cct = new_cct
    
## At some later date, we may want to also specify fade and delay times    
#  def set_level(self, new_level, fade_time, delay):
#    self._ketra.send(Ketra.OP_EXECUTE, Output.CMD_TYPE,
#        Output.ACTION_ZONE_LEVEL, new_level, fade_time, delay)

  @property
  def type(self):
    """Returns the output type. At present AUTO_DETECT or NON_DIM."""
    return self._output_type

  @property
  def is_dimmable(self):
    """Returns a boolean of whether or not the output is dimmable."""
    return self._load_type.lower().find("non-dim") == -1


class Button(KetraEntity):
  """This object represents a keypad button that we can trigger and handle
  events for (button presses)."""
  def __init__(self, ketra, name, area, id, num, button_type, direction):
    super(Button, self).__init__(ketra, name, area, id)
    self._num = num
    self._button_type = button_type
    self._direction = direction

  def __str__(self):
    """Pretty printed string value of the Button object."""
    return 'Button name: "%s" num: %d action: "%s" area: %s id: %s' % (
        self._name, self._num, self._action, self._area, self._id)

  def __repr__(self):
    """String representation of the Button object."""
    return str({'name': self._name, 'num': self._num, 'action': self._action,
                'area': self._area, 'id': self._id})

  @property
  def name(self):
    """Returns the name of the button."""
    return self._name

  @property
  def number(self):
    """Returns the button number."""
    return self._num

  @property
  def button_type(self):
    """Returns the button type (Toggle, MasterRaiseLower, etc.)."""
    return self._button_type


class Keypad(KetraEntity):
  """Object representing a Ketra keypad.
  
  Currently we don't really do much with it except handle the events
  (and drop them on the floor).
  """
  CMD_TYPE = 'DEVICE'

  def __init__(self, ketra, name, area, id):
    """Initializes the Keypad object."""
    super(Keypad, self).__init__(ketra, name, area, id)
    self._buttons = []
    self._ketra.register_id(Keypad.CMD_TYPE, self)

  def add_button(self, button):
    """Adds a button that's part of this keypad. We'll use this to
    dispatch button events."""
    self._buttons.append(button)

  def __str__(self):
    """Returns a pretty-printed string for this object."""
    return 'Keypad name: "%s", area: "%s", id: %d' % (
        self._name, self._area, self._id)

  @property
  def buttons(self):
    """Return a tuple of buttons for this keypad."""
    return tuple(button for button in self._buttons)


class Area(object):
  """An area (i.e. a room) that contains devices/outputs/etc."""
  def __init__(self, ketra, name, parent, id, note):
    self._ketra = ketra
    self._name = name
    self._id = id
    self._note = note
    self._parent = parent
    self._outputs = []
    self._keypads = []
    self._sensors = []

  def __str__(self):
    """Returns a pretty-printed string for this object."""
    return 'Area name: "%s", id: %s' % (
        self._name, self._id)

  def add_output(self, output):
    """Adds an output object that's part of this area, only used during
    initial parsing."""
    self._outputs.append(output)

  def add_keypad(self, keypad):
    """Adds a keypad object that's part of this area, only used during
    initial parsing."""
    self._keypads.append(keypad)

  def add_sensor(self, sensor):
    """Adds a motion sensor object that's part of this area, only used during
    initial parsing."""
    self._sensors.append(sensor)

  @property
  def name(self):
    """Returns the name of this area."""
    return self._name

  @property
  def id(self):
    """The integration id of the area."""
    return self._id

  @property
  def outputs(self):
    """Return the tuple of the Outputs from this area."""
    return tuple(output for output in self._outputs)

  @property
  def keypads(self):
    """Return the tuple of the Keypads from this area."""
    return tuple(keypad for keypad in self._keypads)

  @property
  def sensors(self):
    """Return the tuple of the MotionSensors from this area."""
    return tuple(sensor for sensor in self._sensors)

