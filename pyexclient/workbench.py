#!/usr/bin/env python
import copy
import datetime
import io
import json
import logging
import pprint
import time
from urllib.parse import urlencode
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.basicConfig(level=logging.DEBUG)
logger = logging


class operator:
    def __init__(self):
        self.rhs = []

    def create(self):
        return self.rhs


class notnull(operator):
    '''
    The notnull operator is used to search for fields that are not null.

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=notnull()):
        >>>     print("%s has a close comment of %s" % (ea.expel_name, ea.close_comment))
    '''

    def __init__(self, value=False):
        if value is True:
            self.rhs = ["\u2400true"]
        elif value is False:
            self.rhs = ["\u2400false"]
        else:
            raise ValueError('notnull operator expects True|False')


class isnull(operator):
    '''
    The isnull operator is used to search for fields that are null.

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=isnull()):
        >>>     print("%s has no close comment" % ea.expel_name)
    '''

    def __init__(self, value=True):
        if value is True:
            self.rhs = ["\u2400true"]
        elif value is False:
            self.rhs = ["\u2400false"]
        else:
            raise ValueError('notnull operator expects True|False')


class contains(operator):
    '''
    The contains operator is used to search for fields that contain a sub string..

    :param value: A substring to be checked against the value of a field.
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=contains("foo")):
        >>>     print("%s contains foo in the close comment" % ea.expel_name)
    '''

    def __init__(self, *args):
        self.rhs = [':%s' % substr for substr in args]


class startswith(operator):
    '''
    The startswith operator is used to search for values that start with a specified string..

    :param value: The startswith string
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=startswith("foo")):
        >>>     print("%s starts with foo in the close comment" % ea.expel_name)
    '''

    def __init__(self, swith):
        self.rhs = ['^%s' % swith]


class neq(operator):
    '''
    The neq operator is used to search for for fields that are not equal to a specified value.

    :param value: The value to assert the field is not equal too
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=neq("foo")):
        >>>     print("%s has a close comment that is not equal to 'foo'" % ea.expel_name)
    '''

    def __init__(self, *args):
        self.rhs = ['!%s' % value for value in args]


class gt(operator):
    '''
    The gt (greater than) operator is used to search a specific field for values greater than X.

    :param value: The greater than value to be used in comparison during a search.
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(created_at=gt("2020-01-01")):
        >>>     print("%s was created after 2020-01-01" % ea.expel_name)
    '''

    def __init__(self, value):
        if type(value) == datetime.datetime:
            value = value.isoformat()
        self.rhs = ['>%s' % value]


class lt(operator):
    '''
    The lt (less than) operator is used to search a specific field for values greater than X.

    :param value: The less than value to be used in comparison during a search.
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(created_at=lt("2020-01-01")):
        >>>     print("%s was created before 2020-01-01" % ea.expel_name)
    '''

    def __init__(self, value):
        if type(value) == datetime.datetime:
            value = value.isoformat()
        self.rhs = ['<%s' % value]


class window:
    '''
    The window operator is used to search a specific field that is within a window (range) of values

    :param field_name: The name of the field to perform the window evaluation on
    :type value: Union[str, int, datetime.datetime]
    :param start: The begining of the window range
    :type start: Union[str, int, datetime.datetime]
    :param end: The end of the window range
    :type end: str

    Examples:
        >>> for ea in xc.expel_alerts.search(created_at=lt("2020-01-01")):
        >>>     print("%s was created before 2020-01-01" % ea.expel_name)
    '''

    def __init__(self, field_name, start, end):
        self.start = start
        self.end = end
        self.field_name = field_name

        if type(self.start) == datetime.datetime:
            self.start = self.start.isoformat()

        if type(self.end) == datetime.datetime:
            self.end = self.end.isoformat()

    def create(self):
        retvals = []
        if self.start is not None:
            retvals.append(('filter[%s]' % self.field_name, '>%s' % self.start))

        if self.end is not None:
            retvals.append(('filter[%s]' % self.field_name, '<%s' % self.end))

        return retvals


class flag:
    def __init__(self, field, value):
        self.field = field
        self.value = value

    def create(self):
        return [('flag[%s]' % self.field, self.value)]


class relationship:
    '''
    relationship operator allows for searching of resource objects based on their relationship to other resource objects.

    :param rel_path: A dot notation of the relationship path to a resource object.
    :type rel_path: str
    :param value: The value the rel_path be compared to. This can be an operator, or a primitive value.
    :type value: object

    Examples:
        >>> for inv_action in xc.investigative_actions.search(relationship("investigation.close_comment", notnull()):
        >>>     print("Found investigative action associated with an investigation that has no close comment.")
    '''

    def __init__(self, rel_path, value):
        self.value = value
        self.rel_path = rel_path
        self.has_id = self.rel_path.endswith('_id')
        self.rel_path = self.rel_path.replace('_id', '')
        self.rel_parts = self.rel_path.split('.')

        if len(self.rel_parts) > 2:
            raise Exception("relationship() operator can only be used to define a relationship one level deep. Got %d levels with path %s" % (
                len(self.rel_parts), self.rel_path))

    def create(self, rels):
        value = [self.value]
        if is_operator(self.value):
            value = self.value.create()

        if self.rel_parts[0] not in rels:
            raise Exception("%s not a defined relationship in %s" % (self.rel_parts[0], ','.join(rels)))

        qstr = 'filter' + ''.join(['[%s]' % part for part in self.rel_parts])
        if self.has_id:
            qstr += '[id]'

        results = []
        for rhs in value:
            results.append((qstr, rhs))
        return results


def is_operator(value):
    '''
    Determine if a value implements an operator.

    :param value: The value to check
    :type value: object

    :return: `True` if value is an operator `False` otherwise.
    :rtype: bool
    '''
    if issubclass(type(value), operator):
        return True
    return False


class BaseResourceObject:
    '''
    '''

    def __init__(self, cls, content=None, api_type=None, conn=None):
        self.cls = cls
        self.content = content

        self.api_type = cls._api_type
        self.conn = conn

    def make_url(self, api_type, relation=None, value=None, relationship=False):
        '''
        Construct a JSON API compliant URL that handles requesting relationships, filtering, and including resources.

        :param api_type: The base JSON API resource type
        :type api_type: str
        :param relation: A JSON API resource type relationship to filter by
        :type relation: str or None
        :param value: The ID for the ``api_type``
        :type value: GUID or None
        :param relationship: A flag indicating the relationships suffix should be used when constructing the JSON API URL
        :type relationship: bool or None
        :return: A JSON API compliant URL
        :rtype: str

        Examples:
            >>> url = self.make_url('customers', value='56f00b9b-8fdf-4f7d-aca0-de431f7f50e6', filter_by='investigations')
        '''
        url = '/api/v2/%s' % api_type
        if value is not None:
            url += '/%s' % value

        if relation and relation != api_type:
            if relationship:
                url += '/relationships'
            # NOTE:
            # The route  `GET /:resource/:id/:relation` returns related data (and allows sorting, filtering, etc of that data).
            # The routes `GET|POST|PATCH|DELETE /:resource/:id/relationships/:relation` are used to view and manipulate the *relationships* themselves (i.e. they are not designed for viewing the actual data of the related records).
            url += '/%s' % relation
        return url

    def build_url(self, id=None, relation=None, limit=None, include=None, **kwargs):
        '''
        Given some JSON API retrieval inputs such as id, limit, or other filters. Build the URI that is JSON API compliant.

        :param id: The ID of the resource
        :type id: str or None
        :param relation: A relation that will return related data
        :type relation: str or None
        :param limit: limit the number of resources returned
        :type limit: int or None
        :param kwargs: This kwargs dict is any attribute that the JSON resource has that a developer wants to filter on
        :type kwargs: dict or None
        :return: A JSON API compliant URL
        :rtype: str

        Examples:
            >>> url = xc.investigations.build_url(id=some_guid)
            >>> url = xc.investigations.build_url(customer_id=CUSTOMER_GUID, limit=10)
        '''
        query = []
        url = ''

        if kwargs:

            # Pull out anything that starts with `flag_` .. to create the flag parameter..
            # Example:?flag[scope]=exclude_expired
            for name, value in dict(kwargs).items():
                if name.startswith('flag_'):
                    _, flag_name = name.split('_', 1)
                    query.append(('flag[%s]' % flag_name, value))
                    kwargs.pop(name)

            # Extract from kwargs filter by params that specify gte, gt, lte, lt
            op_look_up = {'_gt': '>', '_lt': '<'}
            # Do we have relationships that have this field as an attribute
            # so we are doing a second level filter..
            # filter_by(action_type='MANUAL', investigation__customer_id)
            # `curl /api/v2/investigative_action?filter[action_type]=MANUAL&filter[investigation][customer][id]=94e7dc2e-f461-4acc-97ae-6fde75ee434a&page[limit]=0 | jq '.meta.page.total`;`
            for name, value in dict(kwargs).items():
                orig_name = name
                if value is None:
                    kwargs.pop(orig_name)
                    continue

                for op_name, op in op_look_up.items():
                    if name.endswith(op_name):
                        name = name[:-len(op_name)]
                        value = '%s%s' % (op, value)

                if name in self.cls._def_attributes:
                    query.append(('filter[%s]' % name, value))
                    kwargs.pop(orig_name)

                # Create the relationship name
                rname = name
                has_id = False
                if name.endswith('_id'):
                    rname = name.replace('_id', '')
                    has_id = True

                parts = rname.split('__')
                # NOTE: users can specify __ to indicate a relationship to a new object that they then want to filter on the body of..
                # For example investigative_actions.filter_by(action_type='MANUAL', investigation__customer_id='someguid") would filter on investigative actions
                # that are manual and map to an investigation owned by customer someguid..
                if parts[0] in self.cls._def_relationships:
                    qstr = 'filter' + ''.join(['[%s]' % part for part in parts])
                    if has_id:
                        qstr += '[id]'
                    query.append((qstr, value))
                    kwargs.pop(orig_name, None)

                if not len(kwargs):
                    break
        if kwargs:
            raise Exception("Unrecognized parameters %s!" % ','.join(["%s=%s" % (k, v) for k, v in kwargs.items()]))

        url = self.make_url(self.api_type, value=id, relation=relation)
        if limit is not None:
            query.append(('page[limit]', limit))

        if include is not None:
            query.append(('include', include))

        query.append(('sort', 'created_at'))
        query.append(('sort', 'id'))

        if query:
            url = url + '?' + urlencode(query)
        return url

    def _fetch_page(self, url):
        content = self.conn.request('get', url).json()
        entries = content.get('data', [])
        included = content.get('included', [])
        if type(entries) != list:
            entries = [entries]

        content['data'] = [RELATIONSHIP_TO_CLASS[entry['type']](entry, self.conn) for entry in entries]
        content['included'] = [RELATIONSHIP_TO_CLASS[entry['type']](entry, self.conn) for entry in included]
        return content

    def filter_by(self, **kwargs):
        '''
        Issue a JSON API call requesting a JSON API resource is filtered by some set
        of attributes, id, limit, etc.

        :param kwargs: The base JSON API resource type
        :type kwargs: dict
        :return: A BaseResourceObject object
        :rtype: BaseResourceObject

        Examples:
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> for inv in xc.investigations.filter_by(customer_id=CUSTOMER_GUID):
            >>>     print(inv.title)
        '''
        url = self.build_url(**kwargs)
        self.content = self._fetch_page(url)
        return self

    def search(self, *args, **kwargs):
        '''
        Search based on a set of criteria made up of operators and attributes.

        :param args: Operators of either relationship, window, flag
        :type args: tuple
        :param limit: Limit the number of results returned.
        :type limit: int
        :param include: Include specific base resource names in request
        :type include: str
        :param kwargs: Fields and values to search on
        :type kwargs: dict
        :return: A BaseResourceObject object
        :rtype: :class:`BaseResourceObject`

        Examples:
            >>> for inv in xc.investigations.filter_by(customer_id=CUSTOMER_GUID):
            >>>     print(inv.title)

        '''

        query = []
        limit = kwargs.pop('limit', None)
        include = kwargs.pop('include', None)

        for rel in args:
            if type(rel) == relationship:
                q = rel.create(self.cls._def_relationships)
                query.extend(q)
            elif type(rel) in [flag, window]:
                q = rel.create()
                if q:
                    query.extend(q)
            else:
                raise Exception("Unexpected arg passed to filter %s" % type(rel))

        for field_name, field_value in kwargs.items():

            # if field_name not in self.cls._def_attributes and field_name not in :
            if is_operator(field_value):
                for rhs in field_value.create():
                    query.append(('filter[%s]' % field_name, rhs))
            else:
                query.append(('filter[%s]' % field_name, field_value))

        url = self.make_url(self.api_type)

        query.append(('sort', 'created_at'))
        query.append(('sort', 'id'))

        if limit is not None:
            query.append(('page[limit]', limit))
        if include is not None:
            query.append(('include', include))

        if query:
            url = url + '?' + urlencode(query)

        self.content = self._fetch_page(url)
        return self

    def count(self):
        '''
        Return the number of records in a JSON API response. You can get the count for entries returned by filtering, or
        you can request the count of the total number of resource instances. The total number of resource instances does not
        require paginating overall entries.

        :return: The number of records in a JSON API response
        :rtype: int

        Examples:
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> print("Investigation Count: ", xc.investigations.filter_by(customer_id=CUSTOMER_GUID).count())
            >>> print("Investigation Count: ", xc.investigations.count())
        '''
        content = self.content
        if not content:
            url = self.make_url(self.api_type)
            content = self.conn.request('get', url + '?page[limit]=0').json()
        return content.get('meta', {}).get('page', {}).get('total', 0)

    def one_or_none(self):
        '''
        Return one record from a JSON API response or None if there were no records.

        :return: A BaseResourceObject object
        :rtype: BaseResourceObject

        Examples:
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> inv = xc.investigations.filter_by(customer_id=CUSTOMER_GUID).one_or_none()
            >>> print(inv.title)
        '''
        entry = None
        for item in self:
            entry = item
            break
        return entry

    def get(self, **kwargs):
        '''
        Request a JSON api resource by id.

        :param id: The GUID of the resource
        :type id: str
        :return: A BaseResourceObject object
        :rtype: BaseResourceObject

        Examples:
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> inv = xc.investigations.get(id=investigation_guid)
            >>> print(inv.title)
        '''
        assert 'id' in kwargs
        assert len(kwargs) == 1

        url = self.build_url(**kwargs)
        content = self.conn.request('get', url).json()
        assert type(content['data']) == dict
        return self.cls(content['data'], self.conn)

    def __iter__(self):
        '''
        Iterate over the JSON response. This iterator will paginate the response to traverse all records return by
        the JSON API request.

        :return: A BaseResourceObject object
        :rtype: BaseResourceObject
        '''

        if self.content is None:
            url = self.make_url(self.api_type)
            self.content = self._fetch_page(url)

        content = self.content
        next_uri = content.get('links', {}).get('next')
        for entry in content['data']:
            yield entry

        for entry in content['included']:
            yield entry

        while next_uri:
            content = self._fetch_page(next_uri)
            for entry in content['data']:
                yield entry

            for entry in content['included']:
                yield entry

            next_uri = content.get('links', {}).get('next')

    def create(self, **kwargs):
        '''
        Create a ResourceInstance object that represents some Json API resource.

        :param kwargs: Attributes to set on the new JSON API resource.
        :type kwargs: dict
        :return: A ResourceInstance object that represents the JSON API resource type requested by the dev.
        :rtype: ResourceInstance

        Examples:
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> i = xc.investigations.create(title='Peter: new investigation 1', relationship_customer=CUSTOMER_GUID, relationship_assigned_to_actor=PETER_S)
            >>> i.save()
        '''
        return self.cls.create(self.conn, **kwargs)


# AUTO GENERATE FIELD TO TYPE

MACGYVER_FIELD_TO_TYPE = {'actor': 'actors',
                          'add_to_actions': 'context_label_actions',
                          'alert_on_actions': 'context_label_actions',
                          'analysis_assigned_investigative_actions': 'investigative_actions',
                          'analysis_assigned_to_actor': 'actors',
                          'analysis_email_file': 'files',
                          'api_keys': 'api_keys',
                          'assembler': 'assemblers',
                          'assemblers': 'assemblers',
                          'assignables': 'actors',
                          'assigned_customer_resilience_actions': 'customer_resilience_actions',
                          'assigned_customer_resilience_actions_list': 'customer_resilience_actions',
                          'assigned_expel_alerts': 'expel_alerts',
                          'assigned_investigations': 'investigations',
                          'assigned_investigative_actions': 'investigative_actions',
                          'assigned_organization_resilience_actions': 'organization_resilience_actions',
                          'assigned_organization_resilience_actions_list': 'organization_resilience_actions',
                          'assigned_remediation_actions': 'remediation_actions',
                          'assigned_to_actor': 'actors',
                          'assigned_to_org': 'actors',
                          'attachment_file': 'files',
                          'child_actors': 'actors',
                          'child_security_devices': 'security_devices',
                          'child_vendor_devices': 'vendor_devices',
                          'coincident_vendor_alerts': 'vendor_alerts',
                          'comment': 'comments',
                          'comment_histories': 'comment_histories',
                          'comments': 'comments',
                          'configuration_default': 'configuration_defaults',
                          'configuration_defaults': 'configuration_defaults',
                          'configurations': 'configurations',
                          'context_label': 'context_labels',
                          'context_label_actions': 'context_label_actions',
                          'context_label_tags': 'context_label_tags',
                          'context_labels': 'context_labels',
                          'created_by': 'actors',
                          'customer': 'customers',
                          'customer_device': 'customer_devices',
                          'customer_devices': 'customer_devices',
                          'customer_em_meta': 'customer_em_meta',
                          'customer_resilience_action': 'customer_resilience_actions',
                          'customer_resilience_action_group': 'customer_resilience_action_groups',
                          'customer_resilience_action_groups': 'customer_resilience_action_groups',
                          'customer_resilience_actions': 'customer_resilience_actions',
                          'customers': 'customers',
                          'dependent_investigative_actions': 'investigative_actions',
                          'depends_on_investigative_action': 'investigative_actions',
                          'destination_expel_alerts': 'expel_alerts',
                          'destination_investigations': 'investigations',
                          'destination_ip_addresses': 'ip_addresses',
                          'engagement_manager': 'engagement_managers',
                          'evidence': 'vendor_alert_evidences',
                          'evidenced_expel_alerts': 'expel_alerts',
                          'evidences': 'vendor_alert_evidences',
                          'expel_alert': 'expel_alerts',
                          'expel_alert_histories': 'expel_alert_histories',
                          'expel_alert_threshold': 'expel_alert_thresholds',
                          'expel_alert_threshold_histories': 'expel_alert_threshold_histories',
                          'expel_alerts': 'expel_alerts',
                          'expel_user': 'user_accounts',
                          'expel_users': 'expel_users',
                          'features': 'features',
                          'files': 'files',
                          'findings': 'investigation_findings',
                          'initial_email_file': 'files',
                          'integrations': 'integrations',
                          'investigation': 'investigations',
                          'investigation_finding': 'investigation_findings',
                          'investigation_finding_histories': 'investigation_finding_histories',
                          'investigation_hints': 'investigations',
                          'investigation_histories': 'investigation_histories',
                          'investigation_resilience_actions': 'investigation_resilience_actions',
                          'investigations': 'investigations',
                          'investigative_action': 'investigative_actions',
                          'investigative_action_histories': 'investigative_action_histories',
                          'investigative_actions': 'investigative_actions',
                          'ip_addresses': 'ip_addresses',
                          'labels': 'configuration_labels',
                          'last_published_by': 'actors',
                          'lead_expel_alert': 'expel_alerts',
                          'nist_category': 'nist_categories',
                          'nist_subcategories': 'nist_subcategories',
                          'nist_subcategory': 'nist_subcategories',
                          'nist_subcategory_score': 'nist_subcategory_scores',
                          'nist_subcategory_score_histories': 'nist_subcategory_score_histories',
                          'nist_subcategory_scores': 'nist_subcategory_scores',
                          'notification_preferences': 'notification_preferences',
                          'organization': 'organizations',
                          'organization_em_meta': 'organization_em_meta',
                          'organization_resilience_action': 'organization_resilience_actions',
                          'organization_resilience_action_group': 'organization_resilience_action_groups',
                          'organization_resilience_action_group_actions': 'organization_resilience_actions',
                          'organization_resilience_action_groups': 'organization_resilience_action_groups',
                          'organization_resilience_action_hints': 'organization_resilience_actions',
                          'organization_resilience_actions': 'organization_resilience_actions',
                          'organization_status': 'organization_statuses',
                          'organization_user_account_roles': 'user_account_roles',
                          'organizations': 'organizations',
                          'parent_actor': 'actors',
                          'parent_security_device': 'security_devices',
                          'parent_vendor_device': 'vendor_devices',
                          'phishing_submission': 'phishing_submissions',
                          'phishing_submission_attachment': 'phishing_submission_attachments',
                          'phishing_submission_attachments': 'phishing_submission_attachments',
                          'phishing_submission_domains': 'phishing_submission_domains',
                          'phishing_submission_headers': 'phishing_submission_headers',
                          'phishing_submission_urls': 'phishing_submission_urls',
                          'phishing_submissions': 'phishing_submissions',
                          'primary_organization': 'organizations',
                          'products': 'products',
                          'raw_body_file': 'files',
                          'related_investigations': 'investigations',
                          'related_investigations_via_involved_host_ips': 'investigations',
                          'remediation_action': 'remediation_actions',
                          'remediation_action_asset': 'remediation_action_assets',
                          'remediation_action_asset_histories': 'remediation_action_asset_histories',
                          'remediation_action_assets': 'remediation_action_assets',
                          'remediation_action_histories': 'remediation_action_histories',
                          'remediation_actions': 'remediation_actions',
                          'resilience_action': 'resilience_actions',
                          'resilience_action_group': 'resilience_action_groups',
                          'resilience_action_investigation_properties': 'resilience_action_investigation_properties',
                          'resilience_actions': 'resilience_actions',
                          'review_requested_by': 'actors',
                          'saml_identity_provider': 'saml_identity_providers',
                          'secret': 'secrets',
                          'security_device': 'security_devices',
                          'security_devices': 'security_devices',
                          'similar_alerts': 'expel_alerts',
                          'source_expel_alerts': 'expel_alerts',
                          'source_investigations': 'investigations',
                          'source_ip_addresses': 'ip_addresses',
                          'source_resilience_action': 'resilience_actions',
                          'source_resilience_action_group': 'resilience_action_groups',
                          'status_last_updated_by': 'actors',
                          'suppress_actions': 'context_label_actions',
                          'suppressed_by': 'expel_alert_thresholds',
                          'suppresses': 'expel_alert_thresholds',
                          'timeline_entries': 'timeline_entries',
                          'updated_by': 'actors',
                          'user_account': 'user_accounts',
                          'user_account_roles': 'user_account_roles',
                          'user_account_status': 'user_account_statuses',
                          'user_accounts': 'user_accounts',
                          'user_accounts_with_roles': 'user_accounts',
                          'vendor': 'vendors',
                          'vendor_alert': 'vendor_alerts',
                          'vendor_alerts': 'vendor_alerts',
                          'vendor_device': 'vendor_devices',
                          'vendor_devices': 'vendor_devices'}
# END AUTO GENERATE FIELD TO TYPE


class Relationship:
    '''
    The object acts a helper to handle JSON API relationships. The object is just a dummy that
    allows for setting / getting attributes that are extracted from the relationship part of the
    JSON API response. Additionally, the object will allow for conversion to a JSON API compliant
    relationship block to include in a request.
    '''

    def __init__(self):
        self._rels = {}
        self._modified = False

    def __getattr__(self, key):
        if key[0] != '_':
            return self._rels[key]
        return super().__getattr__(key)

    def __setattr__(self, key, value):
        if key[0] != '_':
            self._rels[key] = value
        super().__setattr__('_modified', True)
        super().__setattr__(key, value)

    def to_relationship(self):
        '''
        Generate a JSON API compliant relationship section.

        :return: A dict that is JSON API compliant relationship section.
        :rtype: dict
        '''
        relationships = {}
        for relname, relid in self._rels.items():
            reltype = MACGYVER_FIELD_TO_TYPE.get(relname, relname)
            if reltype[-1] != 's':
                reltype = '%ss' % relname

            if type(relid) == RelEntry:
                if relid.type is not None:
                    reltype = relid.type
                    relid = relid.id
                else:
                    continue

            if relid is None:
                continue

            # NOTE: specific exclusion due to reasons :)
            if relname in ['notification_preferences', 'organization_status']:
                continue

            if relname[-1] == 's':
                if type(relid) == list:
                    relationships[relname] = {'data': [{'id': rid, 'type': reltype} for rid in relid]}
                else:
                    relationships[relname] = {'data': [{'id': relid, 'type': reltype}]}
            else:
                relationships[relname] = {'data': {'id': relid, 'type': reltype}}
        return relationships


class RelEntry:
    def __init__(self, relentry):
        self.id = None
        self.type = None
        if relentry is None:
            relentry = dict()
        if type(relentry) == list:
            logger.warning("HIT A RELATIONSHIP ENTRY THAT IS A LIST!")
            return
        self.id = relentry.get('id')
        self.type = relentry.get('type')


class ResourceInstance:
    '''
    Represents an instance of a base resource.
    '''
    _api_type = None

    def __init__(self, data, conn):
        self._data = data
        self._id = data.get('id')
        self._create_id = data['attributes'].get('id')
        self._create = False
        if self._id is None:
            self._create = True

        self._attrs = data['attributes']
        self._conn = conn
        self._modified_fields = set()
        self._relationship = Relationship()
        self._relobjs = {}
        self._deleted = False
        for relname, relinfo in self._data.get('relationships', {}).items():
            reldata = relinfo.get('data')
            if type(reldata) == list:
                for d in reldata:
                    setattr(self._relationship, relname, RelEntry(d))
            setattr(self._relationship, relname, RelEntry(reldata))
        # Modified flag gets flipped to true when we build the relationships .. So we set it to False
        # once we are done.. This is pretty hacky..
        setattr(self._relationship, '_modified', False)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self._deleted:
            return
        # If we aren't creating a new resource, we haven't modified any attributes, and we have no modified relationships
        # then all we've done is grab fields out the object.. THere is no need to issue a patch.
        elif not self._create and not self._modified_fields and not self._relationship._modified:
            return
        self.save()
        return

    def _rel_to_class(self, key):
        if key in RELATIONSHIP_TO_CLASS:
            return RELATIONSHIP_TO_CLASS[key]

        if key in RELATIONSHIP_TO_CLASS_EXT:
            return RELATIONSHIP_TO_CLASS_EXT[key]
        return RELATIONSHIP_TO_CLASS[MACGYVER_FIELD_TO_TYPE[key]]

    def __getattr__(self, key):
        if key[0] != '_':
            # The accessed member is in the relationships definition
            if key in self._data['relationships']:
                if key not in self._relobjs:
                    # Look up the relationship information
                    url = self._data['relationships'][key]['links']['related']
                    resp_data = self._conn.request('get', url).json()['data']
                    if resp_data is None:
                        return None

                    if type(resp_data) == dict:
                        self._relobjs[key] = self._rel_to_class(key)(resp_data, self._conn)
                    else:
                        # Soemtimes we get data as a list, example if investigation_findings response
                        self._relobjs[key] = [self._rel_to_class(key)(entry, self._conn) for entry in resp_data]
                return self._relobjs[key]

            elif key in self._attrs:
                # Get a field in the attributes
                return self._attrs[key]
            elif key == 'relationship':
                return self._relationship
            raise ValueError('Looking up %s, relationship doesnt exist!' % key)
        return super().__getattr__(key)

    def __setattr__(self, key, value):
        if key[0] != '_':
            if key in self._attrs:
                self._attrs[key] = value
                self._modified_fields.add(key)
            else:
                raise ValueError('%s is an unrecognized attribute!' % key)
            return
        super().__setattr__(key, value)

    @classmethod
    def from_resp(cls, data):
        return cls(data)

    def __str__(self):
        attrs = copy.deepcopy(self._attrs)
        attrs['id'] = self._id
        return pprint.pformat(attrs)

    @property
    def id(self):
        '''
        Retreive the identifier for the resource instance.

        :return: A GUID representing the unique instance
        :rtype: str

        Examples:
            >>> for inv in xc.investigations.filter_by(status='OPEN'):
            >>>     print("Investigation ID is %s" % inv.id)
        '''
        return self._id

    def save(self):
        '''
        Write changes made to a resource instance back to the sever.

        :return: The updated resource instance
        :rtype: :class:`ResourceInstance`

        Examples:
            >>> i = xc.investigations.create(title='Peter: new investigation 1', relationship_customer=ORGANIZATION_ID, relationship_assigned_to_actor=ACTOR_ID)
            >>> i.save()
        '''
        if not self._create:
            attrs = {field: self._attrs[field] for field in self._modified_fields}
            body = {'data': {'type': self._api_type, 'attributes': attrs}}
            body['data']['relationships'] = self._relationship.to_relationship()
            body['id'] = self._id
            resp = self._conn.request('patch', '/api/v2/{}/{}'.format(self._api_type, self._id), data=json.dumps(body))
        else:
            body = {'data': {'type': self._api_type, 'attributes': self._attrs}}
            body['data']['relationships'] = self._relationship.to_relationship()
            if self._create_id:
                body['id'] = self._create_id
            resp = self._conn.request('post', '/api/v2/{}'.format(self._api_type), data=json.dumps(body))
            self._id = resp.json()['data']['id']
            self._create = False
        return self._rel_to_class(self._api_type)(resp.json()['data'], self._conn)

    @classmethod
    def create(cls, conn, **kwargs):
        '''
        Create a new resource instance. Users need to call save() after create to write changes to the server.

        :return: The updated resource instance
        :rtype: :class:`ResourceInstance`

        Examples:
            >>> i = xc.investigations.create(title='Peter: new investigation 1', relationship_customer=ORGANIZATION_ID, relationship_assigned_to_actor=ACTOR_ID)
            >>> i.save()
        '''

        attrs = {k: v for k, v in kwargs.items() if not k.startswith('relationship_') and v is not None}
        rels = {}
        for k, v in kwargs.items():
            if k.startswith('relationship_'):
                _, name = k.split('_', 1)
                rels[name] = {'data': {'id': v, 'type': MACGYVER_FIELD_TO_TYPE.get(name, '%ss' % name)}}

        body = {'attributes': attrs, 'relationships': rels}
        c = cls(body, conn)
        return c

    def delete(self, prompt_on_delete=True):
        '''
        Delete a resource instance.


        :param prompt_on_delete: `True` if user wants to be prompted when delete is issued and `False` otherwise., defaults to `True`.
        :type prompt_on_delete: bool, optional

        Examples:
            >>> inv = xc.investigations.get(id='a8bf9750-6a79-4415-9558-a56253606b9f')
            >>> inv.delete()
        '''
        body = {'data': {'type': self._api_type, 'attributes': self._attrs}}
        body['id'] = self._id
        self._conn.request('delete', '/api/v2/{}/{}'.format(self._api_type, self._id),
                           data=json.dumps(body), prompt_on_delete=prompt_on_delete)
        self._deleted = True


class FilesResourceInstance(ResourceInstance):
    def download(self, fd, fmt='json'):
        '''
        Download data from an investigative action. This can only be called on InvestigativeAction or Files objects.


        :param fd: Buffer to write response too.
        :type fd: File bytes object
        :param fmt: The format to request the data be returned in.
        :type fmt: str

        Examples:
            >>> import json
            >>> import pprint
            >>> import tempfile
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> with xc.investigative_actions.get(id=inv_act_id) as ia:
            >>>     fd = tempfile.NamedTemporaryFile(delete=False)
            >>>     ia.download(fd)
            >>>     with open(fd.name, 'r') as fd:
            >>>     pprint.pprint(json.loads(fd.read()))
        '''

        if self._api_type == 'files':
            resp = self._conn.request('get', '/api/v2/{}/{}/download?format={}'.format(self._api_type, self._id, fmt))
        elif self._api_type == 'investigative_actions':
            resp = self._conn.request('get', '/api/v2/tasks/{}/download?format={}'.format(self.result_task_id, fmt))
        else:
            raise Exception("Can not download from api type: %s!" % self._api_type)

        for chunk in resp.iter_content(chunk_size=1024):
            if chunk:
                fd.write(chunk)


class InvestigativeActionsResourceInstance(FilesResourceInstance):
    def upload(self, filename, fbytes, expel_file_type=None, file_meta=None):
        '''
            Upload data associated with an investigative action. Can only be called on InvestigativeAction objects.


            :param filename: Filename, this shows up in Workbench.
            :type filename: str
            :param fbytes: A bytes string representing raw bytes to upload
            :type fbytes: bytes

            Examples:
                >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
                >>> with xc.investigative_actions.get(id=inv_act_id) as ia:
                >>>     ia.upload('test.txt', b'hello world')
            '''

        if self._api_type != 'investigative_actions':
            raise Exception("Can not upload for api type: %s!" % self._api_type)

        # set file_meta to a default..
        if file_meta is None:
            file_meta = {'investigative_action': {'file_type': 'results'}}

        # Get the customer id from the inv or expel alert relationship
        customer_id = None
        if self.relationship.investigation.id:
            customer_id = self._conn.investigations.get(id=self.relationship.investigation.id).customer.id
        elif self.relationship.expel_alert.id:
            customer_id = self._conn.expel_alerts.get(id=self.relationship.expel_alert.id).customer.id
        else:
            raise Exception("Could not determine customer id")

        # Create a files object
        f = self._conn.files.create(filename=filename, file_meta=file_meta, expel_file_type=expel_file_type)
        f.relationship.customer = customer_id
        # This gets pluralized ..
        f.relationship.investigative_actions = self.id
        resp = f.save()
        fid = resp.id

        # Upload the data
        files = {'file': io.BytesIO(fbytes)}
        resp = self._conn.request('post', '/api/v2/files/{}/upload'.format(fid), files=files)

        # Set it ready for analysis.
        with self._conn.investigative_actions.get(id=self.id) as ia:
            existing_files = [f.id for f in ia.files]
            ia.status = 'READY_FOR_ANALYSIS'
            ia.relationship.files = existing_files.append(fid)

        return fid

# AUTO GENERATE JSONAPI CLASSES


class NistSubcategories(ResourceInstance):
    '''
    .. _api nist_subcategories:

    Defines/retrieves expel.io nist_subcategory records

    Resource type name is **nist_subcategories**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'identifier': 'string', 'name': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Field Description                                    | Field Name                  | Field Type                         | Attribute     | Relationship     |
        +======================================================+=============================+====================================+===============+==================+
        | Created timestamp: readonly                          | created_at                  | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Nist subcategory title Allows: "", null              | name                        | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Nist subcategory abbreviated identifier              | identifier                  | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                     | updated_at                  | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records             | created_by                  | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records             | updated_by                  | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_category records     | nist_category               | :class:`NistCategories`            | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                       | nist_subcategory_scores     | :class:`NistSubcategoryScores`     | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategories'
    _def_attributes = ["created_at", "name", "identifier", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "nist_category", "nist_subcategory_scores"]


class InvestigativeActionHistories(ResourceInstance):
    '''
    .. _api investigative_action_histories:

    Investigative action histories

    Resource type name is **investigative_action_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'deleted_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description                                                                                   | Field Name               | Field Type                        | Attribute     | Relationship     |
        +=====================================================================================================+==========================+===================================+===============+==================+
        | Created timestamp: readonly                                                                         | created_at               | string                            | Y             | N                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Investigative action history action Restricted to: "CREATED", "ASSIGNED", "CLOSED" Allows: null     | action                   | any                               | Y             | N                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                   | deleted_at               | string                            | Y             | N                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Investigative action history details Allows: null: no-sort                                          | value                    | object                            | Y             | N                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                            | created_by               | :class:`Actors`                   | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions                                                                               | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Investigations                                                                                      | investigation            | :class:`Investigations`           | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Expel alerts                                                                                        | expel_alert              | :class:`ExpelAlerts`              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                            | assigned_to_actor        | :class:`Actors`                   | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_histories'
    _def_attributes = ["created_at", "action", "deleted_at", "value"]
    _def_relationships = ["created_by", "investigative_action", "investigation", "expel_alert", "assigned_to_actor"]


class InvestigativeActionDataQueryDomain(ResourceInstance):
    '''
    .. _api investigative_action_data_query_domain:

    Investigative action data for query_domain

    Resource type name is **investigative_action_data_query_domain**.

    Example JSON record:

    .. code-block:: javascript

        {           'application': 'string',
            'domain': 'string',
            'dst': 'string',
            'dst_processes': 'string',
            'event_description': 'string',
            'evidence_type': 'string',
            'file_events': 'string',
            'network_events': 'string',
            'process_name': 'string',
            'process_pid': 100,
            'protocol': 'string',
            'referer': 'string',
            'registry_events': 'string',
            'src': 'string',
            'started_at': 'string',
            'summary': 'string',
            'unsigned_modules': 'string',
            'url': 'https://company.com/'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | dst                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | summary                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | protocol                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | evidence_type            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | network_events           | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | referer                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | unsigned_modules         | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_events              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | url                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registry_events          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | process_pid              | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_name             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | application              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst_processes            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | event_description        | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | domain                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_domain'
    _def_attributes = ["dst", "summary", "protocol", "evidence_type", "network_events", "referer", "unsigned_modules", "started_at",
                       "file_events", "url", "registry_events", "process_pid", "process_name", "application", "dst_processes", "event_description", "src", "domain"]
    _def_relationships = ["investigative_action"]


class InvestigativeActionDataQueryUser(ResourceInstance):
    '''
    .. _api investigative_action_data_query_user:

    Investigative action data for query_user

    Resource type name is **investigative_action_data_query_user**.

    Example JSON record:

    .. code-block:: javascript

        {           'bytes_rx': 100,
            'bytes_tx': 100,
            'dst': 'string',
            'dst_port': 100,
            'dst_processes': 'string',
            'dst_user': 'string',
            'ended_at': 'string',
            'evidence_type': 'string',
            'file_events': 'string',
            'network_events': 'string',
            'process_name': 'string',
            'process_pid': 100,
            'registry_events': 'string',
            'sensor': 'string',
            'src': 'string',
            'src_user': 'string',
            'started_at': 'string',
            'summary': 'string',
            'unsigned_modules': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | dst                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | ended_at                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | evidence_type            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | bytes_rx                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | network_events           | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | unsigned_modules         | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_events              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | summary                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src_user                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registry_events          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | process_pid              | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | sensor                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_name             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | bytes_tx                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst_processes            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst_user                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | dst_port                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_user'
    _def_attributes = ["dst", "ended_at", "evidence_type", "bytes_rx", "network_events", "unsigned_modules", "started_at", "file_events",
                       "summary", "src_user", "registry_events", "process_pid", "sensor", "process_name", "bytes_tx", "dst_processes", "dst_user", "src", "dst_port"]
    _def_relationships = ["investigative_action"]


class Investigations(ResourceInstance):
    '''
    .. _api investigations:

    Investigations

    Resource type name is **investigations**.

    Example JSON record:

    .. code-block:: javascript

        {           'analyst_severity': 'CRITICAL',
            'attack_lifecycle': 'INITIAL_RECON',
            'attack_timing': 'HISTORICAL',
            'attack_vector': 'DRIVE_BY',
            'close_comment': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'critical_comment': 'string',
            'decision': 'FALSE_POSITIVE',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'detection_type': 'UNKNOWN',
            'has_hunting_status': True,
            'is_downgrade': True,
            'is_incident': True,
            'is_incident_status_updated_at': '2019-01-15T15:35:00-05:00',
            'is_surge': True,
            'last_published_at': '2019-01-15T15:35:00-05:00',
            'last_published_value': 'string',
            'lead_description': 'string',
            'open_comment': 'string',
            'properties': 'object',
            'review_requested_at': '2019-01-15T15:35:00-05:00',
            'short_link': 'string',
            'source_reason': 'HUNTING',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'threat_type': 'TARGETED',
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                           | Field Name                                       | Field Type                                   | Attribute     | Relationship     |
        +=============================================================================================================================================================================================================================================================================+==================================================+==============================================+===============+==================+
        | Experimental properties Allows: null: no-sort                                                                                                                                                                                                                               | properties                                       | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Review Requested At Allows: null                                                                                                                                                                                                                                            | review_requested_at                              | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Published Value Allows: "", null                                                                                                                                                                                                                                       | last_published_value                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Analyst Severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO" Allows: null                                                                                                                                                                                    | analyst_severity                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                            | updated_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Incident Status timestamp Allows: null: readonly                                                                                                                                                                                                                            | is_incident_status_updated_at                    | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Source Reason Restricted to: "HUNTING", "ORGANIZATION_REPORTED", "DISCOVERY", "PHISHING" Allows: null                                                                                                                                                                       | source_reason                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation short link: readonly                                                                                                                                                                                                                                          | short_link                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Vector Restricted to: "DRIVE_BY", "PHISHING", "PHISHING_LINK", "PHISHING_ATTACHMENT", "REV_MEDIA", "SPEAR_PHISHING", "SPEAR_PHISHING_LINK", "SPEAR_PHISHING_ATTACHMENT", "STRAG_WEB_COMP", "SERVER_SIDE_VULN", "CRED_THEFT", "MISCONFIG", "UNKNOWN" Allows: null     | attack_vector                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Timing Restricted to: "HISTORICAL", "PRESENT" Allows: null                                                                                                                                                                                                           | attack_timing                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is Incident                                                                                                                                                                                                                                                                 | is_incident                                      | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                           | deleted_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                 | created_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Lifecycle Restricted to: "INITIAL_RECON", "DELIVERY", "EXPLOITATION", "INSTALLATION", "COMMAND_CONTROL", "LATERAL_MOVEMENT", "ACTION_TARGETS", "UNKNOWN" Allows: null                                                                                                | attack_lifecycle                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is downgrade                                                                                                                                                                                                                                                                | is_downgrade                                     | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Detection Type Restricted to: "UNKNOWN", "ENDPOINT", "SIEM", "NETWORK", "EXPEL", "HUNTING", "CLOUD" Allows: null                                                                                                                                                            | detection_type                                   | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Decision Restricted to: "FALSE_POSITIVE", "TRUE_POSITIVE", "CLOSED", "OTHER", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "TESTING", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "INCONCLUSIVE" Allows: null                                                   | decision                                         | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Published At Allows: null                                                                                                                                                                                                                                              | last_published_at                                | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Critical Comment Allows: "", null                                                                                                                                                                                                                                           | critical_comment                                 | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                    | status_updated_at                                | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is surge                                                                                                                                                                                                                                                                    | is_surge                                         | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                                                                                                                                                                                                                                      | title                                            | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Reason the investigation/incident was opened Allows: "", null                                                                                                                                                                                                               | open_comment                                     | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Meta: readonly, no-sort                                                                                                                                                                                                                                                     | has_hunting_status                               | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Lead Description Allows: null                                                                                                                                                                                                                                               | lead_description                                 | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Threat Type Restricted to: "TARGETED", "TARGETED_APT", "TARGETED_RANSOMWARE", "BUSINESS_EMAIL_COMPROMISE", "NON_TARGETED", "NON_TARGETED_MALWARE", "POLICY_VIOLATION", "UNKNOWN" Allows: null                                                                               | threat_type                                      | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Close Comment Allows: "", null                                                                                                                                                                                                                                              | close_comment                                    | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                                                                                                         | remediation_actions                              | :class:`RemediationActions`                  | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | created_by                                       | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                                                                                                          | customer_resilience_actions                      | :class:`CustomerResilienceActions`           | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment_history records                                                                                                                                                                                                                          | comment_histories                                | :class:`CommentHistories`                    | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | source_ip_addresses                              | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                              | related_investigations_via_involved_host_ips     | :class:`Investigations`                      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | updated_by                                       | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io investigation_finding_history records                                                                                                                                                                                                            | investigation_finding_histories                  | :class:`InvestigationFindingHistories`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                                                                                                              | investigative_action_histories                   | :class:`InvestigativeActionHistories`        | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | File                                                                                                                                                                                                                                                                        | files                                            | :class:`Files`                               | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action histories                                                                                                                                                                                                                                                | remediation_action_histories                     | :class:`RemediationActionHistories`          | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action asset histories                                                                                                                                                                                                                                          | remediation_action_asset_histories               | :class:`RemediationActionAssetHistories`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                                                                                                                                                 | customer                                         | :class:`Customers`                           | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                | expel_alerts                                     | :class:`ExpelAlerts`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                                                                                                                                                                                     | context_label_actions                            | :class:`ContextLabelActions`                 | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | last_published_by                                | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation histories                                                                                                                                                                                                                                                     | investigation_histories                          | :class:`InvestigationHistories`              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                                                            | context_labels                                   | :class:`ContextLabels`                       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                                                                                                                                                                                 | evidence                                         | :class:`VendorAlertEvidences`                | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                                                                                                          | organization_resilience_action_hints             | :class:`OrganizationResilienceActions`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                             | organization                                     | :class:`Organizations`                       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                | lead_expel_alert                                 | :class:`ExpelAlerts`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io finding records                                                                                                                                                                                                                                  | findings                                         | :class:`InvestigationFindings`               | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                                                                                                          | organization_resilience_actions                  | :class:`OrganizationResilienceActions`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation to resilience actions                                                                                                                                                                                                                                         | investigation_resilience_actions                 | :class:`InvestigationResilienceActions`      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | assigned_to_actor                                | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Timeline Entries                                                                                                                                                                                                                                                            | timeline_entries                                 | :class:`TimelineEntries`                     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | ip_addresses                                     | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | destination_ip_addresses                         | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                                                                                                                                                                                       | expel_alert_histories                            | :class:`ExpelAlertHistories`                 | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                       | investigative_actions                            | :class:`InvestigativeActions`                | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | review_requested_by                              | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                                                                                                                                                                                                                  | comments                                         | :class:`Comments`                            | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | status_last_updated_by                           | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigations'
    _def_attributes = ["properties", "review_requested_at", "last_published_value", "analyst_severity", "updated_at", "is_incident_status_updated_at", "source_reason", "short_link", "attack_vector", "attack_timing", "is_incident", "deleted_at",
                       "created_at", "attack_lifecycle", "is_downgrade", "detection_type", "decision", "last_published_at", "critical_comment", "status_updated_at", "is_surge", "title", "open_comment", "has_hunting_status", "lead_description", "threat_type", "close_comment"]
    _def_relationships = ["remediation_actions", "created_by", "customer_resilience_actions", "comment_histories", "source_ip_addresses", "related_investigations_via_involved_host_ips", "updated_by", "investigation_finding_histories", "investigative_action_histories", "files", "remediation_action_histories", "remediation_action_asset_histories", "customer", "expel_alerts", "context_label_actions", "last_published_by",
                          "investigation_histories", "context_labels", "evidence", "organization_resilience_action_hints", "organization", "lead_expel_alert", "findings", "organization_resilience_actions", "investigation_resilience_actions", "assigned_to_actor", "timeline_entries", "ip_addresses", "destination_ip_addresses", "expel_alert_histories", "investigative_actions", "review_requested_by", "comments", "status_last_updated_by"]


class CustomerDevices(ResourceInstance):
    '''
    .. _api customer_devices:

    Organization devices

    Resource type name is **customer_devices**.

    Example JSON record:

    .. code-block:: javascript

        {           'connection_status': 'Never Connected',
            'connection_status_updated_at': '2019-01-15T15:35:00-05:00',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'install_code': 'string',
            'lifecycle_status': 'New',
            'lifecycle_status_updated_at': '2019-01-15T15:35:00-05:00',
            'location': 'string',
            'name': 'string',
            'status': 'string',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'vpn_ip': 'string'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                       | Field Name                       | Field Type                 | Attribute     | Relationship     |
        +=========================================================================================================================================================================================================================+==================================+============================+===============+==================+
        | Name of organization device Allows: "", null                                                                                                                                                                            | name                             | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device connection status update timestamp: readonly                                                                                                                                                        | connection_status_updated_at     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device status Allows: "", null: readonly, no-sort                                                                                                                                                          | status                           | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                        | updated_at                       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device last status update timestamp: readonly                                                                                                                                                              | status_updated_at                | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device lifecycle status update timestamp: readonly                                                                                                                                                         | lifecycle_status_updated_at      | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Location of organization device Allows: "", null                                                                                                                                                                        | location                         | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device install code Allows: null                                                                                                                                                                           | install_code                     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device life cycle status Restricted to: "New", "Authorized", "Transitioning", "Transitioned", "Transition Failed", "Configuring", "Configuration Failed", "Active", "Inactive", "Deleted" Allows: null     | lifecycle_status                 | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device VPN ip address Allows: null                                                                                                                                                                         | vpn_ip                           | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                       | deleted_at                       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                             | created_at                       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Organization device connection status Restricted to: "Never Connected", "Connection Lost", "Connected to Provisioning", "Connected to Service" Allows: null                                                             | connection_status                | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                | created_by                       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Vendor devices                                                                                                                                                                                                          | vendor_devices                   | :class:`VendorDevices`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                         | organization                     | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                | updated_by                       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                           | vendor_alerts                    | :class:`VendorAlerts`      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                                                                                             | customer                         | :class:`Customers`         | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'customer_devices'
    _def_attributes = ["name", "connection_status_updated_at", "status", "updated_at", "status_updated_at", "lifecycle_status_updated_at",
                       "location", "install_code", "lifecycle_status", "vpn_ip", "deleted_at", "created_at", "connection_status"]
    _def_relationships = ["created_by", "vendor_devices", "organization", "updated_by", "vendor_alerts", "customer"]


class Customers(ResourceInstance):
    '''
    .. _api customers:

    Defines/retrieves expel.io customer records

    Resource type name is **customers**.

    Example JSON record:

    .. code-block:: javascript

        {           'address_1': 'string',
            'address_2': 'string',
            'city': 'string',
            'country_code': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'hq_city': 'string',
            'hq_utc_offset': 'string',
            'industry': 'string',
            'is_surge': True,
            'name': 'string',
            'nodes_count': 100,
            'o365_tenant_id': 'string',
            'o365_tos_id': 'string',
            'postal_code': 'string',
            'prospect': True,
            'region': 'string',
            'service_renewal_at': '2019-01-15T15:35:00-05:00',
            'service_start_at': '2019-01-15T15:35:00-05:00',
            'short_name': 'EXP',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'users_count': 100,
            'vault_token': 'string',
            'vault_token_expires': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Field Description                                                                                             | Field Name                                        | Field Type                                  | Attribute     | Relationship     |
        +===============================================================================================================+===================================================+=============================================+===============+==================+
        | State/Province/Region Allows: "", null                                                                        | region                                            | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Address 1 Allows: "", null                                                                                    | address_1                                         | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                              | updated_at                                        | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | o365 Microsoft tenant id Allows: null: private                                                                | o365_tenant_id                                    | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | The customer's primary industry Allows: "", null                                                              | industry                                          | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Country Code Allows: null                                                                                     | country_code                                      | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Customer service start date Allows: null                                                                      | service_start_at                                  | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                             | deleted_at                                        | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Number of users covered for this customer Allows: null                                                        | users_count                                       | number                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                   | created_at                                        | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | The city where the organization's headquarters is located Allows: "", null                                    | hq_city                                           | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | o365 Terms of Service identifier (e.g. hubspot id, etc.) Allows: null                                         | o365_tos_id                                       | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Postal Code Allows: null                                                                                      | postal_code                                       | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | The customer's operating name                                                                                 | name                                              | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | City Allows: "", null                                                                                         | city                                              | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Is surge                                                                                                      | is_surge                                          | boolean                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Allows: "", null                                                                                              | hq_utc_offset                                     | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Allows: null: private                                                                                         | vault_token_expires                               | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Address 2 Allows: "", null                                                                                    | address_2                                         | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Vault Token Allows: null: private                                                                             | vault_token                                       | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Is Prospective/Demo Customer: private                                                                         | prospect                                          | boolean                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Number of nodes covered for this customer Allows: null                                                        | nodes_count                                       | number                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Customer short name Allows: null                                                                              | short_name                                        | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Customer service renewal date Allows: null                                                                    | service_renewal_at                                | string                                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | created_by                                        | :class:`Actors`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Assemblers                                                                                                    | assemblers                                        | :class:`Assemblers`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io configuration records                                                              | configurations                                    | :class:`Configurations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | assignables                                       | :class:`Actors`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | investigations                                    | :class:`Investigations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | updated_by                                        | :class:`Actors`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | customer_resilience_actions                       | :class:`CustomerResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | File                                                                                                          | files                                             | :class:`Files`                              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Expel users                                                                                                   | expel_users                                       | :class:`ExpelUsers`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer_resilience_action_group records                                           | customer_resilience_action_groups                 | :class:`CustomerResilienceActionGroups`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | actor                                             | :class:`Actors`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | expel_alerts                                      | :class:`ExpelAlerts`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Product features                                                                                              | features                                          | :class:`Features`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_customer_resilience_actions              | :class:`CustomerResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                 | notification_preferences                          | :class:`NotificationPreferences`            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | assigned_investigative_actions                    | :class:`InvestigativeActions`               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Organization devices                                                                                          | customer_devices                                  | :class:`CustomerDevices`                    | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | User accounts                                                                                                 | user_accounts                                     | :class:`UserAccounts`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Security devices                                                                                              | security_devices                                  | :class:`SecurityDevices`                    | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_customer_resilience_actions_list         | :class:`CustomerResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io integration records                                                                | integrations                                      | :class:`Integrations`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                           | assigned_remediation_actions                      | :class:`RemediationActions`                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Investigation histories                                                                                       | investigation_histories                           | :class:`InvestigationHistories`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | assigned_expel_alerts                             | :class:`ExpelAlerts`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                         | expel_alert_histories                             | :class:`ExpelAlertHistories`                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Vendor devices                                                                                                | vendor_devices                                    | :class:`VendorDevices`                      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Products                                                                                                      | products                                          | :class:`Products`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | assigned_investigations                           | :class:`Investigations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io engagement_manager records                                                         | engagement_manager                                | :class:`EngagementManagers`                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io api_key records. These can only be created by a user and require an OTP token.     | api_keys                                          | :class:`ApiKeys`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                 | vendor_alerts                                     | :class:`VendorAlerts`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer_em_meta records                                                           | customer_em_meta                                  | :class:`CustomerEmMeta`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+---------------------------------------------+---------------+------------------+

    '''
    _api_type = 'customers'
    _def_attributes = ["region", "address_1", "updated_at", "o365_tenant_id", "industry", "country_code", "service_start_at", "deleted_at", "users_count", "created_at", "hq_city",
                       "o365_tos_id", "postal_code", "name", "city", "is_surge", "hq_utc_offset", "vault_token_expires", "address_2", "vault_token", "prospect", "nodes_count", "short_name", "service_renewal_at"]
    _def_relationships = ["created_by", "assemblers", "configurations", "assignables", "investigations", "updated_by", "customer_resilience_actions", "files", "expel_users", "customer_resilience_action_groups", "actor", "expel_alerts", "assigned_organization_resilience_actions_list", "features", "assigned_customer_resilience_actions", "notification_preferences", "assigned_investigative_actions", "customer_devices",
                          "user_accounts", "assigned_organization_resilience_actions", "security_devices", "assigned_customer_resilience_actions_list", "integrations", "assigned_remediation_actions", "investigation_histories", "assigned_expel_alerts", "expel_alert_histories", "vendor_devices", "products", "assigned_investigations", "engagement_manager", "api_keys", "vendor_alerts", "customer_em_meta", "analysis_assigned_investigative_actions"]


class RemediationActionHistories(ResourceInstance):
    '''
    .. _api remediation_action_histories:

    Remediation action histories

    Resource type name is **remediation_action_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Field Name             | Field Type                      | Attribute     | Relationship     |
        +==========================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+========================+=================================+===============+==================+
        | Remediation action history details Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | value                  | object                          | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Action type of source parent remediation action Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type            | any                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation action history action Restricted to: "CREATED", "ASSIGNED", "COMPLETED", "CLOSED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | action                 | any                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | created_at             | string                          | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | created_by             | :class:`Actors`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | investigation          | :class:`Investigations`         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | remediation_action     | :class:`RemediationActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | assigned_to_actor      | :class:`Actors`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_histories'
    _def_attributes = ["value", "action_type", "action", "created_at"]
    _def_relationships = ["created_by", "investigation", "remediation_action", "assigned_to_actor"]


class Secrets(ResourceInstance):
    '''
    .. _api secrets:

    Organization secrets. Note - these requests must be in the format of `/secrets/security_device-<guid>`

    Resource type name is **secrets**.

    Example JSON record:

    .. code-block:: javascript

        {           'secret': {           'device_info': {'access_id': '7b0a343c-860e-442e-ab0b-d6f349d364d9', 'access_key': 'secret-access-key', 'source_category': 'alpha'},
                                  'device_secret': {'console_url': 'https://console-access-point.com', 'password': 'password', 'username': 'admin@company.com'},
                                  'two_factor_secret': 'CXKXNRPN8042IKGCLPGSXLBYIANNAI9T'}}


    Below are valid filter by parameters:

        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name       | Field Type                 | Attribute     | Relationship     |
        +=====================================================+==================+============================+===============+==================+
        | Allows: null                                        | secret           | object                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records         | customer         | :class:`Customers`         | N             | Y                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'secrets'
    _def_attributes = ["secret"]
    _def_relationships = ["customer", "organization"]


class OrganizationResilienceActionList(ResourceInstance):
    '''
    .. _api organization_resilience_action_list:

    Organization to resilience action list

    Resource type name is **organization_resilience_action_list**.

    Example JSON record:

    .. code-block:: javascript

        {'category': 'DISRUPT_ATTACKERS', 'comment': 'string', 'details': 'string', 'impact': 'LOW', 'incident_count': 100, 'status': 'TOP_PRIORITY', 'title': 'string', 'visible': True}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Field Description                                                                            | Field Name                               | Field Type                                      | Attribute     | Relationship     |
        +==============================================================================================+==========================================+=================================================+===============+==================+
        | Comment Allows: "", null                                                                     | comment                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Status Restricted to: "TOP_PRIORITY", "IN_PROGRESS", "WONT_DO", "COMPLETED" Allows: null     | status                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Details Allows: "", null                                                                     | details                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null                 | category                                 | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Incident count Allows: null                                                                  | incident_count                           | number                                          | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                                                       | title                                    | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Visible Allows: null                                                                         | visible                                  | boolean                                         | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH" Allows: null                                   | impact                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                           | organization_resilience_action           | :class:`OrganizationResilienceActions`          | N             | Y                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_resilience_action_group records                      | organization_resilience_action_group     | :class:`OrganizationResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                              | organization                             | :class:`Organizations`                          | N             | Y                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                     | assigned_to_actor                        | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organization_resilience_action_list'
    _def_attributes = ["comment", "status", "details", "category", "incident_count", "title", "visible", "impact"]
    _def_relationships = ["organization_resilience_action",
                          "organization_resilience_action_group", "organization", "assigned_to_actor"]


class InvestigativeActionDataRegListing(ResourceInstance):
    '''
    .. _api investigative_action_data_reg_listing:

    Investigative action data for reg_listing

    Resource type name is **investigative_action_data_reg_listing**.

    Example JSON record:

    .. code-block:: javascript

        {'reg_data': 'string', 'reg_last_modified': 'string', 'reg_path': 'string', 'reg_type': 'string', 'reg_username': 'string', 'reg_value': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | reg_value                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_data                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_type                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_username             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_path                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_last_modified        | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_reg_listing'
    _def_attributes = ["reg_value", "reg_data", "reg_type", "reg_username", "reg_path", "reg_last_modified"]
    _def_relationships = ["investigative_action"]


class UserAccountStatuses(ResourceInstance):
    '''
    .. _api user_account_statuses:

    User account status

    Resource type name is **user_account_statuses**.

    Example JSON record:

    .. code-block:: javascript

        {           'active': True,
            'active_status': 'ACTIVE',
            'created_at': '2019-01-15T15:35:00-05:00',
            'invite_token_expires_at': '2019-01-15T15:35:00-05:00',
            'password_reset_token_expires_at': '2019-01-15T15:35:00-05:00',
            'restrictions': [],
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                       | Field Name                          | Field Type                 | Attribute     | Relationship     |
        +=========================================================================================================================+=====================================+============================+===============+==================+
        | Missing Description                                                                                                     | restrictions                        | array                      | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Missing Description                                                                                                     | active                              | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Meta: readonly                                                                                                          | created_at                          | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Allows: null: readonly                                                                                                  | invite_token_expires_at             | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Meta: readonly                                                                                                          | updated_at                          | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Restricted to: "ACTIVE", "LOCKED", "LOCKED_INVITED", "LOCKED_EXPIRED", "ACTIVE_INVITED", "ACTIVE_EXPIRED": readonly     | active_status                       | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Allows: null: readonly                                                                                                  | password_reset_token_expires_at     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                | created_by                          | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                | updated_by                          | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                         | primary_organization                | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | User accounts                                                                                                           | user_account                        | :class:`UserAccounts`      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'user_account_statuses'
    _def_attributes = ["restrictions", "active", "created_at", "invite_token_expires_at",
                       "updated_at", "active_status", "password_reset_token_expires_at"]
    _def_relationships = ["created_by", "updated_by", "primary_organization", "user_account"]


class VendorAlertEvidences(ResourceInstance):
    '''
    .. _api vendor_alert_evidences:

    Vendor alert evidences are extracted from a vendor alert's evidence summary

    Resource type name is **vendor_alert_evidences**.

    Example JSON record:

    .. code-block:: javascript

        {'evidence': 'string', 'evidence_type': 'HOSTNAME'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                 | Field Name                 | Field Type                | Attribute     | Relationship     |
        +===================================================================================================================================================================================================================================================================================================================================================+============================+===========================+===============+==================+
        | Evidence                                                                                                                                                                                                                                                                                                                                          | evidence                   | string                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Type Restricted to: "HOSTNAME", "URL", "PROCESS_ARGUMENTS", "PROCESS_PATH", "PROCESS_MD5", "USERNAME", "SRC_IP", "DST_IP", "PARENT_ARGUMENTS", "PARENT_PATH", "PARENT_MD5", "SRC_USERNAME", "DST_USERNAME", "ALERT_ACTION", "ALERT_DESCRIPTION", "ALERT_MESSAGE", "ALERT_NAME", "SRC_PORT", "DST_PORT", "USER_AGENT", "VENDOR_NAME", "DOMAIN"     | evidence_type              | any                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                                                                                                                                     | vendor_alert               | :class:`VendorAlerts`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                                                                                      | evidenced_expel_alerts     | :class:`ExpelAlerts`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+

    '''
    _api_type = 'vendor_alert_evidences'
    _def_attributes = ["evidence", "evidence_type"]
    _def_relationships = ["vendor_alert", "evidenced_expel_alerts"]


class TimelineEntries(ResourceInstance):
    '''
    .. _api timeline_entries:

    Timeline Entries

    Resource type name is **timeline_entries**.

    Example JSON record:

    .. code-block:: javascript

        {           'attack_phase': 'string',
            'comment': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'dest_host': 'string',
            'event': 'string',
            'event_date': '2019-01-15T15:35:00-05:00',
            'event_type': 'string',
            'is_selected': True,
            'src_host': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Field Description                                                      | Field Name                | Field Type                       | Attribute     | Relationship     |
        +========================================================================+===========================+==================================+===============+==================+
        | Comment on this Timeline Entry Allows: "", null                        | comment                   | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Attack phase of the Timeline Entry Allows: "", null                    | attack_phase              | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | The event, such as Powershell Attack Allows: "", null                  | event                     | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Has been selected for final report.                                    | is_selected               | boolean                          | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                      | deleted_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Destination Host (IP or Hostname) Allows: "", null                     | dest_host                 | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                       | updated_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                            | created_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | The type of the event, such as Carbon Black Alert Allows: "", null     | event_type                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Source Host (IP or Hostname) Allows: "", null                          | src_host                  | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Date/Time of when the event occurred                                   | event_date                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                               | created_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Investigations                                                         | investigation             | :class:`Investigations`          | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                | context_label_actions     | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                               | updated_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Expel alerts                                                           | expel_alert               | :class:`ExpelAlerts`             | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                       | context_labels            | :class:`ContextLabels`           | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'timeline_entries'
    _def_attributes = ["comment", "attack_phase", "event", "is_selected", "deleted_at",
                       "dest_host", "updated_at", "created_at", "event_type", "src_host", "event_date"]
    _def_relationships = ["created_by", "investigation",
                          "context_label_actions", "updated_by", "expel_alert", "context_labels"]


class NistSubcategoryScoreHistories(ResourceInstance):
    '''
    .. _api nist_subcategory_score_histories:

    NIST Subcategory Score History

    Resource type name is **nist_subcategory_score_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'SCORE_UPDATED', 'actual_score': 100, 'assessment_date': '2019-01-15T15:35:00-05:00', 'created_at': '2019-01-15T15:35:00-05:00', 'target_score': 100}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                     | Field Name                 | Field Type                         | Attribute     | Relationship     |
        +=======================================================================================================================================================================================================================================================+============================+====================================+===============+==================+
        | Recorded date of the score assessment (Note: Dates with times will be truncated to the day.  Warning: Dates times and timezones will be converted to UTC before they are truncated.  Providing non-UTC timezones is not recommeneded.): immutable     | assessment_date            | string                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                           | created_at                 | string                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Organization actual score for this nist subcategory                                                                                                                                                                                                   | actual_score               | number                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | NIST subcategory score history action Restricted to: "SCORE_UPDATED", "COMMENT_UPDATED", "PRIORITY_UPDATED", "IMPORT"                                                                                                                                 | action                     | any                                | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Organization target score for this nist subcategory                                                                                                                                                                                                   | target_score               | number                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                              | created_by                 | :class:`Actors`                    | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                                                                                                                                                                                                                        | nist_subcategory_score     | :class:`NistSubcategoryScores`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategory_score_histories'
    _def_attributes = ["assessment_date", "created_at", "actual_score", "action", "target_score"]
    _def_relationships = ["created_by", "nist_subcategory_score"]


class InvestigationHistories(ResourceInstance):
    '''
    .. _api investigation_histories:

    Investigation histories

    Resource type name is **investigation_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'is_incident': True, 'value': {}}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Field Description                                                                                                                           | Field Name            | Field Type                  | Attribute     | Relationship     |
        +=============================================================================================================================================+=======================+=============================+===============+==================+
        | Created timestamp: readonly                                                                                                                 | created_at            | string                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Is Incidence                                                                                                                                | is_incident           | boolean                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigation history action Restricted to: "CREATED", "ASSIGNED", "CHANGED", "CLOSED", "SUMMARY", "REOPENED", "PUBLISHED" Allows: null     | action                | any                         | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigation history details Allows: null: no-sort                                                                                         | value                 | object                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                             | organization          | :class:`Organizations`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | created_by            | :class:`Actors`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigations                                                                                                                              | investigation         | :class:`Investigations`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                 | customer              | :class:`Customers`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | assigned_to_actor     | :class:`Actors`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_histories'
    _def_attributes = ["created_at", "is_incident", "action", "value"]
    _def_relationships = ["organization", "created_by", "investigation", "customer", "assigned_to_actor"]


class PhishingSubmissions(ResourceInstance):
    '''
    .. _api phishing_submissions:

    Phishing submissions

    Resource type name is **phishing_submissions**.

    Example JSON record:

    .. code-block:: javascript

        {           'automated_action_type': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'email_type': 'name@company.com',
            'msg_id': 'string',
            'received_at': '2019-01-15T15:35:00-05:00',
            'reported_at': '2019-01-15T15:35:00-05:00',
            'return_path': 'string',
            'sender': 'string',
            'sender_domain': 'string',
            'subject': 'string',
            'submitted_by': 'string',
            'triaged_at': '2019-01-15T15:35:00-05:00',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                            | Field Name                          | Field Type                                 | Attribute     | Relationship     |
        +==============================================+=====================================+============================================+===============+==================+
        | Message ID                                   | msg_id                              | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Subject Allows: ""                           | subject                             | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Sender                                       | sender                              | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Automated action type Allows: "", null       | automated_action_type               | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Received at                                  | received_at                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Reported at                                  | reported_at                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Return path Allows: ""                       | return_path                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Submitted by                                 | submitted_by                        | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Sender domain                                | sender_domain                       | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                  | created_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Triaged at Allows: null                      | triaged_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Email type Allows: "", null                  | email_type                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | analysis_email_file                 | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | raw_body_file                       | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission attachments              | phishing_submission_attachments     | :class:`PhishingSubmissionAttachments`     | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission domains                  | phishing_submission_domains         | :class:`PhishingSubmissionDomains`         | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                 | expel_alert                         | :class:`ExpelAlerts`                       | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission headers                  | phishing_submission_headers         | :class:`PhishingSubmissionHeaders`         | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | initial_email_file                  | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission URLs                     | phishing_submission_urls            | :class:`PhishingSubmissionUrls`            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submissions'
    _def_attributes = ["msg_id", "updated_at", "subject", "sender", "automated_action_type", "received_at",
                       "reported_at", "return_path", "submitted_by", "sender_domain", "created_at", "triaged_at", "email_type"]
    _def_relationships = ["updated_by", "analysis_email_file", "raw_body_file", "created_by", "phishing_submission_attachments",
                          "phishing_submission_domains", "expel_alert", "phishing_submission_headers", "initial_email_file", "phishing_submission_urls"]


class OrganizationList(ResourceInstance):
    '''
    .. _api organization_list:

    Retrieves expel.io organization records for the organization view

    Resource type name is **organization_list**.

    Example JSON record:

    .. code-block:: javascript

        {           'engagement_manager_name': 'string',
            'hq_city': 'string',
            'hq_utc_offset': 'string',
            'industry': 'string',
            'investigative_actions_assigned_to_expel': 100,
            'investigative_actions_assigned_to_organization': 100,
            'name': 'string',
            'nodes_count': 100,
            'open_incident_count': 100,
            'open_investigation_count': 100,
            'remediation_actions_assigned_to_organization': 100,
            'resilience_actions_assigned': 100,
            'resilience_actions_completed': 100,
            'resilience_actions_ratio': 100,
            'security_device_health': 'string',
            'service_renewal_at': '2019-01-15T15:35:00-05:00',
            'service_start_at': '2019-01-15T15:35:00-05:00',
            'short_name': 'string',
            'tech_stack': 'string',
            'users_count': 100}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                     | Field Name                                         | Field Type                 | Attribute     | Relationship     |
        +=======================================================================================================================+====================================================+============================+===============+==================+
        | Number of investigative actions assigned to Expel, or any Expel analyst Allows: null                                  | investigative_actions_assigned_to_expel            | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | The organization's operating name Allows: "", null                                                                    | name                                               | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Engagement manager name Allows: "", null                                                                              | engagement_manager_name                            | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Organization service renewal date Allows: null                                                                        | service_renewal_at                                 | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | The organization's primary industry Allows: "", null                                                                  | industry                                           | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of open investigations Allows: null                                                                            | open_investigation_count                           | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Comma delimited list of organization's vendors Allows: "", null                                                       | tech_stack                                         | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Allows: "", null                                                                                                      | hq_utc_offset                                      | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Percent of resilience actions completed Allows: null                                                                  | resilience_actions_ratio                           | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of open incidents Allows: null                                                                                 | open_incident_count                                | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of remediation actions assigned to the organization, or any of that organization's analysts Allows: null       | remediation_actions_assigned_to_organization       | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of resilience actions assigned to the organization Allows: null                                                | resilience_actions_assigned                        | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Organization service start date Allows: null                                                                          | service_start_at                                   | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of users covered for this organization Allows: null                                                            | users_count                                        | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Overall security device health Allows: "", null                                                                       | security_device_health                             | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of investigative actions assigned to the organization, or any of that organization's analysts Allows: null     | investigative_actions_assigned_to_organization     | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | The city where the organization's headquarters is located Allows: "", null                                            | hq_city                                            | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Organization short name Allows: null                                                                                  | short_name                                         | string                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of resilience actions completed by the organization Allows: null                                               | resilience_actions_completed                       | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Number of nodes covered for this organization Allows: null                                                            | nodes_count                                        | number                     | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Products                                                                                                              | products                                           | :class:`Products`          | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                       | organization                                       | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+
        | User accounts                                                                                                         | user_account                                       | :class:`UserAccounts`      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'organization_list'
    _def_attributes = ["investigative_actions_assigned_to_expel", "name", "engagement_manager_name", "service_renewal_at", "industry", "open_investigation_count", "tech_stack", "hq_utc_offset", "resilience_actions_ratio", "open_incident_count",
                       "remediation_actions_assigned_to_organization", "resilience_actions_assigned", "service_start_at", "users_count", "security_device_health", "investigative_actions_assigned_to_organization", "hq_city", "short_name", "resilience_actions_completed", "nodes_count"]
    _def_relationships = ["products", "organization", "user_account"]


class InvestigativeActionDataTechniqueScheduledTasks(ResourceInstance):
    '''
    .. _api investigative_action_data_technique_scheduled_tasks:

    Investigative action data for technique_scheduled_tasks

    Resource type name is **investigative_action_data_technique_scheduled_tasks**.

    Example JSON record:

    .. code-block:: javascript

        {'agent_id': 'string', 'registration_date_time': '2019-01-15T15:35:00-05:00', 'task_arguments': 'string', 'task_author': 'string', 'task_command': 'string', 'task_name': 'string'}


    Below are valid filter by parameters:

        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name                 | Field Type                        | Attribute     | Relationship     |
        +===========================+============================+===================================+===============+==================+
        | Allows: null, ""          | task_arguments             | string                            | Y             | N                |
        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | task_name                  | string                            | Y             | N                |
        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | task_command               | string                            | Y             | N                |
        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registration_date_time     | string                            | Y             | N                |
        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | agent_id                   | string                            | Y             | N                |
        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | task_author                | string                            | Y             | N                |
        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action       | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+----------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_technique_scheduled_tasks'
    _def_attributes = ["task_arguments", "task_name", "task_command",
                       "registration_date_time", "agent_id", "task_author"]
    _def_relationships = ["investigative_action"]


class RemediationActionAssets(ResourceInstance):
    '''
    .. _api remediation_action_assets:

    Remediation action assets

    Resource type name is **remediation_action_assets**.

    Example JSON record:

    .. code-block:: javascript

        {'asset_type': 'ACCOUNT', 'category': 'AFFECTED_ACCOUNT', 'created_at': '2019-01-15T15:35:00-05:00', 'status': 'OPEN', 'updated_at': '2019-01-15T15:35:00-05:00', 'value': 'object'}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                           | Field Name                             | Field Type                                   | Attribute     | Relationship     |
        +=============================================================================================================================================================================+========================================+==============================================+===============+==================+
        | Asset status Restricted to: "OPEN", "COMPLETED"                                                                                                                             | status                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation asset category Restricted to: "AFFECTED_ACCOUNT", "COMPROMISED_ACCOUNT", "FORWARDING_ADDRESS" Allows: null                                                      | category                               | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation asset value: no-sort                                                                                                                                            | value                                  | alternatives                                 | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                 | created_at                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                            | updated_at                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation asset type Restricted to: "ACCOUNT", "ACCESS_KEY", "DESCRIPTION", "DEVICE", "DOMAIN_NAME", "EMAIL", "FILE", "HASH", "HOST", "INBOX_RULE_NAME", "IP_ADDRESS"     | asset_type                             | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                    | created_by                             | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                    | updated_by                             | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action asset histories                                                                                                                                          | remediation_action_asset_histories     | :class:`RemediationActionAssetHistories`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                                                                                                                        | context_label_tags                     | :class:`ContextLabelTags`                    | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                         | remediation_action                     | :class:`RemediationActions`                  | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_assets'
    _def_attributes = ["status", "category", "value", "created_at", "updated_at", "asset_type"]
    _def_relationships = ["created_by", "updated_by",
                          "remediation_action_asset_histories", "context_label_tags", "remediation_action"]


class ConfigurationDefaults(ResourceInstance):
    '''
    .. _api configuration_defaults:

    Configuration defaults

    Resource type name is **configuration_defaults**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'description': 'string',
            'metadata': {},
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'validation': {},
            'value': 'object',
            'visibility': 'EXPEL',
            'write_permission_level': 'EXPEL'}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Field Description                                                              | Field Name                 | Field Type                       | Attribute     | Relationship     |
        +================================================================================+============================+==================================+===============+==================+
        | Configuration metadata Allows: null: no-sort                                   | metadata                   | object                           | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Configuration value validation: no-sort                                        | validation                 | object                           | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Write permission required Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"     | write_permission_level     | any                              | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                               | updated_at                 | string                           | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Configuration visibility Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"      | visibility                 | any                              | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                    | created_at                 | string                           | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Description of configuration value Allows: "", null                            | description                | string                           | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Title of configuration value Allows: "", null                                  | title                      | string                           | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Configuration value Allows: null: no-sort                                      | value                      | any                              | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Configuration labels                                                           | labels                     | :class:`ConfigurationLabels`     | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | created_by                 | :class:`Actors`                  | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | updated_by                 | :class:`Actors`                  | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io configuration records                               | configurations             | :class:`Configurations`          | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'configuration_defaults'
    _def_attributes = ["metadata", "validation", "write_permission_level",
                       "updated_at", "visibility", "created_at", "description", "title", "value"]
    _def_relationships = ["labels", "created_by", "updated_by", "configurations"]


class ContextLabelTags(ResourceInstance):
    '''
    .. _api context_label_tags:

    Defines/retrieves expel.io context_label_tag records

    Resource type name is **context_label_tags**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'description': 'string', 'metadata': {}, 'tag': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Field Description                                              | Field Name                    | Field Type                           | Attribute     | Relationship     |
        +================================================================+===============================+======================================+===============+==================+
        | Created timestamp: readonly                                    | created_at                    | string                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Metadata about the context label tag Allows: null: no-sort     | metadata                      | object                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Description Allows: null, ""                                   | description                   | string                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Tag                                                            | tag                           | string                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                               | updated_at                    | string                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                       | created_by                    | :class:`Actors`                      | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                       | updated_by                    | :class:`Actors`                      | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                | organization                  | :class:`Organizations`               | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action assets                                      | remediation_action_assets     | :class:`RemediationActionAssets`     | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records               | context_labels                | :class:`ContextLabels`               | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_tags'
    _def_attributes = ["created_at", "metadata", "description", "tag", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "organization", "remediation_action_assets", "context_labels"]


class RemediationActions(ResourceInstance):
    '''
    .. _api remediation_actions:

    Remediation actions

    Resource type name is **remediation_actions**.

    Example JSON record:

    .. code-block:: javascript

        {           'action': 'string',
            'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS',
            'close_reason': 'string',
            'comment': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'detail_markdown': 'string',
            'status': 'IN_PROGRESS',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'template_name': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'values': {},
            'version': 'V1'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Field Name                       | Field Type                              | Attribute     | Relationship     |
        +======================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+==================================+=========================================+===============+==================+
        | Remediation action details markdown Allows: "", null: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | detail_markdown                  | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation Action Values: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | values                           | object                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | status_updated_at                | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Action type Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type                      | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | updated_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Close Reason Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | close_reason                     | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Comment Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | comment                          | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Restricted to: "IN_PROGRESS", "COMPLETED", "CLOSED"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | status                           | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Version Restricted to: "V1", "V2", "V3"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | version                          | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | deleted_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation Action Template Name Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | template_name                    | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | created_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Action Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | action                           | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | created_by                       | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | investigation                    | :class:`Investigations`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action assets                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | remediation_action_assets        | :class:`RemediationActionAssets`        | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | updated_by                       | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action histories                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | remediation_action_histories     | :class:`RemediationActionHistories`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | assigned_to_actor                | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_actions'
    _def_attributes = ["detail_markdown", "values", "status_updated_at", "action_type", "updated_at",
                       "close_reason", "comment", "status", "version", "deleted_at", "template_name", "created_at", "action"]
    _def_relationships = ["created_by", "investigation", "remediation_action_assets",
                          "updated_by", "remediation_action_histories", "assigned_to_actor"]


class InvestigativeActionDataPersistenceListing(ResourceInstance):
    '''
    .. _api investigative_action_data_persistence_listing:

    Investigative action data for persistence_listing

    Resource type name is **investigative_action_data_persistence_listing**.

    Example JSON record:

    .. code-block:: javascript

        {           'accessed': 'string',
            'changed': 'string',
            'created': 'string',
            'file_description': 'string',
            'file_md5': 'string',
            'file_owner': 'string',
            'file_path': 'string',
            'is_signed': True,
            'modified': 'string',
            'persist_type': 'string',
            'reg_data': 'string',
            'reg_last_modified': 'string',
            'reg_path': 'string',
            'service_args': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null              | accessed                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_data                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | changed                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_path                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_last_modified        | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | reg_path                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_owner               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | service_args             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_md5                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | created                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | is_signed                | boolean                           | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_description         | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | modified                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | persist_type             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_persistence_listing'
    _def_attributes = ["accessed", "reg_data", "changed", "file_path", "reg_last_modified", "reg_path", "file_owner",
                       "service_args", "file_md5", "created", "is_signed", "file_description", "modified", "persist_type"]
    _def_relationships = ["investigative_action"]


class CustomerResilienceActions(ResourceInstance):
    '''
    .. _api customer_resilience_actions:

    Organization to resilience actions

    Resource type name is **customer_resilience_actions**.

    Example JSON record:

    .. code-block:: javascript

        {           'category': 'DISRUPT_ATTACKERS',
            'comment': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'details': 'string',
            'impact': 'LOW',
            'status': 'TOP_PRIORITY',
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'visible': True}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Field Description                                                                | Field Name                           | Field Type                                  | Attribute     | Relationship     |
        +==================================================================================+======================================+=============================================+===============+==================+
        | Comment Allows: "", null                                                         | comment                              | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Status Restricted to: "TOP_PRIORITY", "IN_PROGRESS", "WONT_DO", "COMPLETED"      | status                               | any                                         | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Details                                                                          | details                              | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null     | category                             | any                                         | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                      | created_at                           | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                 | updated_at                           | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Title                                                                            | title                                | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Visible                                                                          | visible                              | boolean                                     | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH"                                    | impact                               | any                                         | Y             | N                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | created_by                           | :class:`Actors`                             | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Investigation to resilience actions                                              | investigation_resilience_actions     | :class:`InvestigationResilienceActions`     | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Resilience actions                                                               | source_resilience_action             | :class:`ResilienceActions`                  | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer_resilience_action_group records              | customer_resilience_action_group     | :class:`CustomerResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Investigations                                                                   | investigations                       | :class:`Investigations`                     | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | updated_by                           | :class:`Actors`                             | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                      | customer                             | :class:`Customers`                          | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | assigned_to_actor                    | :class:`Actors`                             | N             | Y                |
        +----------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+

    '''
    _api_type = 'customer_resilience_actions'
    _def_attributes = ["comment", "status", "details", "category",
                       "created_at", "updated_at", "title", "visible", "impact"]
    _def_relationships = ["created_by", "investigation_resilience_actions", "source_resilience_action",
                          "customer_resilience_action_group", "investigations", "updated_by", "customer", "assigned_to_actor"]


class CommentHistories(ResourceInstance):
    '''
    .. _api comment_histories:

    Defines/retrieves expel.io comment_history records

    Resource type name is **comment_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Field Description                                                                      | Field Name        | Field Type                  | Attribute     | Relationship     |
        +========================================================================================+===================+=============================+===============+==================+
        | Created timestamp: readonly                                                            | created_at        | string                      | Y             | N                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Comment history action Restricted to: "CREATED", "UPDATED", "DELETED" Allows: null     | action            | any                         | Y             | N                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Comment history details Allows: null: no-sort                                          | value             | object                      | Y             | N                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                             | comment           | :class:`Comments`           | N             | Y                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                               | created_by        | :class:`Actors`             | N             | Y                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Investigations                                                                         | investigation     | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'comment_histories'
    _def_attributes = ["created_at", "action", "value"]
    _def_relationships = ["comment", "created_by", "investigation"]


class InvestigativeActionDataQueryLogs(ResourceInstance):
    '''
    .. _api investigative_action_data_query_logs:

    Investigative action data for query_logs

    Resource type name is **investigative_action_data_query_logs**.

    Example JSON record:

    .. code-block:: javascript

        {'index': 'string', 'index_at': 'string', 'query': 'string', 'raw_log': 'string', 'source_name': 'string', 'source_type': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | source_type              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | query                    | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | source_name              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | index                    | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | index_at                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | raw_log                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_logs'
    _def_attributes = ["source_type", "query", "source_name", "index", "index_at", "raw_log"]
    _def_relationships = ["investigative_action"]


class InvestigationResilienceActionHints(ResourceInstance):
    '''
    .. _api investigation_resilience_action_hints:

    Defines/retrieves expel.io investigation_organization_resilience_action_hint records

    Resource type name is **investigation_resilience_action_hints**.

    Example JSON record:

    .. code-block:: javascript

        {}


    Below are valid filter by parameters:


    '''
    _api_type = 'investigation_resilience_action_hints'
    _def_attributes = []
    _def_relationships = []


class InvestigativeActionDataTechniqueSinkholeConnections(ResourceInstance):
    '''
    .. _api investigative_action_data_technique_sinkhole_connections:

    Investigative action data for technique_sinkhole_connections

    Resource type name is **investigative_action_data_technique_sinkhole_connections**.

    Example JSON record:

    .. code-block:: javascript

        {           'asn_s_dest_ip': 'string',
            'connections': 100,
            'destination_ip': 'string',
            'destination_port': 100,
            'domain': 'string',
            'domain_resolution_dest_ip': 'string',
            'first_seen': 'string',
            'first_seen_resolution_dest_ip': 'string',
            'greynoise_first_seen': 'string',
            'greynoise_last_seen': 'string',
            'greynoise_reason': 'string',
            'greynoise_tags': 'string',
            'greynoise_user_agents': 'string',
            'greynoise_web_paths': 'string',
            'ip_hub_suspicious_dest_ip': True,
            'is_dest_ip_greynoise': True,
            'is_dest_ip_tor': True,
            'last_seen': 'string',
            'last_seen_resolution_dest_ip': 'string',
            'owner_domain_dest_ip': 'string',
            'owning_org_s_dest_ip': 'string',
            'source_ip': 'string',
            'unique_days_connected': 100,
            'unique_sources_for_domain': 100,
            'usage_type_dest_ip': 'string'}


    Below are valid filter by parameters:

        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name                        | Field Type                        | Attribute     | Relationship     |
        +===========================+===================================+===================================+===============+==================+
        | Allows: null, ""          | greynoise_tags                    | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | owner_domain_dest_ip              | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | first_seen_resolution_dest_ip     | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | first_seen                        | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | usage_type_dest_ip                | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | connections                       | number                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | domain_resolution_dest_ip         | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | greynoise_first_seen              | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | greynoise_reason                  | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | destination_port                  | number                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | unique_sources_for_domain         | number                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | greynoise_web_paths               | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | domain                            | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | greynoise_last_seen               | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | unique_days_connected             | number                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | is_dest_ip_tor                    | boolean                           | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source_ip                         | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | last_seen_resolution_dest_ip      | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | owning_org_s_dest_ip              | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | is_dest_ip_greynoise              | boolean                           | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | greynoise_user_agents             | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | ip_hub_suspicious_dest_ip         | boolean                           | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | destination_ip                    | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | asn_s_dest_ip                     | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | last_seen                         | string                            | Y             | N                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action              | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+-----------------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_technique_sinkhole_connections'
    _def_attributes = ["greynoise_tags", "owner_domain_dest_ip", "first_seen_resolution_dest_ip", "first_seen", "usage_type_dest_ip", "connections", "domain_resolution_dest_ip", "greynoise_first_seen", "greynoise_reason", "destination_port", "unique_sources_for_domain", "greynoise_web_paths",
                       "domain", "greynoise_last_seen", "unique_days_connected", "is_dest_ip_tor", "source_ip", "last_seen_resolution_dest_ip", "owning_org_s_dest_ip", "is_dest_ip_greynoise", "greynoise_user_agents", "ip_hub_suspicious_dest_ip", "destination_ip", "asn_s_dest_ip", "last_seen"]
    _def_relationships = ["investigative_action"]


class Files(FilesResourceInstance):
    '''
    .. _api files:

    File

    Resource type name is **files**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'expel_file_type': 'string',
            'file_meta': {'investigative_action': {'file_type': 'string'}},
            'filename': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                   | Field Name                         | Field Type                                 | Attribute     | Relationship     |
        +=====================================================+====================================+============================================+===============+==================+
        | Metadata about the file Allows: null: no-sort       | file_meta                          | object                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                         | created_at                         | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at                         | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel file type Allows: null, ""                    | expel_file_type                    | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Filename                                            | filename                           | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission attachments                     | phishing_submission_attachment     | :class:`PhishingSubmissionAttachments`     | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                               | investigative_actions              | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                      | investigations                     | :class:`Investigations`                    | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submissions                                | phishing_submission                | :class:`PhishingSubmissions`               | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization                       | :class:`Organizations`                     | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records         | customer                           | :class:`Customers`                         | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'files'
    _def_attributes = ["file_meta", "created_at", "updated_at", "expel_file_type", "filename"]
    _def_relationships = ["phishing_submission_attachment", "created_by", "investigative_actions",
                          "investigations", "updated_by", "phishing_submission", "organization", "customer"]


class ExpelUsers(ResourceInstance):
    '''
    .. _api expel_users:

    Expel users

    Resource type name is **expel_users**.

    Example JSON record:

    .. code-block:: javascript

        {           'active': True,
            'active_status': 'ACTIVE',
            'assignable': True,
            'created_at': '2019-01-15T15:35:00-05:00',
            'display_name': 'string',
            'email': 'name@company.com',
            'engagement_manager': True,
            'first_name': 'string',
            'homepage_preferences': {},
            'invite_token': 'string',
            'invite_token_expires_at': '2019-01-15T15:35:00-05:00',
            'language': 'string',
            'last_name': 'string',
            'locale': 'string',
            'password_reset_token': 'string',
            'password_reset_token_expires_at': '2019-01-15T15:35:00-05:00',
            'phone_number': 'string',
            'role': 'expel_admin',
            'timezone': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                              | Field Name                                        | Field Type                                 | Attribute     | Relationship     |
        +================================================================================================================================================================================================+===================================================+============================================+===============+==================+
        | Display name Allows: "", null                                                                                                                                                                  | display_name                                      | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Locale Allows: "", null                                                                                                                                                                        | locale                                            | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Invite token Allows: null: readonly, private                                                                                                                                                   | invite_token                                      | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Homepage preferences Allows: null: no-sort                                                                                                                                                     | homepage_preferences                              | object                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Name Allows: "", null                                                                                                                                                                     | last_name                                         | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User account primary role Restricted to: "expel_admin", "expel_analyst", "organization_admin", "organization_analyst", "system", "anonymous", "restricted" Allows: null: readonly, no-sort     | role                                              | any                                        | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                               | updated_at                                        | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Restricted to: "ACTIVE", "LOCKED", "LOCKED_INVITED", "LOCKED_EXPIRED", "ACTIVE_INVITED", "ACTIVE_EXPIRED": readonly, no-sort                                                                   | active_status                                     | any                                        | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Active Allows: null                                                                                                                                                                            | active                                            | boolean                                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Phone number Allows: null                                                                                                                                                                      | phone_number                                      | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Password reset token expiry Allows: null: readonly, private                                                                                                                                    | password_reset_token_expires_at                   | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Language Allows: "", null                                                                                                                                                                      | language                                          | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Can user be assigned items (e.g. investigations, etc)                                                                                                                                          | assignable                                        | boolean                                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Timezone Allows: "", null                                                                                                                                                                      | timezone                                          | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Password reset token Allows: null: readonly, private                                                                                                                                           | password_reset_token                              | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Email Allows: null                                                                                                                                                                             | email                                             | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                    | created_at                                        | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | First Name Allows: "", null                                                                                                                                                                    | first_name                                        | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Invite token expiry Allows: null: readonly, private                                                                                                                                            | invite_token_expires_at                           | string                                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Is an engagement manager                                                                                                                                                                       | engagement_manager                                | boolean                                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                             | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                       | created_by                                        | :class:`Actors`                            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                             | assigned_customer_resilience_actions_list         | :class:`CustomerResilienceActions`         | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                       | updated_by                                        | :class:`Actors`                            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                            | assigned_remediation_actions                      | :class:`RemediationActions`                | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                | organization                                      | :class:`Organizations`                     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                          | assigned_investigative_actions                    | :class:`InvestigativeActions`              | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                   | assigned_expel_alerts                             | :class:`ExpelAlerts`                       | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                          | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`              | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                             | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                             | assigned_customer_resilience_actions              | :class:`CustomerResilienceActions`         | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                 | assigned_investigations                           | :class:`Investigations`                    | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                                                                                                  | notification_preferences                          | :class:`NotificationPreferences`           | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                                                                    | customer                                          | :class:`Customers`                         | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io user_account_role records                                                                                                                                           | user_account_roles                                | :class:`UserAccountRoles`                  | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_users'
    _def_attributes = ["display_name", "locale", "invite_token", "homepage_preferences", "last_name", "role", "updated_at", "active_status", "active", "phone_number",
                       "password_reset_token_expires_at", "language", "assignable", "timezone", "password_reset_token", "email", "created_at", "first_name", "invite_token_expires_at", "engagement_manager"]
    _def_relationships = ["assigned_organization_resilience_actions", "created_by", "assigned_customer_resilience_actions_list", "updated_by", "assigned_remediation_actions", "organization", "assigned_investigative_actions", "assigned_expel_alerts",
                          "analysis_assigned_investigative_actions", "assigned_organization_resilience_actions_list", "assigned_customer_resilience_actions", "assigned_investigations", "notification_preferences", "customer", "user_account_roles"]


class InvestigationFindings(ResourceInstance):
    '''
    .. _api investigation_findings:

    Investigation findings

    Resource type name is **investigation_findings**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'deleted_at': '2019-01-15T15:35:00-05:00', 'finding': 'string', 'rank': 100, 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                    | Field Name                          | Field Type                                 | Attribute     | Relationship     |
        +======================================================================+=====================================+============================================+===============+==================+
        | Finding Allows: "", null                                             | finding                             | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Visualization Rank                                                   | rank                                | number                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                    | deleted_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                     | updated_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                          | created_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                               | title                               | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | created_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | updated_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                       | investigation                       | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io investigation_finding_history records     | investigation_finding_histories     | :class:`InvestigationFindingHistories`     | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_findings'
    _def_attributes = ["finding", "rank", "deleted_at", "updated_at", "created_at", "title"]
    _def_relationships = ["created_by", "updated_by", "investigation", "investigation_finding_histories"]


class ActivityMetrics(ResourceInstance):
    '''
    .. _api activity_metrics:

    Defines/retrieves expel.io activity_metric records

    Resource type name is **activity_metrics**.

    Example JSON record:

    .. code-block:: javascript

        {           'activity': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'data': {},
            'ended_at': '2019-01-15T15:35:00-05:00',
            'referring_url': 'https://company.com/',
            'started_at': '2019-01-15T15:35:00-05:00',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'url': 'https://company.com/'}


    Below are valid filter by parameters:

        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Field Description                                            | Field Name          | Field Type                   | Attribute     | Relationship     |
        +==============================================================+=====================+==============================+===============+==================+
        | Additional data about the activity Allows: null: no-sort     | data                | object                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Date/Time of when the activity concluded                     | ended_at            | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Activity Allows: "", null                                    | activity            | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                             | updated_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Created timestamp: readonly                                  | created_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Date/Time of when the activity started                       | started_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Referring url Allows: "", null                               | referring_url       | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Url Allows: "", null                                         | url                 | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                     | created_by          | :class:`Actors`              | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Security devices                                             | security_device     | :class:`SecurityDevices`     | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Investigations                                               | investigation       | :class:`Investigations`      | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Expel alerts                                                 | expel_alert         | :class:`ExpelAlerts`         | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                     | updated_by          | :class:`Actors`              | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'activity_metrics'
    _def_attributes = ["data", "ended_at", "activity", "updated_at", "created_at", "started_at", "referring_url", "url"]
    _def_relationships = ["created_by", "security_device", "investigation", "expel_alert", "updated_by"]


class CustomerResilienceActionList(ResourceInstance):
    '''
    .. _api customer_resilience_action_list:

    Organization to resilience action list

    Resource type name is **customer_resilience_action_list**.

    Example JSON record:

    .. code-block:: javascript

        {'category': 'DISRUPT_ATTACKERS', 'comment': 'string', 'details': 'string', 'impact': 'LOW', 'incident_count': 100, 'status': 'TOP_PRIORITY', 'title': 'string', 'visible': True}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Field Description                                                                            | Field Name                           | Field Type                                  | Attribute     | Relationship     |
        +==============================================================================================+======================================+=============================================+===============+==================+
        | Comment Allows: "", null                                                                     | comment                              | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Status Restricted to: "TOP_PRIORITY", "IN_PROGRESS", "WONT_DO", "COMPLETED" Allows: null     | status                               | any                                         | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Details Allows: "", null                                                                     | details                              | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null                 | category                             | any                                         | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Incident count Allows: null                                                                  | incident_count                       | number                                      | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                                                       | title                                | string                                      | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Visible Allows: null                                                                         | visible                              | boolean                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH" Allows: null                                   | impact                               | any                                         | Y             | N                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer_resilience_action_group records                          | customer_resilience_action_group     | :class:`CustomerResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                              | organization                         | :class:`Organizations`                      | N             | Y                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                           | customer_resilience_action           | :class:`CustomerResilienceActions`          | N             | Y                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                  | customer                             | :class:`Customers`                          | N             | Y                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                     | assigned_to_actor                    | :class:`Actors`                             | N             | Y                |
        +----------------------------------------------------------------------------------------------+--------------------------------------+---------------------------------------------+---------------+------------------+

    '''
    _api_type = 'customer_resilience_action_list'
    _def_attributes = ["comment", "status", "details", "category", "incident_count", "title", "visible", "impact"]
    _def_relationships = ["customer_resilience_action_group", "organization",
                          "customer_resilience_action", "customer", "assigned_to_actor"]


class InvestigativeActionDataListSources(ResourceInstance):
    '''
    .. _api investigative_action_data_list_sources:

    Investigative action data for list_sources

    Resource type name is **investigative_action_data_list_sources**.

    Example JSON record:

    .. code-block:: javascript

        {'first_source_at': 'string', 'last_source_at': 'string', 'source_count': 100, 'source_name': 'string', 'source_type': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null              | source_name              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source_type              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | first_source_at          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | last_source_at           | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | source_count             | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_list_sources'
    _def_attributes = ["source_name", "source_type", "first_source_at", "last_source_at", "source_count"]
    _def_relationships = ["investigative_action"]


class InvestigativeActionDataQueryFile(ResourceInstance):
    '''
    .. _api investigative_action_data_query_file:

    Investigative action data for query_file

    Resource type name is **investigative_action_data_query_file**.

    Example JSON record:

    .. code-block:: javascript

        {           'application': 'string',
            'dst': 'string',
            'dst_processes': 'string',
            'evidence_type': 'string',
            'file_events': 'string',
            'file_hash': 'string',
            'file_path': 'string',
            'filename': 'string',
            'network_events': 'string',
            'process_pid': 100,
            'registry_events': 'string',
            'sensor': 'string',
            'size': 100,
            'src': 'string',
            'started_at': 'string',
            'summary': 'string',
            'unsigned_modules': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | dst                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | summary                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | unsigned_modules         | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | evidence_type            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | size                     | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | network_events           | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_path                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_events              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | filename                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registry_events          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | process_pid              | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_hash                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | application              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst_processes            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | sensor                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_file'
    _def_attributes = ["dst", "summary", "unsigned_modules", "evidence_type", "size", "network_events", "file_path", "started_at",
                       "file_events", "filename", "registry_events", "process_pid", "file_hash", "application", "dst_processes", "sensor", "src"]
    _def_relationships = ["investigative_action"]


class InvestigativeActionDataProcessListing(ResourceInstance):
    '''
    .. _api investigative_action_data_process_listing:

    Investigative action data for process_listing

    Resource type name is **investigative_action_data_process_listing**.

    Example JSON record:

    .. code-block:: javascript

        {           'is_signed': True,
            'modules': 'object',
            'parent_pid': 100,
            'process_args': 'string',
            'process_md5': 'string',
            'process_name': 'string',
            'process_path': 'string',
            'process_pid': 100,
            'started_at': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | process_path             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | process_pid              | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_md5              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | modules                  | any                               | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_args             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | parent_pid               | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | is_signed                | boolean                           | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_name             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_process_listing'
    _def_attributes = ["process_path", "process_pid", "process_md5", "modules",
                       "process_args", "parent_pid", "is_signed", "started_at", "process_name"]
    _def_relationships = ["investigative_action"]


class EngagementManagers(ResourceInstance):
    '''
    .. _api engagement_managers:

    Defines/retrieves expel.io engagement_manager records

    Resource type name is **engagement_managers**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'display_name': 'string', 'email': 'name@company.com', 'phone_number': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name        | Field Type                 | Attribute     | Relationship     |
        +=====================================================+===================+============================+===============+==================+
        | Display name Allows: "", null                       | display_name      | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                         | created_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Phone number Allows: null                           | phone_number      | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Email Allows: null                                  | email             | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records         | customers         | :class:`Customers`         | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organizations     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'engagement_managers'
    _def_attributes = ["display_name", "created_at", "updated_at", "phone_number", "email"]
    _def_relationships = ["created_by", "updated_by", "customers", "organizations"]


class InvestigativeActionDataQueryUrl(ResourceInstance):
    '''
    .. _api investigative_action_data_query_url:

    Investigative action data for query_url

    Resource type name is **investigative_action_data_query_url**.

    Example JSON record:

    .. code-block:: javascript

        {           'application': 'string',
            'domain': 'string',
            'dst': 'string',
            'dst_processes': 'string',
            'evidence_type': 'string',
            'file_events': 'string',
            'network_events': 'string',
            'process_name': 'string',
            'process_pid': 100,
            'protocol': 'string',
            'referer': 'string',
            'registry_events': 'string',
            'src': 'string',
            'started_at': 'string',
            'summary': 'string',
            'unsigned_modules': 'string',
            'url': 'https://company.com/'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | dst                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | summary                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | protocol                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | evidence_type            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | network_events           | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | referer                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | unsigned_modules         | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_events              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | url                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registry_events          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | process_pid              | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_name             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | application              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst_processes            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | domain                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_url'
    _def_attributes = ["dst", "summary", "protocol", "evidence_type", "network_events", "referer", "unsigned_modules", "started_at",
                       "file_events", "url", "registry_events", "process_pid", "process_name", "application", "dst_processes", "src", "domain"]
    _def_relationships = ["investigative_action"]


class ContextLabels(ResourceInstance):
    '''
    .. _api context_labels:

    Defines/retrieves expel.io context_label records

    Resource type name is **context_labels**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'definition': {},
            'description': 'string',
            'ends_at': '2019-01-15T15:35:00-05:00',
            'metadata': {},
            'starts_at': '2019-01-15T15:35:00-05:00',
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Field Description                                                            | Field Name                | Field Type                       | Attribute     | Relationship     |
        +==============================================================================+===========================+==================================+===============+==================+
        | Title Allows: null, ""                                                       | title                     | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Metadata about the context label Allows: null: no-sort                       | metadata                  | object                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Date/Time of when the context_label should end being tested Allows: null     | ends_at                   | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                             | updated_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                  | created_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Definition: no-sort                                                          | definition                | object                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Description Allows: null, ""                                                 | description               | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Date/Time of when the context_label should start being tested                | starts_at                 | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Expel alerts                                                                 | expel_alerts              | :class:`ExpelAlerts`             | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                     | created_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | add_to_actions            | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Timeline Entries                                                             | timeline_entries          | :class:`TimelineEntries`         | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | alert_on_actions          | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Investigations                                                               | investigations            | :class:`Investigations`          | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | context_label_actions     | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                     | updated_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                         | context_label_tags        | :class:`ContextLabelTags`        | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                              | organization              | :class:`Organizations`           | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | suppress_actions          | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'context_labels'
    _def_attributes = ["title", "metadata", "ends_at", "updated_at",
                       "created_at", "definition", "description", "starts_at"]
    _def_relationships = ["expel_alerts", "created_by", "add_to_actions", "timeline_entries", "alert_on_actions",
                          "investigations", "context_label_actions", "updated_by", "context_label_tags", "organization", "suppress_actions"]


class OrganizationResilienceActionGroups(ResourceInstance):
    '''
    .. _api organization_resilience_action_groups:

    Defines/retrieves expel.io organization_resilience_action_group records

    Resource type name is **organization_resilience_action_groups**.

    Example JSON record:

    .. code-block:: javascript

        {'category': 'DISRUPT_ATTACKERS', 'created_at': '2019-01-15T15:35:00-05:00', 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00', 'visible': True}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                                                 | Field Name                                       | Field Type                                 | Attribute     | Relationship     |
        +===================================================================================================+==================================================+============================================+===============+==================+
        | Created timestamp: readonly                                                                       | created_at                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                  | updated_at                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Group title                                                                                       | title                                            | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Visible                                                                                           | visible                                          | boolean                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization Resilience Group Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS"     | category                                         | any                                        | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_group records                                        | source_resilience_action_group                   | :class:`ResilienceActionGroups`            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | created_by                                       | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | updated_by                                       | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                   | organization                                     | :class:`Organizations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                | organization_resilience_action_group_actions     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organization_resilience_action_groups'
    _def_attributes = ["created_at", "updated_at", "title", "visible", "category"]
    _def_relationships = ["source_resilience_action_group", "created_by",
                          "updated_by", "organization", "organization_resilience_action_group_actions"]


class ExpelAlertThresholds(ResourceInstance):
    '''
    .. _api expel_alert_thresholds:

    Defines/retrieves expel.io expel_alert_threshold records

    Resource type name is **expel_alert_thresholds**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'name': 'string', 'threshold': 100, 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Field Description                                                    | Field Name                          | Field Type                                | Attribute     | Relationship     |
        +======================================================================+=====================================+===========================================+===============+==================+
        | Created timestamp: readonly                                          | created_at                          | string                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Threshold value                                                      | threshold                           | number                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Name                                                                 | name                                | string                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                     | updated_at                          | string                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | created_by                          | :class:`Actors`                           | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | updated_by                          | :class:`Actors`                           | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold_history records     | expel_alert_threshold_histories     | :class:`ExpelAlertThresholdHistories`     | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records             | suppressed_by                       | :class:`ExpelAlertThresholds`             | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records             | suppresses                          | :class:`ExpelAlertThresholds`             | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_thresholds'
    _def_attributes = ["created_at", "threshold", "name", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "expel_alert_threshold_histories", "suppressed_by", "suppresses"]


class InvestigativeActionDataQueryRawLogs(ResourceInstance):
    '''
    .. _api investigative_action_data_query_raw_logs:

    Investigative action data for query_raw_logs

    Resource type name is **investigative_action_data_query_raw_logs**.

    Example JSON record:

    .. code-block:: javascript

        {'raw_log': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null              | raw_log                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_raw_logs'
    _def_attributes = ["raw_log"]
    _def_relationships = ["investigative_action"]


class InvestigativeActionDataTechniqueSuccessiveReconnaissanceCommands(ResourceInstance):
    '''
    .. _api investigative_action_data_technique_successive_reconnaissance_commands:

    Investigative action data for technique_successive_reconnaissance_commands

    Resource type name is **investigative_action_data_technique_successive_reconnaissance_commands**.

    Example JSON record:

    .. code-block:: javascript

        {           'hostname': 'string',
            'parent_args': 'string',
            'parent_id': 'string',
            'parent_name': 'string',
            'process_args': 'string',
            'process_name': 'string',
            'stack_cmds': 100,
            'stack_hosts': 'string',
            'stack_id': 100,
            'stack_last_timestamp': 'string',
            'stack_size': 100,
            'timestamp': 'string',
            'user': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | hostname                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | stack_hosts              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_args             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | parent_name              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | parent_args              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | timestamp                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | stack_id                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | stack_cmds               | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | user                     | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | stack_last_timestamp     | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | parent_id                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | stack_size               | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_name             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_technique_successive_reconnaissance_commands'
    _def_attributes = ["hostname", "stack_hosts", "process_args", "parent_name", "parent_args", "timestamp",
                       "stack_id", "stack_cmds", "user", "stack_last_timestamp", "parent_id", "stack_size", "process_name"]
    _def_relationships = ["investigative_action"]


class Products(ResourceInstance):
    '''
    .. _api products:

    Products

    Resource type name is **products**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'description': 'string', 'name': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name        | Field Type                 | Attribute     | Relationship     |
        +=====================================================+===================+============================+===============+==================+
        | Created timestamp: readonly                         | created_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | name              | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | description       | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Product features                                    | features          | :class:`Features`          | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records         | customers         | :class:`Customers`         | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organizations     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'products'
    _def_attributes = ["created_at", "name", "description", "updated_at"]
    _def_relationships = ["features", "created_by", "updated_by", "customers", "organizations"]


class PhishingSubmissionHeaders(ResourceInstance):
    '''
    .. _api phishing_submission_headers:

    Phishing submission headers

    Resource type name is **phishing_submission_headers**.

    Example JSON record:

    .. code-block:: javascript

        {'name': 'string', 'value': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name              | Field Type                       | Attribute     | Relationship     |
        +==============================================+=========================+==================================+===============+==================+
        | Name                                         | name                    | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Value                                        | value                   | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by              | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission     | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_headers'
    _def_attributes = ["name", "value"]
    _def_relationships = ["created_by", "phishing_submission"]


class VendorAlerts(ResourceInstance):
    '''
    .. _api vendor_alerts:

    Vendor alerts

    Resource type name is **vendor_alerts**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'description': 'string',
            'evidence_activity_end_at': '2019-01-15T15:35:00-05:00',
            'evidence_activity_start_at': '2019-01-15T15:35:00-05:00',
            'evidence_summary': [],
            'first_seen': '2019-01-15T15:35:00-05:00',
            'original_alert_id': 'string',
            'original_source_id': 'string',
            'signature_id': 'string',
            'status': 'NORMAL',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'vendor_message': 'string',
            'vendor_severity': 'CRITICAL',
            'vendor_sig_name': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Field Description                                                                                              | Field Name                     | Field Type                        | Attribute     | Relationship     |
        +================================================================================================================+================================+===================================+===============+==================+
        | Allows: null: immutable                                                                                        | original_alert_id              | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor alert severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "TESTING", "TUNING" Allows: null     | vendor_severity                | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                               | updated_at                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor Sig Name Allows: "", null                                                                               | vendor_sig_name                | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence summary Allows: null: no-sort                                                                         | evidence_summary               | array                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor Message Allows: "", null                                                                                | vendor_message                 | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | First Seen                                                                                                     | first_seen                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Description Allows: "", null                                                                                   | description                    | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Status Restricted to: "NORMAL", "PROVISIONAL" Allows: null: readonly                                           | status                         | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence activity start datetime Allows: null: immutable                                                       | evidence_activity_start_at     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Signature ID Allows: "", null                                                                                  | signature_id                   | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                    | created_at                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence activity end datetime Allows: null: immutable                                                         | evidence_activity_end_at       | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null: immutable                                                                                        | original_source_id             | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Expel alerts                                                                                                   | expel_alerts                   | :class:`ExpelAlerts`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                       | created_by                     | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendors                                                                                                        | vendor                         | :class:`Vendors`                  | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                    | evidences                      | :class:`VendorAlertEvidences`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor devices                                                                                                 | vendor_device                  | :class:`VendorDevices`            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                       | updated_by                     | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Assemblers                                                                                                     | assembler                      | :class:`Assemblers`               | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                | organization                   | :class:`Organizations`            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                    | customer                       | :class:`Customers`                | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | IP addresses                                                                                                   | ip_addresses                   | :class:`IpAddresses`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Security devices                                                                                               | security_device                | :class:`SecurityDevices`          | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Organization devices                                                                                           | customer_device                | :class:`CustomerDevices`          | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'vendor_alerts'
    _def_attributes = ["original_alert_id", "vendor_severity", "updated_at", "vendor_sig_name", "evidence_summary", "vendor_message", "first_seen",
                       "description", "status", "evidence_activity_start_at", "signature_id", "created_at", "evidence_activity_end_at", "original_source_id"]
    _def_relationships = ["expel_alerts", "created_by", "vendor", "evidences", "vendor_device", "updated_by",
                          "assembler", "organization", "customer", "ip_addresses", "security_device", "customer_device"]


class NistSubcategoryScores(ResourceInstance):
    '''
    .. _api nist_subcategory_scores:

    Latest NIST subcategory scores

    Resource type name is **nist_subcategory_scores**.

    Example JSON record:

    .. code-block:: javascript

        {           'actual_score': 100,
            'assessment_date': '2019-01-15T15:35:00-05:00',
            'category_identifier': 'string',
            'category_name': 'string',
            'comment': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'function_type': 'string',
            'is_priority': True,
            'subcategory_identifier': 'string',
            'subcategory_name': 'string',
            'target_score': 100,
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                  | Field Name                           | Field Type                                 | Attribute     | Relationship     |
        +====================================================================================================================================================================================================================================================================+======================================+============================================+===============+==================+
        | Organization nist subcategory is a priority                                                                                                                                                                                                                        | is_priority                          | boolean                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization actual score for this nist subcategory Allows: null                                                                                                                                                                                                   | actual_score                         | number                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | subcategory_name                     | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: immutable, no-sort                                                                                                                                                                                                                               | subcategory_identifier               | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                   | updated_at                           | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Recorded date of the score assessment (Note: Dates with times will be truncated to the day.  Warning: Dates times and timezones will be converted to UTC before they are truncated.  Providing non-UTC timezones is not recommeneded.) Allows: null: immutable     | assessment_date                      | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | function_type                        | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization comment for this nist subcategory Allows: "", null                                                                                                                                                                                                    | comment                              | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | category_name                        | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | category_identifier                  | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization target score for this nist subcategory Allows: null                                                                                                                                                                                                   | target_score                         | number                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                        | created_at                           | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                           | updated_by                           | :class:`Actors`                            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                           | created_by                           | :class:`Actors`                            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_subcategory records                                                                                                                                                                                                                | nist_subcategory                     | :class:`NistSubcategories`                 | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | NIST Subcategory Score History                                                                                                                                                                                                                                     | nist_subcategory_score_histories     | :class:`NistSubcategoryScoreHistories`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                    | organization                         | :class:`Organizations`                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategory_scores'
    _def_attributes = ["is_priority", "actual_score", "subcategory_name", "subcategory_identifier", "updated_at",
                       "assessment_date", "function_type", "comment", "category_name", "category_identifier", "target_score", "created_at"]
    _def_relationships = ["updated_by", "created_by", "nist_subcategory",
                          "nist_subcategory_score_histories", "organization"]


class OrganizationStatuses(ResourceInstance):
    '''
    .. _api organization_statuses:

    Organization status

    Resource type name is **organization_statuses**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'enabled_login_types': [], 'restrictions': [], 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name              | Field Type                 | Attribute     | Relationship     |
        +=====================================================+=========================+============================+===============+==================+
        | Meta: readonly                                      | created_at              | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | enabled_login_types     | array                      | Y             | N                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | restrictions            | array                      | Y             | N                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Meta: readonly                                      | updated_at              | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by              | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by              | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization            | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'organization_statuses'
    _def_attributes = ["created_at", "enabled_login_types", "restrictions", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "organization"]


class Actors(ResourceInstance):
    '''
    .. _api actors:

    Defines/retrieves expel.io actor records

    Resource type name is **actors**.

    Example JSON record:

    .. code-block:: javascript

        {'actor_type': 'system', 'created_at': '2019-01-15T15:35:00-05:00', 'display_name': 'string', 'is_expel': True, 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                     | Field Name                                        | Field Type                                 | Attribute     | Relationship     |
        +=======================================================================+===================================================+============================================+===============+==================+
        | Display name Allows: "", null                                         | display_name                                      | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                           | created_at                                        | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                      | updated_at                                        | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Actor type Restricted to: "system", "user", "organization", "api"     | actor_type                                        | any                                        | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Meta: readonly, no-sort                                               | is_expel                                          | boolean                                    | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`     | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | created_by                                        | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | child_actors                                      | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_customer_resilience_actions_list         | :class:`CustomerResilienceActions`         | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | updated_by                                        | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Remediation actions                                                   | assigned_remediation_actions                      | :class:`RemediationActions`                | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                       | organization                                      | :class:`Organizations`                     | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                           | customer                                          | :class:`Customers`                         | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User accounts                                                         | user_account                                      | :class:`UserAccounts`                      | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | parent_actor                                      | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                                          | assigned_expel_alerts                             | :class:`ExpelAlerts`                       | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                 | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_customer_resilience_actions              | :class:`CustomerResilienceActions`         | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                        | assigned_investigations                           | :class:`Investigations`                    | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User Notification Preferences                                         | notification_preferences                          | :class:`NotificationPreferences`           | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                 | assigned_investigative_actions                    | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'actors'
    _def_attributes = ["display_name", "created_at", "updated_at", "actor_type", "is_expel"]
    _def_relationships = ["assigned_organization_resilience_actions", "created_by", "child_actors", "assigned_customer_resilience_actions_list", "updated_by", "assigned_remediation_actions", "organization", "customer", "user_account", "parent_actor",
                          "assigned_expel_alerts", "analysis_assigned_investigative_actions", "assigned_organization_resilience_actions_list", "assigned_customer_resilience_actions", "assigned_investigations", "notification_preferences", "assigned_investigative_actions"]


class ResilienceActionGroups(ResourceInstance):
    '''
    .. _api resilience_action_groups:

    Defines/retrieves expel.io resilience_action_group records

    Resource type name is **resilience_action_groups**.

    Example JSON record:

    .. code-block:: javascript

        {'category': 'DISRUPT_ATTACKERS', 'created_at': '2019-01-15T15:35:00-05:00', 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Field Description                                                                           | Field Name             | Field Type                     | Attribute     | Relationship     |
        +=============================================================================================+========================+================================+===============+==================+
        | Created timestamp: readonly                                                                 | created_at             | string                         | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                            | updated_at             | string                         | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Group title                                                                                 | title                  | string                         | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Global Resilience Group Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS"     | category               | any                            | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                    | created_by             | :class:`Actors`                | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                    | updated_by             | :class:`Actors`                | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Resilience actions                                                                          | resilience_actions     | :class:`ResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+

    '''
    _api_type = 'resilience_action_groups'
    _def_attributes = ["created_at", "updated_at", "title", "category"]
    _def_relationships = ["created_by", "updated_by", "resilience_actions"]


class Comments(ResourceInstance):
    '''
    .. _api comments:

    Defines/retrieves expel.io comment records

    Resource type name is **comments**.

    Example JSON record:

    .. code-block:: javascript

        {'comment': 'string', 'created_at': '2019-01-15T15:35:00-05:00', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Field Description                                      | Field Name            | Field Type                    | Attribute     | Relationship     |
        +========================================================+=======================+===============================+===============+==================+
        | Comment                                                | comment               | string                        | Y             | N                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Created timestamp: readonly                            | created_at            | string                        | Y             | N                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                       | updated_at            | string                        | Y             | N                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records               | created_by            | :class:`Actors`               | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records               | updated_by            | :class:`Actors`               | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment_history records     | comment_histories     | :class:`CommentHistories`     | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Investigations                                         | investigation         | :class:`Investigations`       | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records        | organization          | :class:`Organizations`        | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+

    '''
    _api_type = 'comments'
    _def_attributes = ["comment", "created_at", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "comment_histories", "investigation", "organization"]


class ExpelAlertThresholdHistories(ResourceInstance):
    '''
    .. _api expel_alert_threshold_histories:

    Defines/retrieves expel.io expel_alert_threshold_history records

    Resource type name is **expel_alert_threshold_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Field Description                                                                                                     | Field Name                | Field Type                        | Attribute     | Relationship     |
        +=======================================================================================================================+===========================+===================================+===============+==================+
        | Created timestamp: readonly                                                                                           | created_at                | string                            | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Expel alert threshold history action Restricted to: "CREATED", "BREACHED", "ACKNOWLEDGED", "RECOVERED", "DELETED"     | action                    | any                               | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Expel alert threshold history details Allows: null: no-sort                                                           | value                     | object                            | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                              | created_by                | :class:`Actors`                   | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records                                                              | expel_alert_threshold     | :class:`ExpelAlertThresholds`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_threshold_histories'
    _def_attributes = ["created_at", "action", "value"]
    _def_relationships = ["created_by", "expel_alert_threshold"]


class PhishingSubmissionUrls(ResourceInstance):
    '''
    .. _api phishing_submission_urls:

    Phishing submission URLs

    Resource type name is **phishing_submission_urls**.

    Example JSON record:

    .. code-block:: javascript

        {'url_type': 'https://company.com/', 'value': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name              | Field Type                       | Attribute     | Relationship     |
        +==============================================+=========================+==================================+===============+==================+
        | URL type                                     | url_type                | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Value                                        | value                   | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by              | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission     | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_urls'
    _def_attributes = ["url_type", "value"]
    _def_relationships = ["created_by", "phishing_submission"]


class InvestigativeActionDataTechniqueRdpConnectionAnomalies(ResourceInstance):
    '''
    .. _api investigative_action_data_technique_rdp_connection_anomalies:

    Investigative action data for technique_rdp_connection_anomalies

    Resource type name is **investigative_action_data_technique_rdp_connection_anomalies**.

    Example JSON record:

    .. code-block:: javascript

        {           'automated': True,
            'automation_first_seen': 'string',
            'avg_authentications_by_users': 100,
            'avg_new_authentication_ratio': 100,
            'avg_new_authentications_by_users': 100,
            'count': 100,
            'destination': 'string',
            'destination_assets': 'string',
            'destination_first_seen': 'string',
            'destination_groups': 'string',
            'destination_new_logon_ratio': 100,
            'destination_new_logons': 100,
            'destination_total_logons': 100,
            'first_seen': 'string',
            'in_baseline': True,
            'in_user_dest_baseline': True,
            'last_seen': 'string',
            'source': 'string',
            'source_assets': 'string',
            'source_country': 100,
            'source_groups': 'string',
            'source_organization': 'string',
            'source_resolutions': 'string',
            'source_routable': True,
            'stddev_of_new_authentication_ratio': 100,
            'subnet': 'string',
            'user': 'string',
            'user_assets': 'string',
            'user_first_seen': 'string',
            'user_groups': 'string',
            'user_ip_addresses': 100,
            'user_max_destinations_per_day': 100,
            'user_new_logon_ratio': 100,
            'user_new_logons': 100,
            'user_subnets': 100,
            'user_total_logons': 100}


    Below are valid filter by parameters:

        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name                             | Field Type                        | Attribute     | Relationship     |
        +===========================+========================================+===================================+===============+==================+
        | Allows: null              | user_total_logons                      | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | subnet                                 | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | user_first_seen                        | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | user_assets                            | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | first_seen                             | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | count                                  | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | automated                              | boolean                           | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | in_baseline                            | boolean                           | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | user_new_logons                        | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | destination_new_logons                 | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | user_new_logon_ratio                   | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | user_subnets                           | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | avg_new_authentications_by_users       | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | source_country                         | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | destination_assets                     | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source_resolutions                     | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | stddev_of_new_authentication_ratio     | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source_groups                          | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | destination_first_seen                 | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | automation_first_seen                  | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | source_routable                        | boolean                           | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | avg_new_authentication_ratio           | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | destination_total_logons               | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source_organization                    | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | user_max_destinations_per_day          | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | destination_new_logon_ratio            | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | destination_groups                     | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | in_user_dest_baseline                  | boolean                           | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | user                                   | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | last_seen                              | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | user_ip_addresses                      | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source                                 | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source_assets                          | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | user_groups                            | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | destination                            | string                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | avg_authentications_by_users           | number                            | Y             | N                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action                   | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+----------------------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_technique_rdp_connection_anomalies'
    _def_attributes = ["user_total_logons", "subnet", "user_first_seen", "user_assets", "first_seen", "count", "automated", "in_baseline", "user_new_logons", "destination_new_logons", "user_new_logon_ratio", "user_subnets", "avg_new_authentications_by_users", "source_country", "destination_assets", "source_resolutions", "stddev_of_new_authentication_ratio", "source_groups",
                       "destination_first_seen", "automation_first_seen", "source_routable", "avg_new_authentication_ratio", "destination_total_logons", "source_organization", "user_max_destinations_per_day", "destination_new_logon_ratio", "destination_groups", "in_user_dest_baseline", "user", "last_seen", "user_ip_addresses", "source", "source_assets", "user_groups", "destination", "avg_authentications_by_users"]
    _def_relationships = ["investigative_action"]


class Assemblers(ResourceInstance):
    '''
    .. _api assemblers:

    Assemblers

    Resource type name is **assemblers**.

    Example JSON record:

    .. code-block:: javascript

        {           'connection_status': 'Never Connected',
            'connection_status_updated_at': '2019-01-15T15:35:00-05:00',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'install_code': 'string',
            'lifecycle_status': 'New',
            'lifecycle_status_updated_at': '2019-01-15T15:35:00-05:00',
            'location': 'string',
            'name': 'string',
            'status': 'string',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'vpn_ip': 'string'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                             | Field Name                       | Field Type                   | Attribute     | Relationship     |
        +===============================================================================================================================================================================================================+==================================+==============================+===============+==================+
        | Name of assembler Allows: "", null                                                                                                                                                                            | name                             | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler connection status update timestamp: readonly                                                                                                                                                        | connection_status_updated_at     | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler status Allows: "", null: readonly, no-sort                                                                                                                                                          | status                           | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                              | updated_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler last status update timestamp: readonly                                                                                                                                                              | status_updated_at                | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler lifecycle status update timestamp: readonly                                                                                                                                                         | lifecycle_status_updated_at      | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Location of assembler Allows: "", null                                                                                                                                                                        | location                         | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler install code Allows: null                                                                                                                                                                           | install_code                     | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler life cycle status Restricted to: "New", "Authorized", "Transitioning", "Transitioned", "Transition Failed", "Configuring", "Configuration Failed", "Active", "Inactive", "Deleted" Allows: null     | lifecycle_status                 | any                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler VPN ip address Allows: null                                                                                                                                                                         | vpn_ip                           | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                             | deleted_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                   | created_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler connection status Restricted to: "Never Connected", "Connection Lost", "Connected to Provisioning", "Connected to Service" Allows: null                                                             | connection_status                | any                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                      | created_by                       | :class:`Actors`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                 | vendor_alerts                    | :class:`VendorAlerts`        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Vendor devices                                                                                                                                                                                                | vendor_devices                   | :class:`VendorDevices`       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                              | security_devices                 | :class:`SecurityDevices`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                      | updated_by                       | :class:`Actors`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                                                                                   | customer                         | :class:`Customers`           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                               | organization                     | :class:`Organizations`       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'assemblers'
    _def_attributes = ["name", "connection_status_updated_at", "status", "updated_at", "status_updated_at", "lifecycle_status_updated_at",
                       "location", "install_code", "lifecycle_status", "vpn_ip", "deleted_at", "created_at", "connection_status"]
    _def_relationships = ["created_by", "vendor_alerts", "vendor_devices",
                          "security_devices", "updated_by", "customer", "organization"]


class InvestigativeActionDataQueryCloudtrail(ResourceInstance):
    '''
    .. _api investigative_action_data_query_cloudtrail:

    Investigative action data for query_cloudtrail

    Resource type name is **investigative_action_data_query_cloudtrail**.

    Example JSON record:

    .. code-block:: javascript

        {           'awsRegion': 'string',
            'destinationAwsAccountId': 'string',
            'errorCode': 'string',
            'errorMessage': 'string',
            'eventName': 'string',
            'eventSource': 'string',
            'eventTime': 'string',
            'eventType': 'string',
            'invokedBy': 'string',
            'mfaAuthenticated': 'string',
            'principalId': 'string',
            'rawEvent': 'string',
            'sessionCreationDate': 'string',
            'sessionIssuerAccountId': 'string',
            'sessionIssuerPrincipalId': 'string',
            'sessionIssuerType': 'string',
            'sessionIssuerUserName': 'string',
            'sourceAwsAccountId': 'string',
            'sourceIPAddress': 'string',
            'userAccessKeyId': 'string',
            'userAgent': 'string',
            'userArn': 'string',
            'userType': 'string'}


    Below are valid filter by parameters:

        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name                   | Field Type                        | Attribute     | Relationship     |
        +===========================+==============================+===================================+===============+==================+
        | Allows: null              | sessionIssuerType            | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | userType                     | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | userAccessKeyId              | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | userAgent                    | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | principalId                  | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | sessionCreationDate          | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | mfaAuthenticated             | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | sourceIPAddress              | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | eventType                    | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | userArn                      | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | invokedBy                    | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | eventTime                    | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | errorCode                    | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | eventSource                  | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | sessionIssuerPrincipalId     | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | awsRegion                    | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | destinationAwsAccountId      | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | sessionIssuerAccountId       | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | rawEvent                     | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | sessionIssuerUserName        | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | eventName                    | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | sourceAwsAccountId           | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | errorMessage                 | string                            | Y             | N                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action         | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+------------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_cloudtrail'
    _def_attributes = ["sessionIssuerType", "userType", "userAccessKeyId", "userAgent", "principalId", "sessionCreationDate", "mfaAuthenticated", "sourceIPAddress", "eventType", "userArn", "invokedBy", "eventTime",
                       "errorCode", "eventSource", "sessionIssuerPrincipalId", "awsRegion", "destinationAwsAccountId", "sessionIssuerAccountId", "rawEvent", "sessionIssuerUserName", "eventName", "sourceAwsAccountId", "errorMessage"]
    _def_relationships = ["investigative_action"]


class InvestigativeActionDataTechniqueFailedC2Connections(ResourceInstance):
    '''
    .. _api investigative_action_data_technique_failed_c_2_connections:

    Investigative action data for technique_failed_c2_connections

    Resource type name is **investigative_action_data_technique_failed_c_2_connections**.

    Example JSON record:

    .. code-block:: javascript

        {           'as_ns': 'string',
            'connection_attempts': 100,
            'country_code': 'string',
            'destination_ip': 'string',
            'destination_port_s': 'string',
            'domains': 'string',
            'ip_networks': 'string',
            'organization_type': 'string',
            'organizations': 'string',
            'source_ip_s_connect_count': 'string',
            'unique_connection_attempts': 100,
            'unique_source_ip_count': 100,
            'virus_total_detected_sample_first_seen': 'string',
            'virus_total_detected_sample_last_seen': 'string',
            'virus_total_detected_samples_count': 100,
            'virus_total_detected_url_count': 100,
            'virus_total_detected_url_first_seen': 'string',
            'virus_total_detected_url_last_seen': 'string',
            'virus_total_undetected_sample_count': 100,
            'virus_total_undetected_sample_first_seen': 'string',
            'virus_total_undetected_sample_last_seen': 'string',
            'virus_total_unique_detected_url_count': 100,
            'virus_total_unique_domain_resolution_count': 100}


    Below are valid filter by parameters:

        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name                                     | Field Type                        | Attribute     | Relationship     |
        +===========================+================================================+===================================+===============+==================+
        | Allows: null, ""          | as_ns                                          | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | virus_total_detected_url_first_seen            | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | virus_total_undetected_sample_last_seen        | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | virus_total_undetected_sample_first_seen       | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | virus_total_unique_detected_url_count          | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | country_code                                   | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | virus_total_unique_domain_resolution_count     | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | ip_networks                                    | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | unique_source_ip_count                         | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | virus_total_detected_sample_first_seen         | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | connection_attempts                            | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | domains                                        | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | unique_connection_attempts                     | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | virus_total_undetected_sample_count            | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | virus_total_detected_samples_count             | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | source_ip_s_connect_count                      | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | organization_type                              | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | virus_total_detected_url_count                 | number                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | virus_total_detected_url_last_seen             | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | virus_total_detected_sample_last_seen          | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | destination_ip                                 | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | destination_port_s                             | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | organizations                                  | string                            | Y             | N                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action                           | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+------------------------------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_technique_failed_c_2_connections'
    _def_attributes = ["as_ns", "virus_total_detected_url_first_seen", "virus_total_undetected_sample_last_seen", "virus_total_undetected_sample_first_seen", "virus_total_unique_detected_url_count", "country_code", "virus_total_unique_domain_resolution_count", "ip_networks", "unique_source_ip_count", "virus_total_detected_sample_first_seen",
                       "connection_attempts", "domains", "unique_connection_attempts", "virus_total_undetected_sample_count", "virus_total_detected_samples_count", "source_ip_s_connect_count", "organization_type", "virus_total_detected_url_count", "virus_total_detected_url_last_seen", "virus_total_detected_sample_last_seen", "destination_ip", "destination_port_s", "organizations"]
    _def_relationships = ["investigative_action"]


class PhishingSubmissionDomains(ResourceInstance):
    '''
    .. _api phishing_submission_domains:

    Phishing submission domains

    Resource type name is **phishing_submission_domains**.

    Example JSON record:

    .. code-block:: javascript

        {'value': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name              | Field Type                       | Attribute     | Relationship     |
        +==============================================+=========================+==================================+===============+==================+
        | Value                                        | value                   | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by              | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission     | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_domains'
    _def_attributes = ["value"]
    _def_relationships = ["created_by", "phishing_submission"]


class ExpelAlertGrid(ResourceInstance):
    '''
    .. _api expel_alert_grid:

    Elastic search backed Alert Grid

    Resource type name is **expel_alert_grid**.

    Example JSON record:

    .. code-block:: javascript

        {           'activity_first_at': '2019-01-15T15:35:00-05:00',
            'activity_last_at': '2019-01-15T15:35:00-05:00',
            'alert_at': '2019-01-15T15:35:00-05:00',
            'alert_type': ['string', ['string', 'string']],
            'assignee_name': ['string', ['string', 'string']],
            'close_comment': ['string', ['string', 'string']],
            'destination_ip_addresses': ['string', ['string', 'string']],
            'expel_guid': ['string', ['string', 'string']],
            'expel_message': ['string', ['string', 'string']],
            'expel_name': ['string', ['string', 'string']],
            'expel_severity': ['string', ['string', 'string']],
            'hostnames': ['string', ['string', 'string']],
            'organization_name': ['string', ['string', 'string']],
            'parent_arguments': ['string', ['string', 'string']],
            'parent_md5': ['string', ['string', 'string']],
            'parent_path': ['string', ['string', 'string']],
            'process_arguments': ['string', ['string', 'string']],
            'process_md5': ['string', ['string', 'string']],
            'process_path': ['string', ['string', 'string']],
            'source_ip_addresses': ['string', ['string', 'string']],
            'status': ['string', ['string', 'string']],
            'tuning_requested': True,
            'updated_at': '2019-01-15T15:35:00-05:00',
            'urls': ['string', ['string', 'string']],
            'usernames': ['string', ['string', 'string']],
            'vendor_alert_count': 100,
            'vendor_device_guid': ['string', ['string', 'string']],
            'vendor_name': ['string', ['string', 'string']],
            'vendor_sig_name': ['string', ['string', 'string']]}


    Below are valid filter by parameters:

        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Field Description                                                | Field Name                   | Field Type                   | Attribute     | Relationship     |
        +==================================================================+==============================+==============================+===============+==================+
        | May be a string or an array of strings: allowStringOperators     | parent_arguments             | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Allows: null                                                     | vendor_alert_count           | number                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | urls                         | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | updated_at                   | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | vendor_name                  | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | activity_last_at             | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | alert_at                     | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | status                       | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | process_arguments            | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Allows: null                                                     | tuning_requested             | boolean                      | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | process_path                 | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_guid                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | process_md5                  | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | parent_path                  | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | vendor_device_guid           | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_severity               | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | alert_type                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | usernames                    | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | activity_first_at            | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_name                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | parent_md5                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | vendor_sig_name              | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | destination_ip_addresses     | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | assignee_name                | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | source_ip_addresses          | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | organization_name            | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | close_comment                | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | hostnames                    | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_message                | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                         | assigned_to_org              | :class:`Actors`              | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Investigations                                                   | investigation                | :class:`Investigations`      | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Vendors                                                          | vendor                       | :class:`Vendors`             | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Security devices                                                 | security_devices             | :class:`SecurityDevices`     | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                                    | vendor_alerts                | :class:`VendorAlerts`        | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Expel alerts                                                     | expel_alert                  | :class:`ExpelAlerts`         | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                  | organization                 | :class:`Organizations`       | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                         | assigned_to_actor            | :class:`Actors`              | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_grid'
    _def_attributes = ["parent_arguments", "vendor_alert_count", "urls", "updated_at", "vendor_name", "activity_last_at", "alert_at", "status", "process_arguments", "tuning_requested", "process_path", "expel_guid", "process_md5", "parent_path", "vendor_device_guid",
                       "expel_severity", "alert_type", "usernames", "activity_first_at", "expel_name", "parent_md5", "vendor_sig_name", "destination_ip_addresses", "assignee_name", "source_ip_addresses", "organization_name", "close_comment", "hostnames", "expel_message"]
    _def_relationships = ["assigned_to_org", "investigation", "vendor", "security_devices",
                          "vendor_alerts", "expel_alert", "organization", "assigned_to_actor"]


class NistCategories(ResourceInstance):
    '''
    .. _api nist_categories:

    Defines/retrieves expel.io nist_category records

    Resource type name is **nist_categories**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'function_type': 'IDENTIFY', 'identifier': 'string', 'name': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Field Description                                                                   | Field Name             | Field Type                     | Attribute     | Relationship     |
        +=====================================================================================+========================+================================+===============+==================+
        | Created timestamp: readonly                                                         | created_at             | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Nist category name                                                                  | name                   | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Actor type Restricted to: "IDENTIFY", "PROTECT", "DETECT", "RECOVER", "RESPOND"     | function_type          | any                            | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Nist category abbreviated identifier                                                | identifier             | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                    | updated_at             | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                            | created_by             | :class:`Actors`                | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                            | updated_by             | :class:`Actors`                | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_subcategory records                                 | nist_subcategories     | :class:`NistSubcategories`     | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_categories'
    _def_attributes = ["created_at", "name", "function_type", "identifier", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "nist_subcategories"]


class InvestigationFindingHistories(ResourceInstance):
    '''
    .. _api investigation_finding_histories:

    Defines/retrieves expel.io investigation_finding_history records

    Resource type name is **investigation_finding_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'updated_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Field Description                                                                                    | Field Name                | Field Type                         | Attribute     | Relationship     |
        +======================================================================================================+===========================+====================================+===============+==================+
        | Investigation finding history details Allows: null: no-sort                                          | value                     | object                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                          | created_at                | string                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigation finding history action Restricted to: "CREATED", "CHANGED", "DELETED" Allows: null     | action                    | any                                | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                     | updated_at                | string                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigation findings                                                                               | investigation_finding     | :class:`InvestigationFindings`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                             | created_by                | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                             | updated_by                | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigations                                                                                       | investigation             | :class:`Investigations`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_finding_histories'
    _def_attributes = ["value", "created_at", "action", "updated_at"]
    _def_relationships = ["investigation_finding", "created_by", "updated_by", "investigation"]


class VendorDevices(ResourceInstance):
    '''
    .. _api vendor_devices:

    Vendor devices

    Resource type name is **vendor_devices**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'device_spec': {},
            'device_type': 'ENDPOINT',
            'has_two_factor_secret': True,
            'location': 'string',
            'name': 'string',
            'plugin_slug': 'string',
            'status': 'healthy',
            'status_details': {},
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'task_source': 'CUSTOMER_PREMISE',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Field Description                                                                            | Field Name                | Field Type                        | Attribute     | Relationship     |
        +==============================================================================================+===========================+===================================+===============+==================+
        | Device Spec Allows: null: no-sort                                                            | device_spec               | object                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Status Details Allows: null: no-sort                                                         | status_details            | object                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Allows: "", null                                                                             | plugin_slug               | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Name                                                                                         | name                      | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Has 2fa secret stored in vault: readonly                                                     | has_two_factor_secret     | boolean                           | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                             | updated_at                | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                     | status_updated_at         | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Location where tasks are run Restricted to: "CUSTOMER_PREMISE", "EXPEL_TASKPOOL"             | task_source               | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Status Restricted to: "healthy", "unhealthy", "health_checks_not_supported" Allows: null     | status                    | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Location Allows: "", null                                                                    | location                  | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Device Type Restricted to: "ENDPOINT", "NETWORK", "SIEM", "OTHER", "CLOUD"                   | device_type               | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                            | deleted_at                | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                  | created_at                | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                     | updated_by                | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                     | created_by                | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Vendors                                                                                      | vendor                    | :class:`Vendors`                  | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Vendor alerts                                                                                | vendor_alerts             | :class:`VendorAlerts`             | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | investigative actions                                                                        | investigative_actions     | :class:`InvestigativeActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Vendor devices                                                                               | parent_vendor_device      | :class:`VendorDevices`            | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Vendor devices                                                                               | child_vendor_devices      | :class:`VendorDevices`            | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Organization devices                                                                         | customer_device           | :class:`CustomerDevices`          | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Assemblers                                                                                   | assembler                 | :class:`Assemblers`               | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                  | customer                  | :class:`Customers`                | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                              | organization              | :class:`Organizations`            | N             | Y                |
        +----------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'vendor_devices'
    _def_attributes = ["device_spec", "status_details", "plugin_slug", "name", "has_two_factor_secret", "updated_at",
                       "status_updated_at", "task_source", "status", "location", "device_type", "deleted_at", "created_at"]
    _def_relationships = ["updated_by", "created_by", "vendor", "vendor_alerts", "investigative_actions",
                          "parent_vendor_device", "child_vendor_devices", "customer_device", "assembler", "customer", "organization"]


class InvestigativeActionDataQueryIp(ResourceInstance):
    '''
    .. _api investigative_action_data_query_ip:

    Investigative action data for query_ip

    Resource type name is **investigative_action_data_query_ip**.

    Example JSON record:

    .. code-block:: javascript

        {           'application': 'string',
            'bytes_rx': 100,
            'bytes_tx': 100,
            'dst': 'string',
            'dst_port': 100,
            'dst_processes': 'string',
            'ended_at': 'string',
            'event_description': 'string',
            'evidence_type': 'string',
            'file_events': 'string',
            'network_events': 'string',
            'packets_rx': 100,
            'packets_tx': 100,
            'process_name': 'string',
            'process_pid': 100,
            'protocol': 'string',
            'registry_events': 'string',
            'sensor': 'string',
            'src': 'string',
            'src_port': 100,
            'started_at': 'string',
            'summary': 'string',
            'unsigned_modules': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | summary                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | unsigned_modules         | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | protocol                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | evidence_type            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | bytes_rx                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | packets_tx               | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | packets_rx               | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registry_events          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | sensor                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_name             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | application              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | src_port                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | event_description        | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | ended_at                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | network_events           | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_events              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | process_pid              | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | bytes_tx                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst_processes            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | dst_port                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_ip'
    _def_attributes = ["summary", "unsigned_modules", "protocol", "evidence_type", "bytes_rx", "packets_tx", "packets_rx", "registry_events", "sensor", "process_name",
                       "application", "src_port", "event_description", "dst", "ended_at", "network_events", "started_at", "file_events", "process_pid", "bytes_tx", "dst_processes", "src", "dst_port"]
    _def_relationships = ["investigative_action"]


class ApiKeys(ResourceInstance):
    '''
    .. _api api_keys:

    Defines/retrieves expel.io api_key records. These can only be created by a user and require an OTP token.

    Resource type name is **api_keys**.

    Example JSON record:

    .. code-block:: javascript

        {           'access_token': 'string',
            'active': True,
            'assignable': True,
            'created_at': '2019-01-15T15:35:00-05:00',
            'display_name': 'string',
            'key': 'string',
            'name': 'string',
            'realm': 'public',
            'role': 'expel_admin',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                                         | Field Name       | Field Type                 | Attribute     | Relationship     |
        +===========================================================================================================================================+==================+============================+===============+==================+
        | Display name Allows: null                                                                                                                 | display_name     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Realm in which the api key can be used. Restricted to: "public", "internal"                                                               | realm            | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Role Restricted to: "expel_admin", "expel_analyst", "organization_admin", "organization_analyst", "system", "anonymous", "restricted"     | role             | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Can Api key be assigned items (e.g. investigations, etc)                                                                                  | assignable       | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                               | created_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                          | updated_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Active Allows: null                                                                                                                       | active           | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Missing Description                                                                                                                       | name             | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Meta: private, readonly                                                                                                                   | key              | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Only upon initial api key creation (POST), contains the bearer api key token required for api access.: readonly, no-sort                  | access_token     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                  | created_by       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                  | updated_by       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                               | customer         | :class:`Customers`         | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                           | organization     | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'api_keys'
    _def_attributes = ["display_name", "realm", "role", "assignable",
                       "created_at", "updated_at", "active", "name", "key", "access_token"]
    _def_relationships = ["created_by", "updated_by", "customer", "organization"]


class ResilienceActions(ResourceInstance):
    '''
    .. _api resilience_actions:

    Resilience actions

    Resource type name is **resilience_actions**.

    Example JSON record:

    .. code-block:: javascript

        {'category': 'DISRUPT_ATTACKERS', 'created_at': '2019-01-15T15:35:00-05:00', 'details': 'string', 'impact': 'LOW', 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Field Description                                                                | Field Name                                     | Field Type                                           | Attribute     | Relationship     |
        +==================================================================================+================================================+======================================================+===============+==================+
        | Details                                                                          | details                                        | string                                               | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null     | category                                       | any                                                  | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                      | created_at                                     | string                                               | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                 | updated_at                                     | string                                               | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Title                                                                            | title                                          | string                                               | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH"                                    | impact                                         | any                                                  | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | created_by                                     | :class:`Actors`                                      | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | updated_by                                     | :class:`Actors`                                      | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_investigation_property records      | resilience_action_investigation_properties     | :class:`ResilienceActionInvestigationProperties`     | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_group records                       | resilience_action_group                        | :class:`ResilienceActionGroups`                      | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------------+------------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'resilience_actions'
    _def_attributes = ["details", "category", "created_at", "updated_at", "title", "impact"]
    _def_relationships = ["created_by", "updated_by",
                          "resilience_action_investigation_properties", "resilience_action_group"]


class SecurityDevices(ResourceInstance):
    '''
    .. _api security_devices:

    Security devices

    Resource type name is **security_devices**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'device_spec': {},
            'device_type': 'ENDPOINT',
            'has_two_factor_secret': True,
            'location': 'string',
            'name': 'string',
            'plugin_slug': 'string',
            'status': 'healthy',
            'status_details': {},
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'task_source': 'CUSTOMER_PREMISE',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                  | Field Name                 | Field Type                        | Attribute     | Relationship     |
        +====================================================================================================================================================================================================================================================================================================================================================================+============================+===================================+===============+==================+
        | Device Spec Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                  | device_spec                | object                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Status Details.  Note: By default if the security device has an assembler, and that assembler is unhealthy, the status details will return that information rather than the raw status of the security device.  To disable this behavior, add the query parameter `flag[raw_status]=true`. Allows: null: no-sort                                                   | status_details             | object                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Allows: "", null                                                                                                                                                                                                                                                                                                                                                   | plugin_slug                | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Name                                                                                                                                                                                                                                                                                                                                                               | name                       | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Has 2fa secret stored in vault: readonly                                                                                                                                                                                                                                                                                                                           | has_two_factor_secret      | boolean                           | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                                                                                                                   | updated_at                 | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                                                                                                           | status_updated_at          | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Location where tasks are run Restricted to: "CUSTOMER_PREMISE", "EXPEL_TASKPOOL"                                                                                                                                                                                                                                                                                   | task_source                | any                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Status.    Note: By default if the security device has an assembler, and that assembler is unhealthy, the status will return that information rather than the raw status of the security device.  To disable this behavior, add the query parameter `flag[raw_status]=true`. Restricted to: "healthy", "unhealthy", "health_checks_not_supported" Allows: null     | status                     | any                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Location Allows: "", null                                                                                                                                                                                                                                                                                                                                          | location                   | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Device Type Restricted to: "ENDPOINT", "NETWORK", "SIEM", "OTHER", "CLOUD"                                                                                                                                                                                                                                                                                         | device_type                | any                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                                                                                                                  | deleted_at                 | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                        | created_at                 | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                           | created_by                 | :class:`Actors`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Vendors                                                                                                                                                                                                                                                                                                                                                            | vendor                     | :class:`Vendors`                  | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                                                                                                                                                      | vendor_alerts              | :class:`VendorAlerts`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                                                                                                              | investigative_actions      | :class:`InvestigativeActions`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                   | child_security_devices     | :class:`SecurityDevices`          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                   | parent_security_device     | :class:`SecurityDevices`          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                           | updated_by                 | :class:`Actors`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Assemblers                                                                                                                                                                                                                                                                                                                                                         | assembler                  | :class:`Assemblers`               | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                                                                                                                                                                                                                                        | customer                   | :class:`Customers`                | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                                                                                                                    | organization               | :class:`Organizations`            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'security_devices'
    _def_attributes = ["device_spec", "status_details", "plugin_slug", "name", "has_two_factor_secret", "updated_at",
                       "status_updated_at", "task_source", "status", "location", "device_type", "deleted_at", "created_at"]
    _def_relationships = ["created_by", "vendor", "vendor_alerts", "investigative_actions",
                          "child_security_devices", "parent_security_device", "updated_by", "assembler", "customer", "organization"]


class NotificationPreferences(ResourceInstance):
    '''
    .. _api notification_preferences:

    User Notification Preferences

    Resource type name is **notification_preferences**.

    Example JSON record:

    .. code-block:: javascript

        {'preferences': []}


    Below are valid filter by parameters:

        +----------------------------------------------+-----------------+---------------------+---------------+------------------+
        | Field Description                            | Field Name      | Field Type          | Attribute     | Relationship     |
        +==============================================+=================+=====================+===============+==================+
        | Missing Description                          | preferences     | array               | Y             | N                |
        +----------------------------------------------+-----------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | actor           | :class:`Actors`     | N             | Y                |
        +----------------------------------------------+-----------------+---------------------+---------------+------------------+

    '''
    _api_type = 'notification_preferences'
    _def_attributes = ["preferences"]
    _def_relationships = ["actor"]


class UserAccounts(ResourceInstance):
    '''
    .. _api user_accounts:

    User accounts

    Resource type name is **user_accounts**.

    Example JSON record:

    .. code-block:: javascript

        {           'active': True,
            'active_status': 'ACTIVE',
            'assignable': True,
            'created_at': '2019-01-15T15:35:00-05:00',
            'display_name': 'string',
            'email': 'name@company.com',
            'engagement_manager': True,
            'first_name': 'string',
            'homepage_preferences': {},
            'invite_token': 'string',
            'invite_token_expires_at': '2019-01-15T15:35:00-05:00',
            'language': 'string',
            'last_name': 'string',
            'locale': 'string',
            'password_reset_token': 'string',
            'password_reset_token_expires_at': '2019-01-15T15:35:00-05:00',
            'phone_number': 'string',
            'timezone': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                | Field Name                                        | Field Type                                 | Attribute     | Relationship     |
        +==================================================================================================================================+===================================================+============================================+===============+==================+
        | Display name Allows: "", null                                                                                                    | display_name                                      | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Locale Allows: "", null                                                                                                          | locale                                            | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Invite token Allows: null: readonly, private                                                                                     | invite_token                                      | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Homepage preferences Allows: null: no-sort                                                                                       | homepage_preferences                              | object                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Name                                                                                                                        | last_name                                         | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                 | updated_at                                        | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Restricted to: "ACTIVE", "LOCKED", "LOCKED_INVITED", "LOCKED_EXPIRED", "ACTIVE_INVITED", "ACTIVE_EXPIRED": readonly, no-sort     | active_status                                     | any                                        | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Active Allows: null                                                                                                              | active                                            | boolean                                    | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Phone number Allows: null                                                                                                        | phone_number                                      | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Password reset token expiry Allows: null: readonly, private                                                                      | password_reset_token_expires_at                   | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Language Allows: "", null                                                                                                        | language                                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Can user be assigned items (e.g. investigations, etc)                                                                            | assignable                                        | boolean                                    | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Timezone Allows: "", null                                                                                                        | timezone                                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Password reset token Allows: null: readonly, private                                                                             | password_reset_token                              | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Email                                                                                                                            | email                                             | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                      | created_at                                        | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | First Name                                                                                                                       | first_name                                        | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Invite token expiry Allows: null: readonly, private                                                                              | invite_token_expires_at                           | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Is an engagement manager                                                                                                         | engagement_manager                                | boolean                                    | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                               | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                         | created_by                                        | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                     | assigned_expel_alerts                             | :class:`ExpelAlerts`                       | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                         | updated_by                                        | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                              | assigned_remediation_actions                      | :class:`RemediationActions`                | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                  | primary_organization                              | :class:`Organizations`                     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                               | assigned_customer_resilience_actions_list         | :class:`CustomerResilienceActions`         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                      | customer                                          | :class:`Customers`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User account status                                                                                                              | user_account_status                               | :class:`UserAccountStatuses`               | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                         | actor                                             | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                            | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                               | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                               | assigned_customer_resilience_actions              | :class:`CustomerResilienceActions`         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                   | assigned_investigations                           | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                                    | notification_preferences                          | :class:`NotificationPreferences`           | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                  | organizations                                     | :class:`Organizations`                     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                            | assigned_investigative_actions                    | :class:`InvestigativeActions`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io user_account_role records                                                                             | user_account_roles                                | :class:`UserAccountRoles`                  | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'user_accounts'
    _def_attributes = ["display_name", "locale", "invite_token", "homepage_preferences", "last_name", "updated_at", "active_status", "active", "phone_number",
                       "password_reset_token_expires_at", "language", "assignable", "timezone", "password_reset_token", "email", "created_at", "first_name", "invite_token_expires_at", "engagement_manager"]
    _def_relationships = ["assigned_organization_resilience_actions", "created_by", "assigned_expel_alerts", "updated_by", "assigned_remediation_actions", "primary_organization", "assigned_customer_resilience_actions_list", "customer", "user_account_status", "actor",
                          "analysis_assigned_investigative_actions", "assigned_organization_resilience_actions_list", "assigned_customer_resilience_actions", "assigned_investigations", "notification_preferences", "organizations", "assigned_investigative_actions", "user_account_roles"]


class ConfigurationLabels(ResourceInstance):
    '''
    .. _api configuration_labels:

    Configuration labels

    Resource type name is **configuration_labels**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'description': 'string', 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Field Description                                       | Field Name                 | Field Type                         | Attribute     | Relationship     |
        +=========================================================+============================+====================================+===============+==================+
        | Created timestamp: readonly                             | created_at                 | string                             | Y             | N                |
        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Description of configuration label Allows: "", null     | description                | string                             | Y             | N                |
        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Title of configuration label Allows: "", null           | title                      | string                             | Y             | N                |
        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                        | updated_at                 | string                             | Y             | N                |
        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration defaults                                  | configuration_defaults     | :class:`ConfigurationDefaults`     | N             | Y                |
        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                | updated_by                 | :class:`Actors`                    | N             | Y                |
        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                | created_by                 | :class:`Actors`                    | N             | Y                |
        +---------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'configuration_labels'
    _def_attributes = ["created_at", "description", "title", "updated_at"]
    _def_relationships = ["configuration_defaults", "updated_by", "created_by"]


class Integrations(ResourceInstance):
    '''
    .. _api integrations:

    Defines/retrieves expel.io integration records

    Resource type name is **integrations**.

    Example JSON record:

    .. code-block:: javascript

        {           'account': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'integration_meta': {},
            'integration_type': 'pagerduty',
            'last_tested_at': '2019-01-15T15:35:00-05:00',
            'service_name': 'string',
            'status': 'UNTESTED',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                           | Field Name           | Field Type                 | Attribute     | Relationship     |
        +=============================================================================================================+======================+============================+===============+==================+
        | Integration status Restricted to: "UNTESTED", "TEST_SUCCESS", "TEST_FAIL": readonly                         | status               | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Last Successful Test Allows: null: readonly                                                                 | last_tested_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Needed information for integration type Allows: null: no-sort                                               | integration_meta     | object                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Service display name                                                                                        | service_name         | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Service account identifier                                                                                  | account              | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                 | created_at           | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                            | updated_at           | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Type of integration Restricted to: "pagerduty", "slack", "ticketing", "service_now", "teams": immutable     | integration_type     | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                    | created_by           | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                    | updated_by           | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Organization secrets. Note - these requests must be in the format of `/secrets/security_device-<guid>`      | secret               | :class:`Secrets`           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                 | customer             | :class:`Customers`         | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                             | organization         | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'integrations'
    _def_attributes = ["status", "last_tested_at", "integration_meta",
                       "service_name", "account", "created_at", "updated_at", "integration_type"]
    _def_relationships = ["created_by", "updated_by", "secret", "customer", "organization"]


class IpAddresses(ResourceInstance):
    '''
    .. _api ip_addresses:

    IP addresses

    Resource type name is **ip_addresses**.

    Example JSON record:

    .. code-block:: javascript

        {'address': 'string', 'created_at': '2019-01-15T15:35:00-05:00', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Field Description                            | Field Name                     | Field Type                  | Attribute     | Relationship     |
        +==============================================+================================+=============================+===============+==================+
        | IP Address: readonly                         | address                        | string                      | Y             | N                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Created timestamp: readonly                  | created_at                     | string                      | Y             | N                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at                     | string                      | Y             | N                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                     | :class:`Actors`             | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | source_investigations          | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                 | source_expel_alerts            | :class:`ExpelAlerts`        | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | destination_investigations     | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | investigations                 | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                     | :class:`Actors`             | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                 | destination_expel_alerts       | :class:`ExpelAlerts`        | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Vendor alerts                                | vendor_alerts                  | :class:`VendorAlerts`       | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'ip_addresses'
    _def_attributes = ["address", "created_at", "updated_at"]
    _def_relationships = ["created_by", "source_investigations", "source_expel_alerts",
                          "destination_investigations", "investigations", "updated_by", "destination_expel_alerts", "vendor_alerts"]


class CpeImages(ResourceInstance):
    '''
    .. _api cpe_images:

    CPE Images

    Resource type name is **cpe_images**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'hash_md5': 'string',
            'hash_sha1': 'string',
            'hash_sha256': 'string',
            'platform': 'VMWARE',
            'release_date': '2019-01-15T15:35:00-05:00',
            'size': 100,
            'updated_at': '2019-01-15T15:35:00-05:00',
            'version': 'string'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Field Description                                                 | Field Name       | Field Type          | Attribute     | Relationship     |
        +===================================================================+==================+=====================+===============+==================+
        | Platform Restricted to: "VMWARE", "HYPERV", "AZURE", "AMAZON"     | platform         | any                 | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | CPE image image release date Allows: null                         | release_date     | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | CPE image image version Allows: "", null                          | version          | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | CPE image image sh1 hash Allows: null                             | hash_sha1        | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | CPE image image size Allows: null                                 | size             | number              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                  | updated_at       | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Created timestamp: readonly                                       | created_at       | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | CPE image image sha256 hash Allows: null                          | hash_sha256      | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | CPE image image md5 hash Allows: null                             | hash_md5         | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | created_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | updated_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+

    '''
    _api_type = 'cpe_images'
    _def_attributes = ["platform", "release_date", "version", "hash_sha1",
                       "size", "updated_at", "created_at", "hash_sha256", "hash_md5"]
    _def_relationships = ["created_by", "updated_by"]


class InvestigativeActionDataFileListing(ResourceInstance):
    '''
    .. _api investigative_action_data_file_listing:

    Investigative action data for file_listing

    Resource type name is **investigative_action_data_file_listing**.

    Example JSON record:

    .. code-block:: javascript

        {           'accessed': 'string',
            'changed': 'string',
            'created': 'string',
            'file_attributes': 'string',
            'file_md5': 'string',
            'file_owner': 'string',
            'file_sha256': 'string',
            'file_size': 100,
            'filename': 'string',
            'full_path': 'string',
            'is_signed': True,
            'modified': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null              | file_size                | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | accessed                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_md5                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | full_path                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | changed                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | filename                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_attributes          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | created                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | is_signed                | boolean                           | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | modified                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_sha256              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_owner               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_file_listing'
    _def_attributes = ["file_size", "accessed", "file_md5", "full_path", "changed", "filename",
                       "file_attributes", "created", "is_signed", "modified", "file_sha256", "file_owner"]
    _def_relationships = ["investigative_action"]


class PhishingSubmissionAttachments(ResourceInstance):
    '''
    .. _api phishing_submission_attachments:

    Phishing submission attachments

    Resource type name is **phishing_submission_attachments**.

    Example JSON record:

    .. code-block:: javascript

        {'file_md5': 'string', 'file_mime': 'string', 'file_name': 'string', 'file_sha256': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name              | Field Type                       | Attribute     | Relationship     |
        +==============================================+=========================+==================================+===============+==================+
        | File sha256 hash                             | file_sha256             | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File md5 hash                                | file_md5                | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File mime type                               | file_mime               | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File name                                    | file_name               | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by              | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File                                         | attachment_file         | :class:`Files`                   | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission     | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_attachments'
    _def_attributes = ["file_sha256", "file_md5", "file_mime", "file_name"]
    _def_relationships = ["created_by", "attachment_file", "phishing_submission"]


class CustomerEmMeta(ResourceInstance):
    '''
    .. _api customer_em_meta:

    Defines/retrieves expel.io customer_em_meta records

    Resource type name is **customer_em_meta**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'renewal_status': 'WONT_RENEW', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------+--------------------+------------------------+---------------+------------------+
        | Field Description                                                                                  | Field Name         | Field Type             | Attribute     | Relationship     |
        +====================================================================================================+====================+========================+===============+==================+
        | Renewal Status Restricted to: "WONT_RENEW", "AT_RISK", "WILL_RENEW", "WILL_REFER" Allows: null     | renewal_status     | any                    | Y             | N                |
        +----------------------------------------------------------------------------------------------------+--------------------+------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                        | created_at         | string                 | Y             | N                |
        +----------------------------------------------------------------------------------------------------+--------------------+------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                   | updated_at         | string                 | Y             | N                |
        +----------------------------------------------------------------------------------------------------+--------------------+------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                           | created_by         | :class:`Actors`        | N             | Y                |
        +----------------------------------------------------------------------------------------------------+--------------------+------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                           | updated_by         | :class:`Actors`        | N             | Y                |
        +----------------------------------------------------------------------------------------------------+--------------------+------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                        | customer           | :class:`Customers`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------+--------------------+------------------------+---------------+------------------+

    '''
    _api_type = 'customer_em_meta'
    _def_attributes = ["renewal_status", "created_at", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "customer"]


class InvestigationResilienceActions(ResourceInstance):
    '''
    .. _api investigation_resilience_actions:

    Investigation to resilience actions

    Resource type name is **investigation_resilience_actions**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                            | Field Name                         | Field Type                                 | Attribute     | Relationship     |
        +==============================================+====================================+============================================+===============+==================+
        | Created timestamp: readonly                  | created_at                         | string                                     | Y             | N                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at                         | string                                     | Y             | N                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                         | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                         | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions           | customer_resilience_action         | :class:`CustomerResilienceActions`         | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                               | investigation                      | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions           | organization_resilience_action     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_resilience_actions'
    _def_attributes = ["created_at", "updated_at"]
    _def_relationships = ["updated_by", "created_by", "customer_resilience_action",
                          "investigation", "organization_resilience_action"]


class UserAccountRoles(ResourceInstance):
    '''
    .. _api user_account_roles:

    Defines/retrieves expel.io user_account_role records

    Resource type name is **user_account_roles**.

    Example JSON record:

    .. code-block:: javascript

        {'active': True, 'assignable': True, 'created_at': '2019-01-15T15:35:00-05:00', 'role': 'expel_admin', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                                                                            | Field Name       | Field Type                 | Attribute     | Relationship     |
        +==============================================================================================================================================================================+==================+============================+===============+==================+
        | Can user be assigned items (e.g. investigations, etc)                                                                                                                        | assignable       | boolean                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | User account role for this organization Restricted to: "expel_admin", "expel_analyst", "organization_admin", "organization_analyst", "system", "anonymous", "restricted"     | role             | any                        | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                             | updated_at       | string                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | If this role is active                                                                                                                                                       | active           | boolean                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                  | created_at       | string                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                     | created_by       | :class:`Actors`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                     | updated_by       | :class:`Actors`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                              | organization     | :class:`Organizations`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | User accounts                                                                                                                                                                | user_account     | :class:`UserAccounts`      | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'user_account_roles'
    _def_attributes = ["assignable", "role", "updated_at", "active", "created_at"]
    _def_relationships = ["created_by", "updated_by", "organization", "user_account"]


class Configurations(ResourceInstance):
    '''
    .. _api configurations:

    Defines/retrieves expel.io configuration records

    Resource type name is **configurations**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'default_value': 'object',
            'description': 'string',
            'is_override': True,
            'key': 'string',
            'metadata': {},
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'validation': {},
            'value': 'object',
            'visibility': 'EXPEL',
            'write_permission_level': 'EXPEL'}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Field Description                                                              | Field Name                 | Field Type                         | Attribute     | Relationship     |
        +================================================================================+============================+====================================+===============+==================+
        | Last Updated timestamp: readonly                                               | updated_at                 | string                             | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration value is an override: readonly                                   | is_override                | boolean                            | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Description of configuration value Allows: "", null: readonly                  | description                | string                             | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Title of configuration value Allows: "", null: readonly                        | title                      | string                             | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration value Allows: null: no-sort                                      | value                      | any                                | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration metadata Allows: null: readonly, no-sort                         | metadata                   | object                             | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration value validation Allows: null: readonly, no-sort                 | validation                 | object                             | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Write permission required Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"     | write_permission_level     | any                                | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                    | created_at                 | string                             | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration visibility Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"      | visibility                 | any                                | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Default configuration value Allows: null: readonly, no-sort                    | default_value              | any                                | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration key: readonly                                                    | key                        | string                             | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                | organization               | :class:`Organizations`             | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | created_by                 | :class:`Actors`                    | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | updated_by                 | :class:`Actors`                    | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                    | customer                   | :class:`Customers`                 | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Configuration defaults                                                         | configuration_default      | :class:`ConfigurationDefaults`     | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'configurations'
    _def_attributes = ["updated_at", "is_override", "description", "title", "value", "metadata",
                       "validation", "write_permission_level", "created_at", "visibility", "default_value", "key"]
    _def_relationships = ["organization", "created_by", "updated_by", "customer", "configuration_default"]


class ResilienceActionInvestigationProperties(ResourceInstance):
    '''
    .. _api resilience_action_investigation_properties:

    Defines/retrieves expel.io resilience_action_investigation_property records

    Resource type name is **resilience_action_investigation_properties**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'enum_type': 'string', 'enum_value': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+
        | Field Description                            | Field Name            | Field Type                     | Attribute     | Relationship     |
        +==============================================+=======================+================================+===============+==================+
        | Created timestamp: readonly                  | created_at            | string                         | Y             | N                |
        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at            | string                         | Y             | N                |
        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+
        | Investigation property value                 | enum_value            | string                         | Y             | N                |
        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+
        | Investigation property type                  | enum_type             | string                         | Y             | N                |
        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by            | :class:`Actors`                | N             | Y                |
        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by            | :class:`Actors`                | N             | Y                |
        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+
        | Resilience actions                           | resilience_action     | :class:`ResilienceActions`     | N             | Y                |
        +----------------------------------------------+-----------------------+--------------------------------+---------------+------------------+

    '''
    _api_type = 'resilience_action_investigation_properties'
    _def_attributes = ["created_at", "updated_at", "enum_value", "enum_type"]
    _def_relationships = ["created_by", "updated_by", "resilience_action"]


class InvestigativeActionDataQueryHost(ResourceInstance):
    '''
    .. _api investigative_action_data_query_host:

    Investigative action data for query_host

    Resource type name is **investigative_action_data_query_host**.

    Example JSON record:

    .. code-block:: javascript

        {           'application': 'string',
            'dst': 'string',
            'dst_port': 100,
            'dst_processes': 'string',
            'event_description': 'string',
            'evidence_type': 'string',
            'file_events': 'string',
            'file_hash': 'string',
            'file_path': 'string',
            'network_events': 'string',
            'process_args': 'string',
            'process_name': 'string',
            'process_pid': 100,
            'protocol': 'string',
            'registry_events': 'string',
            'registry_path': 'string',
            'sensor': 'string',
            'src': 'string',
            'started_at': 'string',
            'summary': 'string',
            'unsigned_modules': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | dst                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | summary                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | protocol                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | evidence_type            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_args             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | network_events           | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_path                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_events              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | unsigned_modules         | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registry_path            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | registry_events          | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | process_pid              | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | file_hash                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | process_name             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | application              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | dst_processes            | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | sensor                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | event_description        | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src                      | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | dst_port                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_host'
    _def_attributes = ["dst", "summary", "protocol", "evidence_type", "process_args", "network_events", "file_path", "started_at", "file_events", "unsigned_modules",
                       "registry_path", "registry_events", "process_pid", "file_hash", "process_name", "application", "dst_processes", "sensor", "event_description", "src", "dst_port"]
    _def_relationships = ["investigative_action"]


class ExpelAlertGridV2(ResourceInstance):
    '''
    .. _api expel_alert_grid_v2:

    Elastic search backed Alert Grid

    Resource type name is **expel_alert_grid_v2**.

    Example JSON record:

    .. code-block:: javascript

        {           'activity_first_at': '2019-01-15T15:35:00-05:00',
            'activity_last_at': '2019-01-15T15:35:00-05:00',
            'alert_at': '2019-01-15T15:35:00-05:00',
            'alert_type': ['string', ['string', 'string']],
            'assignee_name': ['string', ['string', 'string']],
            'close_comment': ['string', ['string', 'string']],
            'destination_ip_addresses': ['string', ['string', 'string']],
            'expel_guid': ['string', ['string', 'string']],
            'expel_message': ['string', ['string', 'string']],
            'expel_name': ['string', ['string', 'string']],
            'expel_severity': ['string', ['string', 'string']],
            'hostnames': ['string', ['string', 'string']],
            'organization_name': ['string', ['string', 'string']],
            'parent_arguments': ['string', ['string', 'string']],
            'parent_md5': ['string', ['string', 'string']],
            'parent_path': ['string', ['string', 'string']],
            'process_arguments': ['string', ['string', 'string']],
            'process_md5': ['string', ['string', 'string']],
            'process_path': ['string', ['string', 'string']],
            'source_ip_addresses': ['string', ['string', 'string']],
            'status': ['string', ['string', 'string']],
            'tuning_requested': True,
            'updated_at': '2019-01-15T15:35:00-05:00',
            'urls': ['string', ['string', 'string']],
            'usernames': ['string', ['string', 'string']],
            'vendor_alert_count': 100,
            'vendor_device_guid': ['string', ['string', 'string']],
            'vendor_name': ['string', ['string', 'string']],
            'vendor_sig_name': ['string', ['string', 'string']]}


    Below are valid filter by parameters:

        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Field Description                                                | Field Name                   | Field Type                   | Attribute     | Relationship     |
        +==================================================================+==============================+==============================+===============+==================+
        | May be a string or an array of strings: allowStringOperators     | parent_arguments             | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Allows: null                                                     | vendor_alert_count           | number                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | urls                         | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | updated_at                   | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | vendor_name                  | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | activity_last_at             | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | alert_at                     | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | status                       | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | process_arguments            | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Allows: null                                                     | tuning_requested             | boolean                      | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | process_path                 | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_guid                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | process_md5                  | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | parent_path                  | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | vendor_device_guid           | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_severity               | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | alert_type                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | usernames                    | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a date or an ISO 8601 date: allowStringOperators          | activity_first_at            | string                       | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_name                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | parent_md5                   | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | vendor_sig_name              | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | destination_ip_addresses     | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | assignee_name                | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | source_ip_addresses          | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | organization_name            | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | close_comment                | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | hostnames                    | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | May be a string or an array of strings: allowStringOperators     | expel_message                | alternatives                 | Y             | N                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                         | assigned_to_org              | :class:`Actors`              | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Investigations                                                   | investigation                | :class:`Investigations`      | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Vendors                                                          | vendor                       | :class:`Vendors`             | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Security devices                                                 | security_devices             | :class:`SecurityDevices`     | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                                    | vendor_alerts                | :class:`VendorAlerts`        | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Expel alerts                                                     | expel_alert                  | :class:`ExpelAlerts`         | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                  | organization                 | :class:`Organizations`       | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                         | assigned_to_actor            | :class:`Actors`              | N             | Y                |
        +------------------------------------------------------------------+------------------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_grid_v2'
    _def_attributes = ["parent_arguments", "vendor_alert_count", "urls", "updated_at", "vendor_name", "activity_last_at", "alert_at", "status", "process_arguments", "tuning_requested", "process_path", "expel_guid", "process_md5", "parent_path", "vendor_device_guid",
                       "expel_severity", "alert_type", "usernames", "activity_first_at", "expel_name", "parent_md5", "vendor_sig_name", "destination_ip_addresses", "assignee_name", "source_ip_addresses", "organization_name", "close_comment", "hostnames", "expel_message"]
    _def_relationships = ["assigned_to_org", "investigation", "vendor", "security_devices",
                          "vendor_alerts", "expel_alert", "organization", "assigned_to_actor"]


class CustomerResilienceActionGroups(ResourceInstance):
    '''
    .. _api customer_resilience_action_groups:

    Defines/retrieves expel.io customer_resilience_action_group records

    Resource type name is **customer_resilience_action_groups**.

    Example JSON record:

    .. code-block:: javascript

        {'category': 'DISRUPT_ATTACKERS', 'created_at': '2019-01-15T15:35:00-05:00', 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00', 'visible': True}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Field Description                                                                                 | Field Name                         | Field Type                             | Attribute     | Relationship     |
        +===================================================================================================+====================================+========================================+===============+==================+
        | Created timestamp: readonly                                                                       | created_at                         | string                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                  | updated_at                         | string                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Group title                                                                                       | title                              | string                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Visible                                                                                           | visible                            | boolean                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Organization Resilience Group Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS"     | category                           | any                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_group records                                        | source_resilience_action_group     | :class:`ResilienceActionGroups`        | N             | Y                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | created_by                         | :class:`Actors`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                | customer_resilience_actions        | :class:`CustomerResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | updated_by                         | :class:`Actors`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                       | customer                           | :class:`Customers`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+------------------------------------+----------------------------------------+---------------+------------------+

    '''
    _api_type = 'customer_resilience_action_groups'
    _def_attributes = ["created_at", "updated_at", "title", "visible", "category"]
    _def_relationships = ["source_resilience_action_group", "created_by",
                          "customer_resilience_actions", "updated_by", "customer"]


class Features(ResourceInstance):
    '''
    .. _api features:

    Product features

    Resource type name is **features**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'name': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name        | Field Type                 | Attribute     | Relationship     |
        +=====================================================+===================+============================+===============+==================+
        | Created timestamp: readonly                         | created_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | name              | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Products                                            | products          | :class:`Products`          | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records         | customers         | :class:`Customers`         | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organizations     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'features'
    _def_attributes = ["created_at", "name", "updated_at"]
    _def_relationships = ["updated_by", "created_by", "products", "customers", "organizations"]


class ContextLabelActions(ResourceInstance):
    '''
    .. _api context_label_actions:

    Defines/retrieves expel.io context_label_action records

    Resource type name is **context_label_actions**.

    Example JSON record:

    .. code-block:: javascript

        {'action_type': 'ALERT_ON', 'created_at': '2019-01-15T15:35:00-05:00', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Field Description                                                       | Field Name           | Field Type                   | Attribute     | Relationship     |
        +=========================================================================+======================+==============================+===============+==================+
        | What action to take Restricted to: "ALERT_ON", "ADD_TO", "SUPPRESS"     | action_type          | any                          | Y             | N                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                        | updated_at           | string                       | Y             | N                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Created timestamp: readonly                                             | created_at           | string                       | Y             | N                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                | created_by           | :class:`Actors`              | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                | updated_by           | :class:`Actors`              | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Investigations                                                          | investigation        | :class:`Investigations`      | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                        | context_label        | :class:`ContextLabels`       | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Timeline Entries                                                        | timeline_entries     | :class:`TimelineEntries`     | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_actions'
    _def_attributes = ["action_type", "updated_at", "created_at"]
    _def_relationships = ["created_by", "updated_by", "investigation", "context_label", "timeline_entries"]


class AssemblerImages(ResourceInstance):
    '''
    .. _api assembler_images:

    Assembler Images

    Resource type name is **assembler_images**.

    Example JSON record:

    .. code-block:: javascript

        {           'created_at': '2019-01-15T15:35:00-05:00',
            'hash_md5': 'string',
            'hash_sha1': 'string',
            'hash_sha256': 'string',
            'platform': 'VMWARE',
            'release_date': '2019-01-15T15:35:00-05:00',
            'size': 100,
            'updated_at': '2019-01-15T15:35:00-05:00',
            'version': 'string'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Field Description                                                 | Field Name       | Field Type          | Attribute     | Relationship     |
        +===================================================================+==================+=====================+===============+==================+
        | Platform Restricted to: "VMWARE", "HYPERV", "AZURE", "AMAZON"     | platform         | any                 | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image release date Allows: null                         | release_date     | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image version Allows: "", null                          | version          | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image sh1 hash Allows: null                             | hash_sha1        | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image size Allows: null                                 | size             | number              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                  | updated_at       | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Created timestamp: readonly                                       | created_at       | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image sha256 hash Allows: null                          | hash_sha256      | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image md5 hash Allows: null                             | hash_md5         | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | created_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | updated_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+

    '''
    _api_type = 'assembler_images'
    _def_attributes = ["platform", "release_date", "version", "hash_sha1",
                       "size", "updated_at", "created_at", "hash_sha256", "hash_md5"]
    _def_relationships = ["created_by", "updated_by"]


class ExpelAlerts(ResourceInstance):
    '''
    .. _api expel_alerts:

    Expel alerts

    Resource type name is **expel_alerts**.

    Example JSON record:

    .. code-block:: javascript

        {           'activity_first_at': '2019-01-15T15:35:00-05:00',
            'activity_last_at': '2019-01-15T15:35:00-05:00',
            'alert_type': 'ENDPOINT',
            'close_comment': 'string',
            'close_reason': 'FALSE_POSITIVE',
            'created_at': '2019-01-15T15:35:00-05:00',
            'cust_disp_alerts_in_critical_incidents_count': 100,
            'cust_disp_alerts_in_incidents_count': 100,
            'cust_disp_alerts_in_investigations_count': 100,
            'cust_disp_closed_alerts_count': 100,
            'cust_disp_disposed_alerts_count': 100,
            'disposition_alerts_in_critical_incidents_count': 100,
            'disposition_alerts_in_incidents_count': 100,
            'disposition_alerts_in_investigations_count': 100,
            'disposition_closed_alerts_count': 100,
            'disposition_disposed_alerts_count': 100,
            'expel_alert_time': '2019-01-15T15:35:00-05:00',
            'expel_alias_name': 'string',
            'expel_message': 'string',
            'expel_name': 'string',
            'expel_severity': 'CRITICAL',
            'expel_signature_id': 'string',
            'expel_version': 'string',
            'git_rule_url': 'https://company.com/',
            'ref_event_id': 'string',
            'status': 'string',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'tuning_requested': True,
            'updated_at': '2019-01-15T15:35:00-05:00',
            'vendor_alert_count': 100}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                   | Field Name                                         | Field Type                                | Attribute     | Relationship     |
        +=====================================================================================================================================================================================================================================+====================================================+===========================================+===============+==================+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_alerts_in_investigations_count           | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort                                                                                                                                                                                                     | vendor_alert_count                                 | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                    | updated_at                                         | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert alias Allows: "", null                                                                                                                                                                                                  | expel_alias_name                                   | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort                                                                                                                                                                                                     | activity_last_at                                   | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert close reason Restricted to: "FALSE_POSITIVE", "TRUE_POSITIVE", "OTHER", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "TESTING", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "INCONCLUSIVE" Allows: null     | close_reason                                       | any                                       | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert signature Allows: "", null                                                                                                                                                                                              | expel_signature_id                                 | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_alerts_in_critical_incidents_count       | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Referring event id Allows: null                                                                                                                                                                                                     | ref_event_id                                       | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | tuning requested                                                                                                                                                                                                                    | tuning_requested                                   | boolean                                   | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel Alert Time first seen time: immutable                                                                                                                                                                                         | expel_alert_time                                   | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                         | created_at                                         | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_alerts_in_incidents_count              | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_closed_alerts_count                      | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "TESTING", "TUNING" Allows: null                                                                                                                           | expel_severity                                     | any                                       | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert type Restricted to: "ENDPOINT", "NETWORK", "SIEM", "RULE_ENGINE", "EXTERNAL", "OTHER", "CLOUD", "PHISHING_SUBMISSION", "PHISHING_SUBMISSION_SIMILAR" Allows: null                                                       | alert_type                                         | any                                       | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort                                                                                                                                                                                                     | activity_first_at                                  | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                            | status_updated_at                                  | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_alerts_in_critical_incidents_count     | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | URL to rule definition for alert Allows: "", null                                                                                                                                                                                   | git_rule_url                                       | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert name Allows: "", null                                                                                                                                                                                                   | expel_name                                         | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_alerts_in_incidents_count                | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert status Restricted to: "OPEN", "IN_PROGRESS", "CLOSED" Allows: null                                                                                                                                                      | status                                             | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_alerts_in_investigations_count         | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_disposed_alerts_count                    | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert version Allows: "", null                                                                                                                                                                                                | expel_version                                      | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_disposed_alerts_count                  | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert close comment Allows: "", null                                                                                                                                                                                          | close_comment                                      | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_closed_alerts_count                    | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert message Allows: "", null                                                                                                                                                                                                | expel_message                                      | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                                                                                                                                         | evidence                                           | :class:`VendorAlertEvidences`             | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | created_by                                         | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                                                                      | investigative_action_histories                     | :class:`InvestigativeActionHistories`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                      | investigation                                      | :class:`Investigations`                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                        | source_ip_addresses                                | :class:`IpAddresses`                      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                      | related_investigations_via_involved_host_ips       | :class:`Investigations`                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                       | vendor_alerts                                      | :class:`VendorAlerts`                     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | updated_by                                         | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                     | organization                                       | :class:`Organizations`                    | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | assigned_to_actor                                  | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Phishing submissions                                                                                                                                                                                                                | phishing_submissions                               | :class:`PhishingSubmissions`              | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | status_last_updated_by                             | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                        | destination_ip_addresses                           | :class:`IpAddresses`                      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendors                                                                                                                                                                                                                             | vendor                                             | :class:`Vendors`                          | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                                                                                                                                               | expel_alert_histories                              | :class:`ExpelAlertHistories`              | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                               | investigative_actions                              | :class:`InvestigativeActions`             | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                        | similar_alerts                                     | :class:`ExpelAlerts`                      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                      | related_investigations                             | :class:`Investigations`                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                       | coincident_vendor_alerts                           | :class:`VendorAlerts`                     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                                                                                                         | customer                                           | :class:`Customers`                        | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                    | context_labels                                     | :class:`ContextLabels`                    | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alerts'
    _def_attributes = ["cust_disp_alerts_in_investigations_count", "vendor_alert_count", "updated_at", "expel_alias_name", "activity_last_at", "close_reason", "expel_signature_id", "cust_disp_alerts_in_critical_incidents_count", "ref_event_id", "tuning_requested", "expel_alert_time", "created_at", "disposition_alerts_in_incidents_count", "cust_disp_closed_alerts_count", "expel_severity",
                       "alert_type", "activity_first_at", "status_updated_at", "disposition_alerts_in_critical_incidents_count", "git_rule_url", "expel_name", "cust_disp_alerts_in_incidents_count", "status", "disposition_alerts_in_investigations_count", "cust_disp_disposed_alerts_count", "expel_version", "disposition_disposed_alerts_count", "close_comment", "disposition_closed_alerts_count", "expel_message"]
    _def_relationships = ["evidence", "created_by", "investigative_action_histories", "investigation", "source_ip_addresses", "related_investigations_via_involved_host_ips", "vendor_alerts", "updated_by", "organization", "assigned_to_actor",
                          "phishing_submissions", "status_last_updated_by", "destination_ip_addresses", "vendor", "expel_alert_histories", "investigative_actions", "similar_alerts", "related_investigations", "coincident_vendor_alerts", "customer", "context_labels"]


class CustomerList(ResourceInstance):
    '''
    .. _api customer_list:

    Retrieves expel.io organization records for the organization view

    Resource type name is **customer_list**.

    Example JSON record:

    .. code-block:: javascript

        {           'engagement_manager_name': 'string',
            'industry': 'string',
            'investigative_actions_assigned_to_customer': 100,
            'investigative_actions_assigned_to_expel': 100,
            'name': 'string',
            'nodes_count': 100,
            'open_incident_count': 100,
            'open_investigation_count': 100,
            'remediation_actions_assigned_to_customer': 100,
            'resilience_actions_assigned': 100,
            'resilience_actions_completed': 100,
            'resilience_actions_ratio': 100,
            'service_renewal_at': '2019-01-15T15:35:00-05:00',
            'service_start_at': '2019-01-15T15:35:00-05:00',
            'short_name': 'string',
            'tech_stack': 'string',
            'users_count': 100,
            'vendor_device_health': 'string'}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Field Description                                                                                                     | Field Name                                     | Field Type                | Attribute     | Relationship     |
        +=======================================================================================================================+================================================+===========================+===============+==================+
        | Number of investigative actions assigned to the organization, or any of that organization's analysts Allows: null     | investigative_actions_assigned_to_customer     | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of investigative actions assigned to Expel, or any Expel analyst Allows: null                                  | investigative_actions_assigned_to_expel        | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of remediation actions assigned to the organization, or any of that organization's analysts Allows: null       | remediation_actions_assigned_to_customer       | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | The organization's operating name Allows: "", null                                                                    | name                                           | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Engagement manager name Allows: "", null                                                                              | engagement_manager_name                        | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Overall security device health Allows: "", null                                                                       | vendor_device_health                           | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | The organization's primary industry Allows: "", null                                                                  | industry                                       | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of open investigations Allows: null                                                                            | open_investigation_count                       | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Comma delimited list of organization's vendors Allows: "", null                                                       | tech_stack                                     | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Organization service start date Allows: null                                                                          | service_start_at                               | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Percent of resilience actions completed Allows: null                                                                  | resilience_actions_ratio                       | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of open incidents Allows: null                                                                                 | open_incident_count                            | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of resilience actions assigned to the organization Allows: null                                                | resilience_actions_assigned                    | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of users covered for this organization Allows: null                                                            | users_count                                    | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of resilience actions completed by the organization Allows: null                                               | resilience_actions_completed                   | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Organization service renewal date Allows: null                                                                        | service_renewal_at                             | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Organization short name Allows: null                                                                                  | short_name                                     | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Number of nodes covered for this organization Allows: null                                                            | nodes_count                                    | number                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Products                                                                                                              | products                                       | :class:`Products`         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                           | customer                                       | :class:`Customers`        | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+
        | User accounts                                                                                                         | expel_user                                     | :class:`UserAccounts`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+------------------------------------------------+---------------------------+---------------+------------------+

    '''
    _api_type = 'customer_list'
    _def_attributes = ["investigative_actions_assigned_to_customer", "investigative_actions_assigned_to_expel", "remediation_actions_assigned_to_customer", "name", "engagement_manager_name", "vendor_device_health", "industry",
                       "open_investigation_count", "tech_stack", "service_start_at", "resilience_actions_ratio", "open_incident_count", "resilience_actions_assigned", "users_count", "resilience_actions_completed", "service_renewal_at", "short_name", "nodes_count"]
    _def_relationships = ["products", "customer", "expel_user"]


class InvestigativeActionDataTechniqueFailedApiRequests(ResourceInstance):
    '''
    .. _api investigative_action_data_technique_failed_api_requests:

    Investigative action data for technique_failed_api_requests

    Resource type name is **investigative_action_data_technique_failed_api_requests**.

    Example JSON record:

    .. code-block:: javascript

        {'details': 'string', 'event_name': 'string', 'last_seen': 'string', 'principal_id': 'string', 'user_arn': 'string', 'user_name': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | user_name                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | last_seen                | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | details                  | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | event_name               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | principal_id             | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | user_arn                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_technique_failed_api_requests'
    _def_attributes = ["user_name", "last_seen", "details", "event_name", "principal_id", "user_arn"]
    _def_relationships = ["investigative_action"]


class OrganizationResilienceActions(ResourceInstance):
    '''
    .. _api organization_resilience_actions:

    Organization to resilience actions

    Resource type name is **organization_resilience_actions**.

    Example JSON record:

    .. code-block:: javascript

        {           'category': 'DISRUPT_ATTACKERS',
            'comment': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'details': 'string',
            'impact': 'LOW',
            'status': 'TOP_PRIORITY',
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'visible': True}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Field Description                                                                | Field Name                               | Field Type                                      | Attribute     | Relationship     |
        +==================================================================================+==========================================+=================================================+===============+==================+
        | Comment Allows: "", null                                                         | comment                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Status Restricted to: "TOP_PRIORITY", "IN_PROGRESS", "WONT_DO", "COMPLETED"      | status                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Details                                                                          | details                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null     | category                                 | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                      | created_at                               | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                 | updated_at                               | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Title                                                                            | title                                    | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Visible                                                                          | visible                                  | boolean                                         | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH"                                    | impact                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                   | investigation_hints                      | :class:`Investigations`                         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | created_by                               | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigation to resilience actions                                              | investigation_resilience_actions         | :class:`InvestigationResilienceActions`         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Resilience actions                                                               | source_resilience_action                 | :class:`ResilienceActions`                      | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                   | investigations                           | :class:`Investigations`                         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | updated_by                               | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_resilience_action_group records          | organization_resilience_action_group     | :class:`OrganizationResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                  | organization                             | :class:`Organizations`                          | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | assigned_to_actor                        | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organization_resilience_actions'
    _def_attributes = ["comment", "status", "details", "category",
                       "created_at", "updated_at", "title", "visible", "impact"]
    _def_relationships = ["investigation_hints", "created_by", "investigation_resilience_actions", "source_resilience_action",
                          "investigations", "updated_by", "organization_resilience_action_group", "organization", "assigned_to_actor"]


class Vendors(ResourceInstance):
    '''
    .. _api vendors:

    Vendors

    Resource type name is **vendors**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'icon': 'string', 'name': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Field Description                            | Field Name           | Field Type                   | Attribute     | Relationship     |
        +==============================================+======================+==============================+===============+==================+
        | Created timestamp: readonly                  | created_at           | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Name Allows: "", null                        | name                 | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Icon Allows: "", null                        | icon                 | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at           | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Expel alerts                                 | expel_alerts         | :class:`ExpelAlerts`         | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by           | :class:`Actors`              | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Vendor devices                               | vendor_devices       | :class:`VendorDevices`       | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Security devices                             | security_devices     | :class:`SecurityDevices`     | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by           | :class:`Actors`              | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                | vendor_alerts        | :class:`VendorAlerts`        | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'vendors'
    _def_attributes = ["created_at", "name", "icon", "updated_at"]
    _def_relationships = ["expel_alerts", "created_by", "vendor_devices",
                          "security_devices", "updated_by", "vendor_alerts"]


class RemediationActionAssetHistories(ResourceInstance):
    '''
    .. _api remediation_action_asset_histories:

    Remediation action asset histories

    Resource type name is **remediation_action_asset_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Field Name                   | Field Type                           | Attribute     | Relationship     |
        +==============================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+==============================+======================================+===============+==================+
        | Remediation action asset history details Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | value                        | object                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Action type of associated parent remediation action Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type                  | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action asset history action Restricted to: "CREATED", "COMPLETED", "REOPENED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | action                       | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | created_at                   | string                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | created_by                   | :class:`Actors`                      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | investigation                | :class:`Investigations`              | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action assets                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | remediation_action_asset     | :class:`RemediationActionAssets`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_asset_histories'
    _def_attributes = ["value", "action_type", "action", "created_at"]
    _def_relationships = ["created_by", "investigation", "remediation_action_asset"]


class ExpelAlertHistories(ResourceInstance):
    '''
    .. _api expel_alert_histories:

    Expel alert histories

    Resource type name is **expel_alert_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Field Description                                                                                                                                | Field Name            | Field Type                  | Attribute     | Relationship     |
        +==================================================================================================================================================+=======================+=============================+===============+==================+
        | Created timestamp: readonly                                                                                                                      | created_at            | string                      | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Expel alert history action Restricted to: "CREATED", "ASSIGNED", "STATUS_CHANGED", "INVESTIGATING", "TUNING_CHANGED", "DELETED" Allows: null     | action                | any                         | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Expel alert history details Allows: null: no-sort                                                                                                | value                 | object                      | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                         | created_by            | :class:`Actors`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigations                                                                                                                                   | investigation         | :class:`Investigations`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                  | organization          | :class:`Organizations`      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                     | expel_alert           | :class:`ExpelAlerts`        | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io customer records                                                                                                      | customer              | :class:`Customers`          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                         | assigned_to_actor     | :class:`Actors`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_histories'
    _def_attributes = ["created_at", "action", "value"]
    _def_relationships = ["created_by", "investigation", "organization", "expel_alert", "customer", "assigned_to_actor"]


class InvestigativeActions(InvestigativeActionsResourceInstance):
    '''
    .. _api investigative_actions:

    investigative actions

    Resource type name is **investigative_actions**.

    Example JSON record:

    .. code-block:: javascript

        {           'action_type': 'TASKABILITY',
            'activity_authorized': True,
            'activity_verified_by': 'string',
            'capability_name': 'string',
            'close_reason': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'downgrade_reason': 'FALSE_POSITIVE',
            'files_count': 100,
            'input_args': {},
            'instructions': 'string',
            'reason': 'string',
            'result_byte_size': 100,
            'result_task_id': 'object',
            'results': 'string',
            'robot_action': True,
            'status': 'RUNNING',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'taskability_action_id': 'string',
            'tasking_error': {},
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'workflow_job_id': 'string',
            'workflow_name': 'string'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                               | Field Name                          | Field Type                                | Attribute     | Relationship     |
        +=================================================================================================================================================================================+=====================================+===========================================+===============+==================+
        | Verify Investigative action verified by Allows: null                                                                                                                            | activity_verified_by                | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                | updated_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative Action Type Restricted to: "TASKABILITY", "HUNTING", "MANUAL", "RESEARCH", "PIVOT", "QUICK_UPLOAD", "VERIFY", "DOWNGRADE", "WORKFLOW", "NOTIFY"                   | action_type                         | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Downgrade reason Restricted to: "FALSE_POSITIVE", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "OTHER" Allows: null     | downgrade_reason                    | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action created by robot action: readonly                                                                                                                          | robot_action                        | boolean                                   | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Results/Analysis Allows: "", null                                                                                                                                               | results                             | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Close Reason Allows: null                                                                                                                                                       | close_reason                        | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Restricted to: "RUNNING", "FAILED", "READY_FOR_ANALYSIS", "CLOSED", "COMPLETED"                                                                                          | status                              | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Task input arguments Allows: null: no-sort                                                                                                                                      | input_args                          | object                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Result byte size: readonly                                                                                                                                                      | result_byte_size                    | number                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                               | deleted_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Result task id Allows: null: readonly                                                                                                                                           | result_task_id                      | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                     | created_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Instructions Allows: "", null                                                                                                                                                   | instructions                        | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Workflow job id Allows: "", null                                                                                                                                                | workflow_job_id                     | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Taskability action id Allows: "", null                                                                                                                                          | taskability_action_id               | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                        | status_updated_at                   | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Verify Investigative action is authorized Allows: null                                                                                                                          | activity_authorized                 | boolean                                   | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Capability name Allows: "", null                                                                                                                                                | capability_name                     | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Title                                                                                                                                                                           | title                               | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Taskabilities error Allows: "", null: no-sort                                                                                                                                   | tasking_error                       | object                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Reason                                                                                                                                                                          | reason                              | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Downgrade reason: readonly                                                                                                                                                      | files_count                         | number                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Workflow name Allows: "", null                                                                                                                                                  | workflow_name                       | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                           | depends_on_investigative_action     | :class:`InvestigativeActions`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | created_by                          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                  | investigative_action_histories      | :class:`InvestigativeActionHistories`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                  | investigation                       | :class:`Investigations`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | updated_by                          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor devices                                                                                                                                                                  | vendor_device                       | :class:`VendorDevices`                    | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                    | expel_alert                         | :class:`ExpelAlerts`                      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | File                                                                                                                                                                            | files                               | :class:`Files`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | analysis_assigned_to_actor          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                           | dependent_investigative_actions     | :class:`InvestigativeActions`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | assigned_to_actor                   | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                | security_device                     | :class:`SecurityDevices`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_actions'
    _def_attributes = ["activity_verified_by", "updated_at", "action_type", "downgrade_reason", "robot_action", "results", "close_reason", "status", "input_args", "result_byte_size", "deleted_at", "result_task_id",
                       "created_at", "instructions", "workflow_job_id", "taskability_action_id", "status_updated_at", "activity_authorized", "capability_name", "title", "tasking_error", "reason", "files_count", "workflow_name"]
    _def_relationships = ["depends_on_investigative_action", "created_by", "investigative_action_histories", "investigation", "updated_by",
                          "vendor_device", "expel_alert", "files", "analysis_assigned_to_actor", "dependent_investigative_actions", "assigned_to_actor", "security_device"]


class Findings(ResourceInstance):
    '''
    .. _api findings:

    Defines/retrieves expel.io finding records

    Resource type name is **findings**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'rank': 100, 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Field Description                            | Field Name     | Field Type          | Attribute     | Relationship     |
        +==============================================+================+=====================+===============+==================+
        | Created timestamp: readonly                  | created_at     | string              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at     | string              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Seed Rank                                    | rank           | number              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Title Allows: "", null                       | title          | string              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by     | :class:`Actors`     | N             | Y                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by     | :class:`Actors`     | N             | Y                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+

    '''
    _api_type = 'findings'
    _def_attributes = ["created_at", "updated_at", "rank", "title"]
    _def_relationships = ["created_by", "updated_by"]


class SamlIdentityProviders(ResourceInstance):
    '''
    .. _api saml_identity_providers:

    SAML Identity Providers

    Resource type name is **saml_identity_providers**.

    Example JSON record:

    .. code-block:: javascript

        {'callback_uri': 'string', 'cert': 'string', 'entity_id': 'string', 'status': 'string'}


    Below are valid filter by parameters:

        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name       | Field Type                 | Attribute     | Relationship     |
        +=====================================================+==================+============================+===============+==================+
        | Allows: ""                                          | callback_uri     | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Restricted to: "not_configured", "configured"       | status           | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Allows: ""                                          | entity_id        | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Allows: "", null                                    | cert             | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'saml_identity_providers'
    _def_attributes = ["callback_uri", "status", "entity_id", "cert"]
    _def_relationships = ["organization"]


class Organizations(ResourceInstance):
    '''
    .. _api organizations:

    Defines/retrieves expel.io organization records

    Resource type name is **organizations**.

    Example JSON record:

    .. code-block:: javascript

        {           'address_1': 'string',
            'address_2': 'string',
            'city': 'string',
            'country_code': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'hq_city': 'string',
            'hq_utc_offset': 'string',
            'industry': 'string',
            'is_surge': True,
            'name': 'string',
            'nodes_count': 100,
            'o365_tenant_id': 'string',
            'o365_tos_id': 'string',
            'postal_code': 'string',
            'prospect': True,
            'region': 'string',
            'service_renewal_at': '2019-01-15T15:35:00-05:00',
            'service_start_at': '2019-01-15T15:35:00-05:00',
            'short_name': 'EXP',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'users_count': 100,
            'vault_token': 'string',
            'vault_token_expires': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Field Description                                                                                             | Field Name                                        | Field Type                                      | Attribute     | Relationship     |
        +===============================================================================================================+===================================================+=================================================+===============+==================+
        | State/Province/Region Allows: "", null                                                                        | region                                            | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Address 1 Allows: "", null                                                                                    | address_1                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                              | updated_at                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | o365 Microsoft tenant id Allows: null: private                                                                | o365_tenant_id                                    | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The organization's primary industry Allows: "", null                                                          | industry                                          | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Country Code Allows: null                                                                                     | country_code                                      | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization service start date Allows: null                                                                  | service_start_at                                  | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                             | deleted_at                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Number of users covered for this organization Allows: null                                                    | users_count                                       | number                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                   | created_at                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The city where the organization's headquarters is located Allows: "", null                                    | hq_city                                           | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | o365 Terms of Service identifier (e.g. hubspot id, etc.) Allows: null                                         | o365_tos_id                                       | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Postal Code Allows: null                                                                                      | postal_code                                       | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The organization's operating name                                                                             | name                                              | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | City Allows: "", null                                                                                         | city                                              | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Is surge                                                                                                      | is_surge                                          | boolean                                         | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Allows: "", null                                                                                              | hq_utc_offset                                     | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Allows: null: private                                                                                         | vault_token_expires                               | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Address 2 Allows: "", null                                                                                    | address_2                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Vault Token Allows: null: private                                                                             | vault_token                                       | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Is Prospective/Demo Organization: private                                                                     | prospect                                          | boolean                                         | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Number of nodes covered for this organization Allows: null                                                    | nodes_count                                       | number                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization short name Allows: null                                                                          | short_name                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization service renewal date Allows: null                                                                | service_renewal_at                                | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | created_by                                        | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Assemblers                                                                                                    | assemblers                                        | :class:`Assemblers`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io configuration records                                                              | configurations                                    | :class:`Configurations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | assignables                                       | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | investigations                                    | :class:`Investigations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | updated_by                                        | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | File                                                                                                          | files                                             | :class:`Files`                                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | organization_resilience_actions                   | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel users                                                                                                   | expel_users                                       | :class:`ExpelUsers`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io user_account_role records                                                          | organization_user_account_roles                   | :class:`UserAccountRoles`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | actor                                             | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | expel_alerts                                      | :class:`ExpelAlerts`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Product features                                                                                              | features                                          | :class:`Features`                               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_customer_resilience_actions              | :class:`CustomerResilienceActions`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                 | notification_preferences                          | :class:`NotificationPreferences`                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User accounts                                                                                                 | user_accounts                                     | :class:`UserAccounts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | assigned_investigative_actions                    | :class:`InvestigativeActions`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization devices                                                                                          | customer_devices                                  | :class:`CustomerDevices`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                              | context_labels                                    | :class:`ContextLabels`                          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | SAML Identity Providers                                                                                       | saml_identity_provider                            | :class:`SamlIdentityProviders`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_resilience_action_group records                                       | organization_resilience_action_groups             | :class:`OrganizationResilienceActionGroups`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Security devices                                                                                              | security_devices                                  | :class:`SecurityDevices`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_customer_resilience_actions_list         | :class:`CustomerResilienceActions`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io integration records                                                                | integrations                                      | :class:`Integrations`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                           | assigned_remediation_actions                      | :class:`RemediationActions`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io api_key records. These can only be created by a user and require an OTP token.     | api_keys                                          | :class:`ApiKeys`                                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User accounts                                                                                                 | user_accounts_with_roles                          | :class:`UserAccounts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigation histories                                                                                       | investigation_histories                           | :class:`InvestigationHistories`                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                                                                                | nist_subcategory_scores                           | :class:`NistSubcategoryScores`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | assigned_expel_alerts                             | :class:`ExpelAlerts`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                         | expel_alert_histories                             | :class:`ExpelAlertHistories`                    | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Vendor devices                                                                                                | vendor_devices                                    | :class:`VendorDevices`                          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Products                                                                                                      | products                                          | :class:`Products`                               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization status                                                                                           | organization_status                               | :class:`OrganizationStatuses`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | assigned_investigations                           | :class:`Investigations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                                                    | comments                                          | :class:`Comments`                               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io engagement_manager records                                                         | engagement_manager                                | :class:`EngagementManagers`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                                                          | context_label_tags                                | :class:`ContextLabelTags`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                 | vendor_alerts                                     | :class:`VendorAlerts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_em_meta records                                                       | organization_em_meta                              | :class:`OrganizationEmMeta`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organizations'
    _def_attributes = ["region", "address_1", "updated_at", "o365_tenant_id", "industry", "country_code", "service_start_at", "deleted_at", "users_count", "created_at", "hq_city",
                       "o365_tos_id", "postal_code", "name", "city", "is_surge", "hq_utc_offset", "vault_token_expires", "address_2", "vault_token", "prospect", "nodes_count", "short_name", "service_renewal_at"]
    _def_relationships = ["created_by", "assemblers", "configurations", "assignables", "investigations", "updated_by", "files", "organization_resilience_actions", "expel_users", "organization_user_account_roles", "actor", "expel_alerts", "assigned_organization_resilience_actions_list", "features", "assigned_customer_resilience_actions", "notification_preferences", "user_accounts", "assigned_investigative_actions", "customer_devices", "context_labels", "assigned_organization_resilience_actions", "saml_identity_provider",
                          "organization_resilience_action_groups", "security_devices", "assigned_customer_resilience_actions_list", "integrations", "assigned_remediation_actions", "api_keys", "user_accounts_with_roles", "investigation_histories", "nist_subcategory_scores", "assigned_expel_alerts", "expel_alert_histories", "vendor_devices", "products", "organization_status", "assigned_investigations", "comments", "engagement_manager", "context_label_tags", "vendor_alerts", "organization_em_meta", "analysis_assigned_investigative_actions"]


class OrganizationEmMeta(ResourceInstance):
    '''
    .. _api organization_em_meta:

    Defines/retrieves expel.io organization_em_meta records

    Resource type name is **organization_em_meta**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'renewal_status': 'WONT_RENEW', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------+--------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                  | Field Name         | Field Type                 | Attribute     | Relationship     |
        +====================================================================================================+====================+============================+===============+==================+
        | Renewal Status Restricted to: "WONT_RENEW", "AT_RISK", "WILL_RENEW", "WILL_REFER" Allows: null     | renewal_status     | any                        | Y             | N                |
        +----------------------------------------------------------------------------------------------------+--------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                        | created_at         | string                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------+--------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                   | updated_at         | string                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------+--------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                           | created_by         | :class:`Actors`            | N             | Y                |
        +----------------------------------------------------------------------------------------------------+--------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                           | updated_by         | :class:`Actors`            | N             | Y                |
        +----------------------------------------------------------------------------------------------------+--------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                    | organization       | :class:`Organizations`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------+--------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'organization_em_meta'
    _def_attributes = ["renewal_status", "created_at", "updated_at"]
    _def_relationships = ["created_by", "updated_by", "organization"]


class InvestigativeActionDataQueryNetflow(ResourceInstance):
    '''
    .. _api investigative_action_data_query_netflow:

    Investigative action data for query_netflow

    Resource type name is **investigative_action_data_query_netflow**.

    Example JSON record:

    .. code-block:: javascript

        {           'application': 'string',
            'bytes_rx': 100,
            'bytes_tx': 100,
            'dst_ip': 'string',
            'dst_port': 100,
            'ended_at': 'string',
            'packets_rx': 100,
            'packets_tx': 100,
            'protocol': 'string',
            'src_ip': 'string',
            'src_port': 100,
            'started_at': 'string'}


    Below are valid filter by parameters:

        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description         | Field Name               | Field Type                        | Attribute     | Relationship     |
        +===========================+==========================+===================================+===============+==================+
        | Allows: null, ""          | dst_ip                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | protocol                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | application              | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | bytes_rx                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | ended_at                 | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | started_at               | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | packets_rx               | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | bytes_tx                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | packets_tx               | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | src_port                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null              | dst_port                 | number                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Allows: null, ""          | src_ip                   | string                            | Y             | N                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions     | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_data_query_netflow'
    _def_attributes = ["dst_ip", "protocol", "application", "bytes_rx", "ended_at",
                       "started_at", "packets_rx", "bytes_tx", "packets_tx", "src_port", "dst_port", "src_ip"]
    _def_relationships = ["investigative_action"]

# END AUTO GENERATE JSONAPI CLASSES


RELATIONSHIP_TO_CLASS_EXT = {
}


# AUTO GENERATE RELATIONSHIP TO CLASS LOOKUP

RELATIONSHIP_TO_CLASS = {
    "nist_subcategories": NistSubcategories,
    "related_investigations_via_involved_host_ips": Investigations,
    "investigative_action_data_query_user": InvestigativeActionDataQueryUser,
    "investigations": Investigations,
    "primary_organization": Organizations,
    "customers": Customers,
    "remediation_action_histories": RemediationActionHistories,
    "remediation_action": RemediationActions,
    "secrets": Secrets,
    "context_label": ContextLabels,
    "user_account_statuses": UserAccountStatuses,
    "coincident_vendor_alerts": VendorAlerts,
    "configuration_default": ConfigurationDefaults,
    "saml_identity_provider": SamlIdentityProviders,
    "phishing_submissions": PhishingSubmissions,
    "timeline_entries": TimelineEntries,
    "destination_ip_addresses": IpAddresses,
    "expel_user": UserAccounts,
    "investigative_action_data_technique_scheduled_tasks": InvestigativeActionDataTechniqueScheduledTasks,
    "configuration_defaults": ConfigurationDefaults,
    "created_by": Actors,
    "investigation_resilience_action_hints": InvestigationResilienceActionHints,
    "analysis_assigned_to_actor": Actors,
    "expel_users": ExpelUsers,
    "remediation_action_asset_histories": RemediationActionAssetHistories,
    "expel_alert_thresholds": ExpelAlertThresholds,
    "investigative_action_data_process_listing": InvestigativeActionDataProcessListing,
    "customer_devices": CustomerDevices,
    "context_labels": ContextLabels,
    "assigned_organization_resilience_actions": OrganizationResilienceActions,
    "nist_subcategory": NistSubcategories,
    "organization_resilience_action_hints": OrganizationResilienceActions,
    "investigative_action_data_technique_successive_reconnaissance_commands": InvestigativeActionDataTechniqueSuccessiveReconnaissanceCommands,
    "phishing_submission_headers": PhishingSubmissionHeaders,
    "lead_expel_alert": ExpelAlerts,
    "ip_addresses": IpAddresses,
    "organization_resilience_action_list": OrganizationResilienceActionList,
    "evidenced_expel_alerts": ExpelAlerts,
    "resilience_action_groups": ResilienceActionGroups,
    "customer_resilience_action_group": CustomerResilienceActionGroups,
    "assigned_investigations": Investigations,
    "expel_alert_threshold_histories": ExpelAlertThresholdHistories,
    "status_last_updated_by": Actors,
    "phishing_submission_urls": PhishingSubmissionUrls,
    "investigative_action_data_technique_rdp_connection_anomalies": InvestigativeActionDataTechniqueRdpConnectionAnomalies,
    "nist_categories": NistCategories,
    "investigation_finding_histories": InvestigationFindingHistories,
    "depends_on_investigative_action": InvestigativeActions,
    "organization_user_account_roles": UserAccountRoles,
    "attachment_file": Files,
    "user_account_status": UserAccountStatuses,
    "parent_security_device": SecurityDevices,
    "security_devices": SecurityDevices,
    "notification_preferences": NotificationPreferences,
    "security_device": SecurityDevices,
    "user_accounts": UserAccounts,
    "evidence": VendorAlertEvidences,
    "investigative_action_data_query_ip": InvestigativeActionDataQueryIp,
    "user_account": UserAccounts,
    "configuration_labels": ConfigurationLabels,
    "investigative_action_data_query_logs": InvestigativeActionDataQueryLogs,
    "assigned_investigative_actions": InvestigativeActions,
    "comment": Comments,
    "organization_statuses": OrganizationStatuses,
    "investigative_action_data_file_listing": InvestigativeActionDataFileListing,
    "phishing_submission_attachments": PhishingSubmissionAttachments,
    "updated_by": Actors,
    "customer_em_meta": CustomerEmMeta,
    "investigation_finding": InvestigationFindings,
    "configurations": Configurations,
    "assignables": Actors,
    "evidences": VendorAlertEvidences,
    "investigative_action_data_query_host": InvestigativeActionDataQueryHost,
    "child_security_devices": SecurityDevices,
    "investigation_hints": Investigations,
    "expel_alert_grid_v2": ExpelAlertGridV2,
    "customer_resilience_action_groups": CustomerResilienceActionGroups,
    "labels": ConfigurationLabels,
    "context_label_actions": ContextLabelActions,
    "customer_list": CustomerList,
    "investigative_action_data_technique_failed_api_requests": InvestigativeActionDataTechniqueFailedApiRequests,
    "source_investigations": Investigations,
    "assigned_remediation_actions": RemediationActions,
    "vendors": Vendors,
    "resilience_action": ResilienceActions,
    "last_published_by": Actors,
    "actor": Actors,
    "vendor_devices": VendorDevices,
    "child_vendor_devices": VendorDevices,
    "parent_vendor_device": VendorDevices,
    "saml_identity_providers": SamlIdentityProviders,
    "customer_device": CustomerDevices,
    "user_account_roles": UserAccountRoles,
    "engagement_manager": EngagementManagers,
    "resilience_action_group": ResilienceActionGroups,
    "investigative_action_histories": InvestigativeActionHistories,
    "vendor": Vendors,
    "suppressed_by": ExpelAlertThresholds,
    "investigative_action_data_query_domain": InvestigativeActionDataQueryDomain,
    "nist_subcategory_score_histories": NistSubcategoryScoreHistories,
    "vendor_device": VendorDevices,
    "phishing_submission": PhishingSubmissions,
    "files": Files,
    "features": Features,
    "actors": Actors,
    "investigative_action_data_reg_listing": InvestigativeActionDataRegListing,
    "vendor_alert_evidences": VendorAlertEvidences,
    "customer": Customers,
    "initial_email_file": Files,
    "nist_subcategory_score": NistSubcategoryScores,
    "investigation_histories": InvestigationHistories,
    "assigned_customer_resilience_actions_list": CustomerResilienceActions,
    "destination_expel_alerts": ExpelAlerts,
    "assigned_to_actor": Actors,
    "expel_alert_grid": ExpelAlertGrid,
    "assigned_expel_alerts": ExpelAlerts,
    "add_to_actions": ContextLabelActions,
    "analysis_assigned_investigative_actions": InvestigativeActions,
    "remediation_action_assets": RemediationActionAssets,
    "context_label_tags": ContextLabelTags,
    "organization_list": OrganizationList,
    "remediation_actions": RemediationActions,
    "investigative_action_data_persistence_listing": InvestigativeActionDataPersistenceListing,
    "customer_resilience_actions": CustomerResilienceActions,
    "comment_histories": CommentHistories,
    "destination_investigations": Investigations,
    "investigative_action_data_technique_sinkhole_connections": InvestigativeActionDataTechniqueSinkholeConnections,
    "child_actors": Actors,
    "investigative_action": InvestigativeActions,
    "activity_metrics": ActivityMetrics,
    "customer_resilience_action_list": CustomerResilienceActionList,
    "raw_body_file": Files,
    "source_expel_alerts": ExpelAlerts,
    "investigative_action_data_list_sources": InvestigativeActionDataListSources,
    "investigative_action_data_query_file": InvestigativeActionDataQueryFile,
    "engagement_managers": EngagementManagers,
    "investigative_action_data_query_url": InvestigativeActionDataQueryUrl,
    "phishing_submission_attachment": PhishingSubmissionAttachments,
    "organization_resilience_action_groups": OrganizationResilienceActionGroups,
    "investigative_action_data_query_raw_logs": InvestigativeActionDataQueryRawLogs,
    "products": Products,
    "investigation_findings": InvestigationFindings,
    "assembler": Assemblers,
    "organization": Organizations,
    "source_resilience_action_group": ResilienceActionGroups,
    "nist_subcategory_scores": NistSubcategoryScores,
    "investigation_resilience_actions": InvestigationResilienceActions,
    "source_ip_addresses": IpAddresses,
    "review_requested_by": Actors,
    "comments": Comments,
    "assemblers": Assemblers,
    "investigative_action_data_query_cloudtrail": InvestigativeActionDataQueryCloudtrail,
    "investigative_action_data_technique_failed_c_2_connections": InvestigativeActionDataTechniqueFailedC2Connections,
    "phishing_submission_domains": PhishingSubmissionDomains,
    "resilience_action_investigation_properties": ResilienceActionInvestigationProperties,
    "similar_alerts": ExpelAlerts,
    "secret": Secrets,
    "api_keys": ApiKeys,
    "organization_resilience_action_group_actions": OrganizationResilienceActions,
    "resilience_actions": ResilienceActions,
    "assigned_customer_resilience_actions": CustomerResilienceActions,
    "organization_resilience_action": OrganizationResilienceActions,
    "assigned_to_org": Actors,
    "investigation": Investigations,
    "user_accounts_with_roles": UserAccounts,
    "findings": InvestigationFindings,
    "integrations": Integrations,
    "vendor_alert": VendorAlerts,
    "expel_alert": ExpelAlerts,
    "related_investigations": Investigations,
    "cpe_images": CpeImages,
    "suppress_actions": ContextLabelActions,
    "source_resilience_action": ResilienceActions,
    "remediation_action_asset": RemediationActionAssets,
    "vendor_alerts": VendorAlerts,
    "suppresses": ExpelAlertThresholds,
    "expel_alert_threshold": ExpelAlertThresholds,
    "alert_on_actions": ContextLabelActions,
    "analysis_email_file": Files,
    "assigned_organization_resilience_actions_list": OrganizationResilienceActions,
    "parent_actor": Actors,
    "assembler_images": AssemblerImages,
    "expel_alerts": ExpelAlerts,
    "organization_resilience_actions": OrganizationResilienceActions,
    "nist_category": NistCategories,
    "dependent_investigative_actions": InvestigativeActions,
    "expel_alert_histories": ExpelAlertHistories,
    "investigative_actions": InvestigativeActions,
    "organization_status": OrganizationStatuses,
    "customer_resilience_action": CustomerResilienceActions,
    "organization_resilience_action_group": OrganizationResilienceActionGroups,
    "organizations": Organizations,
    "organization_em_meta": OrganizationEmMeta,
    "investigative_action_data_query_netflow": InvestigativeActionDataQueryNetflow
}
# END AUTO GENERATE RELATIONSHIP TO CLASS LOOKUP


class WorkbenchCoreClient:
    '''
    Instantiate a Workbench core client that provides just authentication and request capabilities to Workbench

    If the developer specifies a ``username``, then ``password`` and ``mfa_code`` are required inputs. If the developer
    has an ``apikey`` then ``username``, ``password`` and ``mfa_code`` parameters are ignored.

    :param cls: A Workbench class reference.
    :type cls: WorkbenchClient
    :param apikey: An apikey to use for authentication/authorization.
    :type apikey: str or None
    :param username: The username
    :type username: str or None
    :param password: The username's password
    :type password: str or None
    :param mfa_code: The multi factor authenticate code generated by google authenticator.
    :type mfa_code: int or None
    :param token: The bearer token of an authorized session. Can be used instead of ``apikey`` and ``username``/``password`` combo.
    :type token: str or None
    :return: An initialized, and authorized Workbench client.
    :rtype: WorkbenchClient
    '''

    def __init__(self, base_url, apikey=None, username=None, password=None, mfa_code=None, token=None, retries=3, prompt_on_delete=True):
        self.base_url = base_url
        self.apikey = apikey
        self.token = token
        self.mfa_code = mfa_code
        self.username = username
        self.password = password
        self.retries = retries

        self.debug = False
        self.debug_method = []
        self.debug_url_contains = None
        # Undocumented parameter allows for turning off prompt on delete
        self.prompt_on_delete = prompt_on_delete

        self.default_request_kwargs = {
            'timeout': 300,
            'verify': False,
        }
        self.make_session()

    def make_session(self):
        '''
        Create a session with Workbench
        '''
        def _make_retry():
            retryable_status_codes = [429, 500, 503, 504]
            # Retry gives us some control over how retries are performed.
            # In particular, we're looking to backoff and retry on api rate limiting
            # See docs: https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html#urllib3.util.retry.Retry
            return Retry(connect=self.retries, read=self.retries, status=self.retries, status_forcelist=retryable_status_codes, backoff_factor=2)

        session = requests.Session()
        HTTPAdapter(max_retries=_make_retry())

        self.session = session
        self.session.headers = {'content-type': 'application/json'}

        if self.apikey:
            self.token = self.service_login(self.apikey)

        if self.mfa_code:
            self.token = self.login(self.username, self.password, self.mfa_code)

        # if not self.token:
        #    raise Exception('No authorization information provided!')

        if self.token and not self.token.startswith('Bearer'):
            self.token = 'Bearer %s' % self.token

        self.session.headers.update({'Authorization': self.token})

    def login(self, username, password, code):
        '''
        Authenticate as a human, this requires providing the 2FA code.

        :param username: The user's e-mail address.
        :type username: str
        :param password: The user's password.
        :type password: str
        :param code: The 2FA code
        :type code: str
        :return: The bearer token that allows users to call Workbench APIs.
        :rtype: str
        '''

        headers = {'content-type': 'application/x-www-form-urlencoded'}
        data = urlencode({'grant_type': 'password', 'username': username, 'password': password})
        resp = self.request('post', '/auth/v0/login', data=data, headers=headers, skip_raise=True)
        # Note the login route returns 401 even when password is valid as a way to
        # move to the second phase which is posting the 2fa code..
        if resp.status_code != 401:
            logger.bind(status_code=resp.status_code).error("Got unexpected http response code")
            return None

        headers['x-expelinc-otp'] = str(code)

        resp = self.request('post', '/auth/v0/login', data=data, headers=headers)
        return resp.json()['access_token']

    def service_login(self, apikey):
        '''
        Authenticate as a service

        :param apikey: The API key to use to authenticate
        :type apikey: str
        :return: The bearer token that allows users to call Workbench APIs.
        :rtype: str
        '''
        resp = self.request('post', '/api/v2/service_login', data=json.dumps({'id': apikey}))
        return resp.json()['access_token']

    def _get_user_input(self):
        '''
        Broken out to enable easy testing.
        '''
        return input().strip().lower()

    def _prompt_on_delete(self, url):
        cnt = 0
        while cnt < 5:
            logger.info(
                "In the future specify prompt_on_delete=False to not be prompted. You are requesting delete via API route %s. Are you sure you want to do this [y/n]?" % url)
            response = self._get_user_input()
            if response == 'y':
                break
            elif response == 'n':
                raise Exception("User does not want to execute delete API")
            cnt += 1

        if cnt == 5:
            raise Exception("User did not confirm delete!")

    def request(self, method, url, data=None, skip_raise=False, files=None, prompt_on_delete=True, **kwargs):
        url = urljoin(self.base_url, url)

        # We only inject the prompt if its workbench client. Other clients inheriting this class
        # wont inherit the prompt on delete behavior.
        if method == 'delete' and prompt_on_delete and self.prompt_on_delete:
            self._prompt_on_delete(url)

        headers = kwargs.pop('headers', {})

        request_kwargs = dict(self.default_request_kwargs)
        request_kwargs.update(kwargs)

        do_print = False
        if self.debug:
            if not self.debug_method and not self.debug_url_contains:
                do_print = True
            elif self.debug_method and method in self.debug_method:
                do_print = True
            elif self.debug_url_contains and url.lower().find(self.debug_url_contains.lower()) != -1:
                do_print = True

            if do_print:
                logger.debug(method, " ", url)
                if data:
                    logger.debug(pprint.pformat(data))
        if files:
            headers['Authorization'] = self.session.headers['Authorization']
            resp = requests.post(url, headers=headers, data=data, files=files, **request_kwargs)
        else:
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=data,
                    **request_kwargs
                )
            except ConnectionError:
                # if connection was fatally closed, create a new session and try again
                logger.bind().warning("XClient got connection error, recreating session...")
                time.sleep(5)
                self.make_session()
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=data,
                    **request_kwargs
                )

        if self.debug and do_print:
            logger.debug(pprint.pformat(resp.json()))

        if skip_raise:
            return resp

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            # It's HTML code..
            if resp.text.startswith('<'):
                raise e

            err = resp.json()
            errors = err.get('errors')
            if errors and 'detail' in errors[0]:
                raise requests.exceptions.HTTPError(err['errors'][0]['detail'])
            elif errors and 'status' in errors[0]:
                raise requests.exceptions.HTTPError("Got status code: %s" % err['errors'][0]['status'])
            elif errors and 'title' in errors[0]:
                raise requests.exceptions.HTTPError(err['errors'][0]['title'])
            elif err.get('message'):
                msg = '%s: %s' % (err['message'], str(err.get('validation')))
                raise requests.exceptions.HTTPError(msg)
            if err.get('error_description'):
                raise requests.exceptions.HTTPError(err['error_description'])
            elif err.get('error'):
                raise requests.exceptions.HTTPError(err['error'])

        return resp


class WorkbenchClient(WorkbenchCoreClient):
    '''
    Instantiate a client that interacts with Workbench's API server.

    If the developer specifies a ``username``, then ``password`` and ``mfa_code`` are required inputs. If the developer
    has an ``apikey`` then ``username``, ``password`` and ``mfa_code`` parameters are ignored.

    :param cls: A Workbench class reference.
    :type cls: WorkbenchClient
    :param apikey: An apikey to use for authentication/authorization.
    :type apikey: str or None
    :param username: The username
    :type username: str or None
    :param password: The username's password
    :type password: str or None
    :param mfa_code: The multi factor authenticate code generated by google authenticator.
    :type mfa_code: int or None
    :param token: The bearer token of an authorized session. Can be used instead of ``apikey`` and ``username``/``password`` combo.
    :type token: str or None
    :return: An initialized, and authorized Workbench client.
    :rtype: WorkbenchClient
    '''

    def __init__(self, base_url, apikey=None, username=None, password=None, mfa_code=None, token=None, prompt_on_delete=True):
        super().__init__(base_url, apikey=apikey, username=username, password=password,
                         mfa_code=mfa_code, token=token, prompt_on_delete=prompt_on_delete)

    def create_manual_inv_action(self, title: str, reason: str, instructions: str, investigation_id: str = None, expel_alert_id: str = None, security_device_id: str = None, action_type: str = 'MANUAL'):
        '''
        Create a manual investigative action.




        :param title: The title of the investigative action, shows up in Workbench.
        :type title: str
        :param reason: The reason for running the investigative action, shows up in Workbench.
        :type reason: str
        :param instructions: The instructions for running the investigative action.
        :type instructions: str
        :param investigation_id: The investigation ID to associate the action with.
        :type investigation_id: str
        :param expel_alert_id: The expel alert id
        :type expel_alert_id: str
        :param security_device_id: The security device ID, to dispatch the task against.
        :type security_device_id: str
        :param action_type: The type of action that will be run.
        :type action_type: str
        :return: Investigative action response
        :rtype: InvestigativeActions

        Examples:
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> o = xc.create_manual_inv_action('title foo', 'reason bar', 'instructions blah')
            >>> print("Investigative Action ID: ", o.id)
        '''
        if not expel_alert_id and not investigation_id:
            raise Exception("Must specify an expel_alert_id or an investigation_id")

        # Create the manual investigative action in WB
        ia = self.investigative_actions.create(
            title=title, status='READY_FOR_ANALYSIS', reason=reason, action_type=action_type, instructions=instructions)
        if security_device_id is not None:
            ia.relationship.security_device = security_device_id
        if investigation_id:
            ia.relationship.investigation = investigation_id
        else:
            ia.relationship.expel_alert = expel_alert_id

        return ia.save()

    def create_auto_inv_action(self, vendor_device_id: str, capability_name: str, input_args: dict, title: str, reason: str, investigation_id: str = None, expel_alert_id: str = None):
        '''
        Create an automatic investigative action.


        :param investigation_id: The investigation ID to associate the action with.
        :type investigation_id: str
        :param expel_alert_id: The expel alert id
        :type expel_alert_id: str
        :param vendor_device_id: The vendor device ID, to dispatch the task against.
        :type vendor_device_id: str
        :param capability_name: The name of the capability we are running. Defined in classes https://github.com/expel-io/taskabilities/tree/master/py/taskabilities/cpe/capabilities, look at name class variable.
        :type capability_name: str
        :param input_args: The input arguments to the capability to run. Defined in classes https://github.com/expel-io/taskabilities/tree/master/py/taskabilities/cpe/capabilities, look at name class variable.
        :type input_args: dict
        :param title: The title of the investigative action, shows up in Workbench.
        :type title: str
        :param reason: The reason for running the investigative action, shows up in Workbench.
        :type reason: str
        :return: Investigative action response
        :rtype: InvestigativeActions

        Examples:
            >>> xc = XClient.workbench('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
<<<<<<< HEAD
            >>> input_args = &#123;"user_name": 'matt.peters@expel.io', 'time_range_start':'2019-01-30T14:00:40Z', 'time_range_end':'2019-01-30T14:45:40Z'&#125;
            >>> o = xc.create_auto_inv_action(inv_guid, device_guid, 'query_user', input_args, 'Query User', 'Getting user login activity to determine if login is normal')
=======
            >>> input_args = &#123;"user_name": 'willy.wonka@expel.io', 'time_range_start':'2019-01-30T14:00:40Z', 'time_range_end':'2019-01-30T14:45:40Z'&#125;
            >>> o = xc.create_auto_inv_action(customer_guid, inv_guid, device_guid, user_guid, 'query_user', input_args, 'Query User', 'Getting user login activity to determine if login is normal')
>>>>>>> f06dc922fe5a5ad327579e3476ad5f62a05a278c
            >>> print("Investigative Action ID: ", o.id)
        '''
        if not expel_alert_id and not investigation_id:
            raise Exception("Must specify an expel_alert_id or an investigation_id")

        # Create the investigative action in WB
        ia = self.investigative_actions.create(title=title, status='RUNNING', reason=reason, action_type='TASKABILITY',
                                               capability_name=capability_name, input_args=input_args)
        ia.relationship.vendor_device = vendor_device_id
        if investigation_id:
            ia.relationship.investigation = investigation_id
        else:
            ia.relationship.expel_alert = expel_alert_id
        return ia.save()

    def capabilities(self):
        '''
        Get a list of capabilities available based on onboarded devices.

        Examples:
            >>> xc.workbench.capabilities()
        '''
        resp = self.request('get', '/api/v2/capabilities')
        return resp.json()

    def plugins(self):
        '''
        Get a list of plugins.

        Examples:
            >>> xc.workbench.plugins()
        '''
        resp = self.request('get', '/api/v2/plugins')
        return resp.json()

    # AUTO GENERATE PROPERTIES

    @property
    def nist_subcategories(self):
        return BaseResourceObject(NistSubcategories, conn=self)

    @property
    def investigative_action_histories(self):
        return BaseResourceObject(InvestigativeActionHistories, conn=self)

    @property
    def investigative_action_data_query_domain(self):
        return BaseResourceObject(InvestigativeActionDataQueryDomain, conn=self)

    @property
    def investigative_action_data_query_user(self):
        return BaseResourceObject(InvestigativeActionDataQueryUser, conn=self)

    @property
    def investigations(self):
        return BaseResourceObject(Investigations, conn=self)

    @property
    def customer_devices(self):
        return BaseResourceObject(CustomerDevices, conn=self)

    @property
    def customers(self):
        return BaseResourceObject(Customers, conn=self)

    @property
    def remediation_action_histories(self):
        return BaseResourceObject(RemediationActionHistories, conn=self)

    @property
    def secrets(self):
        return BaseResourceObject(Secrets, conn=self)

    @property
    def organization_resilience_action_list(self):
        return BaseResourceObject(OrganizationResilienceActionList, conn=self)

    @property
    def investigative_action_data_reg_listing(self):
        return BaseResourceObject(InvestigativeActionDataRegListing, conn=self)

    @property
    def user_account_statuses(self):
        return BaseResourceObject(UserAccountStatuses, conn=self)

    @property
    def vendor_alert_evidences(self):
        return BaseResourceObject(VendorAlertEvidences, conn=self)

    @property
    def timeline_entries(self):
        return BaseResourceObject(TimelineEntries, conn=self)

    @property
    def nist_subcategory_score_histories(self):
        return BaseResourceObject(NistSubcategoryScoreHistories, conn=self)

    @property
    def investigation_histories(self):
        return BaseResourceObject(InvestigationHistories, conn=self)

    @property
    def phishing_submissions(self):
        return BaseResourceObject(PhishingSubmissions, conn=self)

    @property
    def organization_list(self):
        return BaseResourceObject(OrganizationList, conn=self)

    @property
    def investigative_action_data_technique_scheduled_tasks(self):
        return BaseResourceObject(InvestigativeActionDataTechniqueScheduledTasks, conn=self)

    @property
    def remediation_action_assets(self):
        return BaseResourceObject(RemediationActionAssets, conn=self)

    @property
    def configuration_defaults(self):
        return BaseResourceObject(ConfigurationDefaults, conn=self)

    @property
    def context_label_tags(self):
        return BaseResourceObject(ContextLabelTags, conn=self)

    @property
    def remediation_actions(self):
        return BaseResourceObject(RemediationActions, conn=self)

    @property
    def investigative_action_data_persistence_listing(self):
        return BaseResourceObject(InvestigativeActionDataPersistenceListing, conn=self)

    @property
    def customer_resilience_actions(self):
        return BaseResourceObject(CustomerResilienceActions, conn=self)

    @property
    def comment_histories(self):
        return BaseResourceObject(CommentHistories, conn=self)

    @property
    def investigative_action_data_query_logs(self):
        return BaseResourceObject(InvestigativeActionDataQueryLogs, conn=self)

    @property
    def investigation_resilience_action_hints(self):
        return BaseResourceObject(InvestigationResilienceActionHints, conn=self)

    @property
    def investigative_action_data_technique_sinkhole_connections(self):
        return BaseResourceObject(InvestigativeActionDataTechniqueSinkholeConnections, conn=self)

    @property
    def files(self):
        return BaseResourceObject(Files, conn=self)

    @property
    def expel_users(self):
        return BaseResourceObject(ExpelUsers, conn=self)

    @property
    def investigation_findings(self):
        return BaseResourceObject(InvestigationFindings, conn=self)

    @property
    def activity_metrics(self):
        return BaseResourceObject(ActivityMetrics, conn=self)

    @property
    def customer_resilience_action_list(self):
        return BaseResourceObject(CustomerResilienceActionList, conn=self)

    @property
    def investigative_action_data_list_sources(self):
        return BaseResourceObject(InvestigativeActionDataListSources, conn=self)

    @property
    def investigative_action_data_query_file(self):
        return BaseResourceObject(InvestigativeActionDataQueryFile, conn=self)

    @property
    def investigative_action_data_process_listing(self):
        return BaseResourceObject(InvestigativeActionDataProcessListing, conn=self)

    @property
    def engagement_managers(self):
        return BaseResourceObject(EngagementManagers, conn=self)

    @property
    def investigative_action_data_query_url(self):
        return BaseResourceObject(InvestigativeActionDataQueryUrl, conn=self)

    @property
    def context_labels(self):
        return BaseResourceObject(ContextLabels, conn=self)

    @property
    def organization_resilience_action_groups(self):
        return BaseResourceObject(OrganizationResilienceActionGroups, conn=self)

    @property
    def expel_alert_thresholds(self):
        return BaseResourceObject(ExpelAlertThresholds, conn=self)

    @property
    def investigative_action_data_query_raw_logs(self):
        return BaseResourceObject(InvestigativeActionDataQueryRawLogs, conn=self)

    @property
    def investigative_action_data_technique_successive_reconnaissance_commands(self):
        return BaseResourceObject(InvestigativeActionDataTechniqueSuccessiveReconnaissanceCommands, conn=self)

    @property
    def products(self):
        return BaseResourceObject(Products, conn=self)

    @property
    def phishing_submission_headers(self):
        return BaseResourceObject(PhishingSubmissionHeaders, conn=self)

    @property
    def vendor_alerts(self):
        return BaseResourceObject(VendorAlerts, conn=self)

    @property
    def nist_subcategory_scores(self):
        return BaseResourceObject(NistSubcategoryScores, conn=self)

    @property
    def organization_statuses(self):
        return BaseResourceObject(OrganizationStatuses, conn=self)

    @property
    def actors(self):
        return BaseResourceObject(Actors, conn=self)

    @property
    def resilience_action_groups(self):
        return BaseResourceObject(ResilienceActionGroups, conn=self)

    @property
    def comments(self):
        return BaseResourceObject(Comments, conn=self)

    @property
    def expel_alert_threshold_histories(self):
        return BaseResourceObject(ExpelAlertThresholdHistories, conn=self)

    @property
    def phishing_submission_urls(self):
        return BaseResourceObject(PhishingSubmissionUrls, conn=self)

    @property
    def investigative_action_data_technique_rdp_connection_anomalies(self):
        return BaseResourceObject(InvestigativeActionDataTechniqueRdpConnectionAnomalies, conn=self)

    @property
    def assemblers(self):
        return BaseResourceObject(Assemblers, conn=self)

    @property
    def investigative_action_data_query_cloudtrail(self):
        return BaseResourceObject(InvestigativeActionDataQueryCloudtrail, conn=self)

    @property
    def investigative_action_data_technique_failed_c_2_connections(self):
        return BaseResourceObject(InvestigativeActionDataTechniqueFailedC2Connections, conn=self)

    @property
    def phishing_submission_domains(self):
        return BaseResourceObject(PhishingSubmissionDomains, conn=self)

    @property
    def expel_alert_grid(self):
        return BaseResourceObject(ExpelAlertGrid, conn=self)

    @property
    def nist_categories(self):
        return BaseResourceObject(NistCategories, conn=self)

    @property
    def investigation_finding_histories(self):
        return BaseResourceObject(InvestigationFindingHistories, conn=self)

    @property
    def vendor_devices(self):
        return BaseResourceObject(VendorDevices, conn=self)

    @property
    def investigative_action_data_query_ip(self):
        return BaseResourceObject(InvestigativeActionDataQueryIp, conn=self)

    @property
    def api_keys(self):
        return BaseResourceObject(ApiKeys, conn=self)

    @property
    def resilience_actions(self):
        return BaseResourceObject(ResilienceActions, conn=self)

    @property
    def security_devices(self):
        return BaseResourceObject(SecurityDevices, conn=self)

    @property
    def notification_preferences(self):
        return BaseResourceObject(NotificationPreferences, conn=self)

    @property
    def user_accounts(self):
        return BaseResourceObject(UserAccounts, conn=self)

    @property
    def configuration_labels(self):
        return BaseResourceObject(ConfigurationLabels, conn=self)

    @property
    def integrations(self):
        return BaseResourceObject(Integrations, conn=self)

    @property
    def ip_addresses(self):
        return BaseResourceObject(IpAddresses, conn=self)

    @property
    def cpe_images(self):
        return BaseResourceObject(CpeImages, conn=self)

    @property
    def investigative_action_data_file_listing(self):
        return BaseResourceObject(InvestigativeActionDataFileListing, conn=self)

    @property
    def phishing_submission_attachments(self):
        return BaseResourceObject(PhishingSubmissionAttachments, conn=self)

    @property
    def customer_em_meta(self):
        return BaseResourceObject(CustomerEmMeta, conn=self)

    @property
    def investigation_resilience_actions(self):
        return BaseResourceObject(InvestigationResilienceActions, conn=self)

    @property
    def user_account_roles(self):
        return BaseResourceObject(UserAccountRoles, conn=self)

    @property
    def configurations(self):
        return BaseResourceObject(Configurations, conn=self)

    @property
    def resilience_action_investigation_properties(self):
        return BaseResourceObject(ResilienceActionInvestigationProperties, conn=self)

    @property
    def investigative_action_data_query_host(self):
        return BaseResourceObject(InvestigativeActionDataQueryHost, conn=self)

    @property
    def expel_alert_grid_v2(self):
        return BaseResourceObject(ExpelAlertGridV2, conn=self)

    @property
    def customer_resilience_action_groups(self):
        return BaseResourceObject(CustomerResilienceActionGroups, conn=self)

    @property
    def features(self):
        return BaseResourceObject(Features, conn=self)

    @property
    def context_label_actions(self):
        return BaseResourceObject(ContextLabelActions, conn=self)

    @property
    def assembler_images(self):
        return BaseResourceObject(AssemblerImages, conn=self)

    @property
    def expel_alerts(self):
        return BaseResourceObject(ExpelAlerts, conn=self)

    @property
    def customer_list(self):
        return BaseResourceObject(CustomerList, conn=self)

    @property
    def investigative_action_data_technique_failed_api_requests(self):
        return BaseResourceObject(InvestigativeActionDataTechniqueFailedApiRequests, conn=self)

    @property
    def organization_resilience_actions(self):
        return BaseResourceObject(OrganizationResilienceActions, conn=self)

    @property
    def vendors(self):
        return BaseResourceObject(Vendors, conn=self)

    @property
    def remediation_action_asset_histories(self):
        return BaseResourceObject(RemediationActionAssetHistories, conn=self)

    @property
    def expel_alert_histories(self):
        return BaseResourceObject(ExpelAlertHistories, conn=self)

    @property
    def investigative_actions(self):
        return BaseResourceObject(InvestigativeActions, conn=self)

    @property
    def findings(self):
        return BaseResourceObject(Findings, conn=self)

    @property
    def saml_identity_providers(self):
        return BaseResourceObject(SamlIdentityProviders, conn=self)

    @property
    def organizations(self):
        return BaseResourceObject(Organizations, conn=self)

    @property
    def organization_em_meta(self):
        return BaseResourceObject(OrganizationEmMeta, conn=self)

    @property
    def investigative_action_data_query_netflow(self):
        return BaseResourceObject(InvestigativeActionDataQueryNetflow, conn=self)

# END AUTO GENERATE PROPERTIES
