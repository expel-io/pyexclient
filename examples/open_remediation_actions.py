import sys
import datetime
import argparse
from pyexclient.workbench import WorkbenchClient, relationship, neq, window

from .auth import auth_args, make_wb_client, date_range_args


def main():
    parser = auth_args("List open remediation actions")
    parser = date_range_args(parser)
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
    for rem in xc.remediation_actions.search(window('created_at', start_date, end_date), relationship("investigation.organization_id", '9a5434c2-66b8-49e3-a544-6e8797f4a1d3'), status=neq('COMPLETED', 'CLOSED')):
        # Calculate the number of days since the remediation action was created.
        since = (datetime.datetime.now() - datetime.datetime.strptime(rem.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")).days
        # print message to console
        print(f"{rem.action} created {rem.created_at} ({since} days ago) currently it is {rem.status} and the comment is \"{rem.comment if rem.comment else ''}\"")
        if rem.values:
            # If there are remediation values associated with the actions print them to screen. This is where IPs, or hostname identifiers are specified.
            print(f"\t{rem.values['name']}")
            for key, val in rem.values.items():
                if key == 'name': 
                    continue
                print(f"\t\t* {key} = {val}")
    # End documentation snippet


if __name__ == '__main__':
    sys.exit(main())
