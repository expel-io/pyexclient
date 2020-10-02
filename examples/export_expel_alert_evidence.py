'''
Script: Export Expel Alert with Evidence Fields
Version: 1.0

Requirements:
    python-dateutil

Usage:
    python export_expel_alert_evidence.py -s "2020-01-01" -e "2020-02-01" -o results.csv

'''

import sys
import argparse
import csv
import getpass

from datetime import datetime
from datetime import timedelta
from collections import OrderedDict
from collections import defaultdict
from pyexclient import WorkbenchClient
from pyexclient.workbench import window

try:
    from dateutil import parser as dt_parser
except ImportError:
    raise ImportError('Missing "python-dateutil" package. Run "pip install python-dateutil"')


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
    parser = argparse.ArgumentParser(description='Export Expel Alert with Evidence Fields')
    parser.add_argument('-s', '--start_at', required=False, default=(datetime.now() - timedelta(days=30)).isoformat(), help='Look for Expel Alerts after this date.')
    parser.add_argument('-e', '--end_at', required=False, default=datetime.now().isoformat(), help='Look for Expel Alerts before this date.')
    parser.add_argument('-o', '--outfile', required=True, help='The file to write CSV results to.')
    args = parser.parse_args()

    xc = authenticate()
    start_at = dt_parser.parse(args.start_at)
    end_at = dt_parser.parse(args.end_at)
    print("Querying Expel Alerts for date range: {start} - {end}".format(start=start_at.isoformat(), end=end_at.isoformat()))
    expel_alerts = xc.expel_alerts.search(window("created_at",start_at, end_at))

    csv_columns = ['alert_at', 'alert_type', 'expel_severity', 'expel_name', 'expel_message', 'status', 'close_reason', 'close_comment', 'vendor_name']
    csv_rows = list()
    for alert in expel_alerts:
        row = OrderedDict(
            alert_at = alert.created_at,
            alert_type = alert.alert_type,
            expel_severity = alert.expel_severity,
            expel_name = alert.expel_name,
            expel_message = alert.expel_message,
            status = alert.status,
            close_reason = alert.close_reason,
            close_comment = alert.close_comment,
            vendor_name = alert.vendor.name if alert.vendor else '',
        )
        if alert.evidence:
            evidence_fields = defaultdict(set)
            for evidence in alert.evidence:
                evidence_fields[evidence.evidence_type].add(evidence.evidence)
            for name, values in evidence_fields.items():
                if name.lower() not in csv_columns:
                    csv_columns.append(name.lower())
                row[name.lower()] = ','.join(values)
        csv_rows.append(row)

    print("Writing {num} rows to {outfile}".format(num=len(csv_rows), outfile=args.outfile))
    with open(args.outfile, 'w') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
        writer.writeheader()
        for data in csv_rows:
            writer.writerow(data)


if __name__ == '__main__':
    sys.exit(main())
