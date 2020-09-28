import argparse
import getpass
from pyexclient.workbench import WorkbenchClient


def auth_args(desc):
    '''
    Builds and argparser object that can be used by other scripts to prompt users for creds.
    '''

    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument('-u', '--username', help='Expel username')
    parser.add_argument('-a', '--api-key', help='API Key')
    return parser

def date_range_args(parser):
    '''
    Expectation is that a created ArgumentParser() has been passed in.
    '''
    parser.add_argument('-s', '--start-date', help='Start date in format of YYYY-MM-DD')
    parser.add_argument('-e', '--end-date', help='End date in format of YYYY-MM-DD')
    return parser


def make_wb_client(username=None, api_key=None):
    '''
    Create a WorkbenchClient class, that is authenticated. Based on arguments provided, the method will
    prompt for password and mfa token, or just use the api key.
    '''
    if username is None and api_key is None:
        print("Error: You must provide either a username or an api key!")
        return None

    if username is not None:
        print("Please enter your password:")
        passwd = getpass.getpass()
        print("Please enter your MFA token:")
        mfa_code = input()
        return WorkbenchClient('https://workbench.staging.expel.io', username=username, password=passwd, mfa_code=mfa_code)

    return WorkbenchClient('https://workbench.staging.expel.io', token=api_key)
