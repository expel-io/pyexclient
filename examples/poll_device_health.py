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

    while True:
        since = datetime.now() - timedelta(minutes=5)
        print("Querying device status since: {since}".format(since=since))

        devices = [dev for dev in xc.security_devices.search(status_updated_at=gt(since.isoformat()), status=neq('healthy'), raw_status=flag('true'))]
        if not devices:
            print("\tNo unhealthy devices found")
        else:
            for dev in devices:
                if dev.status == 'health_checks_not_supported':
                    continue
                print(f'{dev.name} is no longer healthy, and has status of {dev.status}')
        time.sleep(60)


if __name__ == '__main__':
    sys.exit(main())
