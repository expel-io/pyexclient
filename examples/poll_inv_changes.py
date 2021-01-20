'''
Script: Poll for changes to investigations and incidents 
Version: 1.0

Usage:
    python poll_inv_changes.py 

'''

import pprint
import time
import sys
import getpass

from datetime import datetime
from datetime import timedelta
from pyexclient import WorkbenchClient
from pyexclient.workbench import gt
from pyexclient.workbench import notnull 
from pyexclient.workbench import relationship 


def authenticate():
    '''
    Prompt user for authentication info
    '''
    username = input("Enter Username: ")
    password = getpass.getpass("Enter Password: ")
    code = input("2FA Code: ")
    xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=code)
    return xc

def get_inv_changes(xc, since):
    '''
    Method polls a few different endpoints for updates to their histories which indicate updates/changes in Workbench.
    '''

    for change in xc.investigative_action_histories.search(relationship('investigation.id', notnull()), created_at=gt(since.isoformat()) ):
        if change.investigation is None:
            print("Skipping ... due to expel alert")
            continue
        entry = {'action': change.action, 'value': change.value, 'investigation_id': change.investigation.id}
        if change.action == 'ASSIGNED':
            entry['assigned_to_actor'] = change.assigned_to_actor.display_name
        yield entry

    for change in xc.investigation_finding_histories.search(created_at=gt(since.isoformat())):
        entry = {'action': change.action, 
                'created_at': change.created_at, 
                'updated_at': change.updated_at, 
                'updated_by': change.updated_by.display_name, 
                'value': change.value, 
                'investigation_id': change.investigation.id}
        yield entry

    for change in xc.investigation_histories.search(created_at=gt(since.isoformat())):
        entry = {'action': change.action, 
                'created_at': change.created_at, 
                'created_by': change.created_by.display_name, 
                'assigned_to_actor': change.assigned_to_actor.display_name, 
                'value': change.value, 
                'investigation_id': change.investigation.id}
        yield entry

def main():
    xc = authenticate()

    # start looking for changes since 5 minutes ago
    since = datetime.now() - timedelta(minutes=5)

    while True:
        print("Querying device status since: {since}".format(since=since))

        now = datetime.now()
        for change in get_inv_changes(xc, since):
            pprint.pprint(change)

        # next time, search for changes since last poll
        since = now
        time.sleep(60)

if __name__ == '__main__':
    sys.exit(main())
