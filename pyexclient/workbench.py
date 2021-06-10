#!/usr/bin/env python
import copy
import datetime
import io
import json
import logging
import os
import pprint
import warnings
from urllib.parse import urlencode
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


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
            raise ValueError(
                'Relationship operator has no class relationships defined')

        if self.rel_parts[0] not in self.rels:
            raise ValueError("%s not a defined relationship in %s" %
                             (self.rel_parts[0], ','.join(self.rels)))

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
            raise ValueError(
                'Sort operator expects asc|desc but got {}'.format(order))

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
                    qstr = 'filter' + \
                        ''.join(['[%s]' % part for part in parts])
                    if has_id:
                        qstr += '[id]'
                    query.append((qstr, value))
                    kwargs.pop(orig_name, None)

                if not len(kwargs):
                    break
        if kwargs:
            raise Exception("Unrecognized parameters %s!" % ','.join(
                ["%s=%s" % (k, v) for k, v in kwargs.items()]))

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

        content['data'] = [RELATIONSHIP_TO_CLASS[entry['type']]
                           (entry, self.conn) for entry in entries]
        content['included'] = [RELATIONSHIP_TO_CLASS[entry['type']]
                               (entry, self.conn) for entry in included if entry['type'] in RELATIONSHIP_TO_CLASS.keys()]
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
        warnings.warn(
            'filter_by has been deprecated in favor of search', DeprecationWarning)
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

        url = self.make_url(self.api_type, value=kwargs['id'])
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

        while next_uri:
            content = self._fetch_page(next_uri)
            for entry in content['data']:
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

MACGYVER_FIELD_TO_TYPE_GEN = {'actor': 'actors',
                              'add_to_actions': 'context_label_actions',
                              'alert_assignables': 'actors',
                              'alert_on_actions': 'context_label_actions',
                              'analysis_assigned_investigative_actions': 'investigative_actions',
                              'analysis_assigned_to_actor': 'actors',
                              'analysis_email_file': 'files',
                              'api_keys': 'api_keys',
                              'approval_histories': 'context_label_histories',
                              'assembler': 'assemblers',
                              'assemblers': 'assemblers',
                              'assigned_expel_alerts': 'expel_alerts',
                              'assigned_investigations': 'investigations',
                              'assigned_investigative_actions': 'investigative_actions',
                              'assigned_organization_resilience_actions': 'organization_resilience_actions',
                              'assigned_organization_resilience_actions_list': 'organization_resilience_actions',
                              'assigned_remediation_actions': 'remediation_actions',
                              'assigned_to_actor': 'actors',
                              'attachment_file': 'files',
                              'automate_opt_in_actor': 'actors',
                              'automate_opt_in_for_remediation_action_setting': 'remediation_action_settings',
                              'child_actors': 'actors',
                              'child_security_devices': 'security_devices',
                              'comment': 'comments',
                              'comment_histories': 'comment_histories',
                              'comments': 'comments',
                              'configurations': 'configurations',
                              'context_label': 'context_labels',
                              'context_label_action': 'context_label_actions',
                              'context_label_action_histories': 'context_label_action_histories',
                              'context_label_actions': 'context_label_actions',
                              'context_label_histories': 'context_label_histories',
                              'context_label_list_sources': 'remediation_action_setting_list_sources',
                              'context_label_tags': 'context_label_tags',
                              'context_labels': 'context_labels',
                              'created_by': 'actors',
                              'dependent_investigative_actions': 'investigative_actions',
                              'depends_on_investigative_action': 'investigative_actions',
                              'destination_expel_alerts': 'expel_alerts',
                              'destination_investigations': 'investigations',
                              'destination_ip_addresses': 'ip_addresses',
                              'engagement_manager': 'engagement_managers',
                              'entitlement': 'entitlements',
                              'evidence': 'vendor_alert_evidences',
                              'evidenced_expel_alerts': 'expel_alerts',
                              'evidences': 'vendor_alert_evidences',
                              'expel_alert': 'expel_alerts',
                              'expel_alert_categories': 'expel_detection_categories',
                              'expel_alert_histories': 'expel_alert_histories',
                              'expel_alert_threshold': 'expel_alert_thresholds',
                              'expel_alert_threshold_histories': 'expel_alert_threshold_histories',
                              'expel_alerts': 'expel_alerts',
                              'expel_response_categories': 'expel_detection_categories',
                              'expel_triage_categories': 'expel_detection_categories',
                              'files': 'files',
                              'findings': 'investigation_findings',
                              'initial_email_file': 'files',
                              'integrations': 'integrations',
                              'investigation': 'investigations',
                              'investigation_assignables': 'actors',
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
                              'mitre_tactics': 'mitre_tactics',
                              'most_recent_investigative_action': 'investigative_actions',
                              'nist_category': 'nist_categories',
                              'nist_subcategories': 'nist_subcategories',
                              'nist_subcategory': 'nist_subcategories',
                              'nist_subcategory_score': 'nist_subcategory_scores',
                              'nist_subcategory_score_histories': 'nist_subcategory_score_histories',
                              'nist_subcategory_scores': 'nist_subcategory_scores',
                              'notification_preferences': 'notification_preferences',
                              'opt_in_histories': 'remediation_action_setting_histories',
                              'opt_out_histories': 'remediation_action_setting_histories',
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
                              'originated_context_labels': 'context_labels',
                              'originating_expel_alerts': 'expel_alerts',
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
                              'raw_body_file': 'files',
                              'related_investigations': 'investigations',
                              'related_investigations_via_involved_host_ips': 'investigations',
                              'remediation_action': 'remediation_actions',
                              'remediation_action_asset': 'remediation_action_assets',
                              'remediation_action_asset_histories': 'remediation_action_asset_histories',
                              'remediation_action_assets': 'remediation_action_assets',
                              'remediation_action_histories': 'remediation_action_histories',
                              'remediation_action_setting': 'remediation_action_settings',
                              'remediation_action_setting_histories': 'remediation_action_setting_histories',
                              'remediation_action_setting_list_source': 'remediation_action_setting_list_sources',
                              'remediation_action_setting_list_source_histories': 'remediation_action_setting_list_source_histories',
                              'remediation_action_setting_list_sources': 'remediation_action_setting_list_sources',
                              'remediation_action_settings': 'remediation_action_settings',
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
                              'suppression_histories': 'expel_alert_histories',
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

MACGYVER_FIELD_TO_TYPE = MACGYVER_FIELD_TO_TYPE_GEN


class JsonApiRelationship:
    '''
    The object acts a helper to handle JSON API relationships. The object is just a dummy that
    allows for setting / getting attributes that are extracted from the relationship part of the
    JSON API response. Additionally, the object will allow for conversion to a JSON API compliant
    relationship block to include in a request.
    '''

    def __init__(self, relationships: dict = None):
        relationships = relationships or {}

        self._rels = {
            name: RelEntry(relationship)
            for name, relationship in relationships.items()
        }
        self._modified = False  # must be set last otherwise will be set to True in __setattr__

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
                if relid.type is None or relid.read_only:
                    continue

                reltype = relid.type
                relid = relid.id

            if relid is None:
                continue

            # NOTE: specific exclusion because external services maintain these relationships
            if relname in ['notification_preferences', 'organization_status', 'entitlements']:
                continue

            if relname[-1] == 's':
                if type(relid) == list:
                    relationships[relname] = {
                        'data': [{'id': rid, 'type': reltype} for rid in relid]}
                else:
                    relationships[relname] = {
                        'data': [{'id': relid, 'type': reltype}]}
            else:
                relationships[relname] = {
                    'data': {'id': relid, 'type': reltype}}
        return relationships


class RelEntry:
    def __init__(self, relationship: dict = None):
        relationship = relationship or {}
        data = relationship.get('data') or {}
        meta = relationship.get('meta') or {}

        self.id = None
        self.type = None
        self.read_only = meta.get('readOnly', False)

        if type(data) == list:
            logger.warning("HIT A RELATIONSHIP ENTRY THAT IS A LIST!")
            return

        self.id = data.get('id')
        self.type = data.get('type')


class ResourceInstance:
    '''
    Represents an instance of a base resource.
    '''
    _api_type = None

    def __init__(self, data, conn, included=None):
        self._data = data
        self._id = data.get('id')
        self._create_id = data['attributes'].get('id')
        self._create = False
        if self._id is None:
            self._create = True

        self._attrs = data['attributes']
        self._conn = conn
        self._modified_fields = set()
        self._relationship = JsonApiRelationship(self._data.get('relationships'))
        self._type = data.get('type')
        self._relobjs = {}
        if included:
            for relationship in self._relationship._rels:
                for item in included:
                    if relationship not in RELATIONSHIP_TO_CLASS.keys() or item['type'] not in RELATIONSHIP_TO_CLASS.keys():
                        continue
                    if RELATIONSHIP_TO_CLASS[item['type']] != RELATIONSHIP_TO_CLASS[relationship]:
                        continue
                    for rel_type in item['relationships']:
                        if item['relationships'][rel_type]['data']['id'] == self._id and RELATIONSHIP_TO_CLASS[rel_type] == RELATIONSHIP_TO_CLASS[self._type]:
                            self._relobjs[relationship] = self._rel_to_class(relationship)(item, self._conn)
        self._deleted = False

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
            if key in self._data.get('relationships', {}):
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

    def to_json(self):
        attrs = copy.deepcopy(self._attrs)
        attrs['id'] = self._id
        return json.dumps(attrs)

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
            attrs = {field: self._attrs[field]
                     for field in self._modified_fields}
            body = {'data': {'type': self._api_type, 'attributes': attrs}}
            body['data']['relationships'] = self._relationship.to_relationship()
            body['id'] = self._id
            resp = self._conn.request(
                'patch', '/api/v2/{}/{}'.format(self._api_type, self._id), data=json.dumps(body))
        else:
            body = {'data': {'type': self._api_type, 'attributes': self._attrs}}
            body['data']['relationships'] = self._relationship.to_relationship()
            if self._create_id:
                body['id'] = self._create_id
            resp = self._conn.request(
                'post', '/api/v2/{}'.format(self._api_type), data=json.dumps(body))
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

        attrs = {k: v for k, v in kwargs.items() if not k.startswith(
            'relationship_') and v is not None}
        rels = {}
        for k, v in kwargs.items():
            if k.startswith('relationship_'):
                _, name = k.split('_', 1)
                rels[name] = {
                    'data': {'id': v, 'type': MACGYVER_FIELD_TO_TYPE.get(name, '%ss' % name)}}

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
            resp = self._conn.request(
                'get', '/api/v2/{}/{}/download?format={}'.format(self._api_type, self._id, fmt))
        elif self._api_type == 'investigative_actions':
            resp = self._conn.request(
                'get', '/api/v2/tasks/{}/download?format={}'.format(self.result_task_id, fmt))
        else:
            raise Exception("Can not download from api type: %s!" %
                            self._api_type)

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
            raise Exception("Can not upload for api type: %s!" %
                            self._api_type)

        # set file_meta to a default..
        if file_meta is None:
            file_meta = {'investigative_action': {'file_type': 'results'}}

        # Get the customer id from the inv or expel alert relationship
        customer_id = None
        if self.relationship.investigation.id:
            customer_id = self._conn.investigations.get(
                id=self.relationship.investigation.id).organization.id
        elif self.relationship.expel_alert.id:
            customer_id = self._conn.expel_alerts.get(
                id=self.relationship.expel_alert.id).organization.id
        else:
            raise Exception("Could not determine customer id")

        # Create a files object
        f = self._conn.files.create(
            filename=filename, file_meta=file_meta, expel_file_type=expel_file_type)
        f.relationship.organization = customer_id
        # This gets pluralized ..
        f.relationship.investigative_actions = self.id
        resp = f.save()
        fid = resp.id

        # Upload the data
        files = {'file': io.BytesIO(fbytes)}
        resp = self._conn.request(
            'post', '/api/v2/files/{}/upload'.format(fid), files=files)

        # Set it ready for analysis.
        with self._conn.investigative_actions.get(id=self.id) as ia:
            existing_files = [f.id for f in ia.files]
            ia.status = 'READY_FOR_ANALYSIS'
            ia.relationship.files = existing_files.append(fid)

        return fid

# AUTO GENERATE JSONAPI CLASSES


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
        | Activity Allows: "", null                                    | activity            | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Created timestamp: readonly                                  | created_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Additional data about the activity Allows: null: no-sort     | data                | object                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Date/Time of when the activity concluded                     | ended_at            | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Referring url Allows: "", null                               | referring_url       | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Date/Time of when the activity started                       | started_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                             | updated_at          | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Url Allows: "", null                                         | url                 | string                       | Y             | N                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                     | created_by          | :class:`Actors`              | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Expel alerts                                                 | expel_alert         | :class:`ExpelAlerts`         | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Investigations                                               | investigation       | :class:`Investigations`      | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Security devices                                             | security_device     | :class:`SecurityDevices`     | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                     | updated_by          | :class:`Actors`              | N             | Y                |
        +--------------------------------------------------------------+---------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'activity_metrics'
    _def_attributes = ["activity", "created_at", "data", "ended_at", "referring_url", "started_at", "updated_at", "url"]
    _def_relationships = ["created_by", "expel_alert", "investigation", "security_device", "updated_by"]


class Actors(ResourceInstance):
    '''
    .. _api actors:

    Defines/retrieves expel.io actor records

    Resource type name is **actors**.

    Example JSON record:

    .. code-block:: javascript

        {'actor_type': 'system', 'created_at': '2019-01-15T15:35:00-05:00', 'display_name': 'string', 'is_expel': True, 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                     | Field Name                                         | Field Type                                 | Attribute     | Relationship     |
        +=======================================================================+====================================================+============================================+===============+==================+
        | Actor type Restricted to: "system", "user", "organization", "api"     | actor_type                                         | any                                        | Y             | N                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                           | created_at                                         | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Display name Allows: "", null                                         | display_name                                       | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Meta: readonly, no-sort, no-filter                                    | is_expel                                           | boolean                                    | Y             | N                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                      | updated_at                                         | string                                     | Y             | N                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                 | analysis_assigned_investigative_actions            | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                                          | assigned_expel_alerts                              | :class:`ExpelAlerts`                       | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                        | assigned_investigations                            | :class:`Investigations`                    | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                 | assigned_investigative_actions                     | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_organization_resilience_actions           | :class:`OrganizationResilienceActions`     | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                    | assigned_organization_resilience_actions_list      | :class:`OrganizationResilienceActions`     | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Remediation actions                                                   | assigned_remediation_actions                       | :class:`RemediationActions`                | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records         | automate_opt_in_for_remediation_action_setting     | :class:`RemediationActionSettings`         | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | child_actors                                       | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | created_by                                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User Notification Preferences                                         | notification_preferences                           | :class:`NotificationPreferences`           | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                       | organization                                       | :class:`Organizations`                     | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | parent_actor                                       | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                              | updated_by                                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User accounts                                                         | user_account                                       | :class:`UserAccounts`                      | N             | Y                |
        +-----------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'actors'
    _def_attributes = ["actor_type", "created_at", "display_name", "is_expel", "updated_at"]
    _def_relationships = ["analysis_assigned_investigative_actions", "assigned_expel_alerts", "assigned_investigations", "assigned_investigative_actions", "assigned_organization_resilience_actions", "assigned_organization_resilience_actions_list",
                          "assigned_remediation_actions", "automate_opt_in_for_remediation_action_setting", "child_actors", "created_by", "notification_preferences", "organization", "parent_actor", "updated_by", "user_account"]


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
        | Only upon initial api key creation (POST), contains the bearer api key token required for api access.: readonly, no-sort, no-filter       | access_token     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Active Allows: null                                                                                                                       | active           | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Can Api key be assigned items (e.g. investigations, etc)                                                                                  | assignable       | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                               | created_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Display name Allows: null                                                                                                                 | display_name     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Missing Description                                                                                                                       | name             | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Realm in which the api key can be used. Restricted to: "public", "internal"                                                               | realm            | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Role Restricted to: "expel_admin", "expel_analyst", "organization_admin", "organization_analyst", "system", "anonymous", "restricted"     | role             | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                          | updated_at       | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                  | created_by       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                           | organization     | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                  | updated_by       | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'api_keys'
    _def_attributes = ["access_token", "active", "assignable",
                       "created_at", "display_name", "name", "realm", "role", "updated_at"]
    _def_relationships = ["created_by", "organization", "updated_by"]


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
        | Assembler image md5 hash Allows: null                             | hash_md5         | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image sh1 hash Allows: null                             | hash_sha1        | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image sha256 hash Allows: null                          | hash_sha256      | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Platform Restricted to: "VMWARE", "HYPERV", "AZURE", "AMAZON"     | platform         | any                 | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image release date Allows: null                         | release_date     | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image size Allows: null                                 | size             | number              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                  | updated_at       | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Assembler image version Allows: "", null                          | version          | string              | Y             | N                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | created_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                          | updated_by       | :class:`Actors`     | N             | Y                |
        +-------------------------------------------------------------------+------------------+---------------------+---------------+------------------+

    '''
    _api_type = 'assembler_images'
    _def_attributes = ["created_at", "hash_md5", "hash_sha1", "hash_sha256",
                       "platform", "release_date", "size", "updated_at", "version"]
    _def_relationships = ["created_by", "updated_by"]


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
        | Assembler connection status Restricted to: "Never Connected", "Connection Lost", "Connected to Provisioning", "Connected to Service" Allows: null                                                             | connection_status                | any                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler connection status update timestamp: readonly                                                                                                                                                        | connection_status_updated_at     | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                   | created_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                             | deleted_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler install code Allows: null                                                                                                                                                                           | install_code                     | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler life cycle status Restricted to: "New", "Authorized", "Transitioning", "Transitioned", "Transition Failed", "Configuring", "Configuration Failed", "Active", "Inactive", "Deleted" Allows: null     | lifecycle_status                 | any                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler lifecycle status update timestamp: readonly                                                                                                                                                         | lifecycle_status_updated_at      | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Location of assembler Allows: "", null                                                                                                                                                                        | location                         | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Name of assembler Allows: "", null                                                                                                                                                                            | name                             | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler status Allows: "", null: readonly, no-sort, no-filter                                                                                                                                               | status                           | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler last status update timestamp: readonly                                                                                                                                                              | status_updated_at                | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                              | updated_at                       | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Assembler VPN ip address Allows: null                                                                                                                                                                         | vpn_ip                           | string                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                      | created_by                       | :class:`Actors`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                               | organization                     | :class:`Organizations`       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                              | security_devices                 | :class:`SecurityDevices`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                      | updated_by                       | :class:`Actors`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                 | vendor_alerts                    | :class:`VendorAlerts`        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'assemblers'
    _def_attributes = ["connection_status", "connection_status_updated_at", "created_at", "deleted_at", "install_code",
                       "lifecycle_status", "lifecycle_status_updated_at", "location", "name", "status", "status_updated_at", "updated_at", "vpn_ip"]
    _def_relationships = ["created_by", "organization", "security_devices", "updated_by", "vendor_alerts"]


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
        | Comment history action Restricted to: "CREATED", "UPDATED", "DELETED" Allows: null     | action            | any                         | Y             | N                |
        +----------------------------------------------------------------------------------------+-------------------+-----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                            | created_at        | string                      | Y             | N                |
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
    _def_attributes = ["action", "created_at", "value"]
    _def_relationships = ["comment", "created_by", "investigation"]


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
        | Defines/retrieves expel.io comment_history records     | comment_histories     | :class:`CommentHistories`     | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records               | created_by            | :class:`Actors`               | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Investigations                                         | investigation         | :class:`Investigations`       | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records        | organization          | :class:`Organizations`        | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records               | updated_by            | :class:`Actors`               | N             | Y                |
        +--------------------------------------------------------+-----------------------+-------------------------------+---------------+------------------+

    '''
    _api_type = 'comments'
    _def_attributes = ["comment", "created_at", "updated_at"]
    _def_relationships = ["comment_histories", "created_by", "investigation", "organization", "updated_by"]


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
        | Created timestamp: readonly                                                    | created_at                 | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Default configuration value Allows: null: readonly, no-sort                    | default_value              | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Description of configuration value Allows: "", null: readonly                  | description                | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration value is an override: readonly                                   | is_override                | boolean                    | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration key: readonly                                                    | key                        | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration metadata Allows: null: readonly, no-sort                         | metadata                   | object                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Title of configuration value Allows: "", null: readonly                        | title                      | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                               | updated_at                 | string                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration value validation Allows: null: readonly, no-sort                 | validation                 | object                     | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration value Allows: null: no-sort                                      | value                      | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Configuration visibility Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"      | visibility                 | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Write permission required Restricted to: "EXPEL", "ORGANIZATION", "SYSTEM"     | write_permission_level     | any                        | Y             | N                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | created_by                 | :class:`Actors`            | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                | organization               | :class:`Organizations`     | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                       | updated_by                 | :class:`Actors`            | N             | Y                |
        +--------------------------------------------------------------------------------+----------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'configurations'
    _def_attributes = ["created_at", "default_value", "description", "is_override", "key", "metadata",
                       "title", "updated_at", "validation", "value", "visibility", "write_permission_level"]
    _def_relationships = ["created_by", "organization", "updated_by"]


class ContextLabelActionHistories(ResourceInstance):
    '''
    .. _api context_label_action_histories:

    Defines/retrieves expel.io context_label_action_history records

    Resource type name is **context_label_action_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'action_type': 'ALERT_ON', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Field Description                                                                                       | Field Name               | Field Type                       | Attribute     | Relationship     |
        +=========================================================================================================+==========================+==================================+===============+==================+
        | Context label action history Restricted to: "CREATED", "UPDATED", "DELETED" Allows: null                | action                   | any                              | Y             | N                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Action type of source parent remediation action Restricted to: "ALERT_ON", "ADD_TO", "SUPPRESS"         | action_type              | any                              | Y             | N                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                             | created_at               | string                           | Y             | N                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Context label action history details (contains important fields that changed) Allows: null: no-sort     | value                    | object                           | Y             | N                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                        | context_label            | :class:`ContextLabels`           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                 | context_label_action     | :class:`ContextLabelActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                | created_by               | :class:`Actors`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+
        | Investigations                                                                                          | investigation            | :class:`Investigations`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------+--------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_action_histories'
    _def_attributes = ["action", "action_type", "created_at", "value"]
    _def_relationships = ["context_label", "context_label_action", "created_by", "investigation"]


class ContextLabelActions(ResourceInstance):
    '''
    .. _api context_label_actions:

    Defines/retrieves expel.io context_label_action records

    Resource type name is **context_label_actions**.

    Example JSON record:

    .. code-block:: javascript

        {'action_type': 'ALERT_ON', 'created_at': '2019-01-15T15:35:00-05:00', 'expel_severity_threshold': 'CRITICAL', 'expel_signature_id': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Field Description                                                                        | Field Name                         | Field Type                               | Attribute     | Relationship     |
        +==========================================================================================+====================================+==========================================+===============+==================+
        | What action to take Restricted to: "ALERT_ON", "ADD_TO", "SUPPRESS"                      | action_type                        | any                                      | Y             | N                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                              | created_at                         | string                                   | Y             | N                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "TESTING", "TUNING" Allows: null     | expel_severity_threshold           | any                                      | Y             | N                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Expel alert signature Allows: "", null                                                   | expel_signature_id                 | string                                   | Y             | N                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                         | updated_at                         | string                                   | Y             | N                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                         | context_label                      | :class:`ContextLabels`                   | N             | Y                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action_history records                          | context_label_action_histories     | :class:`ContextLabelActionHistories`     | N             | Y                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                 | created_by                         | :class:`Actors`                          | N             | Y                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Investigations                                                                           | investigation                      | :class:`Investigations`                  | N             | Y                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Timeline Entries                                                                         | timeline_entries                   | :class:`TimelineEntries`                 | N             | Y                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                 | updated_by                         | :class:`Actors`                          | N             | Y                |
        +------------------------------------------------------------------------------------------+------------------------------------+------------------------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_actions'
    _def_attributes = ["action_type", "created_at", "expel_severity_threshold", "expel_signature_id", "updated_at"]
    _def_relationships = ["context_label", "context_label_action_histories",
                          "created_by", "investigation", "timeline_entries", "updated_by"]


class ContextLabelHistories(ResourceInstance):
    '''
    .. _api context_label_histories:

    Defines/retrieves expel.io context_label_history records

    Resource type name is **context_label_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                                            | Field Name        | Field Type                 | Attribute     | Relationship     |
        +==============================================================================================================================================+===================+============================+===============+==================+
        | Context label history action Restricted to: "CREATED", "UPDATED", "DELETED", "ASSIGNED_TAG_CREATED", "ASSIGNED_TAG_DELETED" Allows: null     | action            | any                        | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                  | created_at        | string                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Context label history details (contains important fields that changed) Allows: null: no-sort                                                 | value             | object                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                             | context_label     | :class:`ContextLabels`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                     | created_by        | :class:`Actors`            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_histories'
    _def_attributes = ["action", "created_at", "value"]
    _def_relationships = ["context_label", "created_by"]


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
        | Description Allows: null, ""                                   | description                   | string                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Metadata about the context label tag Allows: null: no-sort     | metadata                      | object                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Tag                                                            | tag                           | string                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                               | updated_at                    | string                               | Y             | N                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records               | context_labels                | :class:`ContextLabels`               | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                       | created_by                    | :class:`Actors`                      | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                | organization                  | :class:`Organizations`               | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action assets                                      | remediation_action_assets     | :class:`RemediationActionAssets`     | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                       | updated_by                    | :class:`Actors`                      | N             | Y                |
        +----------------------------------------------------------------+-------------------------------+--------------------------------------+---------------+------------------+

    '''
    _api_type = 'context_label_tags'
    _def_attributes = ["created_at", "description", "metadata", "tag", "updated_at"]
    _def_relationships = ["context_labels", "created_by", "organization", "remediation_action_assets", "updated_by"]


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
            'initial_edit_at': '2019-01-15T15:35:00-05:00',
            'metadata': {},
            'review_status': 'APPROVED',
            'starts_at': '2019-01-15T15:35:00-05:00',
            'title': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                    | Field Name                                           | Field Type                                               | Attribute     | Relationship     |
        +======================================================================================================================================+======================================================+==========================================================+===============+==================+
        | Created timestamp: readonly                                                                                                          | created_at                                           | string                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Definition: no-sort                                                                                                                  | definition                                           | object                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Description Allows: null, ""                                                                                                         | description                                          | string                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Date/Time of when the context_label should end being tested Allows: null                                                             | ends_at                                              | string                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Date/Time of when the drawer was first opened to create the context label Allows: null                                               | initial_edit_at                                      | string                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Metadata about the context label Allows: null: no-sort                                                                               | metadata                                             | object                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Current status of the review process Restricted to: "APPROVED", "REVIEW_REQUESTED", "CHANGES_REQUESTED", "DECLINED" Allows: null     | review_status                                        | any                                                      | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Date/Time of when the context_label should start being tested                                                                        | starts_at                                            | string                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Title Allows: null, ""                                                                                                               | title                                                | string                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                     | updated_at                                           | string                                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                                              | add_to_actions                                       | :class:`ContextLabelActions`                             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                                              | alert_on_actions                                     | :class:`ContextLabelActions`                             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_history records                                                                             | approval_histories                                   | :class:`ContextLabelHistories`                           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action_history records                                                                      | context_label_action_histories                       | :class:`ContextLabelActionHistories`                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                                              | context_label_actions                                | :class:`ContextLabelActions`                             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_history records                                                                             | context_label_histories                              | :class:`ContextLabelHistories`                           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                                                                                 | context_label_tags                                   | :class:`ContextLabelTags`                                | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                             | created_by                                           | :class:`Actors`                                          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                         | expel_alerts                                         | :class:`ExpelAlerts`                                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                       | investigations                                       | :class:`Investigations`                                  | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                      | organization                                         | :class:`Organizations`                                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                         | originating_expel_alerts                             | :class:`ExpelAlerts`                                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_list_source_history records                                                    | remediation_action_setting_list_source_histories     | :class:`RemediationActionSettingListSourceHistories`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_list_source records                                                            | remediation_action_setting_list_sources              | :class:`RemediationActionSettingListSources`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records                                                                        | remediation_action_settings                          | :class:`RemediationActionSettings`                       | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                                              | suppress_actions                                     | :class:`ContextLabelActions`                             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Timeline Entries                                                                                                                     | timeline_entries                                     | :class:`TimelineEntries`                                 | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                             | updated_by                                           | :class:`Actors`                                          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'context_labels'
    _def_attributes = ["created_at", "definition", "description", "ends_at",
                       "initial_edit_at", "metadata", "review_status", "starts_at", "title", "updated_at"]
    _def_relationships = ["add_to_actions", "alert_on_actions", "approval_histories", "context_label_action_histories", "context_label_actions", "context_label_histories", "context_label_tags", "created_by", "expel_alerts", "investigations",
                          "organization", "originating_expel_alerts", "remediation_action_setting_list_source_histories", "remediation_action_setting_list_sources", "remediation_action_settings", "suppress_actions", "timeline_entries", "updated_by"]


class Detections(ResourceInstance):
    '''
    .. _api detections:

    How we determine security-relevant data for analyst review

    Resource type name is **detections**.

    Example JSON record:

    .. code-block:: javascript

        {           'author_type': 'string',
            'configuration_slugs': [],
            'created_date': '2019-01-15T15:35:00-05:00',
            'customer_context_tags': [],
            'description': 'string',
            'logic_blob': 'string',
            'name': 'string',
            'priority': 100,
            'severity': 'string',
            'status': 'string',
            'supported_tech': [],
            'tags': [],
            'test_blob': 'string',
            'unique_on': [],
            'unique_within': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | Field Description                                                                                                                     | Field Name                    | Field Type                            | Attribute     | Relationship     |
        +=======================================================================================================================================+===============================+=======================================+===============+==================+
        | The author of this detection Allows: "", null                                                                                         | author_type                   | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | A list of configuration tags used in the logic of this detection: no-filter, no-sort                                                  | configuration_slugs           | array                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The time this detection was created Allows: null                                                                                      | created_date                  | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | A list of customer context tags used in the logic of this detection: no-filter, no-sort                                               | customer_context_tags         | array                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | What this detection is looking for Allows: "", null                                                                                   | description                   | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | A JSON formatted blob of Josie detection logic Allows: "", null                                                                       | logic_blob                    | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The name of the detection Allows: "", null                                                                                            | name                          | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The order in which Josie applies this detection to security alerts, 0 being a higher priority Allows: null                            | priority                      | number                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The potential impact of detected incidents Allows: "", null                                                                           | severity                      | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The production status of this detection Allows: "", null                                                                              | status                        | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The technology that this detection supports                                                                                           | supported_tech                | array                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | A list of tags which may affect upstream behavior: no-filter, no-sort                                                                 | tags                          | array                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | A JSON formatted list of conditions (vendor alerts) that trigger this detection, in turn creating an Expel alert Allows: "", null     | test_blob                     | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | A list of Josie expressions that make this alert unique: no-filter, no-sort                                                           | unique_on                     | array                                 | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The time period in which this alert is unique Allows: "", null                                                                        | unique_within                 | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | The last time this detection was updated Allows: null                                                                                 | updated_at                    | string                                | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | Detection categories                                                                                                                  | expel_alert_categories        | :class:`ExpelDetectionCategories`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | Detection categories                                                                                                                  | expel_response_categories     | :class:`ExpelDetectionCategories`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | Detection categories                                                                                                                  | expel_triage_categories       | :class:`ExpelDetectionCategories`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+
        | Mitre Tactics                                                                                                                         | mitre_tactics                 | :class:`MitreTactics`                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------+-------------------------------+---------------------------------------+---------------+------------------+

    '''
    _api_type = 'detections'
    _def_attributes = ["author_type", "configuration_slugs", "created_date", "customer_context_tags", "description", "logic_blob",
                       "name", "priority", "severity", "status", "supported_tech", "tags", "test_blob", "unique_on", "unique_within", "updated_at"]
    _def_relationships = ["expel_alert_categories",
                          "expel_response_categories", "expel_triage_categories", "mitre_tactics"]


class EngagementManagers(ResourceInstance):
    '''
    .. _api engagement_managers:

    Defines/retrieves expel.io engagement_manager records

    Resource type name is **engagement_managers**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'display_name': 'string', 'email': 'name@company.com', 'pagerduty_id': 'string', 'phone_number': 'string', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name        | Field Type                 | Attribute     | Relationship     |
        +=====================================================+===================+============================+===============+==================+
        | Created timestamp: readonly                         | created_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Display name Allows: "", null                       | display_name      | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Email Allows: null                                  | email             | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Pagerduty ID Allows: null                           | pagerduty_id      | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Phone number Allows: null                           | phone_number      | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at        | string                     | Y             | N                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organizations     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by        | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'engagement_managers'
    _def_attributes = ["created_at", "display_name", "email", "pagerduty_id", "phone_number", "updated_at"]
    _def_relationships = ["created_by", "organizations", "updated_by"]


class Entitlements(ResourceInstance):
    '''
    .. _api entitlements:

    path to entitlements service

    Resource type name is **entitlements**.

    Example JSON record:

    .. code-block:: javascript

        {'entitlement': {'organization_id': 'string', 'service_offerings': [], 'service_offerings_for_hunting': [], 'service_types': []}, 'skus': []}


    Below are valid filter by parameters:

        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Field Description                                   | Field Name       | Field Type                 | Attribute     | Relationship     |
        +=====================================================+==================+============================+===============+==================+
        | Allows: null: readonly                              | entitlement      | object                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Missing Description                                 | skus             | array                      | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'entitlements'
    _def_attributes = ["entitlement", "skus"]
    _def_relationships = ["organization"]


class ExpelAlertHistories(ResourceInstance):
    '''
    .. _api expel_alert_histories:

    Expel alert histories

    Resource type name is **expel_alert_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Field Description                                                                                                                                          | Field Name            | Field Type                  | Attribute     | Relationship     |
        +============================================================================================================================================================+=======================+=============================+===============+==================+
        | Expel alert history action Restricted to: "CREATED", "ASSIGNED", "STATUS_CHANGED", "INVESTIGATING", "TUNING_CHANGED", "DELETED", "VIEWED" Allows: null     | action                | any                         | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                | created_at            | string                      | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Expel alert history details Allows: null: no-sort                                                                                                          | value                 | object                      | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                   | assigned_to_actor     | :class:`Actors`             | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                   | created_by            | :class:`Actors`             | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                               | expel_alert           | :class:`ExpelAlerts`        | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigations                                                                                                                                             | investigation         | :class:`Investigations`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                            | organization          | :class:`Organizations`      | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_histories'
    _def_attributes = ["action", "created_at", "value"]
    _def_relationships = ["assigned_to_actor", "created_by", "expel_alert", "investigation", "organization"]


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
        | Expel alert threshold history action Restricted to: "CREATED", "BREACHED", "ACKNOWLEDGED", "RECOVERED", "DELETED"     | action                    | any                               | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                           | created_at                | string                            | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Expel alert threshold history details Allows: null: no-sort                                                           | value                     | object                            | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                              | created_by                | :class:`Actors`                   | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records                                                              | expel_alert_threshold     | :class:`ExpelAlertThresholds`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+---------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_threshold_histories'
    _def_attributes = ["action", "created_at", "value"]
    _def_relationships = ["created_by", "expel_alert_threshold"]


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
        | Name                                                                 | name                                | string                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Threshold value                                                      | threshold                           | number                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                     | updated_at                          | string                                    | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | created_by                          | :class:`Actors`                           | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold_history records     | expel_alert_threshold_histories     | :class:`ExpelAlertThresholdHistories`     | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records             | suppressed_by                       | :class:`ExpelAlertThresholds`             | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io expel_alert_threshold records             | suppresses                          | :class:`ExpelAlertThresholds`             | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | updated_by                          | :class:`Actors`                           | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alert_thresholds'
    _def_attributes = ["created_at", "name", "threshold", "updated_at"]
    _def_relationships = ["created_by", "expel_alert_threshold_histories", "suppressed_by", "suppresses", "updated_by"]


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
            'investigative_action_count': 100,
            'ref_event_id': 'string',
            'status': 'string',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'tuning_requested': True,
            'updated_at': '2019-01-15T15:35:00-05:00',
            'vendor_alert_count': 100}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                        | Field Name                                         | Field Type                                | Attribute     | Relationship     |
        +==========================================================================================================================================================================================================================================================================+====================================================+===========================================+===============+==================+
        | Allows: null: readonly, no-sort, no-filter                                                                                                                                                                                                                               | activity_first_at                                  | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort, no-filter                                                                                                                                                                                                                               | activity_last_at                                   | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert type Restricted to: "ENDPOINT", "NETWORK", "SIEM", "RULE_ENGINE", "EXTERNAL", "OTHER", "CLOUD", "PHISHING_SUBMISSION", "PHISHING_SUBMISSION_SIMILAR" Allows: null                                                                                            | alert_type                                         | any                                       | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert close comment Allows: "", null                                                                                                                                                                                                                               | close_comment                                      | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert close reason Restricted to: "FALSE_POSITIVE", "TRUE_POSITIVE", "OTHER", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "TESTING", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "INCONCLUSIVE", "SUPPRESSED", "PHISHING_SIMULATION" Allows: null     | close_reason                                       | any                                       | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                              | created_at                                         | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | cust_disp_alerts_in_critical_incidents_count       | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | cust_disp_alerts_in_incidents_count                | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | cust_disp_alerts_in_investigations_count           | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | cust_disp_closed_alerts_count                      | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | cust_disp_disposed_alerts_count                    | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | disposition_alerts_in_critical_incidents_count     | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | disposition_alerts_in_incidents_count              | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | disposition_alerts_in_investigations_count         | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | disposition_closed_alerts_count                    | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null                                                                                                                                                                                                                                                             | disposition_disposed_alerts_count                  | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel Alert Time first seen time: immutable                                                                                                                                                                                                                              | expel_alert_time                                   | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert alias Allows: "", null                                                                                                                                                                                                                                       | expel_alias_name                                   | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert message Allows: "", null                                                                                                                                                                                                                                     | expel_message                                      | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert name Allows: "", null                                                                                                                                                                                                                                        | expel_name                                         | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "TESTING", "TUNING" Allows: null                                                                                                                                                                | expel_severity                                     | any                                       | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert signature Allows: "", null                                                                                                                                                                                                                                   | expel_signature_id                                 | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert version Allows: "", null                                                                                                                                                                                                                                     | expel_version                                      | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | URL to rule definition for alert Allows: "", null                                                                                                                                                                                                                        | git_rule_url                                       | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort, no-filter                                                                                                                                                                                                                               | investigative_action_count                         | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Referring event id Allows: null                                                                                                                                                                                                                                          | ref_event_id                                       | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert status Restricted to: "OPEN", "IN_PROGRESS", "CLOSED" Allows: null                                                                                                                                                                                           | status                                             | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                 | status_updated_at                                  | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | tuning requested                                                                                                                                                                                                                                                         | tuning_requested                                   | boolean                                   | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                         | updated_at                                         | string                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Allows: null: readonly, no-sort, no-filter                                                                                                                                                                                                                               | vendor_alert_count                                 | number                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                 | assigned_to_actor                                  | :class:`Actors`                           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                                                         | context_labels                                     | :class:`ContextLabels`                    | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                 | created_by                                         | :class:`Actors`                           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                             | destination_ip_addresses                           | :class:`IpAddresses`                      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                                                                                                                                                                              | evidence                                           | :class:`VendorAlertEvidences`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                                                                                                                                                                                    | expel_alert_histories                              | :class:`ExpelAlertHistories`              | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                           | investigation                                      | :class:`Investigations`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                                                                                                           | investigative_action_histories                     | :class:`InvestigativeActionHistories`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                    | investigative_actions                              | :class:`InvestigativeActions`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                          | organization                                       | :class:`Organizations`                    | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                                                         | originated_context_labels                          | :class:`ContextLabels`                    | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Phishing submissions                                                                                                                                                                                                                                                     | phishing_submissions                               | :class:`PhishingSubmissions`              | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                           | related_investigations                             | :class:`Investigations`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                           | related_investigations_via_involved_host_ips       | :class:`Investigations`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                             | similar_alerts                                     | :class:`ExpelAlerts`                      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                             | source_ip_addresses                                | :class:`IpAddresses`                      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                 | status_last_updated_by                             | :class:`Actors`                           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                                                                                                                                                                                    | suppression_histories                              | :class:`ExpelAlertHistories`              | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                 | updated_by                                         | :class:`Actors`                           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendors                                                                                                                                                                                                                                                                  | vendor                                             | :class:`Vendors`                          | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                                                            | vendor_alerts                                      | :class:`VendorAlerts`                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'expel_alerts'
    _def_attributes = ["activity_first_at", "activity_last_at", "alert_type", "close_comment", "close_reason", "created_at", "cust_disp_alerts_in_critical_incidents_count", "cust_disp_alerts_in_incidents_count", "cust_disp_alerts_in_investigations_count", "cust_disp_closed_alerts_count", "cust_disp_disposed_alerts_count", "disposition_alerts_in_critical_incidents_count", "disposition_alerts_in_incidents_count",
                       "disposition_alerts_in_investigations_count", "disposition_closed_alerts_count", "disposition_disposed_alerts_count", "expel_alert_time", "expel_alias_name", "expel_message", "expel_name", "expel_severity", "expel_signature_id", "expel_version", "git_rule_url", "investigative_action_count", "ref_event_id", "status", "status_updated_at", "tuning_requested", "updated_at", "vendor_alert_count"]
    _def_relationships = ["assigned_to_actor", "context_labels", "created_by", "destination_ip_addresses", "evidence", "expel_alert_histories", "investigation", "investigative_action_histories", "investigative_actions", "organization", "originated_context_labels",
                          "phishing_submissions", "related_investigations", "related_investigations_via_involved_host_ips", "similar_alerts", "source_ip_addresses", "status_last_updated_by", "suppression_histories", "updated_by", "vendor", "vendor_alerts"]


class ExpelDetectionCategories(ResourceInstance):
    '''
    .. _api expel_detection_categories:

    Detection categories

    Resource type name is **expel_detection_categories**.

    Example JSON record:

    .. code-block:: javascript

        {'category_type': 'string', 'customer_context_tags': [], 'description': 'string', 'investigative_questions': [], 'name': 'string', 'number_of_detections': 100}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------------------------------------+-----------------------------+----------------+---------------+------------------+
        | Field Description                                                                                          | Field Name                  | Field Type     | Attribute     | Relationship     |
        +============================================================================================================+=============================+================+===============+==================+
        | Which part of the detection & response process this category takes effect in Allows: "", null: no-sort     | category_type               | string         | Y             | N                |
        +------------------------------------------------------------------------------------------------------------+-----------------------------+----------------+---------------+------------------+
        | Customer context tags used in this category's detections                                                   | customer_context_tags       | array          | Y             | N                |
        +------------------------------------------------------------------------------------------------------------+-----------------------------+----------------+---------------+------------------+
        | The category description Allows: "", null                                                                  | description                 | string         | Y             | N                |
        +------------------------------------------------------------------------------------------------------------+-----------------------------+----------------+---------------+------------------+
        | The questions analysts ask when responding to Expel alerts                                                 | investigative_questions     | array          | Y             | N                |
        +------------------------------------------------------------------------------------------------------------+-----------------------------+----------------+---------------+------------------+
        | The name of the category Allows: "", null                                                                  | name                        | string         | Y             | N                |
        +------------------------------------------------------------------------------------------------------------+-----------------------------+----------------+---------------+------------------+
        | The number of detections in this category, based on the plugin_slugs filter                                | number_of_detections        | number         | Y             | N                |
        +------------------------------------------------------------------------------------------------------------+-----------------------------+----------------+---------------+------------------+

    '''
    _api_type = 'expel_detection_categories'
    _def_attributes = ["category_type", "customer_context_tags", "description",
                       "investigative_questions", "name", "number_of_detections"]
    _def_relationships = []


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
        | Expel file type Allows: null, ""                    | expel_file_type                    | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Metadata about the file Allows: null: no-sort       | file_meta                          | object                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Filename                                            | filename                           | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                    | updated_at                         | string                                     | Y             | N                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | created_by                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                      | investigations                     | :class:`Investigations`                    | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                               | investigative_actions              | :class:`InvestigativeActions`              | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization                       | :class:`Organizations`                     | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submissions                                | phishing_submission                | :class:`PhishingSubmissions`               | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission attachments                     | phishing_submission_attachment     | :class:`PhishingSubmissionAttachments`     | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by                         | :class:`Actors`                            | N             | Y                |
        +-----------------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'files'
    _def_attributes = ["created_at", "expel_file_type", "file_meta", "filename", "updated_at"]
    _def_relationships = ["created_by", "investigations", "investigative_actions",
                          "organization", "phishing_submission", "phishing_submission_attachment", "updated_by"]


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
        | Seed Rank                                    | rank           | number              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Title Allows: "", null                       | title          | string              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at     | string              | Y             | N                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by     | :class:`Actors`     | N             | Y                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by     | :class:`Actors`     | N             | Y                |
        +----------------------------------------------+----------------+---------------------+---------------+------------------+

    '''
    _api_type = 'findings'
    _def_attributes = ["created_at", "rank", "title", "updated_at"]
    _def_relationships = ["created_by", "updated_by"]


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

        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Field Description                                                                                                        | Field Name           | Field Type                 | Attribute     | Relationship     |
        +==========================================================================================================================+======================+============================+===============+==================+
        | Service account identifier                                                                                               | account              | string                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                              | created_at           | string                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Needed information for integration type Allows: null: no-sort                                                            | integration_meta     | object                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Type of integration Restricted to: "pagerduty", "slack", "ticketing", "service_now", "teams", "ops_genie": immutable     | integration_type     | any                        | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Last Successful Test Allows: null: readonly                                                                              | last_tested_at       | string                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Service display name                                                                                                     | service_name         | string                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Integration status Restricted to: "UNTESTED", "TEST_SUCCESS", "TEST_FAIL": readonly                                      | status               | any                        | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                         | updated_at           | string                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                 | created_by           | :class:`Actors`            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                          | organization         | :class:`Organizations`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Organization secrets. Note - these requests must be in the format of `/secrets/security_device-<guid>`                   | secret               | :class:`Secrets`           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                 | updated_by           | :class:`Actors`            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------+----------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'integrations'
    _def_attributes = ["account", "created_at", "integration_meta",
                       "integration_type", "last_tested_at", "service_name", "status", "updated_at"]
    _def_relationships = ["created_by", "organization", "secret", "updated_by"]


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
        | Investigation finding history action Restricted to: "CREATED", "CHANGED", "DELETED" Allows: null     | action                    | any                                | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                          | created_at                | string                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                     | updated_at                | string                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigation finding history details Allows: null: no-sort                                          | value                     | object                             | Y             | N                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                             | created_by                | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigations                                                                                       | investigation             | :class:`Investigations`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Investigation findings                                                                               | investigation_finding     | :class:`InvestigationFindings`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                             | updated_by                | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------------------------------------------------------+---------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_finding_histories'
    _def_attributes = ["action", "created_at", "updated_at", "value"]
    _def_relationships = ["created_by", "investigation", "investigation_finding", "updated_by"]


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
        | Deleted At timestamp Allows: null                                    | deleted_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Finding Allows: "", null                                             | finding                             | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Visualization Rank                                                   | rank                                | number                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                               | title                               | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                     | updated_at                          | string                                     | Y             | N                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | created_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                       | investigation                       | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io investigation_finding_history records     | investigation_finding_histories     | :class:`InvestigationFindingHistories`     | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                             | updated_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_findings'
    _def_attributes = ["created_at", "deleted_at", "finding", "rank", "title", "updated_at"]
    _def_relationships = ["created_by", "investigation", "investigation_finding_histories", "updated_by"]


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
        | Investigation history action Restricted to: "CREATED", "ASSIGNED", "CHANGED", "CLOSED", "SUMMARY", "REOPENED", "PUBLISHED" Allows: null     | action                | any                         | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                 | created_at            | string                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Is Incidence                                                                                                                                | is_incident           | boolean                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigation history details Allows: null: no-sort                                                                                         | value                 | object                      | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | assigned_to_actor     | :class:`Actors`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | created_by            | :class:`Actors`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Investigations                                                                                                                              | investigation         | :class:`Investigations`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                             | organization          | :class:`Organizations`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+-----------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_histories'
    _def_attributes = ["action", "created_at", "is_incident", "value"]
    _def_relationships = ["assigned_to_actor", "created_by", "investigation", "organization"]


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
        | Defines/retrieves expel.io actor records     | created_by                         | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                               | investigation                      | :class:`Investigations`                    | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions           | organization_resilience_action     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                         | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigation_resilience_actions'
    _def_attributes = ["created_at", "updated_at"]
    _def_relationships = ["created_by", "investigation", "organization_resilience_action", "updated_by"]


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
            'initial_attack_vector': 'string',
            'is_downgrade': True,
            'is_incident': True,
            'is_incident_status_updated_at': '2019-01-15T15:35:00-05:00',
            'is_surge': True,
            'last_published_at': '2019-01-15T15:35:00-05:00',
            'last_published_value': 'string',
            'lead_description': 'string',
            'malware_family': 'string',
            'next_steps': 'string',
            'open_reason': 'ACCESS_KEYS',
            'open_summary': 'string',
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
        | Analyst Severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO" Allows: null                                                                                                                                                                                    | analyst_severity                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Lifecycle Restricted to: "INITIAL_RECON", "DELIVERY", "EXPLOITATION", "INSTALLATION", "COMMAND_CONTROL", "LATERAL_MOVEMENT", "ACTION_TARGETS", "UNKNOWN" Allows: null                                                                                                | attack_lifecycle                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Timing Restricted to: "HISTORICAL", "PRESENT" Allows: null                                                                                                                                                                                                           | attack_timing                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Attack Vector Restricted to: "DRIVE_BY", "PHISHING", "PHISHING_LINK", "PHISHING_ATTACHMENT", "REV_MEDIA", "SPEAR_PHISHING", "SPEAR_PHISHING_LINK", "SPEAR_PHISHING_ATTACHMENT", "STRAG_WEB_COMP", "SERVER_SIDE_VULN", "CRED_THEFT", "MISCONFIG", "UNKNOWN" Allows: null     | attack_vector                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Close Comment Allows: "", null                                                                                                                                                                                                                                              | close_comment                                    | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                 | created_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Critical Comment Allows: "", null                                                                                                                                                                                                                                           | critical_comment                                 | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Decision Restricted to: "FALSE_POSITIVE", "TRUE_POSITIVE", "CLOSED", "OTHER", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "TESTING", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "INCONCLUSIVE", "PHISHING_SIMULATION" Allows: null                            | decision                                         | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                           | deleted_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Detection Type Restricted to: "UNKNOWN", "ENDPOINT", "SIEM", "NETWORK", "EXPEL", "HUNTING", "CLOUD", "PHISHING" Allows: null                                                                                                                                                | detection_type                                   | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Meta: readonly, no-sort, no-filter                                                                                                                                                                                                                                          | has_hunting_status                               | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Initial attack vector Allows: "", null                                                                                                                                                                                                                                      | initial_attack_vector                            | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is downgrade                                                                                                                                                                                                                                                                | is_downgrade                                     | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is Incident                                                                                                                                                                                                                                                                 | is_incident                                      | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Incident Status timestamp Allows: null: readonly                                                                                                                                                                                                                            | is_incident_status_updated_at                    | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Is surge                                                                                                                                                                                                                                                                    | is_surge                                         | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Published At Allows: null                                                                                                                                                                                                                                              | last_published_at                                | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Published Value Allows: "", null                                                                                                                                                                                                                                       | last_published_value                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Lead Description Allows: null                                                                                                                                                                                                                                               | lead_description                                 | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Malware family Allows: "", null                                                                                                                                                                                                                                             | malware_family                                   | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Recommended next steps for starting this investigation or handling this incident Allows: "", null                                                                                                                                                                           | next_steps                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Open Reason Restricted to: "ACCESS_KEYS", "EC2", "S3_BUCKETS", "OTHER" Allows: null                                                                                                                                                                                         | open_reason                                      | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Reason the investigation/incident was opened Allows: "", null                                                                                                                                                                                                               | open_summary                                     | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Review Requested At Allows: null                                                                                                                                                                                                                                            | review_requested_at                              | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation short link: readonly                                                                                                                                                                                                                                          | short_link                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Source Reason Restricted to: "HUNTING", "ORGANIZATION_REPORTED", "DISCOVERY", "PHISHING" Allows: null                                                                                                                                                                       | source_reason                                    | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                    | status_updated_at                                | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Threat Type Restricted to: "TARGETED", "TARGETED_APT", "TARGETED_RANSOMWARE", "BUSINESS_EMAIL_COMPROMISE", "NON_TARGETED", "NON_TARGETED_MALWARE", "POLICY_VIOLATION", "UNKNOWN" Allows: null                                                                               | threat_type                                      | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Title Allows: "", null                                                                                                                                                                                                                                                      | title                                            | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                            | updated_at                                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | assigned_to_actor                                | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment_history records                                                                                                                                                                                                                          | comment_histories                                | :class:`CommentHistories`                    | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                                                                                                                                                                                                                  | comments                                         | :class:`Comments`                            | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action_history records                                                                                                                                                                                                             | context_label_action_histories                   | :class:`ContextLabelActionHistories`         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                                                                                                                                                                                                                     | context_label_actions                            | :class:`ContextLabelActions`                 | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                                                            | context_labels                                   | :class:`ContextLabels`                       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | created_by                                       | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | destination_ip_addresses                         | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                                                                                                                                                                                 | evidence                                         | :class:`VendorAlertEvidences`                | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                                                                                                                                                                                       | expel_alert_histories                            | :class:`ExpelAlertHistories`                 | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                | expel_alerts                                     | :class:`ExpelAlerts`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | File                                                                                                                                                                                                                                                                        | files                                            | :class:`Files`                               | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io finding records                                                                                                                                                                                                                                  | findings                                         | :class:`InvestigationFindings`               | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io investigation_finding_history records                                                                                                                                                                                                            | investigation_finding_histories                  | :class:`InvestigationFindingHistories`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation histories                                                                                                                                                                                                                                                     | investigation_histories                          | :class:`InvestigationHistories`              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigation to resilience actions                                                                                                                                                                                                                                         | investigation_resilience_actions                 | :class:`InvestigationResilienceActions`      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                                                                                                              | investigative_action_histories                   | :class:`InvestigativeActionHistories`        | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                       | investigative_actions                            | :class:`InvestigativeActions`                | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | ip_addresses                                     | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | last_published_by                                | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                | lead_expel_alert                                 | :class:`ExpelAlerts`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                       | most_recent_investigative_action                 | :class:`InvestigativeActions`                | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                             | organization                                     | :class:`Organizations`                       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                                                                                                          | organization_resilience_action_hints             | :class:`OrganizationResilienceActions`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                                                                                                                                                          | organization_resilience_actions                  | :class:`OrganizationResilienceActions`       | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                              | related_investigations_via_involved_host_ips     | :class:`Investigations`                      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action asset histories                                                                                                                                                                                                                                          | remediation_action_asset_histories               | :class:`RemediationActionAssetHistories`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action assets                                                                                                                                                                                                                                                   | remediation_action_assets                        | :class:`RemediationActionAssets`             | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action histories                                                                                                                                                                                                                                                | remediation_action_histories                     | :class:`RemediationActionHistories`          | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                                                                                                         | remediation_actions                              | :class:`RemediationActions`                  | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | review_requested_by                              | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | IP addresses                                                                                                                                                                                                                                                                | source_ip_addresses                              | :class:`IpAddresses`                         | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | status_last_updated_by                           | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Timeline Entries                                                                                                                                                                                                                                                            | timeline_entries                                 | :class:`TimelineEntries`                     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                    | updated_by                                       | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------------------+----------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigations'
    _def_attributes = ["analyst_severity", "attack_lifecycle", "attack_timing", "attack_vector", "close_comment", "created_at", "critical_comment", "decision", "deleted_at", "detection_type", "has_hunting_status", "initial_attack_vector", "is_downgrade", "is_incident",
                       "is_incident_status_updated_at", "is_surge", "last_published_at", "last_published_value", "lead_description", "malware_family", "next_steps", "open_reason", "open_summary", "review_requested_at", "short_link", "source_reason", "status_updated_at", "threat_type", "title", "updated_at"]
    _def_relationships = ["assigned_to_actor", "comment_histories", "comments", "context_label_action_histories", "context_label_actions", "context_labels", "created_by", "destination_ip_addresses", "evidence", "expel_alert_histories", "expel_alerts", "files", "findings", "investigation_finding_histories", "investigation_histories", "investigation_resilience_actions", "investigative_action_histories", "investigative_actions", "ip_addresses",
                          "last_published_by", "lead_expel_alert", "most_recent_investigative_action", "organization", "organization_resilience_action_hints", "organization_resilience_actions", "related_investigations_via_involved_host_ips", "remediation_action_asset_histories", "remediation_action_assets", "remediation_action_histories", "remediation_actions", "review_requested_by", "source_ip_addresses", "status_last_updated_by", "timeline_entries", "updated_by"]


class InvestigativeActionHistories(ResourceInstance):
    '''
    .. _api investigative_action_histories:

    Investigative action histories

    Resource type name is **investigative_action_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'deleted_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Field Description                                                                                                   | Field Name               | Field Type                        | Attribute     | Relationship     |
        +=====================================================================================================================+==========================+===================================+===============+==================+
        | Investigative action history action Restricted to: "CREATED", "ASSIGNED", "CLOSED", "ACKNOWLEDGED" Allows: null     | action                   | any                               | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                         | created_at               | string                            | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                   | deleted_at               | string                            | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Investigative action history details Allows: null: no-sort                                                          | value                    | object                            | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                            | assigned_to_actor        | :class:`Actors`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                            | created_by               | :class:`Actors`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Expel alerts                                                                                                        | expel_alert              | :class:`ExpelAlerts`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | Investigations                                                                                                      | investigation            | :class:`Investigations`           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+
        | investigative actions                                                                                               | investigative_action     | :class:`InvestigativeActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------+--------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_action_histories'
    _def_attributes = ["action", "created_at", "deleted_at", "value"]
    _def_relationships = ["assigned_to_actor", "created_by", "expel_alert", "investigation", "investigative_action"]


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
            'content_driven_results': {},
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
        | Investigative Action Type Restricted to: "TASKABILITY", "HUNTING", "MANUAL", "RESEARCH", "PIVOT", "QUICK_UPLOAD", "VERIFY", "DOWNGRADE", "WORKFLOW", "NOTIFY"                   | action_type                         | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Verify Investigative action is authorized Allows: null                                                                                                                          | activity_authorized                 | boolean                                   | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Verify Investigative action verified by Allows: null                                                                                                                            | activity_verified_by                | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Capability name Allows: "", null                                                                                                                                                | capability_name                     | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Close Reason Allows: null                                                                                                                                                       | close_reason                        | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Content driven results Allows: "", null: no-sort                                                                                                                                | content_driven_results              | object                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                     | created_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                               | deleted_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Downgrade reason Restricted to: "FALSE_POSITIVE", "ATTACK_FAILED", "POLICY_VIOLATION", "ACTIVITY_BLOCKED", "PUP_PUA", "BENIGN", "IT_MISCONFIGURATION", "OTHER" Allows: null     | downgrade_reason                    | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Downgrade reason: readonly                                                                                                                                                      | files_count                         | number                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Task input arguments Allows: null: no-sort                                                                                                                                      | input_args                          | object                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Instructions Allows: "", null                                                                                                                                                   | instructions                        | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Reason                                                                                                                                                                          | reason                              | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Result byte size: readonly                                                                                                                                                      | result_byte_size                    | number                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Result task id Allows: null: readonly                                                                                                                                           | result_task_id                      | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Results/Analysis Allows: "", null                                                                                                                                               | results                             | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action created by robot action: readonly                                                                                                                          | robot_action                        | boolean                                   | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Restricted to: "RUNNING", "FAILED", "READY_FOR_ANALYSIS", "CLOSED", "COMPLETED"                                                                                          | status                              | any                                       | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                        | status_updated_at                   | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Taskability action id Allows: "", null                                                                                                                                          | taskability_action_id               | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Taskabilities error Allows: "", null: no-sort                                                                                                                                   | tasking_error                       | object                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Title                                                                                                                                                                           | title                               | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                | updated_at                          | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Workflow job id Allows: "", null                                                                                                                                                | workflow_job_id                     | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Workflow name Allows: "", null                                                                                                                                                  | workflow_name                       | string                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | analysis_assigned_to_actor          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | assigned_to_actor                   | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | created_by                          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                           | dependent_investigative_actions     | :class:`InvestigativeActions`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                           | depends_on_investigative_action     | :class:`InvestigativeActions`             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                    | expel_alert                         | :class:`ExpelAlerts`                      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | File                                                                                                                                                                            | files                               | :class:`Files`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                  | investigation                       | :class:`Investigations`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Investigative action histories                                                                                                                                                  | investigative_action_histories      | :class:`InvestigativeActionHistories`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                | security_device                     | :class:`SecurityDevices`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                        | updated_by                          | :class:`Actors`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------+-------------------------------------------+---------------+------------------+

    '''
    _api_type = 'investigative_actions'
    _def_attributes = ["action_type", "activity_authorized", "activity_verified_by", "capability_name", "close_reason", "content_driven_results", "created_at", "deleted_at", "downgrade_reason", "files_count", "input_args",
                       "instructions", "reason", "result_byte_size", "result_task_id", "results", "robot_action", "status", "status_updated_at", "taskability_action_id", "tasking_error", "title", "updated_at", "workflow_job_id", "workflow_name"]
    _def_relationships = ["analysis_assigned_to_actor", "assigned_to_actor", "created_by", "dependent_investigative_actions",
                          "depends_on_investigative_action", "expel_alert", "files", "investigation", "investigative_action_histories", "security_device", "updated_by"]


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
        | Expel alerts                                 | destination_expel_alerts       | :class:`ExpelAlerts`        | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | destination_investigations     | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | investigations                 | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Expel alerts                                 | source_expel_alerts            | :class:`ExpelAlerts`        | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Investigations                               | source_investigations          | :class:`Investigations`     | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                     | :class:`Actors`             | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+
        | Vendor alerts                                | vendor_alerts                  | :class:`VendorAlerts`       | N             | Y                |
        +----------------------------------------------+--------------------------------+-----------------------------+---------------+------------------+

    '''
    _api_type = 'ip_addresses'
    _def_attributes = ["address", "created_at", "updated_at"]
    _def_relationships = ["created_by", "destination_expel_alerts", "destination_investigations",
                          "investigations", "source_expel_alerts", "source_investigations", "updated_by", "vendor_alerts"]


class MitreTactics(ResourceInstance):
    '''
    .. _api mitre_tactics:

    Mitre Tactics

    Resource type name is **mitre_tactics**.

    Example JSON record:

    .. code-block:: javascript

        {'description': 'string', 'name': 'string', 'number_of_expel_detections': 100, 'number_of_vendor_detections': 100}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------+---------------------------------+----------------+---------------+------------------+
        | Field Description                                                                            | Field Name                      | Field Type     | Attribute     | Relationship     |
        +==============================================================================================+=================================+================+===============+==================+
        | The tactic description Allows: "", null                                                      | description                     | string         | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------------+----------------+---------------+------------------+
        | The name of the tactic Allows: "", null                                                      | name                            | string         | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------------+----------------+---------------+------------------+
        | The number of Expel-based detections in this category, based on the plugin_slugs filter      | number_of_expel_detections      | number         | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------------+----------------+---------------+------------------+
        | The number of vendor-based detections in this category, based on the plugin_slugs filter     | number_of_vendor_detections     | number         | Y             | N                |
        +----------------------------------------------------------------------------------------------+---------------------------------+----------------+---------------+------------------+

    '''
    _api_type = 'mitre_tactics'
    _def_attributes = ["description", "name", "number_of_expel_detections", "number_of_vendor_detections"]
    _def_relationships = []


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
        | Actor type Restricted to: "IDENTIFY", "PROTECT", "DETECT", "RECOVER", "RESPOND"     | function_type          | any                            | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Nist category abbreviated identifier                                                | identifier             | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Nist category name                                                                  | name                   | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                    | updated_at             | string                         | Y             | N                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                            | created_by             | :class:`Actors`                | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_subcategory records                                 | nist_subcategories     | :class:`NistSubcategories`     | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                            | updated_by             | :class:`Actors`                | N             | Y                |
        +-------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_categories'
    _def_attributes = ["created_at", "function_type", "identifier", "name", "updated_at"]
    _def_relationships = ["created_by", "nist_subcategories", "updated_by"]


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
        | Nist subcategory title Allows: "", null              | name                        | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                     | updated_at                  | string                             | Y             | N                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records             | created_by                  | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_category records     | nist_category               | :class:`NistCategories`            | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                       | nist_subcategory_scores     | :class:`NistSubcategoryScores`     | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records             | updated_by                  | :class:`Actors`                    | N             | Y                |
        +------------------------------------------------------+-----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategories'
    _def_attributes = ["created_at", "identifier", "name", "updated_at"]
    _def_relationships = ["created_by", "nist_category", "nist_subcategory_scores", "updated_by"]


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
        | NIST subcategory score history action Restricted to: "SCORE_UPDATED", "COMMENT_UPDATED", "PRIORITY_UPDATED", "IMPORT"                                                                                                                                 | action                     | any                                | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Organization actual score for this nist subcategory                                                                                                                                                                                                   | actual_score               | number                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Recorded date of the score assessment (Note: Dates with times will be truncated to the day.  Warning: Dates times and timezones will be converted to UTC before they are truncated.  Providing non-UTC timezones is not recommeneded.): immutable     | assessment_date            | string                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                           | created_at                 | string                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Organization target score for this nist subcategory                                                                                                                                                                                                   | target_score               | number                             | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                              | created_by                 | :class:`Actors`                    | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                                                                                                                                                                                                                        | nist_subcategory_score     | :class:`NistSubcategoryScores`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategory_score_histories'
    _def_attributes = ["action", "actual_score", "assessment_date", "created_at", "target_score"]
    _def_relationships = ["created_by", "nist_subcategory_score"]


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
        | Organization actual score for this nist subcategory Allows: null                                                                                                                                                                                                   | actual_score                         | number                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Recorded date of the score assessment (Note: Dates with times will be truncated to the day.  Warning: Dates times and timezones will be converted to UTC before they are truncated.  Providing non-UTC timezones is not recommeneded.) Allows: null: immutable     | assessment_date                      | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort, no-filter                                                                                                                                                                                                         | category_identifier                  | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort, no-filter                                                                                                                                                                                                         | category_name                        | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization comment for this nist subcategory Allows: "", null                                                                                                                                                                                                    | comment                              | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                        | created_at                           | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort, no-filter                                                                                                                                                                                                         | function_type                        | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization nist subcategory is a priority                                                                                                                                                                                                                        | is_priority                          | boolean                                    | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: immutable, no-sort, no-filter                                                                                                                                                                                                                    | subcategory_identifier               | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Allows: "", null: readonly, csv_ignore, no-sort, no-filter                                                                                                                                                                                                         | subcategory_name                     | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization target score for this nist subcategory Allows: null                                                                                                                                                                                                   | target_score                         | number                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                   | updated_at                           | string                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                           | created_by                           | :class:`Actors`                            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io nist_subcategory records                                                                                                                                                                                                                | nist_subcategory                     | :class:`NistSubcategories`                 | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | NIST Subcategory Score History                                                                                                                                                                                                                                     | nist_subcategory_score_histories     | :class:`NistSubcategoryScoreHistories`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                    | organization                         | :class:`Organizations`                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                           | updated_by                           | :class:`Actors`                            | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'nist_subcategory_scores'
    _def_attributes = ["actual_score", "assessment_date", "category_identifier", "category_name", "comment", "created_at",
                       "function_type", "is_priority", "subcategory_identifier", "subcategory_name", "target_score", "updated_at"]
    _def_relationships = ["created_by", "nist_subcategory",
                          "nist_subcategory_score_histories", "organization", "updated_by"]


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
        | Organization Resilience Group Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS"     | category                                         | any                                        | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                       | created_at                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Group title                                                                                       | title                                            | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                  | updated_at                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Visible                                                                                           | visible                                          | boolean                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | created_by                                       | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                   | organization                                     | :class:`Organizations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                | organization_resilience_action_group_actions     | :class:`OrganizationResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_group records                                        | source_resilience_action_group                   | :class:`ResilienceActionGroups`            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                          | updated_by                                       | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------+--------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organization_resilience_action_groups'
    _def_attributes = ["category", "created_at", "title", "updated_at", "visible"]
    _def_relationships = ["created_by", "organization",
                          "organization_resilience_action_group_actions", "source_resilience_action_group", "updated_by"]


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
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null     | category                                 | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Comment Allows: "", null                                                         | comment                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                      | created_at                               | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Details                                                                          | details                                  | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Impact Restricted to: "LOW", "MEDIUM", "HIGH"                                    | impact                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Status Restricted to: "TOP_PRIORITY", "IN_PROGRESS", "WONT_DO", "COMPLETED"      | status                                   | any                                             | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Title                                                                            | title                                    | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                 | updated_at                               | string                                          | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Visible                                                                          | visible                                  | boolean                                         | Y             | N                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | assigned_to_actor                        | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | created_by                               | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                   | investigation_hints                      | :class:`Investigations`                         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigation to resilience actions                                              | investigation_resilience_actions         | :class:`InvestigationResilienceActions`         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                   | investigations                           | :class:`Investigations`                         | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                  | organization                             | :class:`Organizations`                          | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_resilience_action_group records          | organization_resilience_action_group     | :class:`OrganizationResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Resilience actions                                                               | source_resilience_action                 | :class:`ResilienceActions`                      | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | updated_by                               | :class:`Actors`                                 | N             | Y                |
        +----------------------------------------------------------------------------------+------------------------------------------+-------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organization_resilience_actions'
    _def_attributes = ["category", "comment", "created_at", "details",
                       "impact", "status", "title", "updated_at", "visible"]
    _def_relationships = ["assigned_to_actor", "created_by", "investigation_hints", "investigation_resilience_actions",
                          "investigations", "organization", "organization_resilience_action_group", "source_resilience_action", "updated_by"]


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
        | Defines/retrieves expel.io organization records     | organization            | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records            | updated_by              | :class:`Actors`            | N             | Y                |
        +-----------------------------------------------------+-------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'organization_statuses'
    _def_attributes = ["created_at", "enabled_login_types", "restrictions", "updated_at"]
    _def_relationships = ["created_by", "organization", "updated_by"]


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

        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Field Description                                                                                             | Field Name                                         | Field Type                                      | Attribute     | Relationship     |
        +===============================================================================================================+====================================================+=================================================+===============+==================+
        | Address 1 Allows: "", null                                                                                    | address_1                                          | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Address 2 Allows: "", null                                                                                    | address_2                                          | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | City Allows: "", null                                                                                         | city                                               | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Country Code Allows: null                                                                                     | country_code                                       | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                   | created_at                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                             | deleted_at                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The city where the organization's headquarters is located Allows: "", null                                    | hq_city                                            | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Allows: "", null                                                                                              | hq_utc_offset                                      | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The organization's primary industry Allows: "", null                                                          | industry                                           | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Is surge                                                                                                      | is_surge                                           | boolean                                         | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | The organization's operating name                                                                             | name                                               | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Number of nodes covered for this organization Allows: null                                                    | nodes_count                                        | number                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | o365 Terms of Service identifier (e.g. hubspot id, etc.) Allows: null                                         | o365_tos_id                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Postal Code Allows: null                                                                                      | postal_code                                        | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | State/Province/Region Allows: "", null                                                                        | region                                             | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization service renewal date Allows: null                                                                | service_renewal_at                                 | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization service start date Allows: null                                                                  | service_start_at                                   | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization short name Allows: null                                                                          | short_name                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                              | updated_at                                         | string                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Number of users covered for this organization Allows: null                                                    | users_count                                        | number                                          | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | actor                                              | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | alert_assignables                                  | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | analysis_assigned_investigative_actions            | :class:`InvestigativeActions`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io api_key records. These can only be created by a user and require an OTP token.     | api_keys                                           | :class:`ApiKeys`                                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Assemblers                                                                                                    | assemblers                                         | :class:`Assemblers`                             | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | assigned_expel_alerts                              | :class:`ExpelAlerts`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | assigned_investigations                            | :class:`Investigations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | investigative actions                                                                                         | assigned_investigative_actions                     | :class:`InvestigativeActions`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions           | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | assigned_organization_resilience_actions_list      | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                           | assigned_remediation_actions                       | :class:`RemediationActions`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records                                                 | automate_opt_in_for_remediation_action_setting     | :class:`RemediationActionSettings`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io comment records                                                                    | comments                                           | :class:`Comments`                               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io configuration records                                                              | configurations                                     | :class:`Configurations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                                                          | context_label_tags                                 | :class:`ContextLabelTags`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                              | context_labels                                     | :class:`ContextLabels`                          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | created_by                                         | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io engagement_manager records                                                         | engagement_manager                                 | :class:`EngagementManagers`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | path to entitlements service                                                                                  | entitlement                                        | :class:`Entitlements`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alert histories                                                                                         | expel_alert_histories                              | :class:`ExpelAlertHistories`                    | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                  | expel_alerts                                       | :class:`ExpelAlerts`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | File                                                                                                          | files                                              | :class:`Files`                                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io integration records                                                                | integrations                                       | :class:`Integrations`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | investigation_assignables                          | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigation histories                                                                                       | investigation_histories                            | :class:`InvestigationHistories`                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Investigations                                                                                                | investigations                                     | :class:`Investigations`                         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Latest NIST subcategory scores                                                                                | nist_subcategory_scores                            | :class:`NistSubcategoryScores`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                 | notification_preferences                           | :class:`NotificationPreferences`                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization_resilience_action_group records                                       | organization_resilience_action_groups              | :class:`OrganizationResilienceActionGroups`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                            | organization_resilience_actions                    | :class:`OrganizationResilienceActions`          | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Organization status                                                                                           | organization_status                                | :class:`OrganizationStatuses`                   | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io user_account_role records                                                          | organization_user_account_roles                    | :class:`UserAccountRoles`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_history records                                         | remediation_action_setting_histories               | :class:`RemediationActionSettingHistories`      | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records                                                 | remediation_action_settings                        | :class:`RemediationActionSettings`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | SAML Identity Providers                                                                                       | saml_identity_provider                             | :class:`SamlIdentityProviders`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Security devices                                                                                              | security_devices                                   | :class:`SecurityDevices`                        | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                      | updated_by                                         | :class:`Actors`                                 | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User accounts                                                                                                 | user_accounts                                      | :class:`UserAccounts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | User accounts                                                                                                 | user_accounts_with_roles                           | :class:`UserAccounts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                 | vendor_alerts                                      | :class:`VendorAlerts`                           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------+----------------------------------------------------+-------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'organizations'
    _def_attributes = ["address_1", "address_2", "city", "country_code", "created_at", "deleted_at", "hq_city", "hq_utc_offset", "industry", "is_surge",
                       "name", "nodes_count", "o365_tos_id", "postal_code", "region", "service_renewal_at", "service_start_at", "short_name", "updated_at", "users_count"]
    _def_relationships = ["actor", "alert_assignables", "analysis_assigned_investigative_actions", "api_keys", "assemblers", "assigned_expel_alerts", "assigned_investigations", "assigned_investigative_actions", "assigned_organization_resilience_actions", "assigned_organization_resilience_actions_list", "assigned_remediation_actions", "automate_opt_in_for_remediation_action_setting", "comments", "configurations", "context_label_tags", "context_labels", "created_by", "engagement_manager", "entitlement",
                          "expel_alert_histories", "expel_alerts", "files", "integrations", "investigation_assignables", "investigation_histories", "investigations", "nist_subcategory_scores", "notification_preferences", "organization_resilience_action_groups", "organization_resilience_actions", "organization_status", "organization_user_account_roles", "remediation_action_setting_histories", "remediation_action_settings", "saml_identity_provider", "security_devices", "updated_by", "user_accounts", "user_accounts_with_roles", "vendor_alerts"]


class PhishingSubmissionAttachments(ResourceInstance):
    '''
    .. _api phishing_submission_attachments:

    Phishing submission attachments

    Resource type name is **phishing_submission_attachments**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'file_md5': 'string', 'file_mime': 'string', 'file_name': 'string', 'file_sha256': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name              | Field Type                       | Attribute     | Relationship     |
        +==============================================+=========================+==================================+===============+==================+
        | Created timestamp: readonly                  | created_at              | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
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
    _def_attributes = ["created_at", "file_md5", "file_mime", "file_name", "file_sha256"]
    _def_relationships = ["attachment_file", "created_by", "phishing_submission"]


class PhishingSubmissionDomains(ResourceInstance):
    '''
    .. _api phishing_submission_domains:

    Phishing submission domains

    Resource type name is **phishing_submission_domains**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'value': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name              | Field Type                       | Attribute     | Relationship     |
        +==============================================+=========================+==================================+===============+==================+
        | Created timestamp: readonly                  | created_at              | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Value                                        | value                   | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by              | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission     | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_domains'
    _def_attributes = ["created_at", "value"]
    _def_relationships = ["created_by", "phishing_submission"]


class PhishingSubmissionHeaders(ResourceInstance):
    '''
    .. _api phishing_submission_headers:

    Phishing submission headers

    Resource type name is **phishing_submission_headers**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'name': 'string', 'value': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name              | Field Type                       | Attribute     | Relationship     |
        +==============================================+=========================+==================================+===============+==================+
        | Created timestamp: readonly                  | created_at              | string                           | Y             | N                |
        +----------------------------------------------+-------------------------+----------------------------------+---------------+------------------+
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
    _def_attributes = ["created_at", "name", "value"]
    _def_relationships = ["created_by", "phishing_submission"]


class PhishingSubmissionUrls(ResourceInstance):
    '''
    .. _api phishing_submission_urls:

    Phishing submission URLs

    Resource type name is **phishing_submission_urls**.

    Example JSON record:

    .. code-block:: javascript

        {'contains_sub_elements': True, 'created_at': '2019-01-15T15:35:00-05:00', 'link_text': 'string', 'tags': 'https://company.com/', 'url_type': 'https://company.com/', 'value': 'string'}


    Below are valid filter by parameters:

        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Field Description                            | Field Name                | Field Type                       | Attribute     | Relationship     |
        +==============================================+===========================+==================================+===============+==================+
        | Was sonar prediction correct                 | contains_sub_elements     | boolean                          | Y             | N                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Created timestamp: readonly                  | created_at                | string                           | Y             | N                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Link text value                              | link_text                 | string                           | Y             | N                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Interesting URL tags: no-sort                | tags                      | string                           | Y             | N                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | URL type                                     | url_type                  | string                           | Y             | N                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Value                                        | value                     | string                           | Y             | N                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                | :class:`Actors`                  | N             | Y                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Phishing submissions                         | phishing_submission       | :class:`PhishingSubmissions`     | N             | Y                |
        +----------------------------------------------+---------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submission_urls'
    _def_attributes = ["contains_sub_elements", "created_at", "link_text", "tags", "url_type", "value"]
    _def_relationships = ["created_by", "phishing_submission"]


class PhishingSubmissions(ResourceInstance):
    '''
    .. _api phishing_submissions:

    Phishing submissions

    Resource type name is **phishing_submissions**.

    Example JSON record:

    .. code-block:: javascript

        {           'add_to_at': '2019-01-15T15:35:00-05:00',
            'arthurai_inference_id': 'string',
            'automated_action_type': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'email_type': 'name@company.com',
            'ingest_source': 'string',
            'msg_id': 'string',
            'received_at': '2019-01-15T15:35:00-05:00',
            'reported_at': '2019-01-15T15:35:00-05:00',
            'return_path': 'string',
            'sender': 'string',
            'sender_domain': 'string',
            'subject': 'string',
            'submitted_by': 'string',
            'triaged_at': '2019-01-15T15:35:00-05:00',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'was_sonar_correct': True}


    Below are valid filter by parameters:

        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                            | Field Name                          | Field Type                                 | Attribute     | Relationship     |
        +==============================================+=====================================+============================================+===============+==================+
        | Added at Allows: null                        | add_to_at                           | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | ArthurAI Inference ID Allows: null           | arthurai_inference_id               | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Automated action type Allows: "", null       | automated_action_type               | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                  | created_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Email type Allows: "", null                  | email_type                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Ingest source Allows: ""                     | ingest_source                       | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Message ID                                   | msg_id                              | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Received at                                  | received_at                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Reported at                                  | reported_at                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Return path Allows: ""                       | return_path                         | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Sender                                       | sender                              | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Sender domain                                | sender_domain                       | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Subject Allows: ""                           | subject                             | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Submitted by                                 | submitted_by                        | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Triaged at Allows: null                      | triaged_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at                          | string                                     | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Was sonar prediction correct                 | was_sonar_correct                   | boolean                                    | Y             | N                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | analysis_email_file                 | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                 | expel_alert                         | :class:`ExpelAlerts`                       | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | initial_email_file                  | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission attachments              | phishing_submission_attachments     | :class:`PhishingSubmissionAttachments`     | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission domains                  | phishing_submission_domains         | :class:`PhishingSubmissionDomains`         | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission headers                  | phishing_submission_headers         | :class:`PhishingSubmissionHeaders`         | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Phishing submission URLs                     | phishing_submission_urls            | :class:`PhishingSubmissionUrls`            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | File                                         | raw_body_file                       | :class:`Files`                             | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by                          | :class:`Actors`                            | N             | Y                |
        +----------------------------------------------+-------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'phishing_submissions'
    _def_attributes = ["add_to_at", "arthurai_inference_id", "automated_action_type", "created_at", "email_type", "ingest_source", "msg_id",
                       "received_at", "reported_at", "return_path", "sender", "sender_domain", "subject", "submitted_by", "triaged_at", "updated_at", "was_sonar_correct"]
    _def_relationships = ["analysis_email_file", "created_by", "expel_alert", "initial_email_file", "phishing_submission_attachments",
                          "phishing_submission_domains", "phishing_submission_headers", "phishing_submission_urls", "raw_body_file", "updated_by"]


class RemediationActionAssetHistories(ResourceInstance):
    '''
    .. _api remediation_action_asset_histories:

    Remediation action asset histories

    Resource type name is **remediation_action_asset_histories**.

    Example JSON record:

    .. code-block:: javascript

        {           'action': 'CREATED',
            'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS',
            'asset_type': 'ACCOUNT',
            'automate_revert': True,
            'automate_status': 'NEW',
            'created_at': '2019-01-15T15:35:00-05:00',
            'status': 'OPEN',
            'value': {}}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Field Name                   | Field Type                           | Attribute     | Relationship     |
        +==============================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+==============================+======================================+===============+==================+
        | Remediation action asset history action Restricted to: "CREATED", "COMPLETED", "REOPENED", "UPDATED", "DELETED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | action                       | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Action type of associated parent remediation action Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type                  | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation asset type history Restricted to: "ACCOUNT", "ACCESS_KEY", "DESCRIPTION", "DEVICE", "DOMAIN_NAME", "EMAIL", "FILE", "HASH", "HOST", "INBOX_RULE_NAME", "IP_ADDRESS" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                 | asset_type                   | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Automated remediation asset revert history Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | automate_revert              | boolean                              | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Automated remediation asset status history Restricted to: "NEW", "CREATED", "STARTING", "VERIFYING", "COMPLETED", "FAILED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | automate_status              | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | created_at                   | string                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation asset status history Restricted to: "OPEN", "COMPLETED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | status                       | any                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action asset history details Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | value                        | object                               | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | created_by                   | :class:`Actors`                      | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | investigation                | :class:`Investigations`              | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+
        | Remediation action assets                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | remediation_action_asset     | :class:`RemediationActionAssets`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------+--------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_asset_histories'
    _def_attributes = ["action", "action_type", "asset_type",
                       "automate_revert", "automate_status", "created_at", "status", "value"]
    _def_relationships = ["created_by", "investigation", "remediation_action_asset"]


class RemediationActionAssets(ResourceInstance):
    '''
    .. _api remediation_action_assets:

    Remediation action assets

    Resource type name is **remediation_action_assets**.

    Example JSON record:

    .. code-block:: javascript

        {           'asset_type': 'ACCOUNT',
            'automate_revert': True,
            'automate_status': 'NEW',
            'automate_status_updated_at': '2019-01-15T15:35:00-05:00',
            'automate_task_error': {},
            'automate_task_id': 'string',
            'automate_task_result_id': 'object',
            'category': 'AFFECTED_ACCOUNT',
            'created_at': '2019-01-15T15:35:00-05:00',
            'status': 'OPEN',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'value': 'object'}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                           | Field Name                             | Field Type                                   | Attribute     | Relationship     |
        +=============================================================================================================================================================================+========================================+==============================================+===============+==================+
        | Remediation asset type Restricted to: "ACCOUNT", "ACCESS_KEY", "DESCRIPTION", "DEVICE", "DOMAIN_NAME", "EMAIL", "FILE", "HASH", "HOST", "INBOX_RULE_NAME", "IP_ADDRESS"     | asset_type                             | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Start automated remediation revert process                                                                                                                                  | automate_revert                        | boolean                                      | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Automated remediation status for this asset Restricted to: "NEW", "CREATED", "STARTING", "VERIFYING", "COMPLETED", "FAILED" Allows: null: readonly                          | automate_status                        | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Automated remediation status last updated at Allows: null: readonly                                                                                                         | automate_status_updated_at             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Automated remediation task error Allows: "", null: readonly, no-sort                                                                                                        | automate_task_error                    | object                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Automated remediation task id Allows: "", null: readonly                                                                                                                    | automate_task_id                       | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Automated remediation task result id Allows: null: readonly                                                                                                                 | automate_task_result_id                | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation asset category Restricted to: "AFFECTED_ACCOUNT", "COMPROMISED_ACCOUNT", "FORWARDING_ADDRESS" Allows: null                                                      | category                               | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                 | created_at                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Asset status Restricted to: "OPEN", "COMPLETED"                                                                                                                             | status                                 | any                                          | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                            | updated_at                             | string                                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation asset value: allowStringOperators, no-sort                                                                                                                      | value                                  | alternatives                                 | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_tag records                                                                                                                        | context_label_tags                     | :class:`ContextLabelTags`                    | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                    | created_by                             | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                         | remediation_action                     | :class:`RemediationActions`                  | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Remediation action asset histories                                                                                                                                          | remediation_action_asset_histories     | :class:`RemediationActionAssetHistories`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                    | updated_by                             | :class:`Actors`                              | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------+----------------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_assets'
    _def_attributes = ["asset_type", "automate_revert", "automate_status", "automate_status_updated_at", "automate_task_error",
                       "automate_task_id", "automate_task_result_id", "category", "created_at", "status", "updated_at", "value"]
    _def_relationships = ["context_label_tags", "created_by",
                          "remediation_action", "remediation_action_asset_histories", "updated_by"]


class RemediationActionHistories(ResourceInstance):
    '''
    .. _api remediation_action_histories:

    Remediation action histories

    Resource type name is **remediation_action_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS', 'can_automate': True, 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Field Name             | Field Type                      | Attribute     | Relationship     |
        +==========================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+========================+=================================+===============+==================+
        | Remediation action history action Restricted to: "CREATED", "ASSIGNED", "COMPLETED", "CLOSED", "UPDATED", "DELETED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | action                 | any                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Action type of source parent remediation action Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type            | any                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation action can be automated history                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | can_automate           | boolean                         | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | created_at             | string                          | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation action history details Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | value                  | object                          | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | assigned_to_actor      | :class:`Actors`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | created_by             | :class:`Actors`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | investigation          | :class:`Investigations`         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | remediation_action     | :class:`RemediationActions`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | security_device        | :class:`SecurityDevices`        | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+---------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_histories'
    _def_attributes = ["action", "action_type", "can_automate", "created_at", "value"]
    _def_relationships = ["assigned_to_actor", "created_by", "investigation", "remediation_action", "security_device"]


class RemediationActionSettingHistories(ResourceInstance):
    '''
    .. _api remediation_action_setting_histories:

    Defines/retrieves expel.io remediation_action_setting_history records

    Resource type name is **remediation_action_setting_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS', 'created_at': '2019-01-15T15:35:00-05:00', 'value': {}}


    Below are valid filter by parameters:

        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Field Name                     | Field Type                             | Attribute     | Relationship     |
        +==================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+================================+========================================+===============+==================+
        | Remediation action setting history action Restricted to: "CREATED", "UPDATED", "DELETED" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | action                         | any                                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+
        | Action type of source parent remediation action setting Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type                    | any                                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | created_at                     | string                                 | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+
        | Remediation action setting history details Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | value                          | object                                 | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | created_by                     | :class:`Actors`                        | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | organization                   | :class:`Organizations`                 | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | remediation_action_setting     | :class:`RemediationActionSettings`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+--------------------------------+----------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_setting_histories'
    _def_attributes = ["action", "action_type", "created_at", "value"]
    _def_relationships = ["created_by", "organization", "remediation_action_setting"]


class RemediationActionSettingListSourceHistories(ResourceInstance):
    '''
    .. _api remediation_action_setting_list_source_histories:

    Defines/retrieves expel.io remediation_action_setting_list_source_history records

    Resource type name is **remediation_action_setting_list_source_histories**.

    Example JSON record:

    .. code-block:: javascript

        {'action': 'CREATED', 'created_at': '2019-01-15T15:35:00-05:00', 'source_type': 'CONTEXT_LABEL', 'value': {}}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Field Description                                                                                                     | Field Name                                 | Field Type                                       | Attribute     | Relationship     |
        +=======================================================================================================================+============================================+==================================================+===============+==================+
        | Remediation action setting list source history action Restricted to: "CREATED", "UPDATED", "DELETED" Allows: null     | action                                     | any                                              | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                           | created_at                                 | string                                           | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Source type Restricted to: "CONTEXT_LABEL"                                                                            | source_type                                | any                                              | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Remediation action setting list source history details Allows: null: no-sort                                          | value                                      | object                                           | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                      | context_label                              | :class:`ContextLabels`                           | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                              | created_by                                 | :class:`Actors`                                  | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records                                                         | remediation_action_setting                 | :class:`RemediationActionSettings`               | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_list_source records                                             | remediation_action_setting_list_source     | :class:`RemediationActionSettingListSources`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------+--------------------------------------------+--------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_setting_list_source_histories'
    _def_attributes = ["action", "created_at", "source_type", "value"]
    _def_relationships = ["context_label", "created_by",
                          "remediation_action_setting", "remediation_action_setting_list_source"]


class RemediationActionSettingListSources(ResourceInstance):
    '''
    .. _api remediation_action_setting_list_sources:

    Defines/retrieves expel.io remediation_action_setting_list_source records

    Resource type name is **remediation_action_setting_list_sources**.

    Example JSON record:

    .. code-block:: javascript

        {'created_at': '2019-01-15T15:35:00-05:00', 'source_type': 'CONTEXT_LABEL', 'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Field Description                                                                     | Field Name                                           | Field Type                                               | Attribute     | Relationship     |
        +=======================================================================================+======================================================+==========================================================+===============+==================+
        | Created timestamp: readonly                                                           | created_at                                           | string                                                   | Y             | N                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Source type Restricted to: "CONTEXT_LABEL"                                            | source_type                                          | any                                                      | Y             | N                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                      | updated_at                                           | string                                                   | Y             | N                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                      | context_label                                        | :class:`ContextLabels`                                   | N             | Y                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                              | created_by                                           | :class:`Actors`                                          | N             | Y                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records                         | remediation_action_setting                           | :class:`RemediationActionSettings`                       | N             | Y                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_list_source_history records     | remediation_action_setting_list_source_histories     | :class:`RemediationActionSettingListSourceHistories`     | N             | Y                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                              | updated_by                                           | :class:`Actors`                                          | N             | Y                |
        +---------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_setting_list_sources'
    _def_attributes = ["created_at", "source_type", "updated_at"]
    _def_relationships = ["context_label", "created_by", "remediation_action_setting",
                          "remediation_action_setting_list_source_histories", "updated_by"]


class RemediationActionSettings(ResourceInstance):
    '''
    .. _api remediation_action_settings:

    Defines/retrieves expel.io remediation_action_setting records

    Resource type name is **remediation_action_settings**.

    Example JSON record:

    .. code-block:: javascript

        {           'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS',
            'automate_list_type': 'DENY',
            'automate_opt_in': True,
            'automate_opt_in_agreement_version': 'V1<br/>Allows: null',
            'automate_opt_in_at': '2019-01-15T15:35:00-05:00',
            'created_at': '2019-01-15T15:35:00-05:00',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Field Name                                           | Field Type                                               | Attribute     | Relationship     |
        +===============================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+======================================================+==========================================================+===============+==================+
        | Setting's remediation action type Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365"     | action_type                                          | any                                                      | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Automated remediation setting list type Restricted to: "DENY", "ALLOW" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | automate_list_type                                   | any                                                      | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Opted in to automated remediations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | automate_opt_in                                      | boolean                                                  | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Automated remediations opt in agreement version Restricted to: "V1" Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | automate_opt_in_agreement_version                    | any                                                      | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Last opted in to automated remediations time Allows: null: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | automate_opt_in_at                                   | string                                                   | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | created_at                                           | string                                                   | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | updated_at                                           | string                                                   | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | automate_opt_in_actor                                | :class:`Actors`                                          | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_list_source records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | context_label_list_sources                           | :class:`RemediationActionSettingListSources`             | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | context_labels                                       | :class:`ContextLabels`                                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | created_by                                           | :class:`Actors`                                          | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_history records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | opt_in_histories                                     | :class:`RemediationActionSettingHistories`               | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_history records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | opt_out_histories                                    | :class:`RemediationActionSettingHistories`               | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | organization                                         | :class:`Organizations`                                   | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_history records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | remediation_action_setting_histories                 | :class:`RemediationActionSettingHistories`               | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_list_source_history records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | remediation_action_setting_list_source_histories     | :class:`RemediationActionSettingListSourceHistories`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting_list_source records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | remediation_action_setting_list_sources              | :class:`RemediationActionSettingListSources`             | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | updated_by                                           | :class:`Actors`                                          | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------+----------------------------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_action_settings'
    _def_attributes = ["action_type", "automate_list_type", "automate_opt_in",
                       "automate_opt_in_agreement_version", "automate_opt_in_at", "created_at", "updated_at"]
    _def_relationships = ["automate_opt_in_actor", "context_label_list_sources", "context_labels", "created_by", "opt_in_histories", "opt_out_histories", "organization",
                          "remediation_action_setting_histories", "remediation_action_setting_list_source_histories", "remediation_action_setting_list_sources", "updated_by"]


class RemediationActions(ResourceInstance):
    '''
    .. _api remediation_actions:

    Remediation actions

    Resource type name is **remediation_actions**.

    Example JSON record:

    .. code-block:: javascript

        {           'action': 'string',
            'action_type': 'BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS',
            'can_automate': True,
            'can_automate_completely': True,
            'cannot_automate_reason': 'DEVICE_ID_MISSING',
            'close_reason': 'string',
            'comment': 'string',
            'created_at': '2019-01-15T15:35:00-05:00',
            'deleted_at': '2019-01-15T15:35:00-05:00',
            'status': 'IN_PROGRESS',
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'template_name': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00',
            'version': 'V1'}


    Below are valid filter by parameters:

        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Field Name                       | Field Type                              | Attribute     | Relationship     |
        +======================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================================+==================================+=========================================+===============+==================+
        | Action Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | action                           | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Action type Restricted to: "BLOCK_COMMAND_AND_CONTROL_COMMUNICATIONS", "BLOCK_KNOWN_BAD_HASHES", "CONTAIN_HOSTS", "CONTAIN_INFECTED_REMOVABLE_MEDIA", "DELETE_MALICIOUS_FILES", "DISABLE_AND_MODIFY_AWS_ACCESS_KEYS", "MITIGATE_VULNERABILITY", "OTHER_REMEDIATION", "REMOVE_AND_BLOCK_EMAIL_FORWARDING_ADDRESS", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_OTHER", "REMOVE_COMPROMISED_SYSTEMS_FROM_NETWORK_AWS", "REMOVE_INBOX_RULES_FOR_KNOWN_COMPROMISED_ACCOUNTS", "RESET_CREDENTIALS_OTHER", "RESET_CREDENTIALS_AWS", "RESET_CREDENTIALS_O365" Allows: null     | action_type                      | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action can be automated: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | can_automate                     | boolean                                 | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action can be completely automated: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | can_automate_completely          | boolean                                 | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Reason this action cannot be automated Restricted to: "DEVICE_ID_MISSING", "ACTION_NOT_SUPPORTED", "DEVICE_NOT_SUPPORTED", "FEATURE_FLAG_ACTION_DISABLED", "FEATURE_FLAG_VENDOR_NOT_ALLOWED", "CUSTOMER_CONFIG_DISABLED", "ALLOWED_ASSETS_EMPTY", "ASSETS_NOT_ALLOWED" Allows: null: readonly                                                                                                                                                                                                                                                                        | cannot_automate_reason           | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Close Reason Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | close_reason                     | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Comment Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | comment                          | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | created_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | deleted_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Restricted to: "IN_PROGRESS", "COMPLETED", "CLOSED"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | status                           | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | status_updated_at                | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation Action Template Name Allows: "", null                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | template_name                    | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | updated_at                       | string                                  | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Version Restricted to: "V1", "V2", "V3"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | version                          | any                                     | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | assigned_to_actor                | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | created_by                       | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Investigations                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | investigation                    | :class:`Investigations`                 | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action assets                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | remediation_action_assets        | :class:`RemediationActionAssets`        | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action histories                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | remediation_action_histories     | :class:`RemediationActionHistories`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | security_device                  | :class:`SecurityDevices`                | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | updated_by                       | :class:`Actors`                         | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+

    '''
    _api_type = 'remediation_actions'
    _def_attributes = ["action", "action_type", "can_automate", "can_automate_completely", "cannot_automate_reason", "close_reason",
                       "comment", "created_at", "deleted_at", "status", "status_updated_at", "template_name", "updated_at", "version"]
    _def_relationships = ["assigned_to_actor", "created_by", "investigation",
                          "remediation_action_assets", "remediation_action_histories", "security_device", "updated_by"]


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
        | Global Resilience Group Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS"     | category               | any                            | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                 | created_at             | string                         | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Group title                                                                                 | title                  | string                         | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                            | updated_at             | string                         | Y             | N                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                    | created_by             | :class:`Actors`                | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Resilience actions                                                                          | resilience_actions     | :class:`ResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                    | updated_by             | :class:`Actors`                | N             | Y                |
        +---------------------------------------------------------------------------------------------+------------------------+--------------------------------+---------------+------------------+

    '''
    _api_type = 'resilience_action_groups'
    _def_attributes = ["category", "created_at", "title", "updated_at"]
    _def_relationships = ["created_by", "resilience_actions", "updated_by"]


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
        | Category Restricted to: "DISRUPT_ATTACKERS", "ENABLE_DEFENDERS" Allows: null     | category                    | any                                 | Y             | N                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
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
        | Defines/retrieves expel.io actor records                                         | created_by                  | :class:`Actors`                     | N             | Y                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io resilience_action_group records                       | resilience_action_group     | :class:`ResilienceActionGroups`     | N             | Y                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                         | updated_by                  | :class:`Actors`                     | N             | Y                |
        +----------------------------------------------------------------------------------+-----------------------------+-------------------------------------+---------------+------------------+

    '''
    _api_type = 'resilience_actions'
    _def_attributes = ["category", "created_at", "details", "impact", "title", "updated_at"]
    _def_relationships = ["created_by", "resilience_action_group", "updated_by"]


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
        | Allows: "", null                                    | cert             | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Allows: ""                                          | entity_id        | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Restricted to: "not_configured", "configured"       | status           | string                     | Y             | N                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records     | organization     | :class:`Organizations`     | N             | Y                |
        +-----------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'saml_identity_providers'
    _def_attributes = ["callback_uri", "cert", "entity_id", "status"]
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
            'properties': {},
            'status': 'healthy',
            'status_details': {},
            'status_updated_at': '2019-01-15T15:35:00-05:00',
            'task_source': 'CUSTOMER_PREMISE',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                  | Field Name                       | Field Type                              | Attribute     | Relationship     |
        +====================================================================================================================================================================================================================================================================================================================================================================+==================================+=========================================+===============+==================+
        | Created timestamp: readonly                                                                                                                                                                                                                                                                                                                                        | created_at                       | string                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                                                                                                                                                                                                                                                                                                                  | deleted_at                       | string                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Device Spec Allows: null: no-sort                                                                                                                                                                                                                                                                                                                                  | device_spec                      | object                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Device Type Restricted to: "ENDPOINT", "NETWORK", "SIEM", "OTHER", "CLOUD"                                                                                                                                                                                                                                                                                         | device_type                      | any                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Has 2fa secret stored in vault: readonly                                                                                                                                                                                                                                                                                                                           | has_two_factor_secret            | boolean                                 | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Location Allows: "", null                                                                                                                                                                                                                                                                                                                                          | location                         | string                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Name                                                                                                                                                                                                                                                                                                                                                               | name                             | string                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Allows: "", null                                                                                                                                                                                                                                                                                                                                                   | plugin_slug                      | string                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Properties about the security device: no-sort                                                                                                                                                                                                                                                                                                                      | properties                       | object                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status.    Note: By default if the security device has an assembler, and that assembler is unhealthy, the status will return that information rather than the raw status of the security device.  To disable this behavior, add the query parameter `flag[raw_status]=true`. Restricted to: "healthy", "unhealthy", "health_checks_not_supported" Allows: null     | status                           | any                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Details.  Note: By default if the security device has an assembler, and that assembler is unhealthy, the status details will return that information rather than the raw status of the security device.  To disable this behavior, add the query parameter `flag[raw_status]=true`. Allows: null: no-sort                                                   | status_details                   | object                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Status Updated At Allows: null: readonly                                                                                                                                                                                                                                                                                                                           | status_updated_at                | string                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Location where tasks are run Restricted to: "CUSTOMER_PREMISE", "EXPEL_TASKPOOL"                                                                                                                                                                                                                                                                                   | task_source                      | any                                     | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                                                                                                                                                                                                                   | updated_at                       | string                                  | Y             | N                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Assemblers                                                                                                                                                                                                                                                                                                                                                         | assembler                        | :class:`Assemblers`                     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                   | child_security_devices           | :class:`SecurityDevices`                | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                           | created_by                       | :class:`Actors`                         | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                                                                                                                                                                                                                                              | investigative_actions            | :class:`InvestigativeActions`           | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                                                                                                                                                                                                                    | organization                     | :class:`Organizations`                  | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Security devices                                                                                                                                                                                                                                                                                                                                                   | parent_security_device           | :class:`SecurityDevices`                | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation action histories                                                                                                                                                                                                                                                                                                                                       | remediation_action_histories     | :class:`RemediationActionHistories`     | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                                                                                                                                                                                                                                                | remediation_actions              | :class:`RemediationActions`             | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                                                                                                                                                                                                           | updated_by                       | :class:`Actors`                         | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Vendors                                                                                                                                                                                                                                                                                                                                                            | vendor                           | :class:`Vendors`                        | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                                                                                                                                                      | vendor_alerts                    | :class:`VendorAlerts`                   | N             | Y                |
        +--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------+-----------------------------------------+---------------+------------------+

    '''
    _api_type = 'security_devices'
    _def_attributes = ["created_at", "deleted_at", "device_spec", "device_type", "has_two_factor_secret", "location",
                       "name", "plugin_slug", "properties", "status", "status_details", "status_updated_at", "task_source", "updated_at"]
    _def_relationships = ["assembler", "child_security_devices", "created_by", "investigative_actions", "organization",
                          "parent_security_device", "remediation_action_histories", "remediation_actions", "updated_by", "vendor", "vendor_alerts"]


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
        | Attack phase of the Timeline Entry Allows: "", null                    | attack_phase              | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Comment on this Timeline Entry Allows: "", null                        | comment                   | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Created timestamp: readonly                                            | created_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Deleted At timestamp Allows: null                                      | deleted_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Destination Host (IP or Hostname) Allows: "", null                     | dest_host                 | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | The event, such as Powershell Attack Allows: "", null                  | event                     | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Date/Time of when the event occurred                                   | event_date                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | The type of the event, such as Carbon Black Alert Allows: "", null     | event_type                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Has been selected for final report.                                    | is_selected               | boolean                          | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Source Host (IP or Hostname) Allows: "", null                          | src_host                  | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                       | updated_at                | string                           | Y             | N                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label_action records                | context_label_actions     | :class:`ContextLabelActions`     | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io context_label records                       | context_labels            | :class:`ContextLabels`           | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                               | created_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Expel alerts                                                           | expel_alert               | :class:`ExpelAlerts`             | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Investigations                                                         | investigation             | :class:`Investigations`          | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                               | updated_by                | :class:`Actors`                  | N             | Y                |
        +------------------------------------------------------------------------+---------------------------+----------------------------------+---------------+------------------+

    '''
    _api_type = 'timeline_entries'
    _def_attributes = ["attack_phase", "comment", "created_at", "deleted_at", "dest_host",
                       "event", "event_date", "event_type", "is_selected", "src_host", "updated_at"]
    _def_relationships = ["context_label_actions", "context_labels",
                          "created_by", "expel_alert", "investigation", "updated_by"]


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
        | If this role is active                                                                                                                                                       | active           | boolean                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Can user be assigned items (e.g. investigations, etc)                                                                                                                        | assignable       | boolean                    | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                                                  | created_at       | string                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | User account role for this organization Restricted to: "expel_admin", "expel_analyst", "organization_admin", "organization_analyst", "system", "anonymous", "restricted"     | role             | any                        | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                                                             | updated_at       | string                     | Y             | N                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                     | created_by       | :class:`Actors`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                                                              | organization     | :class:`Organizations`     | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                                                     | updated_by       | :class:`Actors`            | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+
        | User accounts                                                                                                                                                                | user_account     | :class:`UserAccounts`      | N             | Y                |
        +------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'user_account_roles'
    _def_attributes = ["active", "assignable", "created_at", "role", "updated_at"]
    _def_relationships = ["created_by", "organization", "updated_by", "user_account"]


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
        | Missing Description                                                                                                     | active                              | boolean                    | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Restricted to: "ACTIVE", "LOCKED", "LOCKED_INVITED", "LOCKED_EXPIRED", "ACTIVE_INVITED", "ACTIVE_EXPIRED": readonly     | active_status                       | any                        | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Meta: readonly                                                                                                          | created_at                          | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Allows: null: readonly                                                                                                  | invite_token_expires_at             | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Allows: null: readonly                                                                                                  | password_reset_token_expires_at     | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Missing Description                                                                                                     | restrictions                        | array                      | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Meta: readonly                                                                                                          | updated_at                          | string                     | Y             | N                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                | created_by                          | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                         | primary_organization                | :class:`Organizations`     | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                | updated_by                          | :class:`Actors`            | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+
        | User accounts                                                                                                           | user_account                        | :class:`UserAccounts`      | N             | Y                |
        +-------------------------------------------------------------------------------------------------------------------------+-------------------------------------+----------------------------+---------------+------------------+

    '''
    _api_type = 'user_account_statuses'
    _def_attributes = ["active", "active_status", "created_at", "invite_token_expires_at",
                       "password_reset_token_expires_at", "restrictions", "updated_at"]
    _def_relationships = ["created_by", "primary_organization", "updated_by", "user_account"]


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
            'default_filter': 'ALL',
            'display_name': 'string',
            'email': 'name@company.com',
            'engagement_manager': True,
            'first_name': 'string',
            'homepage_preferences': {},
            'language': 'string',
            'last_name': 'string',
            'locale': 'string',
            'pagerduty_id': 'string',
            'phone_number': 'string',
            'timezone': 'string',
            'updated_at': '2019-01-15T15:35:00-05:00'}


    Below are valid filter by parameters:

        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Field Description                                                                                                                           | Field Name                                         | Field Type                                 | Attribute     | Relationship     |
        +=============================================================================================================================================+====================================================+============================================+===============+==================+
        | Active Allows: null                                                                                                                         | active                                             | boolean                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Restricted to: "ACTIVE", "LOCKED", "LOCKED_INVITED", "LOCKED_EXPIRED", "ACTIVE_INVITED", "ACTIVE_EXPIRED": readonly, no-sort, no-filter     | active_status                                      | any                                        | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Can user be assigned items (e.g. investigations, etc)                                                                                       | assignable                                         | boolean                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Created timestamp: readonly                                                                                                                 | created_at                                         | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User account default filter Restricted to: "ALL", "MDR", "PHISHING"                                                                         | default_filter                                     | any                                        | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Display name Allows: "", null                                                                                                               | display_name                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Email                                                                                                                                       | email                                              | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Is an engagement manager                                                                                                                    | engagement_manager                                 | boolean                                    | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | First Name                                                                                                                                  | first_name                                         | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Homepage preferences Allows: null: no-sort                                                                                                  | homepage_preferences                               | object                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Language Allows: "", null                                                                                                                   | language                                           | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Name                                                                                                                                   | last_name                                          | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Locale Allows: "", null                                                                                                                     | locale                                             | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Pagerduty ID Allows: null                                                                                                                   | pagerduty_id                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Phone number Allows: null                                                                                                                   | phone_number                                       | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Timezone Allows: "", null                                                                                                                   | timezone                                           | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                                                            | updated_at                                         | string                                     | Y             | N                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | actor                                              | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                       | analysis_assigned_investigative_actions            | :class:`InvestigativeActions`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                | assigned_expel_alerts                              | :class:`ExpelAlerts`                       | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Investigations                                                                                                                              | assigned_investigations                            | :class:`Investigations`                    | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | investigative actions                                                                                                                       | assigned_investigative_actions                     | :class:`InvestigativeActions`              | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                          | assigned_organization_resilience_actions           | :class:`OrganizationResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Organization to resilience actions                                                                                                          | assigned_organization_resilience_actions_list      | :class:`OrganizationResilienceActions`     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Remediation actions                                                                                                                         | assigned_remediation_actions                       | :class:`RemediationActions`                | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io remediation_action_setting records                                                                               | automate_opt_in_for_remediation_action_setting     | :class:`RemediationActionSettings`         | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | created_by                                         | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User Notification Preferences                                                                                                               | notification_preferences                           | :class:`NotificationPreferences`           | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                             | organizations                                      | :class:`Organizations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                                             | primary_organization                               | :class:`Organizations`                     | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                                                    | updated_by                                         | :class:`Actors`                            | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | Defines/retrieves expel.io user_account_role records                                                                                        | user_account_roles                                 | :class:`UserAccountRoles`                  | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+
        | User account status                                                                                                                         | user_account_status                                | :class:`UserAccountStatuses`               | N             | Y                |
        +---------------------------------------------------------------------------------------------------------------------------------------------+----------------------------------------------------+--------------------------------------------+---------------+------------------+

    '''
    _api_type = 'user_accounts'
    _def_attributes = ["active", "active_status", "assignable", "created_at", "default_filter", "display_name", "email", "engagement_manager",
                       "first_name", "homepage_preferences", "language", "last_name", "locale", "pagerduty_id", "phone_number", "timezone", "updated_at"]
    _def_relationships = ["actor", "analysis_assigned_investigative_actions", "assigned_expel_alerts", "assigned_investigations", "assigned_investigative_actions", "assigned_organization_resilience_actions", "assigned_organization_resilience_actions_list",
                          "assigned_remediation_actions", "automate_opt_in_for_remediation_action_setting", "created_by", "notification_preferences", "organizations", "primary_organization", "updated_by", "user_account_roles", "user_account_status"]


class VendorAlertEvidences(ResourceInstance):
    '''
    .. _api vendor_alert_evidences:

    Vendor alert evidences are extracted from a vendor alert's evidence summary

    Resource type name is **vendor_alert_evidences**.

    Example JSON record:

    .. code-block:: javascript

        {'evidence': 'string', 'evidence_type': 'HOSTNAME'}


    Below are valid filter by parameters:

        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Field Description                                                                                                                                                                                                                                                                                                                                                           | Field Name                 | Field Type                | Attribute     | Relationship     |
        +=============================================================================================================================================================================================================================================================================================================================================================================+============================+===========================+===============+==================+
        | Evidence                                                                                                                                                                                                                                                                                                                                                                    | evidence                   | string                    | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Type Restricted to: "HOSTNAME", "URL", "PROCESS_ARGUMENTS", "PROCESS_PATH", "PROCESS_MD5", "USERNAME", "SRC_IP", "DST_IP", "PARENT_ARGUMENTS", "PARENT_PATH", "PARENT_MD5", "SRC_USERNAME", "DST_USERNAME", "ALERT_ACTION", "ALERT_DESCRIPTION", "ALERT_MESSAGE", "ALERT_NAME", "SRC_PORT", "DST_PORT", "USER_AGENT", "VENDOR_NAME", "DOMAIN", "FILE_HASH", "FILE_PATH"     | evidence_type              | any                       | Y             | N                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Expel alerts                                                                                                                                                                                                                                                                                                                                                                | evidenced_expel_alerts     | :class:`ExpelAlerts`      | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+
        | Vendor alerts                                                                                                                                                                                                                                                                                                                                                               | vendor_alert               | :class:`VendorAlerts`     | N             | Y                |
        +-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+----------------------------+---------------------------+---------------+------------------+

    '''
    _api_type = 'vendor_alert_evidences'
    _def_attributes = ["evidence", "evidence_type"]
    _def_relationships = ["evidenced_expel_alerts", "vendor_alert"]


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
        | Created timestamp: readonly                                                                                    | created_at                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Description Allows: "", null                                                                                   | description                    | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence activity end datetime Allows: null: immutable                                                         | evidence_activity_end_at       | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence activity start datetime Allows: null: immutable                                                       | evidence_activity_start_at     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Evidence summary Allows: null: no-sort                                                                         | evidence_summary               | array                             | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | First Seen                                                                                                     | first_seen                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null: immutable                                                                                        | original_alert_id              | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Allows: null: immutable                                                                                        | original_source_id             | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Signature ID Allows: "", null                                                                                  | signature_id                   | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Status Restricted to: "NORMAL", "PROVISIONAL" Allows: null: readonly                                           | status                         | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly                                                                               | updated_at                     | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor Message Allows: "", null                                                                                | vendor_message                 | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor alert severity Restricted to: "CRITICAL", "HIGH", "MEDIUM", "LOW", "TESTING", "TUNING" Allows: null     | vendor_severity                | any                               | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor Sig Name Allows: "", null                                                                               | vendor_sig_name                | string                            | Y             | N                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Assemblers                                                                                                     | assembler                      | :class:`Assemblers`               | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                       | created_by                     | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendor alert evidences are extracted from a vendor alert's evidence summary                                    | evidences                      | :class:`VendorAlertEvidences`     | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Expel alerts                                                                                                   | expel_alerts                   | :class:`ExpelAlerts`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | IP addresses                                                                                                   | ip_addresses                   | :class:`IpAddresses`              | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io organization records                                                                | organization                   | :class:`Organizations`            | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Security devices                                                                                               | security_device                | :class:`SecurityDevices`          | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records                                                                       | updated_by                     | :class:`Actors`                   | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+
        | Vendors                                                                                                        | vendor                         | :class:`Vendors`                  | N             | Y                |
        +----------------------------------------------------------------------------------------------------------------+--------------------------------+-----------------------------------+---------------+------------------+

    '''
    _api_type = 'vendor_alerts'
    _def_attributes = ["created_at", "description", "evidence_activity_end_at", "evidence_activity_start_at", "evidence_summary", "first_seen",
                       "original_alert_id", "original_source_id", "signature_id", "status", "updated_at", "vendor_message", "vendor_severity", "vendor_sig_name"]
    _def_relationships = ["assembler", "created_by", "evidences", "expel_alerts",
                          "ip_addresses", "organization", "security_device", "updated_by", "vendor"]


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
        | Icon Allows: "", null                        | icon                 | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Name Allows: "", null                        | name                 | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Last Updated timestamp: readonly             | updated_at           | string                       | Y             | N                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | created_by           | :class:`Actors`              | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Expel alerts                                 | expel_alerts         | :class:`ExpelAlerts`         | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Security devices                             | security_devices     | :class:`SecurityDevices`     | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Defines/retrieves expel.io actor records     | updated_by           | :class:`Actors`              | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+
        | Vendor alerts                                | vendor_alerts        | :class:`VendorAlerts`        | N             | Y                |
        +----------------------------------------------+----------------------+------------------------------+---------------+------------------+

    '''
    _api_type = 'vendors'
    _def_attributes = ["created_at", "icon", "name", "updated_at"]
    _def_relationships = ["created_by", "expel_alerts", "security_devices", "updated_by", "vendor_alerts"]

# END AUTO GENERATE JSONAPI CLASSES


RELATIONSHIP_TO_CLASS_EXT = {
}


# AUTO GENERATE RELATIONSHIP TO CLASS LOOKUP

RELATIONSHIP_TO_CLASS_GEN = {
    "activity_metrics": ActivityMetrics,
    "created_by": Actors,
    "expel_alert": ExpelAlerts,
    "investigation": Investigations,
    "security_device": SecurityDevices,
    "updated_by": Actors,
    "actors": Actors,
    "analysis_assigned_investigative_actions": InvestigativeActions,
    "assigned_expel_alerts": ExpelAlerts,
    "assigned_investigations": Investigations,
    "assigned_investigative_actions": InvestigativeActions,
    "assigned_organization_resilience_actions": OrganizationResilienceActions,
    "assigned_organization_resilience_actions_list": OrganizationResilienceActions,
    "assigned_remediation_actions": RemediationActions,
    "automate_opt_in_for_remediation_action_setting": RemediationActionSettings,
    "child_actors": Actors,
    "notification_preferences": NotificationPreferences,
    "organization": Organizations,
    "parent_actor": Actors,
    "user_account": UserAccounts,
    "api_keys": ApiKeys,
    "assembler_images": AssemblerImages,
    "assemblers": Assemblers,
    "security_devices": SecurityDevices,
    "vendor_alerts": VendorAlerts,
    "comment_histories": CommentHistories,
    "comment": Comments,
    "comments": Comments,
    "configurations": Configurations,
    "context_label_action_histories": ContextLabelActionHistories,
    "context_label": ContextLabels,
    "context_label_action": ContextLabelActions,
    "context_label_actions": ContextLabelActions,
    "timeline_entries": TimelineEntries,
    "context_label_histories": ContextLabelHistories,
    "context_label_tags": ContextLabelTags,
    "context_labels": ContextLabels,
    "remediation_action_assets": RemediationActionAssets,
    "add_to_actions": ContextLabelActions,
    "alert_on_actions": ContextLabelActions,
    "approval_histories": ContextLabelHistories,
    "expel_alerts": ExpelAlerts,
    "investigations": Investigations,
    "originating_expel_alerts": ExpelAlerts,
    "remediation_action_setting_list_source_histories": RemediationActionSettingListSourceHistories,
    "remediation_action_setting_list_sources": RemediationActionSettingListSources,
    "remediation_action_settings": RemediationActionSettings,
    "suppress_actions": ContextLabelActions,
    "detections": Detections,
    "expel_alert_categories": ExpelDetectionCategories,
    "expel_response_categories": ExpelDetectionCategories,
    "expel_triage_categories": ExpelDetectionCategories,
    "mitre_tactics": MitreTactics,
    "engagement_managers": EngagementManagers,
    "organizations": Organizations,
    "entitlements": Entitlements,
    "expel_alert_histories": ExpelAlertHistories,
    "assigned_to_actor": Actors,
    "expel_alert_threshold_histories": ExpelAlertThresholdHistories,
    "expel_alert_threshold": ExpelAlertThresholds,
    "expel_alert_thresholds": ExpelAlertThresholds,
    "suppressed_by": ExpelAlertThresholds,
    "suppresses": ExpelAlertThresholds,
    "destination_ip_addresses": IpAddresses,
    "evidence": VendorAlertEvidences,
    "investigative_action_histories": InvestigativeActionHistories,
    "investigative_actions": InvestigativeActions,
    "originated_context_labels": ContextLabels,
    "phishing_submissions": PhishingSubmissions,
    "related_investigations": Investigations,
    "related_investigations_via_involved_host_ips": Investigations,
    "similar_alerts": ExpelAlerts,
    "source_ip_addresses": IpAddresses,
    "status_last_updated_by": Actors,
    "suppression_histories": ExpelAlertHistories,
    "vendor": Vendors,
    "expel_detection_categories": ExpelDetectionCategories,
    "files": Files,
    "phishing_submission": PhishingSubmissions,
    "phishing_submission_attachment": PhishingSubmissionAttachments,
    "findings": InvestigationFindings,
    "integrations": Integrations,
    "secret": Secrets,
    "investigation_finding_histories": InvestigationFindingHistories,
    "investigation_finding": InvestigationFindings,
    "investigation_findings": InvestigationFindings,
    "investigation_histories": InvestigationHistories,
    "investigation_resilience_action_hints": InvestigationResilienceActionHints,
    "investigation_resilience_actions": InvestigationResilienceActions,
    "organization_resilience_action": OrganizationResilienceActions,
    "ip_addresses": IpAddresses,
    "last_published_by": Actors,
    "lead_expel_alert": ExpelAlerts,
    "most_recent_investigative_action": InvestigativeActions,
    "organization_resilience_action_hints": OrganizationResilienceActions,
    "organization_resilience_actions": OrganizationResilienceActions,
    "remediation_action_asset_histories": RemediationActionAssetHistories,
    "remediation_action_histories": RemediationActionHistories,
    "remediation_actions": RemediationActions,
    "review_requested_by": Actors,
    "investigative_action": InvestigativeActions,
    "analysis_assigned_to_actor": Actors,
    "dependent_investigative_actions": InvestigativeActions,
    "depends_on_investigative_action": InvestigativeActions,
    "destination_expel_alerts": ExpelAlerts,
    "destination_investigations": Investigations,
    "source_expel_alerts": ExpelAlerts,
    "source_investigations": Investigations,
    "nist_categories": NistCategories,
    "nist_subcategories": NistSubcategories,
    "nist_category": NistCategories,
    "nist_subcategory_scores": NistSubcategoryScores,
    "nist_subcategory_score_histories": NistSubcategoryScoreHistories,
    "nist_subcategory_score": NistSubcategoryScores,
    "nist_subcategory": NistSubcategories,
    "actor": Actors,
    "organization_resilience_action_groups": OrganizationResilienceActionGroups,
    "organization_resilience_action_group_actions": OrganizationResilienceActions,
    "source_resilience_action_group": ResilienceActionGroups,
    "investigation_hints": Investigations,
    "organization_resilience_action_group": OrganizationResilienceActionGroups,
    "source_resilience_action": ResilienceActions,
    "organization_statuses": OrganizationStatuses,
    "alert_assignables": Actors,
    "engagement_manager": EngagementManagers,
    "entitlement": Entitlements,
    "investigation_assignables": Actors,
    "organization_status": OrganizationStatuses,
    "organization_user_account_roles": UserAccountRoles,
    "remediation_action_setting_histories": RemediationActionSettingHistories,
    "saml_identity_provider": SamlIdentityProviders,
    "user_accounts": UserAccounts,
    "user_accounts_with_roles": UserAccounts,
    "phishing_submission_attachments": PhishingSubmissionAttachments,
    "attachment_file": Files,
    "phishing_submission_domains": PhishingSubmissionDomains,
    "phishing_submission_headers": PhishingSubmissionHeaders,
    "phishing_submission_urls": PhishingSubmissionUrls,
    "analysis_email_file": Files,
    "initial_email_file": Files,
    "raw_body_file": Files,
    "remediation_action_asset": RemediationActionAssets,
    "remediation_action": RemediationActions,
    "remediation_action_setting": RemediationActionSettings,
    "remediation_action_setting_list_source": RemediationActionSettingListSources,
    "automate_opt_in_actor": Actors,
    "context_label_list_sources": RemediationActionSettingListSources,
    "opt_in_histories": RemediationActionSettingHistories,
    "opt_out_histories": RemediationActionSettingHistories,
    "resilience_action_groups": ResilienceActionGroups,
    "resilience_actions": ResilienceActions,
    "resilience_action_group": ResilienceActionGroups,
    "saml_identity_providers": SamlIdentityProviders,
    "secrets": Secrets,
    "assembler": Assemblers,
    "child_security_devices": SecurityDevices,
    "parent_security_device": SecurityDevices,
    "user_account_roles": UserAccountRoles,
    "user_account_statuses": UserAccountStatuses,
    "primary_organization": Organizations,
    "user_account_status": UserAccountStatuses,
    "vendor_alert_evidences": VendorAlertEvidences,
    "evidenced_expel_alerts": ExpelAlerts,
    "vendor_alert": VendorAlerts,
    "evidences": VendorAlertEvidences,
    "vendors": Vendors
}
# END AUTO GENERATE RELATIONSHIP TO CLASS LOOKUP

RELATIONSHIP_TO_CLASS = RELATIONSHIP_TO_CLASS_GEN


class WorkbenchCoreClient:
    '''
    Instantiate a Workbench core client that provides just authentication and request capabilities to Workbench

    If the developer specifies a ``username``, then ``password`` and ``mfa_code`` are required inputs. If the developer
    has a ``token`` then ``username``, ``password`` and ``mfa_code`` parameters are ignored.

    :param cls: A Workbench class reference.
    :type cls: WorkbenchClient
    :param username: The username
    :type username: str or None
    :param password: The username's password
    :type password: str or None
    :param mfa_code: The multi factor authenticate code generated by google authenticator.
    :type mfa_code: int or None
    :param token: The bearer token of an authorized session. Can be used instead of ``username``/``password`` combo.
    :type token: str or None
    :return: An initialized, and authorized Workbench client.
    :rtype: WorkbenchClient
    '''

    def __init__(self, base_url, username=None, password=None, mfa_code=None, token=None, retries=3, prompt_on_delete=True):
        self.base_url = base_url
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

        if self.mfa_code:
            self.token = self.login(
                self.username, self.password, self.mfa_code)

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
        data = urlencode(
            {'grant_type': 'password', 'username': username, 'password': password})
        resp = self.request('post', '/auth/v0/login',
                            data=data, headers=headers, skip_raise=True)
        # Note the login route returns 401 even when password is valid as a way to
        # move to the second phase which is posting the 2fa code..
        if resp.status_code != 401:
            logger.error(
                "Got unexpected http response code {}".format(resp.status_code))
            return None

        headers['x-expelinc-otp'] = str(code)

        resp = self.request('post', '/auth/v0/login',
                            data=data, headers=headers)
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
            resp = requests.post(url, headers=headers,
                                 data=data, files=files, **request_kwargs)
        else:
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
                raise requests.exceptions.HTTPError(
                    "Got status code: %s" % err['errors'][0]['status'])
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
    has a ``token`` then ``username``, ``password`` and ``mfa_code`` parameters are ignored.

    :param cls: A Workbench class reference.
    :type cls: WorkbenchClient
    :param username: The username
    :type username: str or None
    :param password: The username's password
    :type password: str or None
    :param mfa_code: The multi factor authenticate code generated by google authenticator.
    :type mfa_code: int or None
    :param token: The bearer token of an authorized session. Can be used instead of ``username``/``password`` combo.
    :type token: str or None
    :return: An initialized, and authorized Workbench client.
    :rtype: WorkbenchClient
    '''

    def __init__(self, base_url, username=None, password=None, mfa_code=None, token=None, prompt_on_delete=True):
        super().__init__(base_url, username=username, password=password,
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
            raise Exception(
                "Must specify an expel_alert_id or an investigation_id")

        # Create the manual investigative action in WB
        ia = self.investigative_actions.create(
            title=title, status='READY_FOR_ANALYSIS', reason=reason, action_type=action_type, instructions=instructions)
        if security_device_id is not None:
            ia.relationship.security_device = security_device_id
        if investigation_id:
            ia.relationship.investigation = investigation_id
        if expel_alert_id:
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
            raise Exception(
                "Must specify an expel_alert_id or an investigation_id")

        # Create the investigative action in WB
        ia = self.investigative_actions.create(title=title, status='RUNNING', reason=reason, action_type='TASKABILITY',
                                               capability_name=capability_name, input_args=input_args)
        ia.relationship.security_device = vendor_device_id
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
    def activity_metrics(self):
        return BaseResourceObject(ActivityMetrics, conn=self)

    @property
    def actors(self):
        return BaseResourceObject(Actors, conn=self)

    @property
    def api_keys(self):
        return BaseResourceObject(ApiKeys, conn=self)

    @property
    def assembler_images(self):
        return BaseResourceObject(AssemblerImages, conn=self)

    @property
    def assemblers(self):
        return BaseResourceObject(Assemblers, conn=self)

    @property
    def comment_histories(self):
        return BaseResourceObject(CommentHistories, conn=self)

    @property
    def comments(self):
        return BaseResourceObject(Comments, conn=self)

    @property
    def configurations(self):
        return BaseResourceObject(Configurations, conn=self)

    @property
    def context_label_action_histories(self):
        return BaseResourceObject(ContextLabelActionHistories, conn=self)

    @property
    def context_label_actions(self):
        return BaseResourceObject(ContextLabelActions, conn=self)

    @property
    def context_label_histories(self):
        return BaseResourceObject(ContextLabelHistories, conn=self)

    @property
    def context_label_tags(self):
        return BaseResourceObject(ContextLabelTags, conn=self)

    @property
    def context_labels(self):
        return BaseResourceObject(ContextLabels, conn=self)

    @property
    def detections(self):
        return BaseResourceObject(Detections, conn=self)

    @property
    def engagement_managers(self):
        return BaseResourceObject(EngagementManagers, conn=self)

    @property
    def entitlements(self):
        return BaseResourceObject(Entitlements, conn=self)

    @property
    def expel_alert_histories(self):
        return BaseResourceObject(ExpelAlertHistories, conn=self)

    @property
    def expel_alert_threshold_histories(self):
        return BaseResourceObject(ExpelAlertThresholdHistories, conn=self)

    @property
    def expel_alert_thresholds(self):
        return BaseResourceObject(ExpelAlertThresholds, conn=self)

    @property
    def expel_alerts(self):
        return BaseResourceObject(ExpelAlerts, conn=self)

    @property
    def expel_detection_categories(self):
        return BaseResourceObject(ExpelDetectionCategories, conn=self)

    @property
    def files(self):
        return BaseResourceObject(Files, conn=self)

    @property
    def findings(self):
        return BaseResourceObject(Findings, conn=self)

    @property
    def integrations(self):
        return BaseResourceObject(Integrations, conn=self)

    @property
    def investigation_finding_histories(self):
        return BaseResourceObject(InvestigationFindingHistories, conn=self)

    @property
    def investigation_findings(self):
        return BaseResourceObject(InvestigationFindings, conn=self)

    @property
    def investigation_histories(self):
        return BaseResourceObject(InvestigationHistories, conn=self)

    @property
    def investigation_resilience_action_hints(self):
        return BaseResourceObject(InvestigationResilienceActionHints, conn=self)

    @property
    def investigation_resilience_actions(self):
        return BaseResourceObject(InvestigationResilienceActions, conn=self)

    @property
    def investigations(self):
        return BaseResourceObject(Investigations, conn=self)

    @property
    def investigative_action_histories(self):
        return BaseResourceObject(InvestigativeActionHistories, conn=self)

    @property
    def investigative_actions(self):
        return BaseResourceObject(InvestigativeActions, conn=self)

    @property
    def ip_addresses(self):
        return BaseResourceObject(IpAddresses, conn=self)

    @property
    def mitre_tactics(self):
        return BaseResourceObject(MitreTactics, conn=self)

    @property
    def nist_categories(self):
        return BaseResourceObject(NistCategories, conn=self)

    @property
    def nist_subcategories(self):
        return BaseResourceObject(NistSubcategories, conn=self)

    @property
    def nist_subcategory_score_histories(self):
        return BaseResourceObject(NistSubcategoryScoreHistories, conn=self)

    @property
    def nist_subcategory_scores(self):
        return BaseResourceObject(NistSubcategoryScores, conn=self)

    @property
    def notification_preferences(self):
        return BaseResourceObject(NotificationPreferences, conn=self)

    @property
    def organization_resilience_action_groups(self):
        return BaseResourceObject(OrganizationResilienceActionGroups, conn=self)

    @property
    def organization_resilience_actions(self):
        return BaseResourceObject(OrganizationResilienceActions, conn=self)

    @property
    def organization_statuses(self):
        return BaseResourceObject(OrganizationStatuses, conn=self)

    @property
    def organizations(self):
        return BaseResourceObject(Organizations, conn=self)

    @property
    def phishing_submission_attachments(self):
        return BaseResourceObject(PhishingSubmissionAttachments, conn=self)

    @property
    def phishing_submission_domains(self):
        return BaseResourceObject(PhishingSubmissionDomains, conn=self)

    @property
    def phishing_submission_headers(self):
        return BaseResourceObject(PhishingSubmissionHeaders, conn=self)

    @property
    def phishing_submission_urls(self):
        return BaseResourceObject(PhishingSubmissionUrls, conn=self)

    @property
    def phishing_submissions(self):
        return BaseResourceObject(PhishingSubmissions, conn=self)

    @property
    def remediation_action_asset_histories(self):
        return BaseResourceObject(RemediationActionAssetHistories, conn=self)

    @property
    def remediation_action_assets(self):
        return BaseResourceObject(RemediationActionAssets, conn=self)

    @property
    def remediation_action_histories(self):
        return BaseResourceObject(RemediationActionHistories, conn=self)

    @property
    def remediation_action_setting_histories(self):
        return BaseResourceObject(RemediationActionSettingHistories, conn=self)

    @property
    def remediation_action_setting_list_source_histories(self):
        return BaseResourceObject(RemediationActionSettingListSourceHistories, conn=self)

    @property
    def remediation_action_setting_list_sources(self):
        return BaseResourceObject(RemediationActionSettingListSources, conn=self)

    @property
    def remediation_action_settings(self):
        return BaseResourceObject(RemediationActionSettings, conn=self)

    @property
    def remediation_actions(self):
        return BaseResourceObject(RemediationActions, conn=self)

    @property
    def resilience_action_groups(self):
        return BaseResourceObject(ResilienceActionGroups, conn=self)

    @property
    def resilience_actions(self):
        return BaseResourceObject(ResilienceActions, conn=self)

    @property
    def saml_identity_providers(self):
        return BaseResourceObject(SamlIdentityProviders, conn=self)

    @property
    def secrets(self):
        return BaseResourceObject(Secrets, conn=self)

    @property
    def security_devices(self):
        return BaseResourceObject(SecurityDevices, conn=self)

    @property
    def timeline_entries(self):
        return BaseResourceObject(TimelineEntries, conn=self)

    @property
    def user_account_roles(self):
        return BaseResourceObject(UserAccountRoles, conn=self)

    @property
    def user_account_statuses(self):
        return BaseResourceObject(UserAccountStatuses, conn=self)

    @property
    def user_accounts(self):
        return BaseResourceObject(UserAccounts, conn=self)

    @property
    def vendor_alert_evidences(self):
        return BaseResourceObject(VendorAlertEvidences, conn=self)

    @property
    def vendor_alerts(self):
        return BaseResourceObject(VendorAlerts, conn=self)

    @property
    def vendors(self):
        return BaseResourceObject(Vendors, conn=self)

# END AUTO GENERATE PROPERTIES
