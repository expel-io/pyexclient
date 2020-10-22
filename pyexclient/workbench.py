#!/usr/bin/env python
import copy
import datetime
import io
import json
import logging
import os
import pprint
import time
import warnings
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
    '''
    Base class for all operators. This should not be used directly.
    '''

    def __init__(self, filter_value):
        self.filter_value = [filter_value]

    def create_query_filters(self, field_name):
        return [('{}[{}]'.format(
            self.op_type, field_name
        ), filter_value) for filter_value in self.filter_value]


class base_filter(operator):
    '''
    Base class for operators which take the form filter[field]. Can
    be used to create a basic one field filter, or subclassed by
    special operators for more complicated logic
    '''
    op_type = 'filter'


class flag(operator):
    '''
    Base class for operators which take the form flag[field]. Can
    be used to create a basic one field flag, or subclassed by
    special operators for more complicated logic
    '''
    op_type = 'flag'


class notnull(base_filter):
    '''
    The notnull operator is used to search for fields that are not null.

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=notnull()):
        >>>     print("%s has a close comment of %s" % (ea.expel_name, ea.close_comment))
    '''

    def __init__(self, filter_value=True):
        if filter_value is False:
            self.filter_value = ["\u2400true"]
        elif filter_value is True:
            self.filter_value = ["\u2400false"]
        else:
            raise ValueError('notnull operator expects True|False')


class isnull(base_filter):
    '''
    The isnull operator is used to search for fields that are null.

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=isnull()):
        >>>     print("%s has no close comment" % ea.expel_name)
    '''

    def __init__(self, filter_value=True):
        if filter_value is True:
            self.filter_value = ["\u2400true"]
        elif filter_value is False:
            self.filter_value = ["\u2400false"]
        else:
            raise ValueError('notnull operator expects True|False')


class contains(base_filter):
    '''
    The contains operator is used to search for fields that contain a sub string..

    :param value: A substring to be checked against the value of a field.
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=contains("foo")):
        >>>     print("%s contains foo in the close comment" % ea.expel_name)
    '''

    def __init__(self, *args):
        self.filter_value = [':%s' % substr for substr in args]


class startswith(base_filter):
    '''
    The startswith operator is used to search for values that start with a specified string..

    :param value: The startswith string
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=startswith("foo")):
        >>>     print("%s starts with foo in the close comment" % ea.expel_name)
    '''

    def __init__(self, swith):
        self.filter_value = ['^%s' % swith]


class neq(base_filter):
    '''
    The neq operator is used to search for for fields that are not equal to a specified value.

    :param value: The value to assert the field is not equal too
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(close_comment=neq("foo")):
        >>>     print("%s has a close comment that is not equal to 'foo'" % ea.expel_name)
    '''

    def __init__(self, *args):
        self.filter_value = ['!%s' % value for value in args]


class gt(base_filter):
    '''
    The gt (greater than) operator is used to search a specific field for values greater than X.

    :param value: The greater than value to be used in comparison during a search.
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(created_at=gt("2020-01-01")):
        >>>     print("%s was created after 2020-01-01" % ea.expel_name)
    '''

    def __init__(self, value):
        if isinstance(value, datetime.datetime):
            value = value.isoformat()
        self.filter_value = ['>%s' % value]


class lt(base_filter):
    '''
    The lt (less than) operator is used to search a specific field for values greater than X.

    :param value: The less than value to be used in comparison during a search.
    :type value: str

    Examples:
        >>> for ea in xc.expel_alerts.search(created_at=lt("2020-01-01")):
        >>>     print("%s was created before 2020-01-01" % ea.expel_name)
    '''

    def __init__(self, value):
        if isinstance(value, datetime.datetime):
            value = value.isoformat()
        self.filter_value = ['<%s' % value]


class window(base_filter):
    '''
    The window operator is used to search a specific field that is within a window (range) of values

    :param start: The begining of the window range
    :type start: Union[str, int, datetime.datetime]
    :param end: The end of the window range
    :type end: str

    Examples:
        >>> for ea in xc.expel_alerts.search(created_at=window("2020-01-01", "2020-05-01")):
        >>>     print("%s was created after 2020-01-01 and before 2020-05-01" % ea.expel_name)
    '''

    def __init__(self, start, end):
        if isinstance(start, datetime.datetime):
            start = start.isoformat()

        if isinstance(end, datetime.datetime):
            end = end.isoformat()

        self.filter_value = ['>%s' % start, '<%s' % end]


class relationship(operator):
    '''
    relationship operator allows for searching of resource objects based on their relationship
    to other resource objects. Passed as arg to search

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
        self.has_id = self.rel_path.endswith('.id')
        self.rel_path = self.rel_path.replace('.id', '')
        self.rel_parts = self.rel_path.split('.')
        self.rels = None  # set at time of search by the resource itself

        if len(self.rel_parts) > 2:
            raise ValueError("relationship operator can only be used to define a relationship one level deep. Got %d levels with path %s" % (
                len(self.rel_parts), self.rel_path))

    def create_query_filters(self):
        if self.rels is None:
            raise ValueError('Relationship operator has no class relationships defined')

        if self.rel_parts[0] not in self.rels:
            raise ValueError("%s not a defined relationship in %s" % (self.rel_parts[0], ','.join(self.rels)))

        field_name = ']['.join(self.rel_parts)
        if self.has_id:
            field_name += '][id'

        query = []
        if is_operator(self.value):
            query.extend(self.value.create_query_filters(field_name))
        else:
            as_op = base_filter(self.value)
            query.extend(as_op.create_query_filters(field_name))
        return query


class limit(operator):
    '''
    The limit operator adds a limit to a search. Passed as arg to search

    :param limit: Limit the number of results returned.
    :type limit: int
    '''

    def __init__(self, limit):
        self.limit = limit

    def create_query_filters(self):
        return [('page[limit]', self.limit)]


class include(operator):
    '''
    The include operator requests base resource names in a search. Cannot
    be used with sort or filtering. Passed as arg to search
    TODO enforce this constraint with asserts

    :param include: Include specific base resource names in request
    :type include: str

    Examples:
    >>> for ea in xc.expel_alerts.search(include='organization,created_by,updated_by'):
    >>>     print(ea.organization)
    '''

    def __init__(self, include):
        self.include = include

    def create_query_filters(self):
        return [('include', self.include)]


class sort(operator):
    '''
    The sort operator passes a sort request to a search. Can add multiple
    sort operators to a single search. If no sort is provided the default
    of sorting by created_at (asc) -> id (asc) will be used. Passed as arg to search
    TODO enforce this with asserts

    :param sort: The column to sort on. Expects `asc` or `desc`. The database will translate asc->+ and desc->-
    :type sort: str
    '''

    def __init__(self, sort, order='asc'):
        if order in ['asc', '+']:
            self.order = '+'
        elif order in ['desc', '-']:
            self.order = '-'
        else:
            raise ValueError('Sort operator expects asc|desc but got {}'.format(order))

        self.sort = sort

    def create_query_filters(self):
        return [('sort', self.order + self.sort)]


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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> for inv in xc.investigations.filter_by(customer_id='1'):
            >>>     print(inv.title)
        '''
        warnings.warn('filter_by has been deprecated in favor of search', DeprecationWarning)
        url = self.build_url(**kwargs)
        self.content = self._fetch_page(url)
        return self

    def search(self, *args, **kwargs):
        '''
        Search based on a set of criteria made up of operators and attributes.

        :param args: Operators of relationship|limit|include|sort
        :type args: tuple
        :param kwargs: Fields and values to search on
        :type kwargs: dict
        :return: A BaseResourceObject object
        :rtype: :class:`BaseResourceObject`

        Examples:
            >>> # field filter
            >>> for inv in xc.investigations.search(customer_id=CUSTOMER_GUID):
            >>>     print(inv.title)

            >>> # operator field filter
            >>> for inv in xc.investigations.search(customer_id=CUSTOMER_GUID, created_at=gt("2020-01-01")):
            >>>     print(inv.title)

            >>> # relationship field filter
            >>> for inv in xc.investigations.search(customer_id=CUSTOMER_GUID, relationship("investigative_actions.created_at", gt("2020-01-01"))):
            >>>     print(inv.title)
        '''

        query = []
        added_sort = False

        for rel in args:
            if not isinstance(rel, operator):
                raise ValueError("Expected arg to be operator %s" % type(rel))

            if isinstance(rel, relationship):
                rel.rels = self.cls._def_relationships
            elif isinstance(rel, sort):
                added_sort = True

            query.extend(rel.create_query_filters())

        for field_name, field_value in sorted(kwargs.items()):
            if is_operator(field_value):
                query.extend(field_value.create_query_filters(field_name))
            else:
                as_op = base_filter(field_value)
                query.extend(as_op.create_query_filters(field_name))

        url = self.make_url(self.api_type)

        if not added_sort:
            query.extend(sort('created_at').create_query_filters())
            query.extend(sort('id').create_query_filters())

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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> print("Investigation Count: ", xc.investigations.filter_by(customer_id='1').count())
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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> inv = xc.investigations.get(id=investigation_guid)
            >>> print(inv.title)
        '''
        if 'id' not in kwargs:
            raise ValueError('Expected `id` argument in get call')

        if not len(kwargs) == 1:
            raise ValueError('Expected a single argument `id` in get call')

        # TODO: remove build_url usage when filter_by is deprecated so it can be removed
        url = self.build_url(**kwargs)
        content = self.conn.request('get', url).json()
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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
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
                          'assigned_expel_alerts': 'expel_alerts',
                          'assigned_investigations': 'investigations',
                          'assigned_investigative_actions': 'investigative_actions',
                          'assigned_organization_resilience_actions': 'organization_resilience_actions',
                          'assigned_organization_resilience_actions_list': 'organization_resilience_actions',
                          'assigned_remediation_actions': 'remediation_actions',
                          'assigned_to_actor': 'actors',
                          'attachment_file': 'files',
                          'child_actors': 'actors',
                          'child_security_devices': 'security_devices',
                          'coincident_vendor_alerts': 'vendor_alerts',
                          'comment': 'comments',
                          'comment_histories': 'comment_histories',
                          'comments': 'comments',
                          'configurations': 'configurations',
                          'context_label': 'context_labels',
                          'context_label_actions': 'context_label_actions',
                          'context_label_tags': 'context_label_tags',
                          'context_labels': 'context_labels',
                          'created_by': 'actors',
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
                          'remediation_action_asset_histories': 'remediation_action_histories',
                          'remediation_action_assets': 'remediation_action_assets',
                          'remediation_action_histories': 'remediation_action_histories',
                          'remediation_actions': 'remediation_actions',
                          'resilience_action_group': 'resilience_action_groups',
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
                          'vendor_alerts': 'vendor_alerts'}
# END AUTO GENERATE FIELD TO TYPE


class JsonApiRelationship:
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
        self._relationship = JsonApiRelationship()
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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
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
                >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
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
        | First Seen                                                                                                     | first_seen                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Status Restricted to: "NORMAL", "PROVISIONAL" Allows: null: readonly                                           | status                         | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null: immutable                                                                                        | original_source_id             | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence summary Allows: null: no-sort                                                                         | evidence_summary               | array                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                               | updated_at                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Signature ID Allows: "", null                                                                                  | signature_id                   | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor alert severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "TESTING", "TUNING" Allows: null     | vendor_severity                | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                    | created_at                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence activity end datetime Allows: null: immutable                                                         | evidence_activity_end_at       | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor Message Allows: "", null                                                                                | vendor_message                 | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence activity start datetime Allows: null: immutable                                                       | evidence_activity_start_at     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null: immutable                                                                                        | original_alert_id              | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Description Allows: "", null                                                                                   | description                    | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor Sig Name Allows: "", null                                                                               | vendor_sig_name                | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                       | updated_by                     | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Assemblers                                                                                                     | assembler                      | :class:`Assemblers`               | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Security devices                                                                                               | security_device                | :class:`SecurityDevices`          | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                    | evidences                      | :class:`VendorAlertEvidences`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                       | created_by                     | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                | organization                   | :class:`Organizations`            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | IP addresses                                                                                                   | ip_addresses                   | :class:`IpAddresses`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Expel alerts                                                                                                   | expel_alerts                   | :class:`ExpelAlerts`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendors                                                                                                        | vendor                         | :class:`Vendors`                  | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'vendor_alerts'
    _def_attributes = ["first_seen", "status", "original_source_id", "evidence_summary", "updated_at", "signature_id", "vendor_severity",
                       "created_at", "evidence_activity_end_at", "vendor_message", "evidence_activity_start_at", "original_alert_id", "description", "vendor_sig_name"]
    _def_relationships = ["updated_by", "assembler", "security_device", "evidences",
                          "created_by", "organization", "ip_addresses", "expel_alerts", "vendor"]


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
        | Remediation asset type Restricted to: "ACCOUNT", "ACCESS_KEY", "DESCRIPTION", "DEVICE", "DOMAIN_NAME", "EMAIL", "FILE", "HASH", "HOST", "INBOX_RULE_NAME", "IP_ADDRESS"     | asset_type                             | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                 | created_at                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Asset status Restricted to: "OPEN", "COMPLETED"                                                                                                                             | status                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation asset category Restricted to: "AFFECTED_ACCOUNT", "COMPROMISED_ACCOUNT", "FORWARDING_ADDRESS" Allows: null                                                      | category                               | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                            | updated_at                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation asset value: no-sort                                                                                                                                            | value                                  | alternatives                                 | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                         | remediation_action                     | :class:`RemediationActions`                  | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action asset histories                                                                                                                                          | remediation_action_asset_histories     | :class:`RemediationActionAssetHistories`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                                                                                                                        | context_label_tags                     | :class:`ContextLabelTags`                    | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                    | updated_by                             | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                    | created_by                             | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_assets'
    _def_attributes = ["asset_type", "created_at", "status", "category", "updated_at", "value"]
    _def_relationships = ["remediation_action", "remediation_action_asset_histories",
                          "context_label_tags", "updated_by", "created_by"]


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
        | Defines/retrieves expel.io actor records                                                            | assigned_to_actor        | :class:`Actors`                   | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Investigations                                                                                      | investigation            | :class:`Investigations`           | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions                                                                               | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                            | created_by               | :class:`Actors`                   | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Expel alerts                                                                                        | expel_alert              | :class:`ExpelAlerts`              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_histories'
    _def_attributes = ["created_at", "action", "deleted_at", "value"]
    _def_relationships = ["assigned_to_actor", "investigation", "investigative_action", "created_by", "expel_alert"]


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
        | Created timestamp: readonly                                                                                                                                                  | created_at       | string                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | If this role is active                                                                                                                                                       | active           | boolean                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                             | updated_at       | string                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Can user be assigned items (e.g. investigations, etc)                                                                                                                        | assignable       | boolean                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | User account role for this organization Restricted to: "expel_admin", "expel_analyst", "organization_admin", "organization_analyst", "system", "anonymous", "restricted"     | role             | any                        | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                     | updated_by       | :class:`Actors`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                              | organization     | :class:`Organizations`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | User accounts                                                                                                                                                                | user_account     | :class:`UserAccounts`      | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                     | created_by       | :class:`Actors`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'user_account_roles'
    _def_attributes = ["created_at", "active", "updated_at", "assignable", "role"]
    _def_relationships = ["updated_by", "organization", "user_account", "created_by"]


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
        | Created timestamp: readonly                                                                                 | created_at           | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Needed information for integration type Allows: null: no-sort                                               | integration_meta     | object                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Integration status Restricted to: "UNTESTED", "TEST_SUCCESS", "TEST_FAIL": readonly                         | status               | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Type of integration Restricted to: "pagerduty", "slack", "ticketing", "service_now", "teams": immutable     | integration_type     | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Service account identifier                                                                                  | account              | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Service display name                                                                                        | service_name         | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                            | updated_at           | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Last Successful Test Allows: null: readonly                                                                 | last_tested_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                    | updated_by           | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                             | organization         | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Organization secrets. Note - these requests must be in the format of `/secrets/security_device-<guid>`      | secret               | :class:`Secrets`           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                    | created_by           | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'integrations'
    _def_attributes = ["created_at", "integration_meta", "status",
                       "integration_type", "account", "service_name", "updated_at", "last_tested_at"]
    _def_relationships = ["updated_by", "organization", "secret", "created_by"]


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
        | Defines/retrieves expel.io expel_alert_threshold records                                                              | expel_alert_threshold     | :class:`ExpelAlertThresholds`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                              | created_by                | :class:`Actors`                   | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_threshold_histories'
    _def_attributes = ["created_at", "action", "value"]
    _def_relationships = ["expel_alert_threshold", "created_by"]


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
        | Threat Type Restricted to: "TARGETED", "TARGETED_APT", "TARGETED_RANSOMWARE", "BUSINESS_EMAIL_COMPROMISE", "NON_TARGETED", "NON_TARGETED_MALWARE", "POLICY_VIOLATION", "UNKNOWN" Allows: null                                                                               | threat_type                                      | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Experimental properties Allows: null: no-sort                                                                                                                                                                                                                               | properties                                       | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Published At Allows: null                                                                                                                                                                                                                                              | last_published_at                                | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Close Comment Allows: "", null                                                                                                                                                                                                                                              | close_comment                                    | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                            | updated_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Lead Description Allows: null                                                                                                                                                                                                                                               | lead_description                                 | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is surge                                                                                                                                                                                                                                                                    | is_surge                                         | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                    | status_updated_at                                | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                 | created_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Analyst Severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO" Allows: null                                                                                                                                                                                    | analyst_severity                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Reason the investigation/incident was opened Allows: "", null                                                                                                                                                                                                               | open_comment                                     | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Decision Restricted to: "FALSE_POSITIVE", "TRUE_POSITIVE", "CLOSED", "OTHER", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "TESTING", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "INCONCLUSIVE" Allows: null                                                   | decision                                         | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation short link: readonly                                                                                                                                                                                                                                          | short_link                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Incident Status timestamp Allows: null: readonly                                                                                                                                                                                                                            | is_incident_status_updated_at                    | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                                                                                                                                                                                                                                      | title                                            | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Vector Restricted to: "DRIVE_BY", "PHISHING", "PHISHING_LINK", "PHISHING_ATTACHMENT", "REV_MEDIA", "SPEAR_PHISHING", "SPEAR_PHISHING_LINK", "SPEAR_PHISHING_ATTACHMENT", "STRAG_WEB_COMP", "SERVER_SIDE_VULN", "CRED_THEFT", "MISCONFIG", "UNKNOWN" Allows: null     | attack_vector                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Meta: readonly, no-sort                                                                                                                                                                                                                                                     | has_hunting_status                               | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                           | deleted_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Timing Restricted to: "HISTORICAL", "PRESENT" Allows: null                                                                                                                                                                                                           | attack_timing                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Lifecycle Restricted to: "INITIAL_RECON", "DELIVERY", "EXPLOITATION", "INSTALLATION", "COMMAND_CONTROL", "LATERAL_MOVEMENT", "ACTION_TARGETS", "UNKNOWN" Allows: null                                                                                                | attack_lifecycle                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Review Requested At Allows: null                                                                                                                                                                                                                                            | review_requested_at                              | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is downgrade                                                                                                                                                                                                                                                                | is_downgrade                                     | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Detection Type Restricted to: "UNKNOWN", "ENDPOINT", "SIEM", "NETWORK", "EXPEL", "HUNTING", "CLOUD" Allows: null                                                                                                                                                            | detection_type                                   | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Published Value Allows: "", null                                                                                                                                                                                                                                       | last_published_value                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is Incident                                                                                                                                                                                                                                                                 | is_incident                                      | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Critical Comment Allows: "", null                                                                                                                                                                                                                                           | critical_comment                                 | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Source Reason Restricted to: "HUNTING", "ORGANIZATION_REPORTED", "DISCOVERY", "PHISHING" Allows: null                                                                                                                                                                       | source_reason                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | source_ip_addresses                              | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation histories                                                                                                                                                                                                                                                     | investigation_histories                          | :class:`InvestigationHistories`              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation to resilience actions                                                                                                                                                                                                                                         | investigation_resilience_actions                 | :class:`InvestigationResilienceActions`      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | created_by                                       | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                                                                                                                                                                                       | expel_alert_histories                            | :class:`ExpelAlertHistories`                 | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | destination_ip_addresses                         | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | review_requested_by                              | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                              | related_investigations_via_involved_host_ips     | :class:`Investigations`                      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                                                                                                                                                                                 | evidence                                         | :class:`VendorAlertEvidences`                | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                                                                                                         | remediation_actions                              | :class:`RemediationActions`                  | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                | lead_expel_alert                                 | :class:`ExpelAlerts`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                       | investigative_actions                            | :class:`InvestigativeActions`                | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io investigation_finding_history records                                                                                                                                                                                                            | investigation_finding_histories                  | :class:`InvestigationFindingHistories`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action histories                                                                                                                                                                                                                                                | remediation_action_histories                     | :class:`RemediationActionHistories`          | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                                                                                                          | organization_resilience_actions                  | :class:`OrganizationResilienceActions`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | last_published_by                                | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io finding records                                                                                                                                                                                                                                  | findings                                         | :class:`InvestigationFindings`               | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | assigned_to_actor                                | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                                                                                                                                                                                     | context_label_actions                            | :class:`ContextLabelActions`                 | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | status_last_updated_by                           | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | ip_addresses                                     | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                                                                                                              | investigative_action_histories                   | :class:`InvestigativeActionHistories`        | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                | expel_alerts                                     | :class:`ExpelAlerts`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment_history records                                                                                                                                                                                                                          | comment_histories                                | :class:`CommentHistories`                    | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                                                                                                                                                                                                                  | comments                                         | :class:`Comments`                            | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | File                                                                                                                                                                                                                                                                        | files                                            | :class:`Files`                               | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Timeline Entries                                                                                                                                                                                                                                                            | timeline_entries                                 | :class:`TimelineEntries`                     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                             | organization                                     | :class:`Organizations`                       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                                                                                                          | organization_resilience_action_hints             | :class:`OrganizationResilienceActions`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action asset histories                                                                                                                                                                                                                                          | remediation_action_asset_histories               | :class:`RemediationActionAssetHistories`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                                                            | context_labels                                   | :class:`ContextLabels`                       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | updated_by                                       | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigations'
    _def_attributes = ["threat_type", "properties", "last_published_at", "close_comment", "updated_at", "lead_description", "is_surge", "status_updated_at", "created_at", "analyst_severity", "open_comment", "decision", "short_link", "is_incident_status_updated_at",
                       "title", "attack_vector", "has_hunting_status", "deleted_at", "attack_timing", "attack_lifecycle", "review_requested_at", "is_downgrade", "detection_type", "last_published_value", "is_incident", "critical_comment", "source_reason"]
    _def_relationships = ["source_ip_addresses", "investigation_histories", "investigation_resilience_actions", "created_by", "expel_alert_histories", "destination_ip_addresses", "review_requested_by", "related_investigations_via_involved_host_ips", "evidence", "remediation_actions", "lead_expel_alert", "investigative_actions", "investigation_finding_histories", "remediation_action_histories",
                          "organization_resilience_actions", "last_published_by", "findings", "assigned_to_actor", "context_label_actions", "status_last_updated_by", "ip_addresses", "investigative_action_histories", "expel_alerts", "comment_histories", "comments", "files", "timeline_entries", "organization", "organization_resilience_action_hints", "remediation_action_asset_histories", "context_labels", "updated_by"]


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
        | Remediation Action Values: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | values                           | object                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Action Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | action                           | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation Action Template Name Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | template_name                    | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Version Restricted to: "V1", "V2", "V3"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | version                          | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Restricted to: "IN_PROGRESS", "COMPLETED", "CLOSED"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | status                           | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | updated_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | created_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | status_updated_at                | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Close Reason Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | close_reason                     | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action details markdown Allows: "", null: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | detail_markdown                  | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Action type Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type                      | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Comment Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | comment                          | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | deleted_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | updated_by                       | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | assigned_to_actor                | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | investigation                    | :class:`Investigations`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | created_by                       | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action assets                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | remediation_action_assets        | :class:`RemediationActionAssets`        | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action histories                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | remediation_action_histories     | :class:`RemediationActionHistories`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_actions'
    _def_attributes = ["values", "action", "template_name", "version", "status", "updated_at", "created_at",
                       "status_updated_at", "close_reason", "detail_markdown", "action_type", "comment", "deleted_at"]
    _def_relationships = ["updated_by", "assigned_to_actor", "investigation",
                          "created_by", "remediation_action_assets", "remediation_action_histories"]


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
        | Missing Description                                 | description       | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | name              | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Product features                                    | features          | :class:`Features`          | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organizations     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'products'
    _def_attributes = ["created_at", "description", "updated_at", "name"]
    _def_relationships = ["updated_by", "features", "created_by", "organizations"]


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
        | Created timestamp: readonly                                                                          | created_at                | string                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigation finding history action Restricted to: "CREATED", "CHANGED", "DELETED" Allows: null     | action                    | any                                | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                     | updated_at                | string                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigation finding history details Allows: null: no-sort                                          | value                     | object                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                             | updated_by                | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigations                                                                                       | investigation             | :class:`Investigations`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigation findings                                                                               | investigation_finding     | :class:`InvestigationFindings`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                             | created_by                | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_finding_histories'
    _def_attributes = ["created_at", "action", "updated_at", "value"]
    _def_relationships = ["updated_by", "investigation", "investigation_finding", "created_by"]


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
        | Meta: readonly                                                                                                          | created_at                          | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Missing Description                                                                                                     | active                              | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Missing Description                                                                                                     | restrictions                        | array                      | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Allows: null: readonly                                                                                                  | invite_token_expires_at             | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Allows: null: readonly                                                                                                  | password_reset_token_expires_at     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Restricted to: "ACTIVE", "LOCKED", "LOCKED_INVITED", "LOCKED_EXPIRED", "ACTIVE_INVITED", "ACTIVE_EXPIRED": readonly     | active_status                       | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Meta: readonly                                                                                                          | updated_at                          | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                | updated_by                          | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | User accounts                                                                                                           | user_account                        | :class:`UserAccounts`      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                         | primary_organization                | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                | created_by                          | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'user_account_statuses'
    _def_attributes = ["created_at", "active", "restrictions", "invite_token_expires_at",
                       "password_reset_token_expires_at", "active_status", "updated_at"]
    _def_relationships = ["updated_by", "user_account", "primary_organization", "created_by"]


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
        | Created timestamp: readonly                                          | created_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Finding Allows: "", null                                             | finding                             | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                     | updated_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                    | deleted_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Visualization Rank                                                   | rank                                | number                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                               | title                               | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | updated_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                       | investigation                       | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | created_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io investigation_finding_history records     | investigation_finding_histories     | :class:`InvestigationFindingHistories`     | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_findings'
    _def_attributes = ["created_at", "finding", "updated_at", "deleted_at", "rank", "title"]
    _def_relationships = ["updated_by", "investigation", "created_by", "investigation_finding_histories"]


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
        | Missing Description                                 | restrictions            | array                      | Y             | N                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Meta: readonly                                      | updated_at              | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | enabled_login_types     | array                      | Y             | N                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by              | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization            | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by              | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'organization_statuses'
    _def_attributes = ["created_at", "restrictions", "updated_at", "enabled_login_types"]
    _def_relationships = ["updated_by", "organization", "created_by"]


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
        | Created timestamp: readonly                         | created_at                         | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Metadata about the file Allows: null: no-sort       | file_meta                          | object                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at                         | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Filename                                            | filename                           | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel file type Allows: null, ""                    | expel_file_type                    | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                      | investigations                     | :class:`Investigations`                    | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                               | investigative_actions              | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission attachments                     | phishing_submission_attachment     | :class:`PhishingSubmissionAttachments`     | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization                       | :class:`Organizations`                     | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submissions                                | phishing_submission                | :class:`PhishingSubmissions`               | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'files'
    _def_attributes = ["created_at", "file_meta", "updated_at", "filename", "expel_file_type"]
    _def_relationships = ["updated_by", "investigations", "created_by", "investigative_actions",
                          "phishing_submission_attachment", "organization", "phishing_submission"]


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
        | Value                                        | value                   | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Name                                         | name                    | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by              | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission     | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_headers'
    _def_attributes = ["value", "name"]
    _def_relationships = ["created_by", "phishing_submission"]


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
        | Title Allows: "", null                       | title          | string              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Seed Rank                                    | rank           | number              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by     | :class:`Actors`     | N             | Y                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by     | :class:`Actors`     | N             | Y                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+

    '''
    _api_type = 'findings'
    _def_attributes = ["created_at", "updated_at", "title", "rank"]
    _def_relationships = ["updated_by", "created_by"]


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
        | Email type Allows: "", null                  | email_type                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Sender domain                                | sender_domain                       | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Message ID                                   | msg_id                              | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Reported at                                  | reported_at                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Subject Allows: ""                           | subject                             | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Automated action type Allows: "", null       | automated_action_type               | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                  | created_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Received at                                  | received_at                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Submitted by                                 | submitted_by                        | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Sender                                       | sender                              | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Return path Allows: ""                       | return_path                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Triaged at Allows: null                      | triaged_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission domains                  | phishing_submission_domains         | :class:`PhishingSubmissionDomains`         | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission attachments              | phishing_submission_attachments     | :class:`PhishingSubmissionAttachments`     | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | analysis_email_file                 | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | raw_body_file                       | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | initial_email_file                  | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission headers                  | phishing_submission_headers         | :class:`PhishingSubmissionHeaders`         | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission URLs                     | phishing_submission_urls            | :class:`PhishingSubmissionUrls`            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                 | expel_alert                         | :class:`ExpelAlerts`                       | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submissions'
    _def_attributes = ["email_type", "sender_domain", "msg_id", "reported_at", "updated_at", "subject",
                       "automated_action_type", "created_at", "received_at", "submitted_by", "sender", "return_path", "triaged_at"]
    _def_relationships = ["phishing_submission_domains", "phishing_submission_attachments", "analysis_email_file", "raw_body_file",
                          "created_by", "initial_email_file", "phishing_submission_headers", "updated_by", "phishing_submission_urls", "expel_alert"]


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
        | Created timestamp: readonly                                  | created_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Referring url Allows: "", null                               | referring_url       | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Activity Allows: "", null                                    | activity            | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Date/Time of when the activity concluded                     | ended_at            | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Additional data about the activity Allows: null: no-sort     | data                | object                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                             | updated_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Url Allows: "", null                                         | url                 | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Date/Time of when the activity started                       | started_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                     | updated_by          | :class:`Actors`              | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Investigations                                               | investigation       | :class:`Investigations`      | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Security devices                                             | security_device     | :class:`SecurityDevices`     | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                     | created_by          | :class:`Actors`              | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Expel alerts                                                 | expel_alert         | :class:`ExpelAlerts`         | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'activity_metrics'
    _def_attributes = ["created_at", "referring_url", "activity", "ended_at", "data", "updated_at", "url", "started_at"]
    _def_relationships = ["updated_by", "investigation", "security_device", "created_by", "expel_alert"]


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
        | Allows: null                                                                                                                                                                                                                        | disposition_disposed_alerts_count                  | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert close comment Allows: "", null                                                                                                                                                                                          | close_comment                                      | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | tuning requested                                                                                                                                                                                                                    | tuning_requested                                   | boolean                                   | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert status Restricted to: "OPEN", "IN_PROGRESS", "CLOSED" Allows: null                                                                                                                                                      | status                                             | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | URL to rule definition for alert Allows: "", null                                                                                                                                                                                   | git_rule_url                                       | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_closed_alerts_count                    | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                    | updated_at                                         | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                            | status_updated_at                                  | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                         | created_at                                         | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert version Allows: "", null                                                                                                                                                                                                | expel_version                                      | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert close reason Restricted to: "FALSE_POSITIVE", "TRUE_POSITIVE", "OTHER", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "TESTING", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "INCONCLUSIVE" Allows: null     | close_reason                                       | any                                       | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort                                                                                                                                                                                                     | activity_last_at                                   | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_alerts_in_critical_incidents_count     | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_alerts_in_incidents_count              | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_alerts_in_critical_incidents_count       | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert signature Allows: "", null                                                                                                                                                                                              | expel_signature_id                                 | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "TESTING", "TUNING" Allows: null                                                                                                                           | expel_severity                                     | any                                       | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert type Restricted to: "ENDPOINT", "NETWORK", "SIEM", "RULE_ENGINE", "EXTERNAL", "OTHER", "CLOUD", "PHISHING_SUBMISSION", "PHISHING_SUBMISSION_SIMILAR" Allows: null                                                       | alert_type                                         | any                                       | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | disposition_alerts_in_investigations_count         | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_alerts_in_investigations_count           | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_disposed_alerts_count                    | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Referring event id Allows: null                                                                                                                                                                                                     | ref_event_id                                       | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert message Allows: "", null                                                                                                                                                                                                | expel_message                                      | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert name Allows: "", null                                                                                                                                                                                                   | expel_name                                         | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort                                                                                                                                                                                                     | vendor_alert_count                                 | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_closed_alerts_count                      | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel Alert Time first seen time: immutable                                                                                                                                                                                         | expel_alert_time                                   | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                        | cust_disp_alerts_in_incidents_count                | number                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort                                                                                                                                                                                                     | activity_first_at                                  | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert alias Allows: "", null                                                                                                                                                                                                  | expel_alias_name                                   | string                                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                        | source_ip_addresses                                | :class:`IpAddresses`                      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | assigned_to_actor                                  | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Phishing submissions                                                                                                                                                                                                                | phishing_submissions                               | :class:`PhishingSubmissions`              | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                               | investigative_actions                              | :class:`InvestigativeActions`             | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | created_by                                         | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                                                                                                                                               | expel_alert_histories                              | :class:`ExpelAlertHistories`              | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                       | vendor_alerts                                      | :class:`VendorAlerts`                     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                        | destination_ip_addresses                           | :class:`IpAddresses`                      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                        | similar_alerts                                     | :class:`ExpelAlerts`                      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                                                                      | investigative_action_histories                     | :class:`InvestigativeActionHistories`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendors                                                                                                                                                                                                                             | vendor                                             | :class:`Vendors`                          | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | updated_by                                         | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                      | related_investigations_via_involved_host_ips       | :class:`Investigations`                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                                                                                                                                         | evidence                                           | :class:`VendorAlertEvidences`             | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                      | investigation                                      | :class:`Investigations`                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                      | related_investigations                             | :class:`Investigations`                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                       | coincident_vendor_alerts                           | :class:`VendorAlerts`                     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                     | organization                                       | :class:`Organizations`                    | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                            | status_last_updated_by                             | :class:`Actors`                           | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                    | context_labels                                     | :class:`ContextLabels`                    | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alerts'
    _def_attributes = ["disposition_disposed_alerts_count", "close_comment", "tuning_requested", "status", "git_rule_url", "disposition_closed_alerts_count", "updated_at", "status_updated_at", "created_at", "expel_version", "close_reason", "activity_last_at", "disposition_alerts_in_critical_incidents_count", "disposition_alerts_in_incidents_count", "cust_disp_alerts_in_critical_incidents_count",
                       "expel_signature_id", "expel_severity", "alert_type", "disposition_alerts_in_investigations_count", "cust_disp_alerts_in_investigations_count", "cust_disp_disposed_alerts_count", "ref_event_id", "expel_message", "expel_name", "vendor_alert_count", "cust_disp_closed_alerts_count", "expel_alert_time", "cust_disp_alerts_in_incidents_count", "activity_first_at", "expel_alias_name"]
    _def_relationships = ["source_ip_addresses", "assigned_to_actor", "phishing_submissions", "investigative_actions", "created_by", "expel_alert_histories", "vendor_alerts", "destination_ip_addresses", "similar_alerts",
                          "investigative_action_histories", "vendor", "updated_by", "related_investigations_via_involved_host_ips", "evidence", "investigation", "related_investigations", "coincident_vendor_alerts", "organization", "status_last_updated_by", "context_labels"]


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
        | Investigations                                                                         | investigation     | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                             | comment           | :class:`Comments`           | N             | Y                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                               | created_by        | :class:`Actors`             | N             | Y                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'comment_histories'
    _def_attributes = ["created_at", "action", "value"]
    _def_relationships = ["investigation", "comment", "created_by"]


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
        | Created timestamp: readonly                                       | created_at       | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image sha256 hash Allows: null                          | hash_sha256      | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image release date Allows: null                         | release_date     | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Platform Restricted to: "VMWARE", "HYPERV", "AZURE", "AMAZON"     | platform         | any                 | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image size Allows: null                                 | size             | number              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image md5 hash Allows: null                             | hash_md5         | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image sh1 hash Allows: null                             | hash_sha1        | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image version Allows: "", null                          | version          | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                  | updated_at       | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | updated_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | created_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+

    '''
    _api_type = 'assembler_images'
    _def_attributes = ["created_at", "hash_sha256", "release_date",
                       "platform", "size", "hash_md5", "hash_sha1", "version", "updated_at"]
    _def_relationships = ["updated_by", "created_by"]


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
        | Status.    Note: By default if the security device has an assembler, and that assembler is unhealthy, the status will return that information rather than the raw status of the security device.  To disable this behavior, add the query parameter `flag[raw_status]=true`. Restricted to: "healthy", "unhealthy", "health_checks_not_supported" Allows: null     | status                     | any                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Status Details.  Note: By default if the security device has an assembler, and that assembler is unhealthy, the status details will return that information rather than the raw status of the security device.  To disable this behavior, add the query parameter `flag[raw_status]=true`. Allows: null: no-sort                                                   | status_details             | object                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                                                                                                           | status_updated_at          | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Allows: "", null                                                                                                                                                                                                                                                                                                                                                   | plugin_slug                | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                                                                                                                   | updated_at                 | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                                                                                                                  | deleted_at                 | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                        | created_at                 | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Device Spec Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                  | device_spec                | object                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Location Allows: "", null                                                                                                                                                                                                                                                                                                                                          | location                   | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Location where tasks are run Restricted to: "CUSTOMER_PREMISE", "EXPEL_TASKPOOL"                                                                                                                                                                                                                                                                                   | task_source                | any                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Name                                                                                                                                                                                                                                                                                                                                                               | name                       | string                            | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Has 2fa secret stored in vault: readonly                                                                                                                                                                                                                                                                                                                           | has_two_factor_secret      | boolean                           | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Device Type Restricted to: "ENDPOINT", "NETWORK", "SIEM", "OTHER", "CLOUD"                                                                                                                                                                                                                                                                                         | device_type                | any                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                           | updated_by                 | :class:`Actors`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Assemblers                                                                                                                                                                                                                                                                                                                                                         | assembler                  | :class:`Assemblers`               | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                           | created_by                 | :class:`Actors`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                   | child_security_devices     | :class:`SecurityDevices`          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                                                                                                              | investigative_actions      | :class:`InvestigativeActions`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                                                                                                                                                      | vendor_alerts              | :class:`VendorAlerts`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                                                                                                                    | organization               | :class:`Organizations`            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                   | parent_security_device     | :class:`SecurityDevices`          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+
        | Vendors                                                                                                                                                                                                                                                                                                                                                            | vendor                     | :class:`Vendors`                  | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'security_devices'
    _def_attributes = ["status", "status_details", "status_updated_at", "plugin_slug", "updated_at", "deleted_at",
                       "created_at", "device_spec", "location", "task_source", "name", "has_two_factor_secret", "device_type"]
    _def_relationships = ["updated_by", "assembler", "created_by", "child_security_devices",
                          "investigative_actions", "vendor_alerts", "organization", "parent_security_device", "vendor"]


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
        | Expel alerts                                                                                                                                                                                                                                                                                                                                      | evidenced_expel_alerts     | :class:`ExpelAlerts`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                                                                                                                                     | vendor_alert               | :class:`VendorAlerts`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+

    '''
    _api_type = 'vendor_alert_evidences'
    _def_attributes = ["evidence", "evidence_type"]
    _def_relationships = ["evidenced_expel_alerts", "vendor_alert"]


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
        | Created timestamp: readonly                                            | created_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | The event, such as Powershell Attack Allows: "", null                  | event                     | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | The type of the event, such as Carbon Black Alert Allows: "", null     | event_type                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Source Host (IP or Hostname) Allows: "", null                          | src_host                  | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Destination Host (IP or Hostname) Allows: "", null                     | dest_host                 | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Date/Time of when the event occurred                                   | event_date                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Attack phase of the Timeline Entry Allows: "", null                    | attack_phase              | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                       | updated_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Comment on this Timeline Entry Allows: "", null                        | comment                   | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                      | deleted_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Has been selected for final report.                                    | is_selected               | boolean                          | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                               | updated_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                | context_label_actions     | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Investigations                                                         | investigation             | :class:`Investigations`          | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                               | created_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                       | context_labels            | :class:`ContextLabels`           | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Expel alerts                                                           | expel_alert               | :class:`ExpelAlerts`             | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'timeline_entries'
    _def_attributes = ["created_at", "event", "event_type", "src_host", "dest_host",
                       "event_date", "attack_phase", "updated_at", "comment", "deleted_at", "is_selected"]
    _def_relationships = ["updated_by", "context_label_actions",
                          "investigation", "created_by", "context_labels", "expel_alert"]


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
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | created_at             | string                          | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation action history action Restricted to: "CREATED", "ASSIGNED", "COMPLETED", "CLOSED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | action                 | any                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Action type of source parent remediation action Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type            | any                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation action history details Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | value                  | object                          | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | remediation_action     | :class:`RemediationActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | assigned_to_actor      | :class:`Actors`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | investigation          | :class:`Investigations`         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | created_by             | :class:`Actors`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_histories'
    _def_attributes = ["created_at", "action", "action_type", "value"]
    _def_relationships = ["remediation_action", "assigned_to_actor", "investigation", "created_by"]


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
        | Defines/retrieves expel.io actor records                       | updated_by                    | :class:`Actors`                      | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                | organization                  | :class:`Organizations`               | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records               | context_labels                | :class:`ContextLabels`               | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                       | created_by                    | :class:`Actors`                      | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action assets                                      | remediation_action_assets     | :class:`RemediationActionAssets`     | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_tags'
    _def_attributes = ["created_at", "metadata", "description", "tag", "updated_at"]
    _def_relationships = ["updated_by", "organization", "context_labels", "created_by", "remediation_action_assets"]


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
            'o365_tos_id': 'string',
            'postal_code': 'string',
            'region': 'string',
            'service_renewal_at': '2019-01-15T15:35:00-05:00',
            'service_start_at': '2019-01-15T15:35:00-05:00',
            'short_name': 'EXP',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'users_count': 100}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Field Description                                                                                             | Field Name                                        | Field Type                                      | Attribute     | Relationship     |
        +===============================================================================================================+===================================================+=================================================+===============+==================+
        | City Allows: "", null                                                                                         | city                                              | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | State/Province/Region Allows: "", null                                                                        | region                                            | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Address 2 Allows: "", null                                                                                    | address_2                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The city where the organization's headquarters is located Allows: "", null                                    | hq_city                                           | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                              | updated_at                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Country Code Allows: null                                                                                     | country_code                                      | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Is surge                                                                                                      | is_surge                                          | boolean                                         | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Number of users covered for this organization Allows: null                                                    | users_count                                       | number                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                   | created_at                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization service renewal date Allows: null                                                                | service_renewal_at                                | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The organization's primary industry Allows: "", null                                                          | industry                                          | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The organization's operating name                                                                             | name                                              | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Address 1 Allows: "", null                                                                                    | address_1                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Postal Code Allows: null                                                                                      | postal_code                                       | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization short name Allows: null                                                                          | short_name                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Number of nodes covered for this organization Allows: null                                                    | nodes_count                                       | number                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization service start date Allows: null                                                                  | service_start_at                                  | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                             | deleted_at                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Allows: "", null                                                                                              | hq_utc_offset                                     | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | o365 Terms of Service identifier (e.g. hubspot id, etc.) Allows: null                                         | o365_tos_id                                       | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | updated_by                                        | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                                                                                | nist_subcategory_scores                           | :class:`NistSubcategoryScores`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | actor                                             | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | created_by                                        | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                 | notification_preferences                          | :class:`NotificationPreferences`                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                           | assigned_remediation_actions                      | :class:`RemediationActions`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io api_key records. These can only be created by a user and require an OTP token.     | api_keys                                          | :class:`ApiKeys`                                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io configuration records                                                              | configurations                                    | :class:`Configurations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | investigations                                    | :class:`Investigations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io engagement_manager records                                                         | engagement_manager                                | :class:`EngagementManagers`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                 | vendor_alerts                                     | :class:`VendorAlerts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io integration records                                                                | integrations                                      | :class:`Integrations`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_resilience_action_group records                                       | organization_resilience_action_groups             | :class:`OrganizationResilienceActionGroups`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | assigned_investigative_actions                    | :class:`InvestigativeActions`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | File                                                                                                          | files                                             | :class:`Files`                                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User accounts                                                                                                 | user_accounts                                     | :class:`UserAccounts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigation histories                                                                                       | investigation_histories                           | :class:`InvestigationHistories`                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                         | expel_alert_histories                             | :class:`ExpelAlertHistories`                    | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Product features                                                                                              | features                                          | :class:`Features`                               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization status                                                                                           | organization_status                               | :class:`OrganizationStatuses`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User accounts                                                                                                 | user_accounts_with_roles                          | :class:`UserAccounts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | SAML Identity Providers                                                                                       | saml_identity_provider                            | :class:`SamlIdentityProviders`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Assemblers                                                                                                    | assemblers                                        | :class:`Assemblers`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | organization_resilience_actions                   | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | expel_alerts                                      | :class:`ExpelAlerts`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Products                                                                                                      | products                                          | :class:`Products`                               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                              | context_labels                                    | :class:`ContextLabels`                          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | assigned_investigations                           | :class:`Investigations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Security devices                                                                                              | security_devices                                  | :class:`SecurityDevices`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | assigned_expel_alerts                             | :class:`ExpelAlerts`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | assignables                                       | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                                                          | context_label_tags                                | :class:`ContextLabelTags`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                                                    | comments                                          | :class:`Comments`                               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io user_account_role records                                                          | organization_user_account_roles                   | :class:`UserAccountRoles`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+---------------------------------------------------+-------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organizations'
    _def_attributes = ["city", "region", "address_2", "hq_city", "updated_at", "country_code", "is_surge", "users_count", "created_at", "service_renewal_at",
                       "industry", "name", "address_1", "postal_code", "short_name", "nodes_count", "service_start_at", "deleted_at", "hq_utc_offset", "o365_tos_id"]
    _def_relationships = ["updated_by", "nist_subcategory_scores", "actor", "created_by", "notification_preferences", "assigned_remediation_actions", "api_keys", "configurations", "assigned_organization_resilience_actions", "investigations", "engagement_manager", "vendor_alerts", "assigned_organization_resilience_actions_list", "integrations", "organization_resilience_action_groups", "assigned_investigative_actions", "files", "user_accounts",
                          "investigation_histories", "expel_alert_histories", "analysis_assigned_investigative_actions", "features", "organization_status", "user_accounts_with_roles", "saml_identity_provider", "assemblers", "organization_resilience_actions", "expel_alerts", "products", "context_labels", "assigned_investigations", "security_devices", "assigned_expel_alerts", "assignables", "context_label_tags", "comments", "organization_user_account_roles"]


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
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | category_name                        | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization actual score for this nist subcategory Allows: null                                                                                                                                                                                                   | actual_score                         | number                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Recorded date of the score assessment (Note: Dates with times will be truncated to the day.  Warning: Dates times and timezones will be converted to UTC before they are truncated.  Providing non-UTC timezones is not recommeneded.) Allows: null: immutable     | assessment_date                      | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                   | updated_at                           | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: immutable, no-sort                                                                                                                                                                                                                               | subcategory_identifier               | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization target score for this nist subcategory Allows: null                                                                                                                                                                                                   | target_score                         | number                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | function_type                        | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                        | created_at                           | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization nist subcategory is a priority                                                                                                                                                                                                                        | is_priority                          | boolean                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | subcategory_name                     | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort                                                                                                                                                                                                                    | category_identifier                  | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization comment for this nist subcategory Allows: "", null                                                                                                                                                                                                    | comment                              | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                           | updated_by                           | :class:`Actors`                            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                    | organization                         | :class:`Organizations`                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | NIST Subcategory Score History                                                                                                                                                                                                                                     | nist_subcategory_score_histories     | :class:`NistSubcategoryScoreHistories`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_subcategory records                                                                                                                                                                                                                | nist_subcategory                     | :class:`NistSubcategories`                 | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                           | created_by                           | :class:`Actors`                            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategory_scores'
    _def_attributes = ["category_name", "actual_score", "assessment_date", "updated_at", "subcategory_identifier",
                       "target_score", "function_type", "created_at", "is_priority", "subcategory_name", "category_identifier", "comment"]
    _def_relationships = ["updated_by", "organization",
                          "nist_subcategory_score_histories", "nist_subcategory", "created_by"]


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
        | Organization to resilience actions           | organization_resilience_action     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                               | investigation                      | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                         | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_resilience_actions'
    _def_attributes = ["created_at", "updated_at"]
    _def_relationships = ["updated_by", "organization_resilience_action", "investigation", "created_by"]


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
        | Global Resilience Group Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS"     | category               | any                            | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Group title                                                                                 | title                  | string                         | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                    | updated_by             | :class:`Actors`                | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Resilience actions                                                                          | resilience_actions     | :class:`ResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                    | created_by             | :class:`Actors`                | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+

    '''
    _api_type = 'resilience_action_groups'
    _def_attributes = ["created_at", "updated_at", "category", "title"]
    _def_relationships = ["updated_by", "resilience_actions", "created_by"]


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
        | Created timestamp: readonly                                           | created_at                                        | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                      | updated_at                                        | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Actor type Restricted to: "system", "user", "organization", "api"     | actor_type                                        | any                                        | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Meta: readonly, no-sort                                               | is_expel                                          | boolean                                    | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Display name Allows: "", null                                         | display_name                                      | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | updated_by                                        | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                 | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | child_actors                                      | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User accounts                                                         | user_account                                      | :class:`UserAccounts`                      | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | created_by                                        | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Remediation actions                                                   | assigned_remediation_actions                      | :class:`RemediationActions`                | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`     | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User Notification Preferences                                         | notification_preferences                          | :class:`NotificationPreferences`           | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                                          | assigned_expel_alerts                             | :class:`ExpelAlerts`                       | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | parent_actor                                      | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                       | organization                                      | :class:`Organizations`                     | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                        | assigned_investigations                           | :class:`Investigations`                    | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                 | assigned_investigative_actions                    | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'actors'
    _def_attributes = ["created_at", "updated_at", "actor_type", "is_expel", "display_name"]
    _def_relationships = ["updated_by", "analysis_assigned_investigative_actions", "child_actors", "user_account", "created_by", "assigned_remediation_actions", "assigned_organization_resilience_actions",
                          "notification_preferences", "assigned_expel_alerts", "parent_actor", "assigned_organization_resilience_actions_list", "organization", "assigned_investigations", "assigned_investigative_actions"]


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
        | Nist subcategory abbreviated identifier              | identifier                  | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                     | updated_at                  | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Nist subcategory title Allows: "", null              | name                        | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_category records     | nist_category               | :class:`NistCategories`            | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                       | nist_subcategory_scores     | :class:`NistSubcategoryScores`     | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records             | updated_by                  | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records             | created_by                  | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategories'
    _def_attributes = ["created_at", "identifier", "updated_at", "name"]
    _def_relationships = ["nist_category", "nist_subcategory_scores", "updated_by", "created_by"]


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
        | Visible                                                                                           | visible                                          | boolean                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                  | updated_at                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization Resilience Group Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS"     | category                                         | any                                        | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Group title                                                                                       | title                                            | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | updated_by                                       | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                   | organization                                     | :class:`Organizations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                | organization_resilience_action_group_actions     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | created_by                                       | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_group records                                        | source_resilience_action_group                   | :class:`ResilienceActionGroups`            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organization_resilience_action_groups'
    _def_attributes = ["created_at", "visible", "updated_at", "category", "title"]
    _def_relationships = ["updated_by", "organization",
                          "organization_resilience_action_group_actions", "created_by", "source_resilience_action_group"]


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
        | Last Updated timestamp: readonly                                     | updated_at                          | string                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Name                                                                 | name                                | string                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | updated_by                          | :class:`Actors`                           | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold_history records     | expel_alert_threshold_histories     | :class:`ExpelAlertThresholdHistories`     | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records             | suppresses                          | :class:`ExpelAlertThresholds`             | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | created_by                          | :class:`Actors`                           | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records             | suppressed_by                       | :class:`ExpelAlertThresholds`             | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_thresholds'
    _def_attributes = ["created_at", "threshold", "updated_at", "name"]
    _def_relationships = ["updated_by", "expel_alert_threshold_histories", "suppresses", "created_by", "suppressed_by"]


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
            'name': 'string',
            'realm': 'public',
            'role': 'expel_admin',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                                         | Field Name       | Field Type                 | Attribute     | Relationship     |
        +===========================================================================================================================================+==================+============================+===============+==================+
        | Only upon initial api key creation (POST), contains the bearer api key token required for api access.: readonly, no-sort                  | access_token     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                               | created_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Active Allows: null                                                                                                                       | active           | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Display name Allows: null                                                                                                                 | display_name     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Can Api key be assigned items (e.g. investigations, etc)                                                                                  | assignable       | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Missing Description                                                                                                                       | name             | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Realm in which the api key can be used. Restricted to: "public", "internal"                                                               | realm            | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Role Restricted to: "expel_admin", "expel_analyst", "organization_admin", "organization_analyst", "system", "anonymous", "restricted"     | role             | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                          | updated_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                  | updated_by       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                           | organization     | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                  | created_by       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'api_keys'
    _def_attributes = ["access_token", "created_at", "active",
                       "display_name", "assignable", "name", "realm", "role", "updated_at"]
    _def_relationships = ["updated_by", "organization", "created_by"]


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


class ResilienceActions(ResourceInstance):
    '''
    .. _api resilience_actions:

    Resilience actions

    Resource type name is **resilience_actions**.

    Example JSON record:

    .. code-block:: javascript

        {'category': 'DISRUPT_ATTACKERS', 'created_at': '2019-01-15T15:35:00-05:00', 'details': 'string', 'impact': 'LOW', 'title': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Field Description                                                                | Field Name                  | Field Type                          | Attribute     | Relationship     |
        +==================================================================================+=============================+=====================================+===============+==================+
        | Created timestamp: readonly                                                      | created_at                  | string                              | Y             | N                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Details                                                                          | details                     | string                              | Y             | N                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH"                                    | impact                      | any                                 | Y             | N                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Title                                                                            | title                       | string                              | Y             | N                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                 | updated_at                  | string                              | Y             | N                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null     | category                    | any                                 | Y             | N                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | updated_by                  | :class:`Actors`                     | N             | Y                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_group records                       | resilience_action_group     | :class:`ResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | created_by                  | :class:`Actors`                     | N             | Y                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+

    '''
    _api_type = 'resilience_actions'
    _def_attributes = ["created_at", "details", "impact", "title", "updated_at", "category"]
    _def_relationships = ["updated_by", "resilience_action_group", "created_by"]


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
        | Capability name Allows: "", null                                                                                                                                                | capability_name                     | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Verify Investigative action verified by Allows: null                                                                                                                            | activity_verified_by                | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Task input arguments Allows: null: no-sort                                                                                                                                      | input_args                          | object                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Verify Investigative action is authorized Allows: null                                                                                                                          | activity_authorized                 | boolean                                   | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Result byte size: readonly                                                                                                                                                      | result_byte_size                    | number                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Downgrade reason Restricted to: "FALSE_POSITIVE", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "OTHER" Allows: null     | downgrade_reason                    | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                     | created_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Result task id Allows: null: readonly                                                                                                                                           | result_task_id                      | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Close Reason Allows: null                                                                                                                                                       | close_reason                        | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action created by robot action: readonly                                                                                                                          | robot_action                        | boolean                                   | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Taskability action id Allows: "", null                                                                                                                                          | taskability_action_id               | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Workflow name Allows: "", null                                                                                                                                                  | workflow_name                       | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Restricted to: "RUNNING", "FAILED", "READY_FOR_ANALYSIS", "CLOSED", "COMPLETED"                                                                                          | status                              | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative Action Type Restricted to: "TASKABILITY", "HUNTING", "MANUAL", "RESEARCH", "PIVOT", "QUICK_UPLOAD", "VERIFY", "DOWNGRADE", "WORKFLOW", "NOTIFY"                   | action_type                         | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                               | deleted_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                | updated_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Title                                                                                                                                                                           | title                               | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Instructions Allows: "", null                                                                                                                                                   | instructions                        | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Taskabilities error Allows: "", null: no-sort                                                                                                                                   | tasking_error                       | object                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                        | status_updated_at                   | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Reason                                                                                                                                                                          | reason                              | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Workflow job id Allows: "", null                                                                                                                                                | workflow_job_id                     | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Downgrade reason: readonly                                                                                                                                                      | files_count                         | number                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Results/Analysis Allows: "", null                                                                                                                                               | results                             | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | updated_by                          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | assigned_to_actor                   | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                  | investigation                       | :class:`Investigations`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                           | depends_on_investigative_action     | :class:`InvestigativeActions`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | created_by                          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                           | dependent_investigative_actions     | :class:`InvestigativeActions`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                | security_device                     | :class:`SecurityDevices`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                    | expel_alert                         | :class:`ExpelAlerts`                      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                  | investigative_action_histories      | :class:`InvestigativeActionHistories`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | File                                                                                                                                                                            | files                               | :class:`Files`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | analysis_assigned_to_actor          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_actions'
    _def_attributes = ["capability_name", "activity_verified_by", "input_args", "activity_authorized", "result_byte_size", "downgrade_reason", "created_at", "result_task_id", "close_reason", "robot_action",
                       "taskability_action_id", "workflow_name", "status", "action_type", "deleted_at", "updated_at", "title", "instructions", "tasking_error", "status_updated_at", "reason", "workflow_job_id", "files_count", "results"]
    _def_relationships = ["updated_by", "assigned_to_actor", "investigation", "depends_on_investigative_action", "created_by",
                          "dependent_investigative_actions", "security_device", "expel_alert", "investigative_action_histories", "files", "analysis_assigned_to_actor"]


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
        | Allows: "", null                                    | cert             | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Allows: ""                                          | entity_id        | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Allows: ""                                          | callback_uri     | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Restricted to: "not_configured", "configured"       | status           | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'saml_identity_providers'
    _def_attributes = ["cert", "entity_id", "callback_uri", "status"]
    _def_relationships = ["organization"]


class Secrets(ResourceInstance):
    '''
    .. _api secrets:

    Organization secrets. Note - these requests must be in the format of `/secrets/security_device-<guid>`

    Resource type name is **secrets**.

    Example JSON record:

    .. code-block:: javascript

        {           'secret': {           'device_info': {'access_id': '7b0a343c-860e-442e-ab0b-d6f349d364d9', 'access_key': 'secret-access-key', 'source_category': 'alpha'},
                                  'device_secret': {'console_url': 'https://console-access-point.com', 'password': 'password', 'username': 'admin@company.com'},
                                  'two_factor_secret': 'GNFXSU2OKNJXUPTGJVQUMNDHM4YVEKRJ'}}


    Below are valid filter by parameters:

        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name       | Field Type                 | Attribute     | Relationship     |
        +=====================================================+==================+============================+===============+==================+
        | Allows: null                                        | secret           | object                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'secrets'
    _def_attributes = ["secret"]
    _def_relationships = ["organization"]


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
        | Created timestamp: readonly                         | created_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Phone number Allows: null                           | phone_number      | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Display name Allows: "", null                       | display_name      | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Email Allows: null                                  | email             | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organizations     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'engagement_managers'
    _def_attributes = ["created_at", "phone_number", "display_name", "updated_at", "email"]
    _def_relationships = ["updated_by", "created_by", "organizations"]


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
            'language': 'string',
            'last_name': 'string',
            'locale': 'string',
            'phone_number': 'string',
            'timezone': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                | Field Name                                        | Field Type                                 | Attribute     | Relationship     |
        +==================================================================================================================================+===================================================+============================================+===============+==================+
        | Active Allows: null                                                                                                              | active                                            | boolean                                    | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Can user be assigned items (e.g. investigations, etc)                                                                            | assignable                                        | boolean                                    | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Locale Allows: "", null                                                                                                          | locale                                            | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Is an engagement manager                                                                                                         | engagement_manager                                | boolean                                    | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Name                                                                                                                        | last_name                                         | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                 | updated_at                                        | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Email                                                                                                                            | email                                             | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                      | created_at                                        | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Display name Allows: "", null                                                                                                    | display_name                                      | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Language Allows: "", null                                                                                                        | language                                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Timezone Allows: "", null                                                                                                        | timezone                                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Phone number Allows: null                                                                                                        | phone_number                                      | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Restricted to: "ACTIVE", "LOCKED", "LOCKED_INVITED", "LOCKED_EXPIRED", "ACTIVE_INVITED", "ACTIVE_EXPIRED": readonly, no-sort     | active_status                                     | any                                        | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Homepage preferences Allows: null: no-sort                                                                                       | homepage_preferences                              | object                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | First Name                                                                                                                       | first_name                                        | string                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                         | updated_by                                        | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                         | actor                                             | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                  | primary_organization                              | :class:`Organizations`                     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                         | created_by                                        | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                              | assigned_remediation_actions                      | :class:`RemediationActions`                | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io user_account_role records                                                                             | user_account_roles                                | :class:`UserAccountRoles`                  | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                            | analysis_assigned_investigative_actions           | :class:`InvestigativeActions`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                               | assigned_organization_resilience_actions          | :class:`OrganizationResilienceActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                                    | notification_preferences                          | :class:`NotificationPreferences`           | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                     | assigned_expel_alerts                             | :class:`ExpelAlerts`                       | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                               | assigned_organization_resilience_actions_list     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User account status                                                                                                              | user_account_status                               | :class:`UserAccountStatuses`               | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                   | assigned_investigations                           | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                            | assigned_investigative_actions                    | :class:`InvestigativeActions`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                  | organizations                                     | :class:`Organizations`                     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------+---------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'user_accounts'
    _def_attributes = ["active", "assignable", "locale", "engagement_manager", "last_name", "updated_at", "email", "created_at",
                       "display_name", "language", "timezone", "phone_number", "active_status", "homepage_preferences", "first_name"]
    _def_relationships = ["updated_by", "actor", "primary_organization", "created_by", "assigned_remediation_actions", "user_account_roles", "analysis_assigned_investigative_actions", "assigned_organization_resilience_actions",
                          "notification_preferences", "assigned_expel_alerts", "assigned_organization_resilience_actions_list", "user_account_status", "assigned_investigations", "assigned_investigative_actions", "organizations"]


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
        | Investigation history action Restricted to: "CREATED", "ASSIGNED", "CHANGED", "CLOSED", "SUMMARY", "REOPENED", "PUBLISHED" Allows: null     | action                | any                         | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Is Incidence                                                                                                                                | is_incident           | boolean                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigation history details Allows: null: no-sort                                                                                         | value                 | object                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | assigned_to_actor     | :class:`Actors`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigations                                                                                                                              | investigation         | :class:`Investigations`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | created_by            | :class:`Actors`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                             | organization          | :class:`Organizations`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_histories'
    _def_attributes = ["created_at", "action", "is_incident", "value"]
    _def_relationships = ["assigned_to_actor", "investigation", "created_by", "organization"]


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
        | Defines/retrieves expel.io actor records                                                                                                         | assigned_to_actor     | :class:`Actors`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigations                                                                                                                                   | investigation         | :class:`Investigations`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                  | organization          | :class:`Organizations`      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                         | created_by            | :class:`Actors`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                     | expel_alert           | :class:`ExpelAlerts`        | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_histories'
    _def_attributes = ["created_at", "action", "value"]
    _def_relationships = ["assigned_to_actor", "investigation", "organization", "created_by", "expel_alert"]


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
        | Created timestamp: readonly                                             | created_at           | string                       | Y             | N                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | What action to take Restricted to: "ALERT_ON", "ADD_TO", "SUPPRESS"     | action_type          | any                          | Y             | N                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                        | updated_at           | string                       | Y             | N                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                | updated_by           | :class:`Actors`              | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Investigations                                                          | investigation        | :class:`Investigations`      | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                        | context_label        | :class:`ContextLabels`       | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Timeline Entries                                                        | timeline_entries     | :class:`TimelineEntries`     | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                | created_by           | :class:`Actors`              | N             | Y                |
        +-------------------------------------------------------------------------+----------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_actions'
    _def_attributes = ["created_at", "action_type", "updated_at"]
    _def_relationships = ["updated_by", "investigation", "context_label", "timeline_entries", "created_by"]


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
        | Created timestamp: readonly                                                                                                                                                                                                                           | created_at                 | string                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | NIST subcategory score history action Restricted to: "SCORE_UPDATED", "COMMENT_UPDATED", "PRIORITY_UPDATED", "IMPORT"                                                                                                                                 | action                     | any                                | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Organization target score for this nist subcategory                                                                                                                                                                                                   | target_score               | number                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Recorded date of the score assessment (Note: Dates with times will be truncated to the day.  Warning: Dates times and timezones will be converted to UTC before they are truncated.  Providing non-UTC timezones is not recommeneded.): immutable     | assessment_date            | string                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Organization actual score for this nist subcategory                                                                                                                                                                                                   | actual_score               | number                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                                                                                                                                                                                                                        | nist_subcategory_score     | :class:`NistSubcategoryScores`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                              | created_by                 | :class:`Actors`                    | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategory_score_histories'
    _def_attributes = ["created_at", "action", "target_score", "assessment_date", "actual_score"]
    _def_relationships = ["nist_subcategory_score", "created_by"]


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
        | Last Updated timestamp: readonly                    | updated_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | name              | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Products                                            | products          | :class:`Products`          | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organizations     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'features'
    _def_attributes = ["created_at", "updated_at", "name"]
    _def_relationships = ["updated_by", "products", "created_by", "organizations"]


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
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | created_at                   | string                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action asset history action Restricted to: "CREATED", "COMPLETED", "REOPENED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | action                       | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Action type of associated parent remediation action Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type                  | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action asset history details Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | value                        | object                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action assets                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | remediation_action_asset     | :class:`RemediationActionAssets`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | investigation                | :class:`Investigations`              | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | created_by                   | :class:`Actors`                      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_asset_histories'
    _def_attributes = ["created_at", "action", "action_type", "value"]
    _def_relationships = ["remediation_action_asset", "investigation", "created_by"]


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
        | Assembler lifecycle status update timestamp: readonly                                                                                                                                                         | lifecycle_status_updated_at      | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler install code Allows: null                                                                                                                                                                           | install_code                     | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler life cycle status Restricted to: "New", "Authorized", "Transitioning", "Transitioned", "Transition Failed", "Configuring", "Configuration Failed", "Active", "Inactive", "Deleted" Allows: null     | lifecycle_status                 | any                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler connection status Restricted to: "Never Connected", "Connection Lost", "Connected to Provisioning", "Connected to Service" Allows: null                                                             | connection_status                | any                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                              | updated_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                   | created_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler last status update timestamp: readonly                                                                                                                                                              | status_updated_at                | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Location of assembler Allows: "", null                                                                                                                                                                        | location                         | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler connection status update timestamp: readonly                                                                                                                                                        | connection_status_updated_at     | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Name of assembler Allows: "", null                                                                                                                                                                            | name                             | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler status Allows: "", null: readonly, no-sort                                                                                                                                                          | status                           | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                             | deleted_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler VPN ip address Allows: null                                                                                                                                                                         | vpn_ip                           | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                      | updated_by                       | :class:`Actors`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                               | organization                     | :class:`Organizations`       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                 | vendor_alerts                    | :class:`VendorAlerts`        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                              | security_devices                 | :class:`SecurityDevices`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                      | created_by                       | :class:`Actors`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'assemblers'
    _def_attributes = ["lifecycle_status_updated_at", "install_code", "lifecycle_status", "connection_status", "updated_at",
                       "created_at", "status_updated_at", "location", "connection_status_updated_at", "name", "status", "deleted_at", "vpn_ip"]
    _def_relationships = ["updated_by", "organization", "vendor_alerts", "security_devices", "created_by"]


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
        | Created timestamp: readonly                  | created_at                     | string                      | Y             | N                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at                     | string                      | Y             | N                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | IP Address: readonly                         | address                        | string                      | Y             | N                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                     | :class:`Actors`             | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | investigations                 | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                     | :class:`Actors`             | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                 | source_expel_alerts            | :class:`ExpelAlerts`        | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Vendor alerts                                | vendor_alerts                  | :class:`VendorAlerts`       | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | destination_investigations     | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                 | destination_expel_alerts       | :class:`ExpelAlerts`        | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | source_investigations          | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'ip_addresses'
    _def_attributes = ["created_at", "updated_at", "address"]
    _def_relationships = ["updated_by", "investigations", "created_by", "source_expel_alerts",
                          "vendor_alerts", "destination_investigations", "destination_expel_alerts", "source_investigations"]


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
        | Created timestamp: readonly                                                      | created_at                               | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Details                                                                          | details                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Title                                                                            | title                                    | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Visible                                                                          | visible                                  | boolean                                         | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Status Restricted to: "TOP_PRIORITY", "IN_PROGRESS", "WONT_DO", "COMPLETED"      | status                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null     | category                                 | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                 | updated_at                               | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Comment Allows: "", null                                                         | comment                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH"                                    | impact                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | updated_by                               | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | assigned_to_actor                        | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigation to resilience actions                                              | investigation_resilience_actions         | :class:`InvestigationResilienceActions`         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Resilience actions                                                               | source_resilience_action                 | :class:`ResilienceActions`                      | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | created_by                               | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                  | organization                             | :class:`Organizations`                          | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_resilience_action_group records          | organization_resilience_action_group     | :class:`OrganizationResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                   | investigations                           | :class:`Investigations`                         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                   | investigation_hints                      | :class:`Investigations`                         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organization_resilience_actions'
    _def_attributes = ["created_at", "details", "title", "visible",
                       "status", "category", "updated_at", "comment", "impact"]
    _def_relationships = ["updated_by", "assigned_to_actor", "investigation_resilience_actions", "source_resilience_action",
                          "created_by", "organization", "organization_resilience_action_group", "investigations", "investigation_hints"]


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

        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Field Description                                                              | Field Name                 | Field Type                 | Attribute     | Relationship     |
        +================================================================================+============================+============================+===============+==================+
        | Configuration metadata Allows: null: readonly, no-sort                         | metadata                   | object                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Description of configuration value Allows: "", null: readonly                  | description                | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Default configuration value Allows: null: readonly, no-sort                    | default_value              | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Title of configuration value Allows: "", null: readonly                        | title                      | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration key: readonly                                                    | key                        | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Write permission required Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"     | write_permission_level     | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                               | updated_at                 | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                    | created_at                 | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration value validation Allows: null: readonly, no-sort                 | validation                 | object                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration value Allows: null: no-sort                                      | value                      | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration value is an override: readonly                                   | is_override                | boolean                    | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration visibility Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"      | visibility                 | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | updated_by                 | :class:`Actors`            | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                | organization               | :class:`Organizations`     | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | created_by                 | :class:`Actors`            | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'configurations'
    _def_attributes = ["metadata", "description", "default_value", "title", "key", "write_permission_level",
                       "updated_at", "created_at", "validation", "value", "is_override", "visibility"]
    _def_relationships = ["updated_by", "organization", "created_by"]


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
        | Created timestamp: readonly                            | created_at            | string                        | Y             | N                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                       | updated_at            | string                        | Y             | N                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Comment                                                | comment               | string                        | Y             | N                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records               | updated_by            | :class:`Actors`               | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records        | organization          | :class:`Organizations`        | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Investigations                                         | investigation         | :class:`Investigations`       | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records               | created_by            | :class:`Actors`               | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment_history records     | comment_histories     | :class:`CommentHistories`     | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+

    '''
    _api_type = 'comments'
    _def_attributes = ["created_at", "updated_at", "comment"]
    _def_relationships = ["updated_by", "organization", "investigation", "created_by", "comment_histories"]


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
        | File md5 hash                                | file_md5                | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File mime type                               | file_mime               | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File name                                    | file_name               | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File sha256 hash                             | file_sha256             | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | File                                         | attachment_file         | :class:`Files`                   | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by              | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission     | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_attachments'
    _def_attributes = ["file_md5", "file_mime", "file_name", "file_sha256"]
    _def_relationships = ["attachment_file", "created_by", "phishing_submission"]


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
        | Nist category abbreviated identifier                                                | identifier             | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                    | updated_at             | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Nist category name                                                                  | name                   | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Actor type Restricted to: "IDENTIFY", "PROTECT", "DETECT", "RECOVER", "RESPOND"     | function_type          | any                            | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                            | updated_by             | :class:`Actors`                | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                            | created_by             | :class:`Actors`                | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_subcategory records                                 | nist_subcategories     | :class:`NistSubcategories`     | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_categories'
    _def_attributes = ["created_at", "identifier", "updated_at", "name", "function_type"]
    _def_relationships = ["updated_by", "created_by", "nist_subcategories"]


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
        | Last Updated timestamp: readonly             | updated_at           | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Icon Allows: "", null                        | icon                 | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Name Allows: "", null                        | name                 | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by           | :class:`Actors`              | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                | vendor_alerts        | :class:`VendorAlerts`        | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Security devices                             | security_devices     | :class:`SecurityDevices`     | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Expel alerts                                 | expel_alerts         | :class:`ExpelAlerts`         | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by           | :class:`Actors`              | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'vendors'
    _def_attributes = ["created_at", "updated_at", "icon", "name"]
    _def_relationships = ["updated_by", "vendor_alerts", "security_devices", "expel_alerts", "created_by"]


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
        | Created timestamp: readonly                                                  | created_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Metadata about the context label Allows: null: no-sort                       | metadata                  | object                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Description Allows: null, ""                                                 | description               | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Title Allows: null, ""                                                       | title                     | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Date/Time of when the context_label should start being tested                | starts_at                 | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Definition: no-sort                                                          | definition                | object                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                             | updated_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Date/Time of when the context_label should end being tested Allows: null     | ends_at                   | string                           | Y             | N                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                     | updated_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | context_label_actions     | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Timeline Entries                                                             | timeline_entries          | :class:`TimelineEntries`         | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | add_to_actions            | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | suppress_actions          | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                     | created_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                              | organization              | :class:`Organizations`           | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                      | alert_on_actions          | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                         | context_label_tags        | :class:`ContextLabelTags`        | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Expel alerts                                                                 | expel_alerts              | :class:`ExpelAlerts`             | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Investigations                                                               | investigations            | :class:`Investigations`          | N             | Y                |
        +------------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'context_labels'
    _def_attributes = ["created_at", "metadata", "description",
                       "title", "starts_at", "definition", "updated_at", "ends_at"]
    _def_relationships = ["updated_by", "context_label_actions", "timeline_entries", "add_to_actions", "suppress_actions",
                          "created_by", "organization", "alert_on_actions", "context_label_tags", "expel_alerts", "investigations"]

# END AUTO GENERATE JSONAPI CLASSES


RELATIONSHIP_TO_CLASS_EXT = {
}


# AUTO GENERATE RELATIONSHIP TO CLASS LOOKUP

RELATIONSHIP_TO_CLASS = {
    "updated_by": Actors,
    "add_to_actions": ContextLabelActions,
    "investigation_resilience_action_hints": InvestigationResilienceActionHints,
    "user_account_roles": UserAccountRoles,
    "vendor": Vendors,
    "phishing_submission_urls": PhishingSubmissionUrls,
    "suppressed_by": ExpelAlertThresholds,
    "comment_histories": CommentHistories,
    "saml_identity_providers": SamlIdentityProviders,
    "evidenced_expel_alerts": ExpelAlerts,
    "assigned_organization_resilience_actions_list": OrganizationResilienceActions,
    "investigation_findings": InvestigationFindings,
    "files": Files,
    "expel_alert": ExpelAlerts,
    "status_last_updated_by": Actors,
    "resilience_action_group": ResilienceActionGroups,
    "source_expel_alerts": ExpelAlerts,
    "organization_resilience_action_group": OrganizationResilienceActionGroups,
    "expel_alerts": ExpelAlerts,
    "products": Products,
    "assembler_images": AssemblerImages,
    "organization_user_account_roles": UserAccountRoles,
    "secret": Secrets,
    "organization_resilience_action_group_actions": OrganizationResilienceActions,
    "organization": Organizations,
    "remediation_action_histories": RemediationActionHistories,
    "remediation_action_asset_histories": RemediationActionAssetHistories,
    "phishing_submission_attachment": PhishingSubmissionAttachments,
    "organizations": Organizations,
    "remediation_action_assets": RemediationActionAssets,
    "investigation_resilience_actions": InvestigationResilienceActions,
    "child_actors": Actors,
    "suppress_actions": ContextLabelActions,
    "created_by": Actors,
    "expel_alert_histories": ExpelAlertHistories,
    "destination_ip_addresses": IpAddresses,
    "child_security_devices": SecurityDevices,
    "parent_security_device": SecurityDevices,
    "suppresses": ExpelAlertThresholds,
    "expel_alert_threshold": ExpelAlertThresholds,
    "timeline_entries": TimelineEntries,
    "related_investigations": Investigations,
    "review_requested_by": Actors,
    "parent_actor": Actors,
    "organization_resilience_action": OrganizationResilienceActions,
    "secrets": Secrets,
    "destination_investigations": Investigations,
    "user_accounts": UserAccounts,
    "investigation_histories": InvestigationHistories,
    "similar_alerts": ExpelAlerts,
    "context_label_actions": ContextLabelActions,
    "assignables": Actors,
    "depends_on_investigative_action": InvestigativeActions,
    "organization_status": OrganizationStatuses,
    "evidence": VendorAlertEvidences,
    "nist_subcategory": NistSubcategories,
    "assemblers": Assemblers,
    "lead_expel_alert": ExpelAlerts,
    "nist_category": NistCategories,
    "phishing_submission_attachments": PhishingSubmissionAttachments,
    "assigned_remediation_actions": RemediationActions,
    "configurations": Configurations,
    "nist_categories": NistCategories,
    "source_resilience_action_group": ResilienceActionGroups,
    "comments": Comments,
    "phishing_submission_domains": PhishingSubmissionDomains,
    "analysis_email_file": Files,
    "evidences": VendorAlertEvidences,
    "dependent_investigative_actions": InvestigativeActions,
    "vendor_alerts": VendorAlerts,
    "investigative_action_histories": InvestigativeActionHistories,
    "vendor_alert": VendorAlerts,
    "expel_alert_threshold_histories": ExpelAlertThresholdHistories,
    "actor": Actors,
    "related_investigations_via_involved_host_ips": Investigations,
    "remediation_action": RemediationActions,
    "assigned_organization_resilience_actions": OrganizationResilienceActions,
    "investigations": Investigations,
    "investigation_finding_histories": InvestigationFindingHistories,
    "user_account_statuses": UserAccountStatuses,
    "alert_on_actions": ContextLabelActions,
    "assigned_investigative_actions": InvestigativeActions,
    "last_published_by": Actors,
    "phishing_submission_headers": PhishingSubmissionHeaders,
    "findings": InvestigationFindings,
    "assigned_to_actor": Actors,
    "phishing_submissions": PhishingSubmissions,
    "primary_organization": Organizations,
    "investigative_action": InvestigativeActions,
    "activity_metrics": ActivityMetrics,
    "investigation": Investigations,
    "organization_statuses": OrganizationStatuses,
    "organization_resilience_action_groups": OrganizationResilienceActionGroups,
    "security_devices": SecurityDevices,
    "user_account_status": UserAccountStatuses,
    "coincident_vendor_alerts": VendorAlerts,
    "context_label": ContextLabels,
    "context_label_tags": ContextLabelTags,
    "investigation_hints": Investigations,
    "source_ip_addresses": IpAddresses,
    "vendor_alert_evidences": VendorAlertEvidences,
    "resilience_action_groups": ResilienceActionGroups,
    "actors": Actors,
    "raw_body_file": Files,
    "nist_subcategories": NistSubcategories,
    "assigned_investigations": Investigations,
    "expel_alert_thresholds": ExpelAlertThresholds,
    "source_investigations": Investigations,
    "api_keys": ApiKeys,
    "assembler": Assemblers,
    "integrations": Integrations,
    "resilience_actions": ResilienceActions,
    "investigative_actions": InvestigativeActions,
    "attachment_file": Files,
    "comment": Comments,
    "engagement_managers": EngagementManagers,
    "analysis_assigned_to_actor": Actors,
    "remediation_actions": RemediationActions,
    "analysis_assigned_investigative_actions": InvestigativeActions,
    "nist_subcategory_score_histories": NistSubcategoryScoreHistories,
    "user_account": UserAccounts,
    "features": Features,
    "user_accounts_with_roles": UserAccounts,
    "nist_subcategory_scores": NistSubcategoryScores,
    "saml_identity_provider": SamlIdentityProviders,
    "ip_addresses": IpAddresses,
    "organization_resilience_actions": OrganizationResilienceActions,
    "notification_preferences": NotificationPreferences,
    "source_resilience_action": ResilienceActions,
    "phishing_submission": PhishingSubmissions,
    "remediation_action_asset": RemediationActionAssets,
    "engagement_manager": EngagementManagers,
    "nist_subcategory_score": NistSubcategoryScores,
    "assigned_expel_alerts": ExpelAlerts,
    "destination_expel_alerts": ExpelAlerts,
    "initial_email_file": Files,
    "security_device": SecurityDevices,
    "organization_resilience_action_hints": OrganizationResilienceActions,
    "vendors": Vendors,
    "investigation_finding": InvestigationFindings,
    "context_labels": ContextLabels
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
        self.session = None

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
        self.session.headers = {'content-type': 'application/json',
                                'User-Agent': os.path.dirname(__file__).split(os.path.sep)[-1], 'Accept-Encoding': 'gzip'}

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
            logger.error("Got unexpected http response code {}".format(resp.status_code))
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
        headers['User-Agent'] = self.session.headers['User-Agent']

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
                logger.warning("got connection error, recreating session...")
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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
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

    def create_auto_inv_action(self, customer_id: str, vendor_device_id: str, created_by_id: str, capability_name: str, input_args: dict, title: str, reason: str, investigation_id: str = None, expel_alert_id: str = None):
        '''
        Create an automatic investigative action.


        :param customer_id: The customer ID
        :type customer_id: str
        :param investigation_id: The investigation ID to associate the action with.
        :type investigation_id: str
        :param expel_alert_id: The expel alert id
        :type expel_alert_id: str
        :param vendor_device_id: The vendor device ID, to dispatch the task against.
        :type vendor_device_id: str
        :param created_by_id: The user ID that created the action
        :type created_by_id: str
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
            >>> xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=mfa_code)
            >>> input_args = &#123;"user_name": 'willy.wonka@expel.io', 'time_range_start':'2019-01-30T14:00:40Z', 'time_range_end':'2019-01-30T14:45:40Z'&#125;
            >>> o = xc.create_auto_inv_action(customer_guid, inv_guid, device_guid, user_guid, 'query_user', input_args, 'Query User', 'Getting user login activity to determine if login is normal')
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

    def capabilities(self, customer_id: str):
        '''
        Get a list of capabilities for a given customer.

        :param customer_id: The customer ID
        :type customer_id: str

        Examples:
            >>> xc.workbench.capabilities("my-customer-guid-123")
        '''
        resp = self.request('get', '/api/v2/capabilities/%s' % customer_id)
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
    def vendor_alerts(self):
        return BaseResourceObject(VendorAlerts, conn=self)

    @property
    def remediation_action_assets(self):
        return BaseResourceObject(RemediationActionAssets, conn=self)

    @property
    def investigation_resilience_action_hints(self):
        return BaseResourceObject(InvestigationResilienceActionHints, conn=self)

    @property
    def investigative_action_histories(self):
        return BaseResourceObject(InvestigativeActionHistories, conn=self)

    @property
    def user_account_roles(self):
        return BaseResourceObject(UserAccountRoles, conn=self)

    @property
    def phishing_submission_urls(self):
        return BaseResourceObject(PhishingSubmissionUrls, conn=self)

    @property
    def integrations(self):
        return BaseResourceObject(Integrations, conn=self)

    @property
    def expel_alert_threshold_histories(self):
        return BaseResourceObject(ExpelAlertThresholdHistories, conn=self)

    @property
    def investigations(self):
        return BaseResourceObject(Investigations, conn=self)

    @property
    def remediation_actions(self):
        return BaseResourceObject(RemediationActions, conn=self)

    @property
    def products(self):
        return BaseResourceObject(Products, conn=self)

    @property
    def investigation_finding_histories(self):
        return BaseResourceObject(InvestigationFindingHistories, conn=self)

    @property
    def user_account_statuses(self):
        return BaseResourceObject(UserAccountStatuses, conn=self)

    @property
    def investigation_findings(self):
        return BaseResourceObject(InvestigationFindings, conn=self)

    @property
    def organization_statuses(self):
        return BaseResourceObject(OrganizationStatuses, conn=self)

    @property
    def files(self):
        return BaseResourceObject(Files, conn=self)

    @property
    def phishing_submission_headers(self):
        return BaseResourceObject(PhishingSubmissionHeaders, conn=self)

    @property
    def findings(self):
        return BaseResourceObject(Findings, conn=self)

    @property
    def phishing_submissions(self):
        return BaseResourceObject(PhishingSubmissions, conn=self)

    @property
    def activity_metrics(self):
        return BaseResourceObject(ActivityMetrics, conn=self)

    @property
    def expel_alerts(self):
        return BaseResourceObject(ExpelAlerts, conn=self)

    @property
    def comment_histories(self):
        return BaseResourceObject(CommentHistories, conn=self)

    @property
    def assembler_images(self):
        return BaseResourceObject(AssemblerImages, conn=self)

    @property
    def security_devices(self):
        return BaseResourceObject(SecurityDevices, conn=self)

    @property
    def vendor_alert_evidences(self):
        return BaseResourceObject(VendorAlertEvidences, conn=self)

    @property
    def timeline_entries(self):
        return BaseResourceObject(TimelineEntries, conn=self)

    @property
    def remediation_action_histories(self):
        return BaseResourceObject(RemediationActionHistories, conn=self)

    @property
    def context_label_tags(self):
        return BaseResourceObject(ContextLabelTags, conn=self)

    @property
    def organizations(self):
        return BaseResourceObject(Organizations, conn=self)

    @property
    def nist_subcategory_scores(self):
        return BaseResourceObject(NistSubcategoryScores, conn=self)

    @property
    def investigation_resilience_actions(self):
        return BaseResourceObject(InvestigationResilienceActions, conn=self)

    @property
    def resilience_action_groups(self):
        return BaseResourceObject(ResilienceActionGroups, conn=self)

    @property
    def actors(self):
        return BaseResourceObject(Actors, conn=self)

    @property
    def nist_subcategories(self):
        return BaseResourceObject(NistSubcategories, conn=self)

    @property
    def organization_resilience_action_groups(self):
        return BaseResourceObject(OrganizationResilienceActionGroups, conn=self)

    @property
    def expel_alert_thresholds(self):
        return BaseResourceObject(ExpelAlertThresholds, conn=self)

    @property
    def api_keys(self):
        return BaseResourceObject(ApiKeys, conn=self)

    @property
    def notification_preferences(self):
        return BaseResourceObject(NotificationPreferences, conn=self)

    @property
    def resilience_actions(self):
        return BaseResourceObject(ResilienceActions, conn=self)

    @property
    def investigative_actions(self):
        return BaseResourceObject(InvestigativeActions, conn=self)

    @property
    def saml_identity_providers(self):
        return BaseResourceObject(SamlIdentityProviders, conn=self)

    @property
    def secrets(self):
        return BaseResourceObject(Secrets, conn=self)

    @property
    def engagement_managers(self):
        return BaseResourceObject(EngagementManagers, conn=self)

    @property
    def user_accounts(self):
        return BaseResourceObject(UserAccounts, conn=self)

    @property
    def investigation_histories(self):
        return BaseResourceObject(InvestigationHistories, conn=self)

    @property
    def expel_alert_histories(self):
        return BaseResourceObject(ExpelAlertHistories, conn=self)

    @property
    def context_label_actions(self):
        return BaseResourceObject(ContextLabelActions, conn=self)

    @property
    def nist_subcategory_score_histories(self):
        return BaseResourceObject(NistSubcategoryScoreHistories, conn=self)

    @property
    def features(self):
        return BaseResourceObject(Features, conn=self)

    @property
    def remediation_action_asset_histories(self):
        return BaseResourceObject(RemediationActionAssetHistories, conn=self)

    @property
    def assemblers(self):
        return BaseResourceObject(Assemblers, conn=self)

    @property
    def ip_addresses(self):
        return BaseResourceObject(IpAddresses, conn=self)

    @property
    def organization_resilience_actions(self):
        return BaseResourceObject(OrganizationResilienceActions, conn=self)

    @property
    def configurations(self):
        return BaseResourceObject(Configurations, conn=self)

    @property
    def comments(self):
        return BaseResourceObject(Comments, conn=self)

    @property
    def phishing_submission_domains(self):
        return BaseResourceObject(PhishingSubmissionDomains, conn=self)

    @property
    def phishing_submission_attachments(self):
        return BaseResourceObject(PhishingSubmissionAttachments, conn=self)

    @property
    def nist_categories(self):
        return BaseResourceObject(NistCategories, conn=self)

    @property
    def vendors(self):
        return BaseResourceObject(Vendors, conn=self)

    @property
    def context_labels(self):
        return BaseResourceObject(ContextLabels, conn=self)

# END AUTO GENERATE PROPERTIES
