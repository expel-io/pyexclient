'''
Script: Poll Unhealthy Devices 
Version: 1.0

Usage:
    python poll_device_health.py 

'''

import time
import argparse
import sys
import getpass

from datetime import datetime
from datetime import timedelta
from pyexclient import WorkbenchClient
from pyexclient.workbench import neq 
from pyexclient.workbench import gt
from pyexclient.workbench import flag
import json

import pdb


def authenticate():
    '''
    Prompt user for authentication info
    '''
    username = input("Enter Username: ")
    password = getpass.getpass("Enter Password: ")
    code = input("2FA Code: ")
    xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=code)
    return xc


def main():
    xc = authenticate()

    device_list = []

    via_siem_config_inventory = {}
    hail_mary_dict = {}
    for device in device_list:
        try:
            config = xc.secrets.get(id=f'security_device-{device}') #I assumed the docs had a typo for a while, but the URL *actually* looks like this lol
            defined_secrets = config._data['attributes']['secret'].keys() # the .keys() returns only which secrets *are defined*, not the values. Be very careful when copypasting if you delete this
            key_list = ','.join(defined_secrets)
            csv_str = f"{device},{key_list},"
            print(csv_str)
            hail_mary_dict[device] = key_list
        except:
            csv_str = f"{device},ERROR,"
            print(csv_str)
            hail_mary_dict[device] = "ERROR"
        time.sleep(60) # Yes, you *actually* have to wait this long per device, my deepest condolences

    print(json.dumps(hail_mary_dict, indent=4))
    


if __name__ == '__main__':
    sys.exit(main())
