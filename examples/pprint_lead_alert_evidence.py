'''
Script: For a given investigation short name show the evidence of the lead alert.
Version: 1.0

Usage:
    python show_lead_alert_evidence.py <ACME-1234>

'''

import sys
import getpass

from pyexclient import WorkbenchClient


def authenticate():
    '''
    Prompt user for authentication info
    '''
    username = input("Enter Username: ")
    password = getpass.getpass("Enter Password: ")
    code = input("2FA Code: ")
    xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=code)
    return xc

def flatten_dict(blob):
    '''
    Flattens a nested dict.

    >>> print(flatten_dict({"a": "b", "c":['a', 'b', {'d':'e'}]}))
    >>> {'a': 'b', 'c.0': 'a', 'c.1': 'b', 'c.2.d': 'e'}
    '''
    out = {}
    def _make_flat(elms, name=''):
        if type(elms) is dict:
            for elm in elms:
                _make_flat(elms[elm], name + elm + '.')
        elif type(elms) is list:
            for i, elm in enumerate(elms):
                _make_flat(elm, name + str(i) + '.')
        else:
            out[name[:-1]] = elms

    _make_flat(blob)
    return out

def make_evidence_dict(ea):
    '''
    This method will take an ExpelAlert and iterate over vendor alerts,
    and vendor evidences.

    :param ea: The ExpelAlert for which we want to extract associated vendor alert evidences
    :type ea: :class:`ExpelAlerts`
    :return: A list where each entry in the list a corresponding dict containing vendor alert, and vendor evidences.
    :rtype: list

    Examples:
        >>> vendor_evidences = make_evidence_dict(xc.expel_alerts.get(id='ea52123b-383f-4a3b-aa7b-45658a0ce873'))

    '''
    vendor_evidences = []
    for va in ea.vendor_alerts:
        ev_dict = {}
        ev_dict['signame'] = va.vendor_sig_name
        ev_dict['desc'] = va.description
        ev_dict['message'] = va.vendor_message
        ev_dict['evidence'] = {}

        for evidence in va.evidence_summary:
            # Skip empty evidence..
            for evidence in va.evidence_summary:
                for evidence_type in evidence.keys():
                    flat_ev = flatten_dict(evidence[evidence_type])
                    if evidence_type not in ev_dict['evidence']:
                        ev_dict['evidence'][evidence_type] = {}
                    # NOTE: this is because evidence_source is top level key and so when we flatten and pull out evidence type (in this case evidence_source)
                    # our key value pair, has an empty key. This is a side effect of flattening out the evidence.
                    ev_dict['evidence'][evidence_type].update({k if k else evidence_type: v for k,v in flat_ev.items()})
        vendor_evidences.append(ev_dict)
    return vendor_evidences

def pprint_expel_alert(ea, include_query=False):
    '''
    Pretty print to console an ExpelAlert object retrieved by pyexclient.
    '''
    # Expel Alerts are just a container for vendor evidences, so first print top level Expel Alert details..
    print("====== Expel Alert Summary ======")
    print("Expel Alert Name: {}".format(ea.expel_name))
    print("Expel Alert Message: {}".format(ea.expel_message))
    print("Expel Alert Severity: {}".format(ea.expel_severity))
    print("Supporting Vendor Alerts: {}\n".format(len(ea.vendor_alerts)))

    # Call make evidence which will return a list of dicts making up the evidence for the given Expel Alert.
    vendor_evidences = make_evidence_dict(ea)

    # Iterate over the vendor evidences that are in the expel alert
    for ev_dict in vendor_evidences:
        # Print a summary of each vendor alert
        print("\t====== Vendor Alert Summary ======")
        print("\tVendor Signature Name: {}".format(ev_dict['signame']))
        print("\tVendor Alert Description: {}".format(ev_dict['desc']))
        print("\tVendor Alert Message: {}\n".format(ev_dict['message']))
        # Print out the evidence contained in the vendor alert
        print("\t====== Vendor Alert Evidence ======")
        for evidence_type, flat_ev in ev_dict['evidence'].items():
            # There are multiple types of evidence, so we'll break evidence out by evidence type which is keyed into the dict returned by make_evidence_dict
            print("\t\t{}".format(evidence_type))
            # iterate over the flattened vendor evidence
            for field, value in sorted(flat_ev.items(), key=lambda x: x[0]):
                # query field is large and messes with display so by default we'll not display the query.
                if include_query is False and field.endswith('query_result.query'):
                    continue
                print("\t\t\t{}={}".format(field, value))
            print("\n")

def main():
    xc = authenticate()

    if len(sys.argv) != 2:
        print("Must specify an investigation short name or ID")
        print("Examples:\n")
        print("\tpython show_lead_alert_evidence.py ACME-1234")
        print("\tpython show_lead_alert_evidence.py 69e895a2-7a9d-46ef-9e99-f7b6d691a74d")
        return 0

    elif sys.argv[1].count('-') == 1:
        inv = list(xc.investigations.search(short_link=sys.argv[1]))[0]
    else:
        inv = xc.investigations.get(id=sys.argv[1])

    expel_alert = inv.lead_expel_alert

    pprint_expel_alert(expel_alert)

if __name__ == '__main__':
    sys.exit(main())
