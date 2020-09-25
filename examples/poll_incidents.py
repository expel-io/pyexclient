'''
Script: Poll Incidents
Version: 1.0

Usage:
    python poll_ransomware_incidents.py -t <INCIDENT_TYPE> -k <KEYWORD>

'''

import time
import argparse
import sys
import getpass

from datetime import datetime
from datetime import timedelta
from pyexclient import WorkbenchClient
from pyexclient.workbench import gt
from pyexclient.workbench import contains


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
    parser = argparse.ArgumentParser(description='Poll for Incidents')
    parser.add_argument('-t', '--type', required=False, default=None, help='Optionally only return incidents of this type')
    parser.add_argument('-k', '--keyword', required=False, default=None, help='Optionally only return incidents with titles containing this keyword')
    args = parser.parse_args()

    xc = authenticate()

    while True:
        since = datetime.now() - timedelta(minutes=5)
        print("Querying incidents since: {since}".format(since=since))
        args = {
            'is_incident': True,
            'created_at': gt(since.isoformat())
        }
        if args.get('type'):
            args['threat_type'] = args['type']
        if args.get('type'):
            args['title'] = contains(args['keyword'])
        incidents = [i for i in xc.investigations.search(**args)]
        if not incidents:
            print("\tNo incidents found")
        else:
            [print(i) for i in incidents]
        time.sleep(60)


if __name__ == '__main__':
    sys.exit(main())
