import json
import requests
import logging
import time
import socket


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
    print "Discovering N4 with serial number " + n4SerialNumber
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    outgoing_ip_address = getMyIpAddress()
    print "Using local interface " + outgoing_ip_address
    sock.bind((outgoing_ip_address, 0))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)
    for m in range(5):
        time.sleep(.1)
        try:
            sock.sendto("*", ('255.255.255.255', 4934))
        except socket.error, e:
            print ip, e
        
        t_end = time.time() + 1
        while time.time() < t_end:
            try:
                data, addr = sock.recvfrom(1024)
                response = dict([s.split("=") for s in data.splitlines()])
                response["address"] = str(addr[0])
                if (response["serial"] == n4SerialNumber):
                    print "Found N4 at address " + response["address"]
                    return response["address"]
            except socket.error:
                pass
    return None

######    
# Main program begins here
######

# to get rid of the SSL warnings
logging.captureWarnings(True)   

# Put the N4 IP Address in the n4IpAddr variable.  
# You can use SSDP to discover the device, or use the discoverN4Device function
# which uses an UDP broadcast discovery mechanism.
n4IpAddr = discoverN4Device("KP00001485")

# N4 Authentication
# you will get the password below from the oauth request, explained separately
password = '4767e6ebe15afec6feffa66e79bda0921b4d74c9cdd5d4f1cdd65257ec450620'

# Example 1:
# Get the list of available keypads
#
getKeypadsUrl = 'https://' + n4IpAddr + '/ketra.cgi/api/v1/keypads'
r = requests.get(getKeypadsUrl, auth=('', password), verify=False)
# convert the response into a JSON object
responseEnvelope = r.json()
# pull the relevant content out of the response envelope
keypads = responseEnvelope['Content']
print "All Keypads:"
print json.dumps(keypads, sort_keys=True, indent=4, separators=(',', ': '))
print

# Example 2:
# Get a keypad by name
# replace this with your keypad's name as configured in DS
keypadName = 'KC00000255'
getKeypadsUrl = 'https://' + n4IpAddr + '/ketra.cgi/api/v1/keypads?name=' + keypadName
r = requests.get(getKeypadsUrl, auth=('', password), verify=False)
# convert the response into a JSON object
responseEnvelope = r.json()
# pull the relevant content out of the response envelope
keypads = responseEnvelope['Content']
print "Keypad " + keypadName + ":"
print json.dumps(keypads, sort_keys=True, indent=4, separators=(',', ': '))
print

# Example 3:
# Activate a button
# replace this with your keypad's name as configured in DS
# and the button name
keypadName = 'KC00000255'
buttonName = 'Get to Work'
level=32768
activateUrl = 'https://' + n4IpAddr + '/ketra.cgi/api/v1/activateButton?keypadName=' + keypadName + '&buttonName=' + buttonName
r = requests.post(activateUrl, auth=('', password), verify=False, data = json.dumps({"Level" : level }))
print "Activated button " + buttonName + " on keypad " + keypadName + " to level " + str(level)
print

# Example 4:
# Group Control
groupsUrl = 'https://' + n4IpAddr + '/ketra.cgi/api/v1/groups'
r = requests.get(groupsUrl, auth=('', password), verify=False)
# convert the response into a JSON object
responseEnvelope = r.json()
# pull the relevant content out of the response envelope
groups = responseEnvelope['Content']

# enumerate the groups
firstGroup = None
print ""
print "Found " + str(len(groups)) + " groups"
for group in groups:
    print "\t" + str(group['Name']) + ":"
    if firstGroup == None and not group['Name'].startswith('Internal_'):
        firstGroup = group

# Examples of immediate lamp group control
if firstGroup != None:
    print "Controlling group '" + firstGroup['Name'] + "'"
    groupStateUrl = groupsUrl + '/' + firstGroup['Id'] + '/state'
    
    # a 'get' operation doesn't have any side effects
    r = requests.get(groupStateUrl, auth=('', password), verify=False)
    lampState = r.json();
    
    ####
    # set group color
    ####
    
    # 5000 kelvin CCT
    # 40% brightness
    # 1 second transition
    # no start state specified, so transition occurs from the light's current state
    print "Setting 5000K / 50%"
    lampState10k_noStart = { "Brightness": 0.4, "CCT": 5000, "PowerOn": True, "Vibrancy": 0.6, "TransitionTime": 1000 }
    r = requests.put(groupStateUrl, data=json.dumps(lampState10k_noStart), auth=('', password), verify=False)
    lampState = r.json();
    time.sleep(2)

    # 3500 kelvin CCT
    # 60% brightness
    # 2 second transition from StartState
    #   StartState specifies 2000K at 90% brightness
    print "Setting 3500K / 60%"
    lampState10k_2kStart = { "Brightness": 0.6, "CCT": 3500, "PowerOn": True, "Vibrancy": 0.6, "TransitionTime": 2000, "StartState": {"Brightness": 0.9, "CCT": 2000, "PowerOn": True, "Vibrancy": 0.3} }
    r = requests.put(groupStateUrl, data=json.dumps(lampState10k_2kStart), auth=('', password), verify=False)
    lampState = r.json();
    time.sleep(3)
    
    # Saturated red (x=0.68/y=0.3) 
    # 75% brightness
    # 1 second transition
    # no start state specified
    print "Setting red / 75%"
    lampStateRed_noStart = { "Brightness": 0.75, "xChromaticity": 0.68, "yChromaticity": 0.3, "PowerOn": True, "Vibrancy": 0.8, "TransitionTime": 1000 }
    r = requests.put(groupStateUrl, data=json.dumps(lampStateRed_noStart), auth=('', password), verify=False)
    lampState = r.json();
    time.sleep(2)
    
    # Saturated blue (x=0.155/y=0.076)
    # 100% brightness
    # 1 second transition from StartState
    # StartState is saturated green (x=0.299/y=0.594)
    print "Setting blue / 100%"
    lampStateBlue_greenStart = { "Brightness": 1.0, "xChromaticity": 0.155, "yChromaticity": 0.076, "PowerOn": True, "Vibrancy": 0.75, "TransitionTime": 1000, "StartState": {"Brightness": 0.9, "xChromaticity": 0.299, "yChromaticity": 0.594, "PowerOn": True, "Vibrancy": 0.3} }
    r = requests.put(groupStateUrl, data=json.dumps(lampStateBlue_greenStart), auth=('', password), verify=False)
    lampState = r.json();
    time.sleep(2)
    
    # only change brightness:  50%
    print "Setting brightness to 50%"
    brightness_only = { "Brightness": 0.5 }
    r = requests.put(groupStateUrl, data=json.dumps(brightness_only), auth=('', password), verify=False)
    lampState = r.json();
    time.sleep(2)
    
    # power off
    print "Setting power off"
    power_only = { "PowerOn": False }
    r = requests.put(groupStateUrl, data=json.dumps(power_only), auth=('', password), verify=False)
    lampState = r.json();
    time.sleep(2)
    
    # power on
    print "Setting power on"
    power_only = { "PowerOn": True }
    r = requests.put(groupStateUrl, data=json.dumps(power_only), auth=('', password), verify=False)
    lampState = r.json();
    time.sleep(2)
    
    r = requests.get(groupStateUrl, auth=('', password), verify=False)
    lampState = r.json();


        
