import sys
import datetime
import argparse
import getpass
from pyexclient.workbench import WorkbenchClient, relationship, neq, window


def make_wb_client(username=None, api_key=None):
    '''
    Create a WorkbenchClient class, that is authenticated. Based on arguments provided, the method will
    prompt for password and mfa token, or just use the api key.
    '''
    if username is None and api_key is None:
        raise Exception("Error: You must provide either a username or an api key!")

    if username is not None:
        return WorkbenchClient('https://workbench.expel.io',
                    username=username,
                    password=getpass.getpass("Please enter your password: "),
                    mfa_code=input("Please enter your MFA token: "))

    return WorkbenchClient('https://workbench.expel.io', token=api_key)


def main():
    parser = argparse.ArgumentParser(description="List open remediation actions")
    parser.add_argument('-u', '--username', help='Expel username')
    parser.add_argument('-a', '--api-key', help='API Key')
    parser.add_argument('-s', '--start-date', help='Start date in format of YYYY-MM-DD')
    parser.add_argument('-e', '--end-date', help='End date in format of YYYY-MM-DD')
    args = parser.parse_args()

    start_date = end_date = None

    xc = make_wb_client(username=args.username, api_key=args.api_key)
    if args.start_date:
        start_date = datetime.datetime.strptime(args.start_date, '%Y-%m-%d')

    if args.end_date:
        end_date = datetime.datetime.strptime(args.end_date, '%Y-%m-%d')

    # Start documentation snippet

    # Search remediation actions where the status is not equal to CLOSED or COMPLETED, and optionally it was created within the window of start_date and end_date.
    # start and end date's can be None in which case the search will look at all remediation actions.
    for rem in xc.remediation_actions.search(created_at=window(start_date, end_date), status=neq('COMPLETED', 'CLOSED')):
        # Calculate the number of days since the remediation action was created.
        since = (datetime.datetime.now() - datetime.datetime.strptime(rem.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")).days
        # print message to console
        print(f"{rem.action} created {rem.created_at} ({since} days ago) currently it is {rem.status} and the comment is \"{rem.comment if rem.comment else ''}\"")
        if 'values' in rem._attrs and rem.values:
            # If there are remediation values associated with the actions print them to screen. This is where IPs, or hostname identifiers are specified.
            print(f"\t{rem.values['name']}")
            for key, val in rem.values.items():
                if key == 'name':
                    continue
                print(f"\t\t* {key} = {val}")
        elif 'remediation_action_assets' in rem._data['relationships']:
            for a in rem.remediation_action_assets:
                print(f"\t{a.status} - {a.asset_type} - {a.value}")
    # End documentation snippet


if __name__ == '__main__':
    sys.exit(main())
